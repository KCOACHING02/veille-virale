"""
Comptes à copier suggérés : Claude propose des candidats, puis chacun est vérifié par une vraie collecte
(collecteur économique, quelques centimes) — on ne garde que les comptes qui existent et dont les publications performent.
"""

from __future__ import annotations

import re
import statistics

from modele import log

PUBLICATIONS_PAR_COMPTE = 12


def _propre(pseudo: str) -> str:
    return re.sub(r"[^a-z0-9._]", "", (pseudo or "").lower().strip().lstrip("@"))


def suggere(cfg: dict, token: str | None, demo: bool = False) -> list[dict]:
    deja = [c.lower() for c in (cfg["comptes"].get("instagram") or [])]
    if demo:
        log("Je cherche des comptes qui cartonnent dans ta niche…")
        return [{"plateforme": "Instagram", "compte": f"compte_demo_{i}", "pourquoi": "[démo] Carrousels « erreurs à éviter » très partagés",
                 "vues_mediane": v, "likes_median": v // 30, "publications": 12, "reels": 9, "carrousels": 3,
                 "exemple": "https://example.com/demo"} for i, v in enumerate((240000, 180000, 96000, 61000, 42000), 1)]
    from collecte import collecte_instagram
    from ia import propose_comptes
    log("Virall.ai cherche des comptes qui cartonnent dans ta niche…")
    candidats = {}
    for x in propose_comptes(cfg, deja):
        ps = _propre(x["pseudo"])
        if ps and ps not in deja and ps not in candidats:
            candidats[ps] = x.get("pourquoi", "")
    if not candidats:
        return []
    log(f"Je vérifie {len(candidats)} comptes (existence et audience réelle)…")
    posts = collecte_instagram(list(candidats), 90, PUBLICATIONS_PAR_COMPTE, cfg, token)
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
        res.append({"plateforme": "Instagram", "compte": ps, "pourquoi": pourquoi,
                    "vues_mediane": int(statistics.median(vues)) if vues else None,
                    "likes_median": int(statistics.median(likes)) if likes else None,
                    "publications": len(lst), "reels": sum(1 for p in lst if p.format == "Reel"),
                    "carrousels": sum(1 for p in lst if p.format == "Carrousel"), "exemple": meilleur.url})
    res.sort(key=lambda r: (r["vues_mediane"] or 0) + 30 * (r["likes_median"] or 0), reverse=True)
    log(f"✅ {len(res)} compte(s) vérifié(s)")
    return res[:10]
