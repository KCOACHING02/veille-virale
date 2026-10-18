"""
Studio : transforme un Reel adapté en contenu prêt à publier.
  - Carrousel : slides 1080×1350 avec les textes posés sur les images de l'utilisateur (ou sur un fond uni).
  - Reel : la vidéo de l'utilisateur recadrée en 9:16, avec le hook et les sous-titres incrustés.
           Sans vidéo, un diaporama 9:16 est monté à partir de ses images et des textes des slides.
  - Package ZIP : visuels + légende + script + messages privés + consignes de publication.
Un projet = un dossier data/espaces/<id>/studio/<sid>/ (projet.json, sources/, sortie/).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from espace import CODE, Espace
from modele import log

POLICES = CODE / "static" / "fonts"
CARROUSEL = (1080, 1350)
VERTICAL = (1080, 1920)
EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXT_VIDEOS = {".mp4", ".mov", ".m4v", ".webm"}
THEMES = {
    "sombre": {"fond": (39, 27, 45), "texte": (255, 255, 255), "accent": (255, 79, 121), "doux": (216, 206, 221)},
    "clair": {"fond": (246, 244, 248), "texte": (39, 27, 45), "accent": (255, 79, 121), "doux": (94, 81, 102)},
    "rose": {"fond": (255, 79, 121), "texte": (255, 255, 255), "accent": (39, 27, 45), "doux": (255, 227, 234)},
}
# Styles d'écriture proposés (le texte reste dans la voix de l'utilisateur ; seule la construction change)
STYLES = {
    "ma_voix": ("Ma voix", "Comme sur ton compte", ""),
    "histoire": ("Storytelling", "Un vécu raconté à la 1re personne",
                 "storytelling : une histoire vécue racontée à la première personne (situation, déclic, ce qui a changé), avec du concret et un peu d'émotion"),
    "direct": ("Direct", "Phrases courtes qui claquent",
               "direct et percutant : phrases très courtes, affirmations franches, zéro détour, rythme rapide"),
    "pedago": ("Pédagogique", "Des étapes concrètes",
               "pédagogique : étapes numérotées ou conseils concrets et actionnables, un exemple précis à chaque fois"),
    "confidence": ("Confidence", "Intime, comme à une amie",
                   "confidence : ton intime et complice, comme un message à une amie, on avoue ses doutes et ses erreurs"),
    "mythe": ("Idée reçue", "Casser une croyance",
              "idée reçue démontée : on cite ce que tout le monde croit, on explique pourquoi c'est faux, puis ce qui marche vraiment"),
}
# Typographies : (police du titre, axe de graisse si police variable, police du texte, majuscules, facteur de taille, nom pour libass)
TYPOS = {
    "moderne": ("Poppins-Bold.ttf", None, "Poppins-Regular.ttf", False, 1.0, "Poppins"),
    "geometrique": ("Montserrat-ExtraBold.ttf", None, "Poppins-Regular.ttf", False, 0.98, "Montserrat"),
    "minimal": ("SpaceGrotesk-Bold.ttf", None, "Poppins-Regular.ttf", False, 1.02, "Space Grotesk"),
    "douce": ("Quicksand-Bold.ttf", None, "Poppins-Regular.ttf", False, 1.04, "Quicksand"),
    "impact": ("Anton-Regular.ttf", None, "Poppins-Medium.ttf", True, 1.12, "Anton"),
    "affiche": ("BebasNeue-Regular.ttf", None, "Poppins-Medium.ttf", True, 1.22, "Bebas Neue"),
    "brut": ("ArchivoBlack-Regular.ttf", None, "Poppins-Regular.ttf", False, 0.94, "Archivo Black"),
    "elegant": ("DMSerifDisplay-Regular.ttf", None, "Poppins-Regular.ttf", False, 1.04, "DM Serif Display"),
    "classique": ("PlayfairDisplay-Bold.ttf", None, "Poppins-Regular.ttf", False, 1.02, "Playfair Display"),
    "retro": ("AbrilFatface-Regular.ttf", None, "Poppins-Regular.ttf", False, 1.0, "Abril Fatface"),
    "manuscrit": ("Caveat-Bold.ttf", None, "Poppins-Regular.ttf", False, 1.3, "Caveat"),
    "signature": ("Pacifico-Regular.ttf", None, "Poppins-Regular.ttf", False, 1.08, "Pacifico"),
}
INTERLIGNES = {"signature": 1.55, "manuscrit": 1.1, "affiche": 1.05}  # polices aux jambages très hauts ou très bas
NOMS_TYPOS = {"moderne": "Moderne", "geometrique": "Géométrique", "minimal": "Minimal", "douce": "Douce", "impact": "Impact",
              "affiche": "Affiche", "brut": "Brut", "elegant": "Élégant", "classique": "Classique", "retro": "Rétro",
              "manuscrit": "Manuscrit", "signature": "Signature"}
DUREE_MAX_REEL = 180
SLIDE_DIAPORAMA_S = 3.0


# ------------------------------------------------------------
#  Projets
# ------------------------------------------------------------
def _racine(esp: Espace) -> Path:
    return esp.racine / "studio"


def dossier(esp: Espace, sid: str) -> Path:
    d = _racine(esp) / Path(sid).name
    if not (d / "projet.json").exists():
        raise FileNotFoundError(sid)
    return d


def charge(esp: Espace, sid: str) -> dict:
    return json.loads((dossier(esp, sid) / "projet.json").read_text(encoding="utf-8"))


def sauve(esp: Espace, projet: dict):
    d = _racine(esp) / projet["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "projet.tmp"
    tmp.write_text(json.dumps(projet, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "projet.json")


def liste(esp: Espace) -> list[dict]:
    r = _racine(esp)
    res = []
    for f in sorted(r.glob("*/projet.json"), reverse=True) if r.exists() else []:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            res.append({k: p.get(k) for k in ("id", "cree", "titre", "type", "statut", "miniature", "compte", "fichiers", "zip")})
        except ValueError:
            continue
    return sorted(res, key=lambda p: p.get("cree") or "", reverse=True)


def supprime(esp: Espace, sid: str):
    shutil.rmtree(dossier(esp, sid), ignore_errors=True)


def _coupe(t: str, n: int) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _phrases(script: str) -> list[str]:
    """Phrases du corps du script (sans les repères [0-3 s], [corps], [fin])."""
    corps = re.sub(r"\[[^\]]*\]", "\n", script or "")
    morceaux = re.split(r"(?<=[.!?…])\s+|\n+", corps)
    return [m.strip(" -–•") for m in morceaux if len(m.strip(" -–•")) > 3]


def prerempli(ad: dict, cfg: dict) -> list[dict]:
    """
    Slides pré-remplies tout de suite à partir de l'adaptation (hook viral, corps du script, CTA),
    pour ne jamais présenter un carrousel vide ; Claude les réécrit ensuite dans le style choisi.
    """
    hook = ad.get("hook_viral") or (ad.get("hooks_adaptes") or [""])[0]
    phrases = [p for p in _phrases(ad.get("script_reel")) if p.lower().rstrip(" .?!…") not in hook.lower()]
    phrases = [p for p in phrases if "comment" not in p.lower()[:12]][:5]  # le CTA a sa propre slide
    slides = [{"titre": hook, "texte": "", "photo": ad.get("idee_visuelle") or ""}]
    slides += [{"titre": _coupe(p, 70), "texte": "", "photo": ""} for p in phrases]
    cta = ad.get("cta_conversation") or f"Commente {cfg['objectifs']['mot_cle_cta']}"
    slides.append({"titre": _coupe(cta, 60), "texte": "", "photo": ""})
    return slides


def slides_du_modele(ad: dict) -> list[dict]:
    """Carrousel modèle analysé slide par slide : mêmes slides, textes adaptés, photo à prendre pour chacune."""
    res = []
    for x in ad.get("slides_modele") or []:
        if isinstance(x, dict) and (x.get("adapte") or x.get("original")):
            res.append({"titre": (x.get("adapte") or x.get("original") or "").strip(), "texte": "", "photo": (x.get("photo") or "").strip(),
                        "recherche": (x.get("recherche") or "").strip()})
    return res[:10]


def _source(post: dict) -> dict:
    """Ce que l'on sait du modèle (Reel ou carrousel), pour en reproduire la structure."""
    ad = post.get("adaptation") or {}
    return {"format": post.get("format"), "url": post.get("url"), "compte": post.get("compte"), "duree_s": post.get("duree_s"),
            "slides_modele": [{"original": x.get("original", ""), "visuel": x.get("visuel", "")} for x in ad.get("slides_modele") or []
                              if isinstance(x, dict)][:10],
            "style_visuel": ad.get("style_visuel") or "", "son": post.get("son") or {},
            "legende": (post.get("legende") or "")[:1500], "transcription": (post.get("transcription") or "")[:2500],
            "structure": ad.get("structure") or "", "analyse_visuelle": ad.get("analyse_visuelle") or "",
            "texte_ecran": ad.get("texte_ecran") or "", "hook_original": ad.get("hook_original") or ""}


