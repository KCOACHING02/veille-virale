"""
Moteur d'analyse, partagé par la ligne de commande (veille.py) et l'interface web (app.py).

Deux modes :
  - « veille » : les comptes surveillés de config.yaml → planning de la semaine (2 Reels/jour)
  - « copie »  : des comptes ou des Reels précis que tu donnes → analyse + adaptation de leurs meilleurs Reels
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import yaml

import rapports
import selection
from espace import Espace
from modele import Post, cle, log

ICI = Path(__file__).resolve().parent
MAX_AFFICHES = 300


# ------------------------------------------------------------
#  Lecture des comptes / liens saisis librement
# ------------------------------------------------------------
_PREFIXES = {"ig": "Instagram", "insta": "Instagram", "instagram": "Instagram",
             "tt": "TikTok", "tk": "TikTok", "tiktok": "TikTok"}


def parse_saisie(texte: str, plateforme_defaut: str = "Instagram") -> dict:
    """
    Accepte, un par ligne ou séparés par des virgules :
      @compte · compte · ig:compte · tt:compte
      https://www.instagram.com/compte/ · https://www.tiktok.com/@compte
      https://www.instagram.com/reel/XXXX/ · https://www.tiktok.com/@compte/video/123  (Reels précis)
    """
    comptes, posts, ignores = [], [], []
    for brut in re.split(r"[\s,;]+", texte or ""):
        t = brut.strip().strip("/")
        if not t:
            continue
        low = t.lower()
        if "instagram.com" in low:
            m = re.search(r"instagram\.com/(?:[^/]+/)?(p|reel|reels|tv)/([\w-]+)", t)
            if m:
                posts.append(("Instagram", f"https://www.instagram.com/{'reel' if m.group(1) != 'p' else 'p'}/{m.group(2)}/"))
                continue
            m = re.search(r"instagram\.com/([\w.]+)", t)
            if m and m.group(1).lower() not in ("explore", "stories", "accounts"):
                comptes.append(("Instagram", m.group(1)))
            else:
                ignores.append(brut)
            continue
        if "tiktok.com" in low:
            m = re.search(r"tiktok\.com/@([\w.]+)/(?:video|photo)/(\d+)", t)
            if m:
                posts.append(("TikTok", f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}"))
                continue
            m = re.search(r"tiktok\.com/@([\w.]+)", t)
            (comptes.append(("TikTok", m.group(1))) if m else ignores.append(brut))
            continue
        plat = plateforme_defaut
        if ":" in t:
            pre, t = t.split(":", 1)
            plat = _PREFIXES.get(pre.lower().strip(), plateforme_defaut)
        nom = t.strip().lstrip("@")
        if re.fullmatch(r"[\w.]{1,40}", nom):
            comptes.append((plat, nom))
        else:
            ignores.append(brut)
    dedup = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    return {"comptes": dedup(comptes), "posts": dedup(posts), "ignores": ignores}


def ajoute_a_la_veille(esp: Espace, comptes: list[tuple[str, str]]) -> list[str]:
    cfg = esp.lit_config()
    ajoutes = []
    for pl, c in comptes:
        k = "instagram" if pl == "Instagram" else "tiktok"
        lst = cfg["comptes"].get(k) or []
        if c not in lst:
            lst.append(c)
            ajoutes.append(f"{pl} @{c}")
        cfg["comptes"][k] = lst
    if ajoutes:
        esp.ecrit_config(cfg)
    return ajoutes


def retire_de_la_veille(esp: Espace, plateforme: str, compte: str):
    cfg = esp.lit_config()
    k = "instagram" if plateforme == "Instagram" else "tiktok"
    cfg["comptes"][k] = [c for c in (cfg["comptes"].get(k) or []) if c != compte]
    esp.ecrit_config(cfg)


# ------------------------------------------------------------
#  Sauvegarde des analyses
# ------------------------------------------------------------
def _post_vers_dict(p: Post) -> dict:
    d = asdict(p)
    d.pop("images", None)
    d["cle"] = cle(p)
    return d


def _dict_vers_post(d: dict) -> Post:
    return Post(**{k: v for k, v in d.items() if k in Post.__dataclass_fields__})


def sauve(esp: Espace, analyse: dict):
    (esp.analyses / f"{analyse['id']}.json").write_text(json.dumps(analyse, ensure_ascii=False), encoding="utf-8")


def charge(esp: Espace, analyse_id: str) -> dict:
    return json.loads((esp.analyses / f"{Path(analyse_id).name}.json").read_text(encoding="utf-8"))


def liste_analyses(esp: Espace) -> list[dict]:
    res = []
    for f in sorted(esp.analyses.glob("*.json"), reverse=True):
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        res.append({k: a.get(k) for k in ("id", "date", "mode", "titre", "stats", "demo")})
    return res


# Plafonds de coût fixés par l'éditeur : ils s'appliquent à tous les espaces, même créés avant cette version.
PLAFONDS = {
    ("analyse", "posts_max_par_compte"): 60,   # 60 publications récentes suffisent sur 3 mois
    ("commentaires", "par_post"): 20,          # les 20 commentaires les plus likés portent l'essentiel
    ("decouverte", "posts_par_hashtag"): 50,
    ("diversite", "marge_candidats"): 1.2,      # 17 Reels analysés pour en garder 14 (au lieu de 21)
}
DECOUVERTE_TOUS_LES_JOURS = 28                   # découverte de nouveaux comptes : une fois par mois


def applique_plafonds(cfg: dict) -> dict:
    for (bloc, cle_), maxi in PLAFONDS.items():
        if bloc in cfg and cle_ in cfg[bloc]:
            cfg[bloc][cle_] = min(cfg[bloc][cle_], maxi)
    return cfg


def verifie_cle_claude():
    """Appel gratuit qui valide la clé Claude : on arrête tout de suite au lieu de collecter pour rien."""
    import anthropic
    try:
        anthropic.Anthropic().models.list(limit=1)
    except anthropic.AuthenticationError:
        raise RuntimeError("La clé Claude (ANTHROPIC_API_KEY) est refusée : elle est invalide, incomplète ou supprimée. "
                           "Crée une nouvelle clé dans la console Claude et remplace-la dans les variables Railway.") from None
    except anthropic.PermissionDeniedError:
        raise RuntimeError("La clé Claude n'a pas les droits nécessaires (organisation ou espace de travail).") from None
    except Exception as e:  # noqa: BLE001 — réseau, etc. : on n'empêche pas l'analyse
        log(f"⚠️  Vérification de la clé Claude impossible : {e}")


# ------------------------------------------------------------
#  Exécution
# ------------------------------------------------------------
def executer(esp: Espace, cfg: dict, mode: str = "veille", saisie: dict | None = None, nb_adapter: int | None = None,
             demo: bool = False, sans_ia: bool = False, depuis: str | None = None, max_adaptations: int | None = None) -> dict:
    cfg = applique_plafonds(cfg)
    o = cfg["objectifs"]
    token = os.getenv("APIFY_TOKEN")
    a_ia = not sans_ia and bool(os.getenv("ANTHROPIC_API_KEY"))
    travail = Path(tempfile.mkdtemp(prefix="veille_"))
    saisie = saisie or {"comptes": [], "posts": []}
    besoin = o["reels_par_jour"] * o["jours_planifies"]
    nb_adapter = nb_adapter or (besoin if mode == "veille" else 10)

    if not demo:
        if not depuis and not token:
            raise RuntimeError("Clé APIFY_TOKEN manquante (fichier .env).")
        if not sans_ia and not a_ia:
            raise RuntimeError("Clé ANTHROPIC_API_KEY manquante (fichier .env).")
        if a_ia:
            verifie_cle_claude()  # avant de dépenser des crédits Apify
    if mode == "copie" and not (saisie["comptes"] or saisie["posts"]):
        raise RuntimeError("Aucun compte ni lien de Reel reconnu.")

    try:
        # ---------------- 1. Collecte ----------------
        if demo:
            import demo as d
            log("MODE DÉMO : données fictives")
            posts = d.posts_concurrents(saisie["comptes"] or [(pl, "reel_demande_demo") for pl, _ in saisie["posts"]] or None)
            if saisie["posts"]:
                for p in posts[:len(saisie["posts"])]:
                    p.demande = True
        elif depuis:
            posts = [_dict_vers_post(x) for x in json.loads(Path(depuis).read_text(encoding="utf-8"))]
            log(f"{len(posts)} posts rechargés depuis {depuis}")
        else:
            from collecte import collecte_concurrents, collecte_instagram, collecte_posts, collecte_tiktok
            if mode == "veille":
                posts = collecte_concurrents(cfg, token)
            else:
                a = cfg["analyse"]
                jours = a["mois"] * 30
                ig = [c for pl, c in saisie["comptes"] if pl == "Instagram"]
                tt = [c for pl, c in saisie["comptes"] if pl == "TikTok"]
                posts = (collecte_instagram(ig, jours, a["posts_max_par_compte"], cfg, token)
                         + collecte_tiktok(tt, jours, a["posts_max_par_compte"], cfg, token)
                         + (collecte_posts(saisie["posts"], cfg, token) if saisie["posts"] else []))
            (esp.rapports / f"brut_{datetime.now():%Y-%m-%d_%H%M}.json").write_text(
                json.dumps([_post_vers_dict(p) for p in posts], ensure_ascii=False), encoding="utf-8")
            log(f"{len(posts)} publications collectées")
        if not posts:
            raise RuntimeError("Aucune publication récupérée. Vérifie les noms de comptes et qu'ils sont publics.")

        # ---------------- 2. Scores et candidats ----------------
        histo = selection.Historique(esp.historique)
        demandes = [p for p in posts if p.demande]
        classes = selection.calcule_scores([p for p in posts if not p.demande], cfg)
        # Les Reels donnés explicitement passent toujours, même s'ils ne remplissent pas les critères
        selection.calcule_scores_individuels(demandes, cfg)
        if mode == "veille":
            pool = selection.candidats(classes, cfg, histo)
        else:
            ok = [p for p in classes if p.criteres_ok]
            reste = [p for p in classes if not p.criteres_ok]
            pool = demandes + ok[:nb_adapter]
            if len(pool) < nb_adapter + len(demandes):
                pool += reste[:nb_adapter + len(demandes) - len(pool)]
        if max_adaptations is not None and len(pool) > max_adaptations:
            pool = pool[:max(max_adaptations, 1)]  # on reste dans le quota restant de la formule
        log(f"{len(pool)} Reels à analyser en profondeur")

        # ---------------- 3. Vidéos, commentaires, miniatures ----------------
        if demo:
            d.lit_videos(pool, travail / "media", esp.media)
        else:
            # Lecture des vidéos et collecte des commentaires en parallèle
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(max_workers=2) as ex:
                taches = []
                if cfg["video"].get("actif", True):
                    from video import traite_videos
                    taches.append(ex.submit(traite_videos, pool, cfg, token, travail / "media", esp.media))
                if cfg["commentaires"].get("actif", True) and token:
                    from commentaires import recupere
                    taches.append(ex.submit(recupere, pool, cfg, token))
                for t in taches:
                    t.result()

        tous = demandes + classes
        affiches = (demandes + [p for p in classes if p.criteres_ok] + pool + classes[:80])
        affiches = list({cle(p): p for p in affiches}.values())[:MAX_AFFICHES]
        if demo:
            d.miniatures(affiches, travail / "media", esp.media)
        elif not depuis:
            from video import miniatures
            miniatures(affiches, esp.media)

        # ---------------- 4. Apprentissage + voix ----------------
        from apprentissage import mon_compte, suivi_excel, synthese, voix
        ia = None
        if a_ia:
            from ia import IA
            ia = IA(cfg)
        if demo:
            appr = d.apprentissages()
        else:
            a_un_compte = any((cfg.get("mon_compte") or {}).values())
            mes_posts = mon_compte(cfg, token, ia) if (token and ia and a_un_compte) else []
            appr = synthese(mes_posts, suivi_excel([esp.suivi]))
            appr = complete_avec_profil(esp, appr)
        texte_voix = voix(cfg, esp.racine, appr.get("meilleures_legendes") or [])

        # ---------------- 5. Adaptation ----------------
        voix_client = {}
        if demo and not a_ia:
            for i, p in enumerate(pool):
                p.adaptation = d.adaptation(p, i)
            voix_client = d.voix_client()
        elif a_ia:
            ia = IA(cfg, voix=texte_voix, apprentissages=appr.get("texte", ""))
            ia.adapte_tous(pool)
            if cfg["commentaires"].get("synthese", True):
                voix_client = ia.voix_client(pool)

        # ---------------- 6. Planning (mode veille) ----------------
        planning = []
        if mode == "veille":
            semaine = selection.choix_final(pool, cfg, histo, appr) if (a_ia or demo) else pool[:besoin]
            selection.planifie(semaine, cfg)
            planning = [cle(p) for p in semaine]
            if a_ia and not demo:
                histo.enregistre(semaine)
        else:
            semaine = [p for p in pool if p.adaptation]

        # ---------------- 7. Découverte (mode veille) ----------------
        decouvertes = []
        if mode == "veille":
            if demo:
                decouvertes = d.decouvertes()
            elif cfg["decouverte"].get("actif") and token:
                memo = esp.racine / "decouverte.json"
                precedente = json.loads(memo.read_text(encoding="utf-8")) if memo.exists() else {}
                age = (datetime.now() - datetime.fromisoformat(precedente["date"])).days if precedente.get("date") else 999
                if age < DECOUVERTE_TOUS_LES_JOURS:
                    decouvertes = precedente.get("comptes") or []
                    log(f"Découverte de comptes : résultats du {precedente['date'][:10]} réutilisés (prochaine dans {DECOUVERTE_TOUS_LES_JOURS - age} j)")
                else:
                    from collecte import collecte_hashtags
                    from decouverte import ajoute_a_config, comptes_a_ajouter
                    try:
                        decouvertes = comptes_a_ajouter(collecte_hashtags(cfg, token), cfg)
                        memo.write_text(json.dumps({"date": datetime.now().isoformat(timespec="minutes"), "comptes": decouvertes},
                                                   ensure_ascii=False), encoding="utf-8")
                        if cfg["decouverte"].get("auto_ajout", 0):
                            ajoute_a_config(esp.config, decouvertes, cfg["decouverte"]["auto_ajout"])
                    except Exception as e:  # noqa: BLE001
                        log(f"⚠️  Découverte impossible : {e}")

        # ---------------- 8. Rapports et sauvegarde ----------------
        maintenant = datetime.now()
        aid = f"{maintenant:%Y%m%d-%H%M%S}-{mode}"
        if mode == "veille":
            titre = "Veille de la semaine"
        else:
            noms = [f"@{c}" for _, c in saisie["comptes"]] + [f"{len(saisie['posts'])} Reel(s) précis"] * bool(saisie["posts"])
            titre = "Analyse " + ", ".join(noms[:4]) + ("…" if len(noms) > 4 else "")
        stats = {
            "videos": len(tous), "comptes": len({(p.plateforme, p.compte) for p in tous}),
            "criteres_ok": len([p for p in classes if p.criteres_ok]),
            "exclus": len([p for p in classes if histo.deja_utilise(p)]) if mode == "veille" else 0,
            "adaptes": len([p for p in pool if p.adaptation and not p.adaptation.get("erreur")]),
            "videos_lues": len([p for p in pool if p.images]),
            "nb_commentaires": sum(len(p.commentaires_texte) for p in pool),
        }
        sortie = esp.rapports
        base = f"{'veille' if mode == 'veille' else 'copie'}_{maintenant:%Y-%m-%d_%H%M}"
        rapports.export_excel(semaine, sortie / f"{base}.xlsx", cfg, voix_client, decouvertes, appr)
        rapports.export_html(semaine, cfg, sortie / f"{base}.html", stats, voix_client, decouvertes, appr, esp.media)

        analyse = {
            "id": aid, "date": maintenant.isoformat(timespec="minutes"), "mode": mode, "titre": titre, "demo": demo,
            "saisie": saisie, "criteres": {k: cfg["analyse"][k] for k in ("mois", "vues_min", "taux_engagement_min")},
            "objectifs": o, "stats": stats, "planning": planning,
            "posts": [_post_vers_dict(p) for p in affiches],
            "voix_client": voix_client if not voix_client.get("erreur") else {},
            "decouvertes": decouvertes,
            "apprentissage": {k: appr.get(k) for k in ("par_mecanique", "mecaniques_top", "mecaniques_flop", "nb_reels", "nb_suivi", "texte")},
            "fichiers": {"html": f"{base}.html", "xlsx": f"{base}.xlsx"},
        }
        sauve(esp, analyse)
        log(f"✅ Analyse terminée : {stats['adaptes']} Reels adaptés")
        return analyse
    finally:
        shutil.rmtree(travail, ignore_errors=True)


# ------------------------------------------------------------
#  Adapter un Reel à la demande (depuis la galerie)
# ------------------------------------------------------------
def adapter_un(esp: Espace, cfg: dict, analyse_id: str, cle_post: str, demo: bool = False) -> dict:
    cfg = applique_plafonds(cfg)
    analyse = charge(esp, analyse_id)
    idx = next((i for i, x in enumerate(analyse["posts"]) if x["cle"] == cle_post), None)
    if idx is None:
        raise KeyError("Reel introuvable dans cette analyse")
    p = _dict_vers_post(analyse["posts"][idx])
    travail = Path(tempfile.mkdtemp(prefix="veille1_"))
    try:
        if demo or analyse.get("demo"):
            import demo as d
            d.lit_videos([p], travail, esp.media)
            p.adaptation = d.adaptation(p, idx)
        else:
            token = os.getenv("APIFY_TOKEN")
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise RuntimeError("Clé ANTHROPIC_API_KEY manquante.")
            if cfg["video"].get("actif", True):
                from video import traite_videos
                traite_videos([p], cfg, token, travail, esp.media)
            if token and cfg["commentaires"].get("actif", True):
                from commentaires import recupere
                recupere([p], cfg, token)
            from apprentissage import voix
            from ia import IA
            appr = analyse.get("apprentissage") or {}
            ia = IA(cfg, voix=voix(cfg, esp.racine, []), apprentissages=appr.get("texte") or "")
            ia.adapte_tous([p])
        analyse["posts"][idx] = _post_vers_dict(p)
        analyse["stats"]["adaptes"] = len([x for x in analyse["posts"] if x.get("adaptation") and not x["adaptation"].get("erreur")])
        sauve(esp, analyse)
        return analyse["posts"][idx]
    finally:
        shutil.rmtree(travail, ignore_errors=True)


# ------------------------------------------------------------
#  Assistant : analyse du compte de l'utilisateur
# ------------------------------------------------------------
def complete_avec_profil(esp: Espace, appr: dict) -> dict:
    """Si l'analyse du jour n'a pas pu lire le compte, on réutilise celle faite pendant la configuration."""
    if appr.get("par_mecanique") or not esp.profil_compte.exists():
        return appr
    try:
        prof = json.loads(esp.profil_compte.read_text(encoding="utf-8"))
        return {**appr, **(prof.get("apprentissage") or {})}
    except json.JSONDecodeError:
        return appr


def analyse_mon_compte(esp: Espace, cfg: dict, instagram: str = "", tiktok: str = "", demo: bool = False) -> dict:
    import statistics as st
    from apprentissage import synthese
    cfg = {**cfg, "mon_compte": {"instagram": instagram.strip().lstrip("@"), "tiktok": tiktok.strip().lstrip("@")}}
    if not (instagram or tiktok):
        raise RuntimeError("Indique au moins un compte Instagram ou TikTok.")
    if demo:
        import demo as d
        log("MODE DÉMO : compte fictif")
        posts = [p for p in d.posts_concurrents([("Instagram", instagram or tiktok)]) if p.format in ("Reel", "Vidéo")][:30]
        from modele import MECANIQUES
        for i, p in enumerate(posts):
            p.adaptation = {"mecanique": MECANIQUES[i % 7]}
            for k in ("vues", "likes", "commentaires", "partages", "enregistrements"):
                setattr(p, k, (getattr(p, k) or 0) // 8)
        d.miniatures(posts, Path(tempfile.mkdtemp()), esp.media)
        prop = d.profil()
        bio = d.bio(instagram or tiktok)
    else:
        token = os.getenv("APIFY_TOKEN")
        verifie_cle_claude()
        from apprentissage import mon_compte
        from ia import IA, propose_profil
        from video import miniatures
        log("Lecture de tes Reels…")
        posts = mon_compte(cfg, token, IA(cfg))
        if not posts:
            raise RuntimeError("Aucun Reel trouvé sur ce compte (vérifie qu'il est public et qu'il a publié ces 60 derniers jours).")
        miniatures(sorted(posts, key=lambda p: p.vues or 0, reverse=True)[:12], esp.media)
        from collecte import profil_reseaux
        log("Lecture de ta bio…")
        bio = profil_reseaux(cfg, token, cfg["mon_compte"]["instagram"], cfg["mon_compte"]["tiktok"])
        log("Claude analyse ton positionnement…")
        prop = None
    vues = [p.vues for p in posts if p.vues]
    er = [((p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)) / p.vues for p in posts if p.vues]
    com = [(p.commentaires or 0) / p.vues for p in posts if p.vues]
    chiffres = {"reels": len(posts), "vues_mediane": int(st.median(vues)) if vues else 0, "vues_max": max(vues) if vues else 0,
                "engagement_median": round(st.median(er), 4) if er else None, "commentaires_par_vue": round(st.median(com), 5) if com else None}
    if prop is None:
        prop = propose_profil(cfg, sorted(posts, key=lambda p: p.vues or 0, reverse=True),
                              f"{chiffres['reels']} Reels, médiane {chiffres['vues_mediane']} vues", bio)
    appr = synthese(posts, [])
    top = sorted(posts, key=lambda p: p.vues or 0, reverse=True)[:6]
    profil = {
        "date": datetime.now().isoformat(timespec="minutes"), "instagram": instagram, "tiktok": tiktok, "chiffres": chiffres, "bio": bio,
        "top": [{"cle": cle(p), "miniature": p.miniature, "vues": p.vues, "legende": p.legende[:160], "url": p.url,
                 "mecanique": (p.adaptation or {}).get("mecanique")} for p in top],
        "proposition": prop if not prop.get("erreur") else {},
        "apprentissage": {k: appr.get(k) for k in ("par_mecanique", "mecaniques_top", "mecaniques_flop", "nb_reels", "texte", "meilleures_legendes")},
    }
    esp.profil_compte.write_text(json.dumps(profil, ensure_ascii=False), encoding="utf-8")
    log("✅ Analyse de ton compte terminée")
    return profil


def suggere_hashtags(cfg: dict, demo: bool = False) -> dict:
    if demo:
        return {"instagram": ["nutritionfemme", "ventreplat", "reequilibragealimentaire", "grignotage", "energie", "mincirsansregime"],
                "tiktok": ["nutrition", "ventregonfle", "astucesante", "recettehealthy", "perdredupoids", "bienetre"]}
    from ia import propose_hashtags
    return propose_hashtags(cfg)
