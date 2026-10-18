"""Collecte des publications via Apify (Instagram, TikTok, hashtags)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

from modele import Post, entier, log

APIFY_BASE = "https://api.apify.com/v2"


def apify_run(actor: str, payload: dict, token: str, timeout_min: int = 30) -> list[dict]:
    """Lance un actor Apify, attend la fin, renvoie les éléments du dataset."""
    r = requests.post(f"{APIFY_BASE}/acts/{actor}/runs", params={"token": token}, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Apify {actor} : {r.status_code} {r.text[:300]}")
    run = r.json()["data"]
    run_id, dataset_id = run["id"], run["defaultDatasetId"]
    log(f"  Apify {actor} lancé")

    limite = time.time() + timeout_min * 60
    while True:
        s = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=60).json()["data"]
        if s["status"] == "SUCCEEDED":
            break
        if s["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Run Apify {actor} terminé en {s['status']}")
        if time.time() > limite:
            raise TimeoutError(f"Run Apify {actor} trop long (> {timeout_min} min)")
        time.sleep(8)

    items, offset = [], 0
    while True:
        page = requests.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": token, "clean": "true", "format": "json", "offset": offset, "limit": 1000},
            timeout=120,
        ).json()
        items.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    log(f"  {len(items)} éléments récupérés")
    return items


# ------------------------------------------------------------
#  Normalisation
# ------------------------------------------------------------
def post_instagram(it: dict) -> Post | None:
    if it.get("error") or not (it.get("shortCode") or it.get("id")):
        return None
    typ = (it.get("productType") or it.get("type") or "").lower()
    fmt = "Reel" if typ in ("clips", "video") or it.get("videoPlayCount") or it.get("videoUrl") else (
        "Carrousel" if typ in ("sidecar", "carousel_container") else "Photo")
    p = Post(
        plateforme="Instagram",
        compte=it.get("ownerUsername") or "?",
        id=str(it.get("shortCode") or it.get("id")),
        url=it.get("url") or f"https://www.instagram.com/p/{it.get('shortCode')}/",
        date=it.get("timestamp") or "",
        format=fmt,
        legende=it.get("caption") or "",
        likes=entier(it.get("likesCount")),
        commentaires=entier(it.get("commentsCount")),
        vues=entier(it.get("videoPlayCount") or it.get("videoViewCount")),
        video_url=it.get("videoUrl"),
        cover_url=it.get("displayUrl") or (it.get("images") or [None])[0],
        duree_s=it.get("videoDuration"),
    )
    # Les derniers commentaires sont souvent fournis gratuitement avec le post
    for c in it.get("latestComments") or []:
        if c.get("text"):
            p.commentaires_texte.append({"texte": c["text"], "likes": entier(c.get("likesCount")) or 0})
    return p


def post_tiktok(it: dict) -> Post | None:
    if it.get("error") or not it.get("id"):
        return None
    auteur = it.get("authorMeta") or {}
    video = it.get("videoMeta") or {}
    return Post(
        plateforme="TikTok",
        compte=auteur.get("name") or auteur.get("uniqueId") or "?",
        id=str(it["id"]),
        url=it.get("webVideoUrl") or "",
        date=it.get("createTimeISO") or "",
        format="Carrousel" if it.get("isSlideshow") else "Vidéo",
        legende=it.get("text") or "",
        likes=entier(it.get("diggCount")),
        commentaires=entier(it.get("commentCount")),
        vues=entier(it.get("playCount")),
        partages=entier(it.get("shareCount")),
        enregistrements=entier(it.get("collectCount")),
        duree_s=video.get("duration"),
        cover_url=video.get("coverUrl") or video.get("originalCoverUrl") or (it.get("covers") or [None])[0],
    )


# ------------------------------------------------------------
#  Collecte par comptes
# ------------------------------------------------------------
def collecte_instagram(comptes: list[str], jours: int, max_par_compte: int, cfg: dict, token: str) -> list[Post]:
    if not comptes:
        return []
    log(f"Instagram : {len(comptes)} compte(s), {jours} jours")
    items = apify_run(cfg["apify"]["actor_instagram"], {
        "directUrls": [f"https://www.instagram.com/{c.strip('@')}/" for c in comptes],
        "resultsType": "posts",
        "resultsLimit": max_par_compte,
        "onlyPostsNewerThan": f"{jours} days",
        "addParentData": False,
    }, token)
    return [p for p in map(post_instagram, items) if p]


def collecte_tiktok(comptes: list[str], jours: int, max_par_compte: int, cfg: dict, token: str) -> list[Post]:
    if not comptes:
        return []
    log(f"TikTok : {len(comptes)} compte(s), {jours} jours")
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%d")
    items = apify_run(cfg["apify"]["actor_tiktok"], {
        "profiles": [c.strip("@") for c in comptes],
        "profileScrapeSections": ["videos"],
        "profileSorting": "latest",
        "resultsPerPage": max_par_compte,
        "oldestPostDateUnified": depuis,
        "excludePinnedPosts": True,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }, token)
    return [p for p in map(post_tiktok, items) if p]


def collecte_concurrents(cfg: dict, token: str) -> list[Post]:
    a, c = cfg["analyse"], cfg["comptes"]
    jours = a["mois"] * 30
    # Instagram et TikTok sont collectés en parallèle
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        ig = ex.submit(collecte_instagram, c.get("instagram") or [], jours, a["posts_max_par_compte"], cfg, token)
        tt = ex.submit(collecte_tiktok, c.get("tiktok") or [], jours, a["posts_max_par_compte"], cfg, token)
        return ig.result() + tt.result()


# ------------------------------------------------------------
#  Collecte par hashtags (découverte de comptes)
# ------------------------------------------------------------
def collecte_hashtags(cfg: dict, token: str) -> list[Post]:
    d = cfg["decouverte"]
    posts = []
    tags_ig = [t.strip("#") for t in d.get("hashtags_instagram") or []]
    tags_tt = [t.strip("#") for t in d.get("hashtags_tiktok") or []]
    if tags_ig:
        log(f"Découverte Instagram : {len(tags_ig)} hashtag(s)")
        items = apify_run(cfg["apify"]["actor_instagram"], {
            "directUrls": [f"https://www.instagram.com/explore/tags/{t}/" for t in tags_ig],
            "resultsType": "posts",
            "resultsLimit": d["posts_par_hashtag"],
            "onlyPostsNewerThan": f"{cfg['analyse']['mois'] * 30} days",
        }, token)
        posts += [p for p in map(post_instagram, items) if p]
    if tags_tt:
        log(f"Découverte TikTok : {len(tags_tt)} hashtag(s)")
        items = apify_run(cfg["apify"]["actor_tiktok"], {
            "hashtags": tags_tt,
            "resultsPerPage": d["posts_par_hashtag"],
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        }, token)
        posts += [p for p in map(post_tiktok, items) if p]
    return posts


# ------------------------------------------------------------
#  Reels précis donnés par l'utilisateur (liens)
# ------------------------------------------------------------
def collecte_posts(liens: list[tuple[str, str]], cfg: dict, token: str) -> list[Post]:
    ig = [u for pl, u in liens if pl == "Instagram"]
    tt = [u for pl, u in liens if pl == "TikTok"]
    posts = []
    if ig:
        log(f"Instagram : {len(ig)} Reel(s) précis")
        items = apify_run(cfg["apify"]["actor_instagram"], {"directUrls": ig, "resultsType": "posts", "resultsLimit": 1}, token)
        posts += [p for p in map(post_instagram, items) if p]
    if tt:
        log(f"TikTok : {len(tt)} vidéo(s) précise(s)")
        items = apify_run(cfg["apify"]["actor_tiktok"], {"postURLs": tt, "shouldDownloadVideos": False,
                                                          "shouldDownloadCovers": False}, token)
        posts += [p for p in map(post_tiktok, items) if p]
    for p in posts:
        p.demande = True
    return posts


# ------------------------------------------------------------
#  Profil (bio, nom, lien, abonnés) d'un compte
# ------------------------------------------------------------
def profil_reseaux(cfg: dict, token: str, instagram: str = "", tiktok: str = "") -> dict:
    """Bio et informations publiques du profil. Ne bloque jamais l'analyse en cas d'échec."""
    res = {}
    if instagram:
        try:
            items = apify_run(cfg["apify"]["actor_instagram"], {
                "directUrls": [f"https://www.instagram.com/{instagram.strip('@')}/"], "resultsType": "details", "resultsLimit": 1,
            }, token)
            it = next((x for x in items if x.get("username") or x.get("biography") is not None), {})
            if it:
                res["instagram"] = {
                    "nom": it.get("fullName") or "", "bio": it.get("biography") or "", "lien": it.get("externalUrl") or "",
                    "abonnes": entier(it.get("followersCount")), "publications": entier(it.get("postsCount")),
                    "categorie": it.get("businessCategoryName") or "",
                }
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  Bio Instagram indisponible : {e}")
    if tiktok:
        try:
            items = apify_run(cfg["apify"]["actor_tiktok"], {
                "profiles": [tiktok.strip("@")], "resultsPerPage": 1, "shouldDownloadVideos": False, "shouldDownloadCovers": False,
            }, token)
            a = next((x.get("authorMeta") for x in items if x.get("authorMeta")), {}) or {}
            if a:
                res["tiktok"] = {"nom": a.get("nickName") or "", "bio": a.get("signature") or "",
                                 "lien": a.get("bioLink") or "", "abonnes": entier(a.get("fans"))}
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  Bio TikTok indisponible : {e}")
    return res