def cree(esp: Espace, cfg: dict, post: dict, typ: str, analyse_id: str | None, style: str = "ma_voix") -> dict:
    """Nouveau projet à partir d'un Reel adapté (les textes des slides sont écrits ensuite par Claude)."""
    ad = post.get("adaptation") or {}
    hook = ad.get("hook_viral") or (ad.get("hooks_adaptes") or [""])[0]
    hashtags = " ".join("#" + h for h in (cfg["decouverte"].get("hashtags_instagram") or [])[:5])
    legende = ad.get("legende_adaptee") or ad.get("legende_reprise") or ""
    if hashtags and "#" not in legende:
        legende = legende.rstrip() + "\n\n" + hashtags
    sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    projet = {
        "id": sid, "cree": datetime.now().isoformat(timespec="minutes"), "type": typ if typ in ("carrousel", "reel") else "carrousel",
        "titre": _coupe(hook, 90) or "Sans titre", "analyse_id": analyse_id, "cle": post.get("cle"), "compte": post.get("compte"),
        "miniature": post.get("miniature"), "statut": "brouillon", "erreur": None,
        "hook": hook, "texte_ecran": ad.get("texte_ecran_adapte") or "", "script": ad.get("script_reel") or "",
        "cta": ad.get("cta_conversation") or "", "dm": ad.get("sequence_dm") or [], "legende": legende,
        "slides": slides_du_modele(ad) or prerempli(ad, cfg), "images": [], "video": None,
        "theme": ad.get("theme_conseille") if ad.get("theme_conseille") in THEMES else "sombre", "sous_titres": True,
        "source": _source(post), "nb_photos": None, "copie_du_modele": bool(slides_du_modele(ad)),
        "style": "ma_voix", "typo": ad.get("typo_conseillee") if ad.get("typo_conseillee") in TYPOS else "moderne",
        "pseudo": (cfg.get("mon_compte") or {}).get("instagram") or "",
        "fichiers": [], "zip": None, "adaptation": ad,
    }
    projet["style"] = style if style in STYLES else "ma_voix"
    projet["nb_photos"] = sum(1 for x in projet["slides"] if x.get("photo"))
    sauve(esp, projet)
    return projet


def voix_connue(esp: Espace) -> bool:
    """Vrai si l'outil connaît la façon d'écrire de l'utilisateur (compte analysé ou textes de référence)."""
    try:
        prof = json.loads(esp.profil_compte.read_text(encoding="utf-8")) if esp.profil_compte.exists() else {}
    except ValueError:
        prof = {}
    ref = esp.voix.read_text(encoding="utf-8").strip() if esp.voix.exists() else ""
    return bool((prof.get("proposition") or {}).get("guide_voix") or (prof.get("apprentissage") or {}).get("meilleures_legendes")
                or (ref and "COLLE ICI" not in ref))


