"""Scores, filtres, historique anti-doublon et choix final diversifié."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modele import Post, log

FORMATS_VIDEO = {"Reel", "Vidéo"}


# ------------------------------------------------------------
#  Scores
# ------------------------------------------------------------
def calcule_scores(posts: list[Post], cfg: dict) -> list[Post]:
    """
    - taux d'engagement    = (likes + commentaires + partages + enregistrements) / vues
    - taux de commentaires = commentaires / vues  → signal direct de conversations
    - score viral          = vues / médiane des vues du compte
    Critères : Reel/vidéo, vues ≥ vues_min, taux d'engagement ≥ taux_engagement_min.
    Classement : rang moyen (taux de commentaires, taux d'engagement), critères OK d'abord.
    """
    a = cfg["analyse"]
    maintenant = datetime.now(timezone.utc)
    limite = maintenant - timedelta(days=a["mois"] * 30)

    candidats = []
    for p in posts:
        if a.get("reels_uniquement", True) and p.format not in FORMATS_VIDEO:
            continue
        try:
            d = datetime.fromisoformat(p.date.replace("Z", "+00:00"))
            if d < limite or maintenant - d < timedelta(hours=48):
                continue
        except ValueError:
            pass
        p.interactions = (p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)
        if p.vues:
            p.taux_engagement = round(p.interactions / p.vues, 4)
            p.taux_commentaires = round((p.commentaires or 0) / p.vues, 5)
        candidats.append(p)

    par_compte: dict[tuple, list[Post]] = {}
    for p in candidats:
        par_compte.setdefault((p.plateforme, p.compte), []).append(p)
    retenus = []
    for (plat, compte), lst in par_compte.items():
        vues = [p.vues for p in lst if p.vues]
        med = statistics.median(vues) if vues else None
        for p in lst:
            p.score_viral = round(p.vues / med, 2) if (med and p.vues) else 0.0
            p.criteres_ok = bool(p.vues and p.vues >= a["vues_min"]
                                 and (p.taux_engagement or 0) >= a["taux_engagement_min"])
            retenus.append(p)

    def rangs(cle):
        tri = sorted(retenus, key=lambda p: getattr(p, cle) or 0, reverse=True)
        return {id(p): i for i, p in enumerate(tri)}
    r_com, r_eng = rangs("taux_commentaires"), rangs("taux_engagement")
    retenus.sort(key=lambda p: (not p.criteres_ok, r_com[id(p)] + r_eng[id(p)]))
    return retenus


def calcule_scores_individuels(posts: list[Post], cfg: dict):
    """Pour des Reels donnés un par un : pas de médiane de compte, mais engagement et critères."""
    a = cfg["analyse"]
    for p in posts:
        p.interactions = (p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)
        if p.vues:
            p.taux_engagement = round(p.interactions / p.vues, 4)
            p.taux_commentaires = round((p.commentaires or 0) / p.vues, 5)
        p.criteres_ok = bool(p.vues and p.vues >= a["vues_min"] and (p.taux_engagement or 0) >= a["taux_engagement_min"])


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
