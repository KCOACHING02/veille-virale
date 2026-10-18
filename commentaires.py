"""Récupération des commentaires des Reels retenus (la voix du client idéal)."""

from __future__ import annotations

import re

from collecte import apify_run
from modele import Post, entier, log

_EMOJI_SEUL = re.compile(r"^[\W_\d\s]*$", re.UNICODE)


def utile(texte: str) -> bool:
    """Écarte les commentaires sans contenu : emojis seuls, tags seuls, « 🔥🔥 », « top »…"""
    t = re.sub(r"@\w[\w.]*", "", texte or "").strip()
    return len(t) >= 8 and not _EMOJI_SEUL.match(t)


def _rattache(items: list[dict], posts: list[Post], champs: tuple[str, ...], plateforme: str):
    for it in items:
        texte = it.get("text") or ""
        if not utile(texte):
            continue
        source = " ".join(str(it.get(c) or "") for c in champs)
        for p in posts:
            if p.plateforme == plateforme and p.id in source:
                p.commentaires_texte.append({"texte": texte, "likes": entier(it.get("likesCount") or it.get("diggCount")) or 0})
                break


def recupere(posts: list[Post], cfg: dict, token: str):
    c = cfg["commentaires"]
    n = c["par_post"]
    ig = [p for p in posts if p.plateforme == "Instagram"]
    tt = [p for p in posts if p.plateforme == "TikTok"]

    if ig:
        log(f"Commentaires Instagram ({len(ig)} Reels)")
        try:
            items = apify_run(cfg["apify"]["actor_instagram"], {
                "directUrls": [p.url for p in ig], "resultsType": "comments", "resultsLimit": n,
            }, token)
            _rattache(items, ig, ("postUrl", "inputUrl", "url", "input"), "Instagram")
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  {e} — on garde les derniers commentaires fournis avec les posts")
    if tt:
        log(f"Commentaires TikTok ({len(tt)} vidéos)")
        try:
            items = apify_run(c["actor_tiktok"], {
                "postURLs": [p.url for p in tt], "commentsPerPost": n, "maxRepliesPerComment": 0,
            }, token)
            _rattache(items, tt, ("videoWebUrl", "awemeId", "aweme_id", "postUrl", "input"), "TikTok")
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  {e}")

    # Dédoublonnage, nettoyage, tri par likes
    for p in posts:
        vus, propres = set(), []
        for com in p.commentaires_texte:
            cle = com["texte"].strip().lower()
            if cle not in vus and utile(com["texte"]):
                vus.add(cle)
                propres.append(com)
        p.commentaires_texte = sorted(propres, key=lambda x: x["likes"], reverse=True)[:n]
    log(f"  {sum(len(p.commentaires_texte) for p in posts)} commentaires utiles au total")