def ecrit_textes(esp: Espace, cfg: dict, sid: str, demo: bool = False) -> dict:
    """Tâche de fond : Claude écrit les textes des slides à partir de l'adaptation."""
    p = charge(esp, sid)
    nom_style, _, consigne = STYLES.get(p.get("style") or "ma_voix", STYLES["ma_voix"])
    reel = p["type"] == "reel"
    log(f"J'écris tes textes, style « {nom_style} »…")
    if demo:
        res = {"slides": [{"titre": p["hook"] or "[démo] Ton hook", "texte": "", "photo": "[démo] Toi en gros plan, l'air surpris, lumière naturelle"},
                          *({"titre": f"[démo · {nom_style}] Étape {i} du Reel modèle", "texte": "[démo] Une phrase courte qui développe l'idée, dans ton ton.",
                             "photo": "[démo] Ton bol du matin vu de dessus" if i in (2, 4) else ""} for i in range(1, 6)),
                          {"titre": f"Commente {cfg['objectifs']['mot_cle_cta']}", "texte": "[démo] et je t'envoie le guide en privé", "photo": ""}],
               "legende": f"[démo · {nom_style}] " + ((p.get("adaptation") or {}).get("legende_adaptee") or ""),
               "script": f"[0-3 s] {p['hook']}\n[corps] [démo · {nom_style}] trois phrases dans ce style\n[fin] Commente {cfg['objectifs']['mot_cle_cta']}" if reel else ""}
    else:
        from apprentissage import voix
        from ia import IA
        nb_modele = len((p.get("source") or {}).get("slides_modele") or [])
        res = IA(cfg, voix=voix(cfg, esp.racine, [])).carrousel(p.get("adaptation") or {}, nb=(nb_modele or None) if not reel else None,
                                                             style=consigne, reel=reel, source=p.get("source") or {})
        if res.get("erreur"):
            raise RuntimeError(res["erreur"])
    slides = res.get("slides")
    if isinstance(slides, str):  # certains modèles renvoient le tableau sous forme de texte JSON
        try:
            slides = json.loads(slides)
        except ValueError:
            slides = None
    slides = [x for x in (slides or []) if isinstance(x, dict) and (x.get("titre") or "").strip()]
    if not slides:
        raise RuntimeError("Claude n'a pas proposé de slides : tes textes pré-remplis sont gardés, réessaie « Réécrire dans ce style ».")
    p = charge(esp, sid)  # relu : l'utilisateur a pu importer des fichiers pendant ce temps
    anciennes = p.get("slides") or []
    p["slides"] = [{"titre": x.get("titre", "").strip(), "texte": (x.get("texte") or "").strip(), "photo": (x.get("photo") or "").strip(),
                    "recherche": (x.get("recherche") or "").strip(),
                    "image": anciennes[k].get("image", "") if k < len(anciennes) else ""} for k, x in enumerate(slides)][:10]
    p["nb_photos"] = sum(1 for x in p["slides"] if x["photo"])
    if res.get("legende"):
        p["legende"] = res["legende"]
    if reel and res.get("script"):
        p["script"] = res["script"]
    sauve(esp, p)
    log(f"✅ {len(p['slides'])} slides écrites")
    remplit_banque(esp, sid, demo=demo)
    return {"id": sid}


