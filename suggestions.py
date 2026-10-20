"""
Comptes à copier suggérés : Claude propose des candidats, puis chacun est vérifié par une vraie collecte
(collecteur économique, quelques centimes) — on ne garde que les comptes qui existent et dont les publications performent.
"""

from __future__ import annotations

import re
import statistics

from modele import log

PUBLICATIONS_PAR_COMPTE = 12
# TikTok : collecte environ 30 fois plus chère qu'Instagram → moins de candidats et moins de vidéos par compte
CANDIDATS = {"Instagram": 18, "TikTok": 12}
PUBLICATIONS = {"Instagram": PUBLICATIONS_PAR_COMPTE, "TikTok": 8}


def _propre(pseudo: str) -> str:
    return re.sub(r"[^a-z0-9._]", "", (pseudo or "").lower().strip().lstrip("@"))


def suggere(cfg: dict, token: str | None, demo: bool = False, plateforme: str = "Instagram") -> list[dict]:
    plateforme = "TikTok" if plateforme == "TikTok" else "Instagram"
    deja = [c.lower() for c in (cfg["comptes"].get(plateforme.lower()) or [])]
    if demo:
        log(f"Je cherche des comptes {plateforme} qui cartonnent dans ta niche…")
        return [{"plateforme": plateforme, "compte": f"{plateforme.lower()}_demo_{i}",
                 "pourquoi": "[démo] Vidéos « erreurs à éviter » très partagées" if plateforme == "TikTok" else "[démo] Carrousels « erreurs à éviter » très partagés",
                 "vues_mediane": v, "likes_median": v // 30, "publications": 12, "reels": 9, "carrousels": 3,
                 "exemple": "https://example.com/demo"} for i, v in enumerate((240000, 180000, 96000, 61000, 42000), 1)]
    from collecte import collecte_comptes
    from ia import propose_comptes
    log(f"Virall.ai cherche des comptes {plateforme} qui cartonnent dans ta niche…")
    candidats = {}
    for x in propose_comptes(cfg, deja, plateforme, CANDIDATS[plateforme]):
        ps = _propre(x["pseudo"])
        if ps and ps not in deja and ps not in candidats:
            candidats[ps] = x.get("pourquoi", "")
    if not candidats:
        return []
    log(f"Je vérifie {len(candidats)} comptes (existence et audience réelle)…")
    # Un compte par collecte (comme la veille) : la limite de publications du collecteur porte sur l'ensemble d'une
    # collecte, pas sur chaque compte. Les comptes déjà collectés depuis moins de 24 h sont réutilisés.
    posts = collecte_comptes([(plateforme, ps) for ps in candidats], 90, PUBLICATIONS[plateforme], cfg, token)
    par_compte: dict[str, list] = {}
    for p in posts:
        par_compte.setdefault(p.compte.lower(), []).append(p)
    res = []
    for ps, pourquoi in candidats.items():
        lst = par_compte.get(ps) or []
        if len(lst) < 3:
            continue  # compte inexistant, privé ou inactif
        vues = [p.vues for p in lst if p.vues]
        likes = [p.likes for p in lst if p.likes]
        meilleur = max(lst, key=lambda p: (p.vues or 0) + 30 * (p.likes or 0))
        res.append({"plateforme": plateforme, "compte": ps, "pourquoi": pourquoi,
                    "vues_mediane": int(statistics.median(vues)) if vues else None,
                    "likes_median": int(statistics.median(likes)) if likes else None,
                    "publications": len(lst), "reels": sum(1 for p in lst if p.format == "Reel"),
                    "carrousels": sum(1 for p in lst if p.format == "Carrousel"), "exemple": meilleur.url})
    res.sort(key=lambda r: (r["vues_mediane"] or 0) + 30 * (r["likes_median"] or 0), reverse=True)
    log(f"✅ {len(res)} compte(s) vérifié(s)")
    return res[:10]
