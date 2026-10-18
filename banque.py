"""
Banque d'images et de vidéos libres de droits, gratuites et utilisables commercialement :
  - Pixabay (clé immédiate : https://pixabay.com/api/docs/ une fois connecté) → variable PIXABAY_API_KEY
  - Pexels (si une clé existe déjà) → variable PEXELS_API_KEY
Pixabay est utilisé en priorité. Sans clé, en mode démo, des images de démonstration sont générées localement.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

from espace import DATA

API = "https://api.pexels.com"
CACHE_JOURS = 7


def fournisseur() -> str | None:
    if os.getenv("PIXABAY_API_KEY"):
        return "pixabay"
    if os.getenv("PEXELS_API_KEY"):
        return "pexels"
    return None


def nom_source() -> str:
    return {"pixabay": "Pixabay", "pexels": "Pexels"}.get(fournisseur() or "", "démo")


def active() -> bool:
    return fournisseur() is not None


def _cache(cle: str) -> Path:
    d = DATA / "cache" / "banque"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(cle.encode()).hexdigest()[:20] + ".json")


def _get(chemin: str, params: dict) -> dict:
    f = _cache(chemin + json.dumps(params, sort_keys=True))
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_JOURS * 86400:
        return json.loads(f.read_text(encoding="utf-8"))
    r = requests.get(API + chemin, params=params, headers={"Authorization": os.environ["PEXELS_API_KEY"].strip()}, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("La banque d'images est très sollicitée : réessaie dans quelques minutes.")
    if r.status_code >= 400:
        raise RuntimeError(f"Banque d'images indisponible ({r.status_code}).")
    d = r.json()
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def _pixabay(chemin: str, params: dict) -> dict:
    """Pixabay impose un cache de 24 h et ses liens d'images expirent après 24 h : cache de 20 h."""
    f = _cache("pixabay" + chemin + json.dumps(params, sort_keys=True))
    if f.exists() and time.time() - f.stat().st_mtime < 20 * 3600:
        return json.loads(f.read_text(encoding="utf-8"))
    r = requests.get("https://pixabay.com/api" + chemin, params={"key": os.environ["PIXABAY_API_KEY"].strip(), **params}, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("La banque d'images est très sollicitée : réessaie dans une minute.")
    if r.status_code >= 400:
        raise RuntimeError(f"Banque d'images indisponible ({r.status_code} : {r.text[:80]}).")
    d = r.json()
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def photos(requete: str, n: int = 15, orientation: str = "portrait") -> list[dict]:
    if not active():
        return demo_photos(requete, n)
    if fournisseur() == "pixabay":
        d = _pixabay("/", {"q": requete[:100], "per_page": max(3, n), "image_type": "photo", "safesearch": "true",
                           "orientation": "vertical" if orientation == "portrait" else "all", "lang": "en"})
        hits = d.get("hits", [])
        if len(hits) < 4 and orientation == "portrait":  # peu de photos verticales : on élargit
            hits += _pixabay("/", {"q": requete[:100], "per_page": max(3, n), "image_type": "photo", "safesearch": "true", "lang": "en"}).get("hits", [])
        return [{"id": f"x{h['id']}", "type": "photo", "miniature": h.get("webformatURL") or h.get("previewURL"),
                 "grande": h.get("largeImageURL") or h.get("webformatURL"), "auteur": h.get("user", ""), "lien": h.get("pageURL", ""),
                 "alt": h.get("tags", "")} for h in hits[:n]]
    d = _get("/v1/search", {"query": requete[:120], "per_page": n, "orientation": orientation, "locale": "fr-FR"})
    return [{"id": f"p{x['id']}", "type": "photo", "miniature": x["src"].get("medium") or x["src"]["small"],
             "grande": x["src"].get("large2x") or x["src"]["original"], "auteur": x.get("photographer", ""),
             "lien": x.get("url", ""), "alt": x.get("alt", "")} for x in d.get("photos", [])]


def videos(requete: str, n: int = 12) -> list[dict]:
    if not active():
        return []
    if fournisseur() == "pixabay":
        d = _pixabay("/videos/", {"q": requete[:100], "per_page": max(3, n * 2), "safesearch": "true", "lang": "en"})
        res = []
        for v in d.get("hits", []):
            tailles = [x for x in (v.get("videos") or {}).values() if isinstance(x, dict) and x.get("url")]
            if not tailles:
                continue
            fichier = min(tailles, key=lambda x: abs((x.get("height") or 0) - 1920) if (x.get("height") or 0) >= (x.get("width") or 0)
                          else abs((x.get("width") or 0) - 1920) + 5000)
            res.append({"id": f"y{v['id']}", "type": "video", "miniature": fichier.get("thumbnail") or "", "grande": fichier["url"],
                        "auteur": v.get("user", ""), "lien": v.get("pageURL", ""), "duree": v.get("duration"),
                        "vertical": (fichier.get("height") or 0) >= (fichier.get("width") or 0)})
        res.sort(key=lambda x: not x["vertical"])  # les vidéos verticales d'abord
        return res[:n]
    d = _get("/videos/search", {"query": requete[:120], "per_page": n, "orientation": "portrait", "locale": "fr-FR"})
    res = []
    for v in d.get("videos", []):
        fichiers = sorted([f for f in v.get("video_files", []) if f.get("height") and f.get("width") and f["height"] >= f["width"]
                           and f.get("file_type") == "video/mp4"], key=lambda f: abs((f.get("height") or 0) - 1920))
        if fichiers:
            res.append({"id": f"v{v['id']}", "type": "video", "miniature": v.get("image", ""), "grande": fichiers[0]["link"],
                        "auteur": (v.get("user") or {}).get("name", ""), "lien": v.get("url", ""), "duree": v.get("duration")})
    return res


# ------------------------------------------------------------
#  Démo : images générées (dégradés), pour tester sans clé
# ------------------------------------------------------------
TEINTES = [((255, 179, 167), (255, 79, 121)), ((180, 220, 210), (19, 147, 107)), ((250, 225, 180), (230, 140, 60)),
           ((205, 200, 245), (110, 90, 200)), ((240, 235, 225), (170, 150, 130)), ((190, 225, 245), (60, 130, 200))]


def _demo_dossier() -> Path:
    d = DATA / "cache" / "banque_demo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def demo_photos(requete: str, n: int = 15) -> list[dict]:
    from PIL import Image, ImageDraw
    graine = int(hashlib.sha1(requete.encode()).hexdigest()[:6], 16)
    res = []
    for k in range(min(n, 9)):
        nom = f"demo_{(graine + k) % 997}.jpg"
        f = _demo_dossier() / nom
        if not f.exists():
            a, b = TEINTES[(graine + k) % len(TEINTES)]
            im = Image.new("RGB", (1080, 1350), a)
            d = ImageDraw.Draw(im)
            for y in range(1350):
                t = y / 1350
                d.line([(0, y), (1080, y)], fill=tuple(int(a[c] + (b[c] - a[c]) * t) for c in range(3)))
            d.ellipse([300 + 40 * (k % 3), 380, 780 + 40 * (k % 3), 860], fill=tuple(min(255, c + 30) for c in b))
            im.save(f, "JPEG", quality=85)
        res.append({"id": f"d{nom}", "type": "photo", "miniature": f"/banque-demo/{nom}", "grande": f"/banque-demo/{nom}",
                    "auteur": "Démo", "lien": "", "alt": f"[démo] {requete}"})
    return res


def chemin_demo(nom: str) -> Path:
    return _demo_dossier() / Path(nom).name


def telecharge(element: dict, dest: Path) -> Path:
    """Télécharge l'image (réduite à 2160 px) ou la vidéo choisie dans le dossier du projet."""
    url = element["grande"]
    if url.startswith("/banque-demo/"):
        import shutil
        shutil.copy(chemin_demo(url.rsplit("/", 1)[1]), dest)
        return dest
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for bloc in r.iter_content(1 << 16):
                f.write(bloc)
    if dest.suffix == ".jpg":
        from PIL import Image
        im = Image.open(dest).convert("RGB")
        im.thumbnail((2160, 2160))
        im.save(dest, "JPEG", quality=90)
    return dest