def ajoute_fichier(esp: Espace, sid: str, nom: str, flux, slide_i: int | None = None) -> dict:
    """Importe une image (convertie en JPEG) ou une vidéo dans le projet ; slide_i : image destinée à cette slide."""
    p = charge(esp, sid)
    src = dossier(esp, sid) / "sources"
    src.mkdir(exist_ok=True)
    ext = Path(nom or "").suffix.lower()
    if ext in EXT_VIDEOS:
        for ancien in src.glob("video.*"):
            ancien.unlink()
        dest = src / f"video{ext}"
        flux.save(dest)
        d = _duree(dest)
        if not d:
            dest.unlink(missing_ok=True)
            raise ValueError("Cette vidéo est illisible. Essaie un fichier .mp4 ou .mov.")
        p["video"] = dest.name
        p["video_duree"] = round(d, 1)
    elif ext in EXT_IMAGES:
        if len(p["images"]) >= 15:
            raise ValueError("15 images maximum par projet.")
        from PIL import Image, ImageOps
        if ext in (".heic", ".heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                raise ValueError("Format HEIC non pris en charge : exporte la photo en JPEG.") from None
        try:
            im = ImageOps.exif_transpose(Image.open(flux.stream)).convert("RGB")
        except Exception:  # noqa: BLE001
            raise ValueError(f"Image illisible : {nom}") from None
        im.thumbnail((2160, 2160))
        dest = src / f"img_{uuid.uuid4().hex[:8]}.jpg"
        im.save(dest, "JPEG", quality=90)
        p["images"].append(dest.name)
        if slide_i is not None and 0 <= slide_i < len(p["slides"]):
            _remplace_image_slide(dossier(esp, sid), p, slide_i, dest.name)
    else:
        raise ValueError("Format non pris en charge : images JPEG/PNG/WEBP/HEIC ou vidéos MP4/MOV.")
    sauve(esp, p)
    return p


def _remplace_image_slide(d: Path, p: dict, i: int, nom: str):
    """Affecte une image à la slide i ; l'ancienne image de cette slide, si elle venait de la banque, est supprimée."""
    ancienne = p["slides"][i].get("image")
    p["slides"][i]["image"] = nom
    if ancienne and ancienne != nom and ancienne.startswith("banque_") and not any(x.get("image") == ancienne for x in p["slides"]):
        (d / "sources" / ancienne).unlink(missing_ok=True)
        p["images"] = [x for x in p["images"] if x != ancienne]
        p.setdefault("credits", {}).pop(ancienne, None)


def choisit_banque(esp: Espace, sid: str, slide_i: int | None, element: dict) -> dict:
    """Image (ou vidéo, pour un Reel) de la banque choisie pour une slide : téléchargée dans le projet."""
    import banque
    p = charge(esp, sid)
    d = dossier(esp, sid)
    (d / "sources").mkdir(exist_ok=True)
    if element.get("type") == "video":
        for ancien in (d / "sources").glob("video.*"):
            ancien.unlink()
        dest = banque.telecharge(element, d / "sources" / "video.mp4")
        p["video"], p["video_duree"] = dest.name, round(_duree(dest) or 0, 1)
    else:
        nom = f"banque_{re.sub(r'[^a-z0-9]', '', str(element.get('id', '')).lower())[:20]}_{uuid.uuid4().hex[:4]}.jpg"
        banque.telecharge(element, d / "sources" / nom)
        p["images"].append(nom)
        p.setdefault("credits", {})[nom] = {"auteur": element.get("auteur", ""), "lien": element.get("lien", "")}
        if slide_i is not None and 0 <= slide_i < len(p["slides"]):
            _remplace_image_slide(d, p, slide_i, nom)
    sauve(esp, p)
    return p


def requete_photo(x: dict) -> str:
    """Mots-clés de recherche d'une slide (fournis par Claude, sinon tirés de la description de la photo)."""
    if x.get("recherche"):
        return x["recherche"]
    t = re.sub(r"\[[^\]]*\]", " ", x.get("photo") or x.get("titre") or "").lower()
    t = re.sub(r"\b(toi|ton|ta|tes|te|tu|vous|votre|de|du|des|la|le|les|un|une|et|en|avec|qui|sur|dans|ou|à|au|aux|photo|plan|gros)\b", " ", t)
    return " ".join(t.replace(",", " ").split()[:6]) or "lifestyle"


def remplit_banque(esp: Espace, sid: str, demo: bool = False, toutes: bool = False) -> dict:
    """Propose par défaut une image de la banque pour chaque slide qui demande une photo et n'en a pas encore."""
    import banque
    if not (banque.active() or demo):
        log("Banque d'images non configurée")
        return {"id": sid}
    p = charge(esp, sid)
    if p["type"] == "reel" and p.get("video"):
        return {"id": sid}
    deja = attribue(p["slides"], p["images"])
    cibles = [i for i, x in enumerate(p["slides"]) if (x.get("photo") or toutes) and not deja[i]]
    if not cibles:
        return {"id": sid}
    log(f"Je choisis des images pour {len(cibles)} slide(s)…")
    utilises = set()
    for i in cibles:
        # Slide sans idée de photo : on garde l'ambiance des slides qui en ont une (même univers visuel)
        ambiance = next((requete_photo(x) for x in p["slides"] if x.get("photo") or x.get("recherche")), "")
        try:
            res = [r for r in banque.photos(requete_photo(p["slides"][i]), n=12) if r["id"] not in utilises]
            if len(res) < 2 and ambiance:
                res += [r for r in banque.photos(ambiance, n=12) if r["id"] not in utilises and r not in res]
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  {str(e)[:120]}")
            break
        if res:
            utilises.add(res[0]["id"])
            choisit_banque(esp, sid, i, res[0])
    log("✅ Images proposées : remplace-les par les tiennes quand tu veux")
    return {"id": sid}


def retire_fichier(esp: Espace, sid: str, nom: str) -> dict:
    p = charge(esp, sid)
    nom = Path(nom).name
    (dossier(esp, sid) / "sources" / nom).unlink(missing_ok=True)
    p["images"] = [i for i in p["images"] if i != nom]
    for x in p["slides"]:
        if x.get("image") == nom:
            x.pop("image")
    if p.get("video") == nom:
        p["video"] = None
    sauve(esp, p)
    return p


def modifie(esp: Espace, sid: str, champs: dict) -> dict:
    p = charge(esp, sid)
    for k in ("legende", "hook", "theme", "sous_titres", "type", "pseudo", "titre", "script", "style", "typo"):
        if k in champs:
            p[k] = champs[k]
    if isinstance(champs.get("slides"), list):
        anciennes = p.get("slides") or []
        def garde(s, i, k, n):
            return str(s.get(k, anciennes[i].get(k, "") if i < len(anciennes) else ""))[:n]
        p["slides"] = [{"titre": str(s.get("titre", ""))[:200], "texte": str(s.get("texte", ""))[:400], "photo": garde(s, i, "photo", 300),
                        "recherche": garde(s, i, "recherche", 120), "image": garde(s, i, "image", 80)}
                       for i, s in enumerate(champs["slides"])][:10]
        for x in p["slides"]:
            if x["image"] not in p["images"]:
                x["image"] = ""
        p["nb_photos"] = sum(1 for x in p["slides"] if x.get("photo"))
    if isinstance(champs.get("images"), list):  # nouvel ordre des images
        p["images"] = [i for i in champs["images"] if i in p["images"]] + [i for i in p["images"] if i not in champs["images"]]
    if p["theme"] not in THEMES:
        p["theme"] = "sombre"
    if p.get("style") not in STYLES:
        p["style"] = "ma_voix"
    if p.get("typo") not in TYPOS:
        p["typo"] = "moderne"
    sauve(esp, p)
    return p


# ------------------------------------------------------------
#  Texte et images (Pillow)
# ------------------------------------------------------------
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍\U000E0000-\U000E007F]+")


def propre(t: str) -> str:
    """Retire les emojis (absents de la police) et les espaces superflus."""
    return re.sub(r"[ \t]+", " ", _EMOJI.sub("", t or "")).strip()


def _police(graisse: str, taille: int):
    """graisse : « Bold », « Regular », « Medium » (Poppins) ou un nom de fichier (.ttf), éventuellement « fichier@700 » (police variable)."""
    from PIL import ImageFont
    fichier, _, poids = graisse.partition("@")
    pol = ImageFont.truetype(str(POLICES / (fichier if fichier.endswith(".ttf") else f"Poppins-{fichier}.ttf")), taille)
    if poids:
        try:
            pol.set_variation_by_axes([int(poids)])
        except Exception:  # noqa: BLE001
            pass
    return pol


