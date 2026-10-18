"""Scores, filtres, historique anti-doublon et choix final diversifié."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modele import Post, date_utc, log

FORMATS_VIDEO = {"Reel", "Vidéo"}
FORMATS_DEFAUT = ["Reel", "Vidéo", "Carrousel"]
PLANCHER_INTERACTIONS = 300   # carrousels : minimum de j'aime + commentaires pour être retenu


def famille(p: Post) -> str:
    """Les vidéos se jugent sur les vues ; les carrousels (sans vues publiques) sur les j'aime + commentaires."""
    return "video" if p.format in FORMATS_VIDEO else "image"


# ------------------------------------------------------------
#  Scores
# ------------------------------------------------------------
def calcule_scores(posts: list[Post], cfg: dict) -> list[Post]:
    """
    Vidéos (Reels, TikTok) :
    - taux d'engagement    = (likes + commentaires + partages + enregistrements) / vues
    - taux de commentaires = commentaires / vues  → signal direct de conversations
    - score viral          = vues / médiane des vues du compte
    - critères : vues ≥ seuil, taux d'engagement ≥ taux_engagement_min
    Carrousels (Instagram ne publie pas leurs vues) :
    - score viral = (j'aime + commentaires) / médiane des carrousels du même compte
    - critères : interactions ≥ N × l'habitude du compte (et ≥ un plancher)
    Classement : rang moyen (surperformance, taux de commentaires, taux d'engagement), critères OK d'abord.
    """
    a = cfg["analyse"]
    maintenant = datetime.now(timezone.utc)
    limite = maintenant - timedelta(days=a["mois"] * 30)

    candidats = []
    for p in posts:
        if p.format not in (a.get("formats") or FORMATS_DEFAUT):
            continue
        d = date_utc(p.date)
        if d and (d < limite or maintenant - d < timedelta(hours=48)):
            continue
        p.interactions = (p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)
        if p.vues:
            p.taux_engagement = round(p.interactions / p.vues, 4)
            p.taux_commentaires = round((p.commentaires or 0) / p.vues, 5)
        candidats.append(p)

    par_compte: dict[tuple, list[Post]] = {}
    for p in candidats:
        par_compte.setdefault((p.plateforme, p.compte, famille(p)), []).append(p)
    retenus = []
    for (plat, compte, fam), lst in par_compte.items():
        if fam == "video":
            vues = [p.vues for p in lst if p.vues]
            med = statistics.median(vues) if vues else None
            seuil = seuil_vues(a, med)
            for p in lst:
                p.score_viral = round(p.vues / med, 2) if (med and p.vues) else 0.0
                p.seuil_vues = seuil
                p.criteres_ok = bool(p.vues and p.vues >= seuil
                                     and (p.taux_engagement or 0) >= a["taux_engagement_min"])
                retenus.append(p)
        else:
            inter = [p.interactions for p in lst if p.interactions]
            med = statistics.median(inter) if inter else None
            seuil = int(max(a.get("plancher_interactions", PLANCHER_INTERACTIONS), a.get("seuil_multiple", 3) * med)) if med else None
            for p in lst:
                p.score_viral = round(p.interactions / med, 2) if (med and p.interactions) else 0.0
                p.seuil_vues = seuil  # pour un carrousel : seuil d'interactions
                # Un compte qui n'a publié qu'un ou deux carrousels n'a pas d'« habitude » : on exige alors le double du plancher
                assez = len(inter) >= 3 or (p.interactions or 0) >= 2 * a.get("plancher_interactions", PLANCHER_INTERACTIONS)
                p.criteres_ok = bool(seuil and p.interactions >= seuil and assez)
                retenus.append(p)

    def rangs(cle):
        presents = sorted([getattr(p, cle) for p in retenus if getattr(p, cle) is not None])
        mediane = presents[len(presents) // 2] if presents else 0
        tri = sorted(retenus, key=lambda p: getattr(p, cle) if getattr(p, cle) is not None else mediane, reverse=True)
        return {id(p): i for i, p in enumerate(tri)}
    r_com, r_eng, r_vir = rangs("taux_commentaires"), rangs("taux_engagement"), rangs("score_viral")
    retenus.sort(key=lambda p: (not p.criteres_ok, r_com[id(p)] + r_eng[id(p)] + r_vir[id(p)]))
    return retenus


def seuil_vues(a: dict, mediane: float | None) -> int:
    """
    Seuil fixe (vues_min) ou automatique : N fois les vues habituelles du compte, avec un plancher.
    Le mode automatique s'adapte aux petits comptes comme aux très gros.
    """
    if a.get("seuil_mode") == "auto" and mediane:
        return int(max(a.get("seuil_plancher", 30000), a.get("seuil_multiple", 3) * mediane))
    return int(a["vues_min"])


def calcule_scores_individuels(posts: list[Post], cfg: dict):
    """Pour des Reels donnés un par un : pas de médiane de compte, mais engagement et critères."""
    a = cfg["analyse"]
    for p in posts:
        p.interactions = (p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)
        if p.vues:
            p.taux_engagement = round(p.interactions / p.vues, 4)
            p.taux_commentaires = round((p.commentaires or 0) / p.vues, 5)
        p.seuil_vues = int(a["vues_min"])
        p.criteres_ok = bool(p.vues and p.vues >= p.seuil_vues and (p.taux_engagement or 0) >= a["taux_engagement_min"])


# ------------------------------------------------------------
#  Historique : ne jamais reproposer une inspiration déjà utilisée
# ------------------------------------------------------------
class Historique:
    def __init__(self, chemin: Path):
        self.chemin = chemin
        self.data = {"posts": {}}
        if chemin.exists():
            try:
                self.data = json.loads(chemin.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log("⚠️  historique.json illisible, on repart de zéro")

    def deja_utilise(self, p: Post) -> bool:
        return f"{p.plateforme}:{p.id}" in self.data["posts"]

    def mecaniques_recentes(self, semaines: int = 2) -> dict[str, int]:
        """Combien de fois chaque mécanique a été planifiée récemment."""
        seuil = (datetime.now() - timedelta(weeks=semaines)).strftime("%Y-%m-%d")
        compte: dict[str, int] = {}
        for v in self.data["posts"].values():
            if v.get("date", "") >= seuil and v.get("mecanique"):
                compte[v["mecanique"]] = compte.get(v["mecanique"], 0) + 1
        return compte

    def enregistre(self, posts: list[Post]):
        jour = datetime.now().strftime("%Y-%m-%d")
        for p in posts:
            self.data["posts"][f"{p.plateforme}:{p.id}"] = {
                "date": jour, "compte": p.compte, "url": p.url, "creneau": p.creneau,
                "mecanique": (p.adaptation or {}).get("mecanique", ""),
                "hook": (p.adaptation or {}).get("hook_viral") or ((p.adaptation or {}).get("hooks_adaptes") or [""])[0],
            }
        self.chemin.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def candidats(classes: list[Post], cfg: dict, histo: Historique) -> list[Post]:
    """Pool de candidats à enrichir et adapter : un peu plus que nécessaire, pour pouvoir diversifier."""
    o, a = cfg["objectifs"], cfg["analyse"]
    besoin = o["reels_par_jour"] * o["jours_planifies"]
    taille = int(besoin * cfg["diversite"]["marge_candidats"] + 0.999)

    frais = [p for p in classes if not histo.deja_utilise(p)]
    exclus = len(classes) - len(frais)
    if exclus:
        log(f"{exclus} Reel(s) déjà utilisés les semaines précédentes, écartés")

    ok = [p for p in frais if p.criteres_ok]
    pool = ok[:taille]
    # Diversité des formats : les carrousels viraux ont leur place même si les Reels dominent le classement
    car = [p for p in ok if famille(p) == "image"]
    quota = min(len(car), max(2, taille // 3))
    manquants = [p for p in car if p not in pool][:max(0, quota - sum(1 for p in pool if famille(p) == "image"))]
    if manquants:
        reels_pool = [p for p in pool if famille(p) != "image"]
        retires = set(id(p) for p in reels_pool[len(reels_pool) - len(manquants):])
        pool = [p for p in pool if id(p) not in retires] + manquants
    if len(ok) < besoin:
        log(f"⚠️  Seulement {len(ok)} Reels inédits remplissent les critères pour {besoin} nécessaires.")
    if len(pool) < taille and a.get("completer_si_insuffisant", True):
        reste = [p for p in frais if not p.criteres_ok]
        reste.sort(key=lambda p: ((p.taux_engagement or 0) >= a["taux_engagement_min"], p.vues or 0), reverse=True)
        pool += reste[:taille - len(pool)]
    return pool


def choix_final(pool: list[Post], cfg: dict, histo: Historique, apprentissages: dict) -> list[Post]:
    """
    Choisit les Reels de la semaine :
      1. critères OK d'abord, puis transposabilité ≥ 3/5
      2. bonus aux mécaniques qui marchent sur TON compte, malus à celles qui ne marchent pas
      3. pas plus de N Reels d'une même mécanique dans la semaine
    """
    o, dv = cfg["objectifs"], cfg["diversite"]
    besoin = o["reels_par_jour"] * o["jours_planifies"]
    top = set(apprentissages.get("mecaniques_top") or [])
    flop = set(apprentissages.get("mecaniques_flop") or [])
    recentes = histo.mecaniques_recentes()

    def priorite(i_p):
        i, p = i_p
        ad = p.adaptation or {}
        mec = ad.get("mecanique", "Autre")
        bonus = (-3 if mec in top else 0) + (3 if mec in flop else 0) + min(recentes.get(mec, 0), 4) * 0.5
        return (not p.criteres_ok, (ad.get("pertinence") or 0) < 3, i + bonus)

    ordonnes = [p for _, p in sorted(enumerate(pool), key=priorite)]
    choisis, par_mec = [], {}
    for p in ordonnes:
        mec = (p.adaptation or {}).get("mecanique", "Autre")
        if par_mec.get(mec, 0) >= dv["max_par_mecanique"]:
            continue
        choisis.append(p)
        par_mec[mec] = par_mec.get(mec, 0) + 1
        if len(choisis) == besoin:
            break
    # S'il manque des Reels à cause de la contrainte de diversité, on la relâche
    for p in ordonnes:
        if len(choisis) == besoin:
            break
        if p not in choisis:
            choisis.append(p)
    return alterne(choisis)


def alterne(posts: list[Post]) -> list[Post]:
    """Évite deux mécaniques identiques d'affilée dans le planning."""
    restant, res = list(posts), []
    while restant:
        prec = (res[-1].adaptation or {}).get("mecanique") if res else None
        idx = next((i for i, p in enumerate(restant) if (p.adaptation or {}).get("mecanique") != prec), 0)
        res.append(restant.pop(idx))
    return res


def planifie(posts: list[Post], cfg: dict):
    o = cfg["objectifs"]
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    moments = ["matin", "soir"] if o["reels_par_jour"] == 2 else [f"n°{i + 1}" for i in range(o["reels_par_jour"])]
    for i, p in enumerate(posts):
        p.creneau = f"{jours[(i // len(moments)) % 7]} {moments[i % len(moments)]}"
