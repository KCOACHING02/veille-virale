"""Découverte de nouveaux comptes à surveiller, à partir des hashtags de la niche."""

from __future__ import annotations

import statistics

import yaml

from modele import Post, log


def comptes_a_ajouter(posts_hashtags: list[Post], cfg: dict) -> list[dict]:
    a, d = cfg["analyse"], cfg["decouverte"]
    connus = {(pl, c.lower().strip("@")) for pl, lst in (("Instagram", cfg["comptes"].get("instagram") or []),
                                                         ("TikTok", cfg["comptes"].get("tiktok") or [])) for c in lst}
    m = cfg.get("mon_compte") or {}
    connus |= {("Instagram", (m.get("instagram") or "").lower()), ("TikTok", (m.get("tiktok") or "").lower())}

    par_compte: dict[tuple, list[Post]] = {}
    for p in posts_hashtags:
        if p.format not in ("Reel", "Vidéo") or not p.vues or (p.plateforme, p.compte.lower()) in connus:
            continue
        par_compte.setdefault((p.plateforme, p.compte), []).append(p)

    resultats = []
    for (plat, compte), lst in par_compte.items():
        forts = [p for p in lst if p.vues >= a["vues_min"]]
        if len(forts) < d["min_reels_au_dessus_seuil"]:
            continue
        meilleur = max(forts, key=lambda p: p.vues)
        er = [((p.likes or 0) + (p.commentaires or 0) + (p.partages or 0) + (p.enregistrements or 0)) / p.vues for p in forts]
        resultats.append({
            "plateforme": plat, "compte": compte, "reels_au_dessus_seuil": len(forts),
            "vues_max": meilleur.vues, "engagement_median": round(statistics.median(er), 4),
            "exemple": meilleur.url, "legende": meilleur.legende[:120],
        })
    resultats.sort(key=lambda r: (r["reels_au_dessus_seuil"], r["vues_max"]), reverse=True)
    log(f"Découverte : {len(resultats)} nouveau(x) compte(s) qui dépassent {a['vues_min']:,} vues".replace(",", " "))
    return resultats[:d["max_suggestions"]]


def ajoute_a_config(chemin_config, suggestions: list[dict], nb: int):
    """Option auto_ajout : ajoute les N meilleurs comptes découverts à config.yaml (commentaires du fichier perdus)."""
    if not suggestions or nb <= 0:
        return []
    cfg = yaml.safe_load(chemin_config.read_text(encoding="utf-8"))
    ajoutes = []
    for s in suggestions[:nb]:
        cle = "instagram" if s["plateforme"] == "Instagram" else "tiktok"
        lst = cfg["comptes"].setdefault(cle, []) or []
        if s["compte"] not in lst:
            lst.append(s["compte"])
            cfg["comptes"][cle] = lst
            ajoutes.append(f"{s['plateforme']} @{s['compte']}")
    if ajoutes:
        chemin_config.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        log(f"  Ajoutés automatiquement à config.yaml : {', '.join(ajoutes)}")
    return ajoutes