def _lignes(dessin, texte: str, police, largeur: int) -> list[str]:
    res = []
    for paragraphe in texte.split("\n"):
        ligne = ""
        for mot in paragraphe.split():
            essai = (ligne + " " + mot).strip()
            if dessin.textlength(essai, font=police) <= largeur or not ligne:
                ligne = essai
            else:
                res.append(ligne)
                ligne = mot
        res.append(ligne)
    return [l for l in res if l is not None]


def _ajuste(dessin, texte, graisse, largeur, hauteur, maxi, mini, interligne=1.18):
    """Plus grande taille de police pour laquelle le texte tient dans la boîte."""
    taille = maxi
    while True:
        pol = _police(graisse, taille)
        lignes = _lignes(dessin, texte, pol, largeur)
        h = int(len(lignes) * taille * interligne)
        if h <= hauteur or taille <= mini:
            return pol, lignes, h, taille
        taille -= 4


def _couvre(im, taille):
    """Recadre l'image pour remplir exactement le format (comme object-fit: cover)."""
    from PIL import ImageOps
    return ImageOps.fit(im, taille, method=3, centering=(0.5, 0.4))


def _degrade(taille, debut: float, alpha_max: int = 215):
    """Calque noir transparent en haut, de plus en plus opaque vers le bas (pour lire le texte sur la photo)."""
    from PIL import Image
    l, h = taille
    calque = Image.new("L", (1, h), 0)
    for y in range(h):
        r = (y / h - debut) / (1 - debut)
        calque.putpixel((0, y), int(alpha_max * max(0.0, min(1.0, r)) ** 1.3))
    noir = Image.new("RGBA", taille, (15, 10, 18, 0))
    noir.putalpha(calque.resize(taille))
    return noir


def slide(slide_: dict, i: int, n: int, image: Path | None, theme: str, pseudo: str, taille=CARROUSEL, reel: bool = False,
          typo: str = "moderne"):
    """Dessine une slide. Avec image : texte en bas sur un dégradé. Sans image : fond uni du thème."""
    from PIL import Image, ImageDraw
    th = THEMES.get(theme, THEMES["sombre"])
    l, h = taille
    marge = int(l * 0.085)
    f_titre, poids, f_texte, majuscules, facteur, _ = TYPOS.get(typo, TYPOS["moderne"])
    police_titre = f_titre + (f"@{poids}" if poids else "")
    titre, texte = propre(slide_.get("titre", "")), propre(slide_.get("texte", ""))
    if majuscules:
        titre = titre.upper()
    premiere, derniere = i == 0, i == n - 1
    if image and image.exists():
        fond = _couvre(Image.open(image).convert("RGB"), taille).convert("RGBA")
        fond.alpha_composite(_degrade(taille, 0.32 if (texte or premiere) else 0.45))
        couleur, couleur2, accent = (255, 255, 255), (235, 228, 238), th["accent"] if theme != "rose" else (255, 79, 121)
        sur_photo = True
    else:
        fond = Image.new("RGBA", taille, th["fond"] + (255,))
        couleur, couleur2, accent = th["texte"], th["doux"], th["accent"]
        sur_photo = False
    d = ImageDraw.Draw(fond)
    largeur = l - 2 * marge
    # Zone de texte : bas de l'image sur photo, centrée sur fond uni
    h_titre_max = int(h * (0.42 if premiere else 0.30))
    maxi = int((104 if premiere else (82 if sur_photo else 96)) * facteur)
    interligne = INTERLIGNES.get(typo, 1.12 if majuscules else 1.18)
    pol_t, lignes_t, ht, taille_t = _ajuste(d, titre, police_titre, largeur, h_titre_max, maxi, int(46 * facteur), interligne)
    pol_x, lignes_x, hx, taille_x = (None, [], 0, 0)
    if texte:
        pol_x, lignes_x, hx, taille_x = _ajuste(d, texte, f_texte, largeur, int(h * 0.26), 46, 30, 1.32)
    ecart = int(taille_t * 0.55) if texte else 0
    bloc = ht + ecart + hx + int(h * 0.025)
    y = (h - int(h * 0.12) - bloc) if sur_photo else (h - bloc) // 2
    # Barre d'accent au-dessus du titre
    d.rounded_rectangle([marge, y - 34, marge + 86, y - 22], radius=6, fill=accent)
    for ligne in lignes_t:
        d.text((marge, y), ligne, font=pol_t, fill=couleur)
        y += int(taille_t * interligne)
    y += ecart
    for ligne in lignes_x:
        d.text((marge, y), ligne, font=pol_x, fill=couleur2)
        y += int(taille_x * 1.32)
    # Compteur, pseudo, invitation à faire glisser
    petit = _police("Medium", 30)
    haut = int(h * (0.09 if reel else 0.045))  # en Reel, on laisse la place à l'interface d'Instagram
    if n > 1 and not reel:
        cpt = f"{i + 1}/{n}"
        d.text((l - marge - d.textlength(cpt, font=petit), haut), cpt, font=petit, fill=couleur2)
    if pseudo:
        d.text((marge, haut), "@" + pseudo.lstrip("@"), font=petit, fill=couleur2)
    if n > 1 and not derniere and not reel:
        g, c_g = "Glisse", (accent if not sur_photo else couleur)
        y_g = h - int(h * 0.065)
        x_fleche = l - marge - 34
        d.text((x_fleche - 14 - d.textlength(g, font=petit), y_g), g, font=petit, fill=c_g)
        y_m = y_g + 22  # flèche dessinée (la police n'a pas le caractère →)
        d.line([(x_fleche, y_m), (x_fleche + 30, y_m)], fill=c_g, width=4)
        d.line([(x_fleche + 19, y_m - 11), (x_fleche + 31, y_m), (x_fleche + 19, y_m + 11)], fill=c_g, width=4, joint="curve")
    return fond.convert("RGB")


