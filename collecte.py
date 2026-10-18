"""Collecte des publications via Apify (Instagram, TikTok, hashtags)."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from modele import Post, date_utc, entier, log

APIFY_BASE = "https://api.apify.com/v2"

# Collecteur de Reels par profil : ~0,05 $ / 1 000 Reels (contre ~2,30 $ pour apify/instagram-scraper).
# En cas d'échec sur un compte, repli automatique sur apify/instagram-scraper.
ACTOR_REELS_ECO = os.getenv("APIFY_ACTOR_REELS", "esdrasdw~instagram-content-scraper")
CHAMPS_REELS = ["displayUrl", "title", "ownerUsername", "url", "timestamp", "videoPlayCount", "likesCount", "commentsCount",
                "videoDuration", "videoUrl", "shortCode", "id", "caption", "type", "productType", "childPosts", "images", "musicInfo", "hasAudio"]
MAX_SLIDES = 10

# Coût réel des runs Apify (une analyse à la fois : un compteur global suffit)
_COUT = {"usd": 0.0}
_COUT_VERROU = threading.Lock()


def cout_apify_reinitialise():
    with _COUT_VERROU:
        _COUT["usd"] = 0.0


def cout_apify() -> float:
    return round(_COUT["usd"], 3)


def apify_run(actor: str, payload: dict, token: str, timeout_min: int = 30) -> list[dict]:
    """Lance un actor Apify, attend la fin, renvoie les éléments du dataset."""
    for essai in range(10):
        r = requests.post(f"{APIFY_BASE}/acts/{actor}/runs", params={"token": token}, json=payload, timeout=60)
        texte = r.text[:400].lower()
        # Trop de runs simultanés ou mémoire du compte saturée : on patiente au lieu d'échouer
        if r.status_code in (402, 429) and any(x in texte for x in ("memory", "concurren", "rate", "too many")) and essai < 9:
            time.sleep(15)
            continue
        if r.status_code >= 400:
            if "usage" in texte and ("limit" in texte or "exceed" in texte):
                raise RuntimeError("Crédit Apify épuisé pour ce mois : passe au plan Starter sur apify.com (Billing) ou attends le renouvellement.")
            raise RuntimeError(f"Apify {actor} : {r.status_code} {r.text[:300]}")
        break
    run = r.json()["data"]
    run_id, dataset_id = run["id"], run["defaultDatasetId"]

    limite = time.time() + timeout_min * 60
    while True:
        s = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", params={"token": token}, timeout=60).json()["data"]
        if s["status"] == "SUCCEEDED":
            with _COUT_VERROU:
                _COUT["usd"] += float(s.get("usageTotalUsd") or 0)
            break
        if s["status"] in ("FAILED", "ABORTED", "TIMED-OUT"):
            with _COUT_VERROU:
                _COUT["usd"] += float(s.get("usageTotalUsd") or 0)
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
    return items


def _iso(v) -> str:
    d = date_utc(v)
    return d.isoformat() if d else ""


# ------------------------------------------------------------
#  Normalisation
# ------------------------------------------------------------
def url_image(c) -> str | None:
    """URL de l'image d'une slide de carrousel, quel que soit le format renvoyé par le collecteur."""
    if isinstance(c, str):
        return c if c.startswith("http") else None
    if not isinstance(c, dict):
        return None
    for k in ("displayUrl", "display_url", "imageUrl", "image_url", "thumbnailUrl", "thumbnail_url", "url", "src"):
        v = c.get(k)
        if isinstance(v, str) and v.startswith("http") and "instagram.com/p/" not in v:
            return v
    for k in ("images", "image_versions2", "candidates", "imageVersions"):
        v = c.get(k)
        if isinstance(v, dict):
            v = v.get("candidates") or list(v.values())
        if isinstance(v, list):
            for x in v:
                u = url_image(x)
                if u:
                    return u
    return None


def _premier(d: dict, *cles):
    for k in cles:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def son_instagram(it: dict) -> dict:
    """Son utilisé par un Reel (musique ou son original), quel que soit le format renvoyé par le collecteur."""
    m = it.get("musicInfo") or {}
    if not isinstance(m, dict) or not m:
        return {}
    m = {**m, **(m.get("music_info") or {}), **(m.get("music_asset_info") or {}), **(m.get("original_sound_info") or {})}
    titre = _premier(m, "song_name", "songName", "title", "original_audio_title", "audio_title")
    artiste = _premier(m, "artist_name", "artistName", "display_artist", "ig_artist_username", "artist")
    if isinstance(artiste, dict):
        artiste = artiste.get("username") or artiste.get("full_name")
    original = bool(_premier(m, "uses_original_audio", "usesOriginalAudio", "is_original_audio", "is_original")) or (
        bool(m.get("original_audio_title")) and not m.get("song_name"))
    ident = _premier(m, "audio_id", "audioId", "audio_asset_id", "audio_cluster_id", "id")
    if not (titre or artiste or ident):
        return {}
    return {"titre": str(titre or ("Son original" if original else "")), "artiste": str(artiste or ""), "original": original,
            "url": f"https://www.instagram.com/reels/audio/{ident}/" if ident else ""}


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
        date=_iso(it.get("timestamp") or it.get("takenAt") or it.get("taken_at")),
        format=fmt,
        legende=it.get("caption") or "",
        likes=entier(it.get("likesCount")),
        commentaires=entier(it.get("commentsCount")),
        vues=entier(it.get("videoPlayCount") or it.get("videoViewCount")),
        video_url=it.get("videoUrl"),
        cover_url=it.get("displayUrl") or (it.get("images") or [None])[0],
        duree_s=it.get("videoDuration"),
    )
    if fmt == "Reel":
        p.son = son_instagram(it)
    if fmt == "Carrousel":
        for c in (it.get("childPosts") or it.get("carouselMedia") or it.get("sidecarChildren") or [])[:MAX_SLIDES]:
            u = url_image(c)
            if u and u not in p.medias:
                p.medias.append(u)
        if not p.medias and p.cover_url:
            p.medias = [p.cover_url]  # au minimum la couverture : c'est elle qui porte le hook
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
    mu = it.get("musicMeta") or {}
    son = {}
    if mu.get("musicName") or mu.get("musicId"):
        son = {"titre": mu.get("musicName") or "", "artiste": mu.get("musicAuthor") or "", "original": bool(mu.get("musicOriginal")),
               "url": f"https://www.tiktok.com/music/son-{mu['musicId']}" if mu.get("musicId") else ""}
    return Post(son=son,
        plateforme="TikTok",
        compte=auteur.get("name") or auteur.get("uniqueId") or "?",
        id=str(it["id"]),
        url=it.get("webVideoUrl") or "",
        date=_iso(it.get("createTimeISO") or it.get("createTime")),
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
    if ACTOR_REELS_ECO:
        try:
            items = apify_run(ACTOR_REELS_ECO, {
                # « posts » : Reels ET carrousels (avec l'image de chaque slide), même prix que les Reels seuls
                "directUrls": [c.strip("@") for c in comptes], "resultsType": "posts", "resultsLimit": max_par_compte,
                "onlyPostsNewerThan": f"{jours} days", "skipPinnedPosts": True, "selectedFields": CHAMPS_REELS,
            }, token)
            posts = [p for p in map(post_instagram, items) if p]
            if posts:
                return posts
            log(f"  Collecteur économique sans résultat pour {', '.join(comptes)} : repli sur le collecteur standard")
        except Exception as e:  # noqa: BLE001
            log(f"  Collecteur économique indisponible ({str(e)[:100]}) : repli sur le collecteur standard")
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


# ------------------------------------------------------------
#  Collecte parallèle par compte, avec cache partagé de 24 h
# ------------------------------------------------------------
CACHE_HEURES = 24
PARALLELE = 4   # runs Apify simultanés (le plan gratuit en autorise 5)


def _cache_dir():
    from espace import DATA
    d = DATA / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_fichier(plateforme: str, compte: str):
    # v2 : Reels + carrousels (les anciens caches ne contenaient que les Reels)
    return _cache_dir() / f"v2_{plateforme.lower()}_{compte.lower().strip('@')}.json"


def cache_frais(plateforme: str, compte: str, jours: int, maxi: int) -> list[Post] | None:
    """Publications d'un compte collectées il y a moins de 24 h (partagées entre tous les clients)."""
    import json
    f = _cache_fichier(plateforme, compte)
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        age = datetime.now() - datetime.fromisoformat(d["date"])
        if age > timedelta(hours=CACHE_HEURES) or d.get("jours", 0) < jours or d.get("max", 0) < min(maxi, d.get("n", 0) + 1):
            return None
        return [Post(**{k: v for k, v in x.items() if k in Post.__dataclass_fields__}) for x in d["posts"]]
    except (ValueError, KeyError, TypeError):
        return None