# ------------------------------------------------------------
#  Vidéo (ffmpeg + libass)
# ------------------------------------------------------------
def _duree(f: Path) -> float | None:
    from video import duree
    return duree(f)


def _dimensions(f: Path) -> tuple[int, int]:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
                              "-of", "json", str(f)], capture_output=True, text=True, timeout=60).stdout
        st = json.loads(out)["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        rot = abs(int(next((x.get("rotation", 0) for x in st.get("side_data_list") or [] if "rotation" in x), 0)))
        return (h, w) if rot in (90, 270) else (w, h)
    except Exception:  # noqa: BLE001
        return (1080, 1920)


def _hdr(f: Path) -> bool:
    """Vidéo HDR (iPhone : HLG / Dolby Vision) : il faut la convertir en SDR, sinon les couleurs sortent délavées."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                              "-of", "csv=p=0", str(f)], capture_output=True, text=True, timeout=60).stdout
        return out.strip() in ("arib-std-b67", "smpte2084")
    except Exception:  # noqa: BLE001
        return False


TONEMAP = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"


def _a_du_son(f: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True, timeout=60).stdout
    return bool(out.strip())


def _t(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def _ass_txt(t: str) -> str:
    return propre(t).replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def sous_titres(fichier: Path, dossier_: Path) -> list[tuple[float, float, str]]:
    """Transcription mot à mot (Whisper local) → blocs de 2 à 4 mots."""
    from video import audio, lit_wav, modele_whisper
    import os
    wav = audio(fichier, dossier_, secondes=DUREE_MAX_REEL)
    if not wav:
        return []
    try:
        son = lit_wav(wav, DUREE_MAX_REEL)
        if son.size < 1600:
            return []
        segments, _ = modele_whisper(os.getenv("WHISPER_MODEL", "base")).transcribe(
            son, vad_filter=True, beam_size=1, word_timestamps=True, condition_on_previous_text=False)
        mots = [(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or []) if w.word.strip()]
    finally:
        wav.unlink(missing_ok=True)
    blocs, courant = [], []
    for m in mots:
        courant.append(m)
        texte = " ".join(x[2] for x in courant)
        if len(courant) >= 4 or len(texte) >= 20 or m[2][-1:] in ".?!,":
            blocs.append((courant[0][0], courant[-1][1], texte))
            courant = []
    if courant:
        blocs.append((courant[0][0], courant[-1][1], " ".join(x[2] for x in courant)))
    # Pas de trou de clignotement entre deux blocs proches
    res = []
    for i, (a, b, t) in enumerate(blocs):
        suivant = blocs[i + 1][0] if i + 1 < len(blocs) else None
        res.append((a, min(suivant, b + 0.4) if suivant and suivant - b < 0.6 else b + 0.15, t))
    return res


def fichier_ass(hook: str, duree_hook: float, blocs: list, chemin: Path, typo: str = "moderne"):
    _, _, _, majuscules, facteur, famille = TYPOS.get(typo, TYPOS["moderne"])
    if majuscules:
        hook = hook.upper()
    entete = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{famille},{taille_hook},&H002D1B27,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,20,0,8,110,110,250,1
Style: Sous,{famille},{taille_sous},&H00FFFFFF,&H000000FF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,7,3,2,90,90,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".replace("{famille}", famille).replace("{taille_hook}", str(int(74 * facteur))).replace("{taille_sous}", str(int(82 * facteur)))
    lignes = []
    if hook:
        lignes.append(f"Dialogue: 1,{_t(0)},{_t(duree_hook)},Hook,,0,0,0,,{{\\fad(0,250)}}{_ass_txt(hook)}")
    for a, b, t in blocs:
        lignes.append(f"Dialogue: 0,{_t(a)},{_t(b)},Sous,,0,0,0,,{_ass_txt(t)}")
    chemin.write_text(entete + "\n".join(lignes) + "\n", encoding="utf-8")


def _ffmpeg(args: list[str], cwd: Path, timeout: int = 1800):
    try:
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Le montage vidéo a pris trop de temps : essaie une vidéo plus courte.") from None
    if r.returncode != 0:
        print(f"[ffmpeg] code {r.returncode} pour {' '.join(args)[:300]}\n{r.stderr[-2000:]}", flush=True)  # visible dans les journaux du serveur
        lignes = [l for l in r.stderr.strip().splitlines() if l.strip()]
        if r.returncode < 0:
            raise RuntimeError("Le montage vidéo a été interrompu par le serveur (mémoire insuffisante pour cette vidéo).")
        raise RuntimeError("Le montage vidéo a échoué : " + (lignes[-1][:200] if lignes else f"code {r.returncode}"))


ENCODAGE = ["-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
LEGER = ["-threads", "2", "-filter_threads", "1"]  # limite la mémoire (vidéos 4K HDR des iPhone)


def normalise(src: Path, d: Path) -> tuple[Path, Path | None]:
    """
    Version « compatible » d'une vidéo difficile (4K HDR, son spatial, flux exotiques) : image ramenée à 1080 px max,
    8 bits, 30 i/s, et son extrait à part. Utilisée si le montage direct échoue.
    """
    image = d / "norm.mp4"
    _ffmpeg(["-threads", "1", "-i", str(src), "-map", "0:v:0", "-t", str(DUREE_MAX_REEL), "-an", "-sn", "-dn",
             "-vf", "scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease,fps=30,format=yuv420p",
             "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", "18", str(image)], d)
    son = d / "son.m4a"
    try:
        _ffmpeg(["-i", str(src), "-map", "0:a:0", "-vn", "-t", str(DUREE_MAX_REEL), "-c:a", "aac", "-b:a", "128k", str(son)], d, 300)
    except RuntimeError:
        son = None  # piste audio illisible : le Reel sera muet (on ajoute un son dans Instagram)
    return image, son


def monte_reel(p: dict, d: Path, sortie: Path) -> list[str]:
    src = d / "sources" / p["video"]
    duree = min(_duree(src) or 0, DUREE_MAX_REEL)
    log("Je recadre ta vidéo au format Reel…")
    blocs = []
    if p.get("sous_titres", True):
        log("J'écoute ta vidéo pour écrire les sous-titres…")
        try:
            blocs = sous_titres(src, d)
            log(f"  {len(blocs)} sous-titres" if blocs else "  Aucune parole détectée : pas de sous-titres")
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  Sous-titres impossibles ({str(e)[:120]}) : le Reel est monté sans")
    fichier_ass(propre(p.get("hook") or ""), min(3.5, duree or 3.5), blocs, d / "sous.ass", p.get("typo", "moderne"))
    w, h = _dimensions(src)
    ass = f"ass=sous.ass:fontsdir={POLICES}"
    tm = TONEMAP if _hdr(src) else ""

    def filtre_pour(hdr: str) -> str:
        if w / h > 0.75:  # vidéo horizontale ou carrée : fond flou + vidéo entière au centre
            return ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[fond];"
                    "[0:v]scale=1080:-2[av];[fond][av]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1," + hdr + "format=yuv420p," + ass + "[v]")
        return "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1," + hdr + "format=yuv420p," + ass + "[v]"
    filtre = filtre_pour(tm)
    log("Montage de ton Reel (hook + sous-titres)…")
    try:
        son = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k"] if _a_du_son(src) else []
        _ffmpeg([*LEGER, "-i", str(src), "-t", str(DUREE_MAX_REEL), "-filter_complex", filtre, "-map", "[v]", *son, *ENCODAGE,
                 str(sortie / "reel.mp4")], d)
    except RuntimeError as e:
        log(f"  Montage direct impossible ({str(e)[:100]}) : nouvel essai en mode compatible…")
        image, piste = normalise(src, d)
        entrees = ["-i", str(image)] + (["-i", str(piste)] if piste else [])
        son = ["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-shortest"] if piste else []
        _ffmpeg([*LEGER, *entrees, "-filter_complex", filtre_pour(""), "-map", "[v]", *son, *ENCODAGE, str(sortie / "reel.mp4")], d)
        image.unlink(missing_ok=True)
        if piste:
            piste.unlink(missing_ok=True)
    # Couverture : une image du début avec le hook
    from PIL import Image
    _ffmpeg(["-ss", "0.6", "-i", str(sortie / "reel.mp4"), "-frames:v", "1", "-q:v", "3", str(d / "cadre.jpg")], d, 120)
    if (d / "cadre.jpg").exists():
        couv = slide({"titre": p.get("hook") or "", "texte": ""}, 0, 1, d / "cadre.jpg", p.get("theme", "sombre"), "", VERTICAL, reel=True,
                     typo=p.get("typo", "moderne"))
        couv.save(sortie / "couverture.jpg", "JPEG", quality=90)
        (d / "cadre.jpg").unlink(missing_ok=True)
    return ["reel.mp4", "couverture.jpg"] if (sortie / "couverture.jpg").exists() else ["reel.mp4"]


def monte_diaporama(p: dict, d: Path, sortie: Path) -> list[str]:
    """Reel sans vidéo : chaque slide (texte + image) devient un plan de 3 s, en 9:16."""
    log("Je prépare les plans de ton Reel…")
    slides = p["slides"] or [{"titre": p.get("hook") or "", "texte": ""}]
    images = attribue(slides, [d / "sources" / i for i in p["images"]]) if p["images"] else [None] * len(slides)
    plans = d / "plans"
    shutil.rmtree(plans, ignore_errors=True)
    plans.mkdir()
    for i, s in enumerate(slides):
        img = images[i]
        slide(s, i, len(slides), img, p.get("theme", "sombre"), p.get("pseudo", ""), VERTICAL, reel=True,
              typo=p.get("typo", "moderne")).save(plans / f"{i:02d}.jpg", "JPEG", quality=92)
    liste_ = "".join(f"file 'plans/{i:02d}.jpg'\nduration {SLIDE_DIAPORAMA_S}\n" for i in range(len(slides)))
    liste_ += f"file 'plans/{len(slides) - 1:02d}.jpg'\n"
    (d / "plans.txt").write_text(liste_, encoding="utf-8")
    log("Montage du diaporama…")
    duree = SLIDE_DIAPORAMA_S * len(slides)
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "plans.txt", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-vf", "fps=30,format=yuv420p,setsar=1", "-t", f"{duree:.1f}", "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "64k",
             *ENCODAGE, str(sortie / "reel.mp4")], d)
    shutil.copy(plans / "00.jpg", sortie / "couverture.jpg")
    shutil.rmtree(plans, ignore_errors=True)
    return ["reel.mp4", "couverture.jpg"]


# ------------------------------------------------------------
#  Génération + package
# ------------------------------------------------------------
def genere(esp: Espace, sid: str, demo: bool = False) -> dict:
    p = charge(esp, sid)
    d = dossier(esp, sid)
    sortie = d / "sortie"
    shutil.rmtree(sortie, ignore_errors=True)
    sortie.mkdir()
    p.update(statut="en_cours", erreur=None)
    sauve(esp, p)
    try:
        if p["type"] == "carrousel":
            if not p["slides"]:
                raise ValueError("Ajoute au moins une slide.")
            n = len(p["slides"])
            log(f"Je dessine tes {n} slides…")
            images = attribue(p["slides"], [d / "sources" / i for i in p["images"]])
            fichiers = []
            for i, s in enumerate(p["slides"]):
                nom = f"slide_{i + 1:02d}.jpg"
                img = images[i]
                slide(s, i, n, img, p.get("theme", "sombre"), p.get("pseudo", ""), typo=p.get("typo", "moderne")).save(
                    sortie / nom, "JPEG", quality=92)
                fichiers.append(nom)
        elif p.get("video"):
            fichiers = monte_reel(p, d, sortie)
        else:
            if not (p["slides"] or p["images"]):
                raise ValueError("Ajoute ta vidéo, ou des images pour un Reel en diaporama.")
            fichiers = monte_diaporama(p, d, sortie)
        log("Je prépare ton package prêt à publier…")
        p = charge(esp, sid)
        p.update(fichiers=fichiers, zip=package(p, d, sortie, fichiers), statut="pret",
                 genere_le=datetime.now().isoformat(timespec="minutes"))
        sauve(esp, p)
        log("✅ Contenu prêt")
        return {"id": sid}
    except Exception as e:
        p = charge(esp, sid)
        p.update(statut="erreur", erreur=str(e)[:300])
        sauve(esp, p)
        raise


def attribue(slides: list[dict], images: list) -> list:
    """
    Image de chaque slide. Les photos vont d'abord, dans l'ordre, aux slides pour lesquelles une photo est prévue ;
    les photos en trop complètent les slides suivantes. Sans indication, une photo par slide dans l'ordre.
    """
    res = [None] * len(slides)
    noms = {Path(str(img)).name: img for img in images}
    # 1. Images choisies pour une slide précise (banque d'images ou « ma photo » sur cette slide)
    for i, x in enumerate(slides):
        if x.get("image") and x["image"] in noms:
            res[i] = noms.pop(x["image"])
    # 2. Les autres photos, dans l'ordre, aux slides qui demandent une photo, puis aux suivantes
    libres = [img for img in images if Path(str(img)).name in noms]
    prevues = [i for i, x in enumerate(slides) if x.get("photo") and res[i] is None] or [i for i in range(len(slides)) if res[i] is None]
    ordre = prevues + [i for i in range(len(slides)) if i not in prevues and res[i] is None]
    for i, img in zip(ordre, libres):
        res[i] = img
    return res


def _txt_dm(p: dict) -> str:
    lignes = [f"Appel à l'action dans la vidéo / la légende :\n{p.get('cta') or ''}", ""]
    for e in p.get("dm") or []:
        lignes += [e.get("etape", ""), e.get("message", ""), ""]
    return "\n".join(lignes).strip() + "\n"


def _ligne_son(p: dict) -> str:
    so = (p.get("source") or {}).get("son") or {}
    if so.get("titre") and not so.get("original"):
        return (f"3. Son du Reel modèle : « {so['titre']} »{' — ' + so['artiste'] if so.get('artiste') else ''}. Cherche-le dans Instagram "
                f"(bouton Audio) au moment de publier{' : ' + so['url'] if so.get('url') else ''}.")
    if so.get("original"):
        return "3. Le Reel modèle utilisait un son original (la voix) : garde ta propre voix, ou ajoute un son tendance à volume bas."
    return "3. Ajoute un son tendance dans Instagram si tu veux (volume bas si tu parles)."


def package(p: dict, d: Path, sortie: Path, fichiers: list[str]) -> str:
    nom = f"{'carrousel' if p['type'] == 'carrousel' else 'reel'}_{p['id'][:15]}.zip"
    lisez = [
        "TON CONTENU PRÊT À PUBLIER", "=" * 26, "",
        "1. Ouvre Instagram > + > " + ("Publication, et sélectionne les slides dans l'ordre (slide_01, slide_02…)."
                                      if p["type"] == "carrousel" else "Reel, et choisis reel.mp4. Mets couverture.jpg comme couverture."),
        "2. Colle la légende de « legende.txt ».",
        _ligne_son(p),
        "4. Active la réponse automatique au mot-clé avec le premier message de « messages-prives.txt ».",
        "5. Publie, puis colle le lien du post dans Veille virale (« J'ai publié ») pour suivre ses résultats.", "",
    ]
    with zipfile.ZipFile(sortie / nom, "w", zipfile.ZIP_DEFLATED) as z:
        for f in fichiers:
            z.write(sortie / f, f)
        z.writestr("legende.txt", (p.get("legende") or "").strip() + "\n")
        if p["type"] == "reel":
            z.writestr("script.txt", f"HOOK (texte à l'écran)\n{p.get('hook') or ''}\n\nSCRIPT\n{p.get('script') or ''}\n")
        z.writestr("messages-prives.txt", _txt_dm(p))
        z.writestr("LISEZ-MOI.txt", "\n".join(lisez))
    return nom


# ------------------------------------------------------------
#  Aperçu en direct (rendu léger, sans file de tâches : aucune API consommée)
# ------------------------------------------------------------
def apercu(esp: Espace, sid: str, i: int) -> bytes:
    """Image JPEG de la slide i telle qu'elle sera créée (ou de la couverture du Reel monté sur la vidéo)."""
    import io
    p = charge(esp, sid)
    d = dossier(esp, sid)
    theme, typo, pseudo = p.get("theme", "sombre"), p.get("typo", "moderne"), p.get("pseudo", "")
    if p["type"] == "reel" and p.get("video"):
        cadre = d / "apercu_cadre.jpg"
        src = d / "sources" / p["video"]
        if not cadre.exists() or cadre.stat().st_mtime < src.stat().st_mtime:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=1080:-2", str(cadre)], capture_output=True, timeout=60)
        im = slide({"titre": p.get("hook") or "", "texte": ""}, 0, 1, cadre if cadre.exists() else None, theme, "", VERTICAL,
                   reel=True, typo=typo)
    else:
        slides = p["slides"] or [{"titre": p.get("hook") or "", "texte": ""}]
        i = max(0, min(i, len(slides) - 1))
        images = attribue(slides, [d / "sources" / x for x in p["images"]])
        reel = p["type"] == "reel"
        im = slide(slides[i], i, len(slides), images[i], theme, pseudo, VERTICAL if reel else CARROUSEL, reel=reel, typo=typo)
    im.thumbnail((540, 960))
    tampon = io.BytesIO()
    im.save(tampon, "JPEG", quality=82)
    return tampon.getvalue()