def _met_en_cache(plateforme: str, compte: str, jours: int, maxi: int, posts: list[Post]):
    import json
    from dataclasses import asdict
    garde = ("plateforme", "compte", "id", "url", "date", "format", "legende", "likes", "commentaires", "vues",
             "partages", "enregistrements", "video_url", "cover_url", "duree_s", "commentaires_texte", "medias", "son")
    _cache_fichier(plateforme, compte).write_text(json.dumps({
        "date": datetime.now().isoformat(timespec="seconds"), "jours": jours, "max": maxi, "n": len(posts),
        "posts": [{k: v for k, v in asdict(p).items() if k in garde} for p in posts]}, ensure_ascii=False), encoding="utf-8")


def collecte_comptes(comptes: list[tuple[str, str]], jours: int, maxi: int, cfg: dict, token: str) -> list[Post]:
    """Collecte chaque compte dans son propre run Apify, en parallèle, et réutilise les collectes de moins de 24 h."""
    import concurrent.futures as cf
    comptes = list(dict.fromkeys((pl, c.strip("@")) for pl, c in comptes if c))
    if not comptes:
        return []
    posts, a_collecter = [], []
    for pl, c in comptes:
        cache = cache_frais(pl, c, jours, maxi)
        if cache is not None:
            posts += cache
        else:
            a_collecter.append((pl, c))
    if len(comptes) > len(a_collecter):
        log(f"Collecte : {len(comptes) - len(a_collecter)} compte(s) déjà collecté(s) il y a moins de {CACHE_HEURES} h, réutilisé(s)")
    if not a_collecter:
        return posts
    log(f"Collecte de {len(a_collecter)} compte(s) en parallèle sur Apify…")

    def un(pl_c):
        pl, c = pl_c
        fn = collecte_instagram if pl == "Instagram" else collecte_tiktok
        res = fn([c], jours, maxi, cfg, token)
        _met_en_cache(pl, c, jours, maxi, res)
        return res

    erreurs, faits = [], 0
    with cf.ThreadPoolExecutor(max_workers=PARALLELE) as ex:
        futures = {ex.submit(un, x): x for x in a_collecter}
        for f in cf.as_completed(futures):
            pl, c = futures[f]
            faits += 1
            try:
                res = f.result()
                posts += res
                log(f"  {faits}/{len(a_collecter)} — {pl} @{c} : {len(res)} publications")
            except Exception as e:  # noqa: BLE001
                erreurs.append(str(e))
                log(f"  {faits}/{len(a_collecter)} — ⚠️  {pl} @{c} : {str(e)[:160]}")
    if erreurs and len(erreurs) == len(a_collecter) and not posts:
        raise RuntimeError(erreurs[0])
    return posts


def collecte_concurrents(cfg: dict, token: str) -> list[Post]:
    a, c = cfg["analyse"], cfg["comptes"]
    comptes = [("Instagram", x) for x in c.get("instagram") or []] + [("TikTok", x) for x in c.get("tiktok") or []]
    return collecte_comptes(comptes, a["mois"] * 30, a["posts_max_par_compte"], cfg, token)


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
