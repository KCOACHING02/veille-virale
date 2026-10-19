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
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from espace import CODE, DATA, Espace
from modele import log

POLICES = CODE / "static" / "fonts"
CARROUSEL = (1080, 1350)
VERTICAL = (1080, 1920)
EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXT_VIDEOS = {".mp4", ".mov", ".m4v", ".webm"}
import studio_styles as SS

THEMES = {
    "sombre": {"fond": (39, 27, 45), "texte": (255, 255, 255), "accent": (255, 79, 121), "doux": (216, 206, 221)},
    "clair": {"fond": (246, 244, 248), "texte": (39, 27, 45), "accent": (255, 79, 121), "doux": (94, 81, 102)},
    "rose": {"fond": (255, 79, 121), "texte": (255, 255, 255), "accent": (39, 27, 45), "doux": (255, 227, 234)},
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def couleurs_marque(cfg: dict) -> dict | None:
    """Couleurs saisies dans Réglages → Ta marque ({fond, texte, accent} en #rrggbb), si elles sont complètes."""
    c = ((cfg or {}).get("marque") or {}).get("couleurs") or {}
    return c if all(HEX.match(str(c.get(k) or "")) for k in ("fond", "texte", "accent")) else None


def theme_de(p: dict):
    """Thème à dessiner : un nom de THEMES, ou un dictionnaire (« Ma marque », style de carrousel, couleurs du texte choisies)."""
    c = p.get("couleurs")
    m = SS.MODELES.get(p.get("modele") or "")
    if m:
        th = {**m, "texte": m["titre"], "doux": m["texte"], "titre": m["titre"], "corps": m["texte"], "modele": p["modele"]}
    elif p.get("theme") == "marque" and c:
        fond, texte = _rgb(c["fond"]), _rgb(c["texte"])
        th = {"fond": fond, "texte": texte, "accent": _rgb(c["accent"]),
              "doux": tuple(round(t * 0.78 + f * 0.22) for t, f in zip(texte, fond))}
    else:
        nom = p.get("theme") if p.get("theme") in THEMES else "sombre"
        if not _couleurs_texte(p):
            return nom
        th = {**THEMES[nom], "nom": nom}
    ct = _couleurs_texte(p)
    if ct.get("titre"):
        th["titre"] = th["photo_titre"] = _rgb(ct["titre"])
    if ct.get("texte"):
        th["corps"] = th["photo_texte"] = _rgb(ct["texte"])
    return th


def _couleurs_texte(p: dict) -> dict:
    ct = p.get("couleurs_texte") or {}
    return {k: v for k, v in ct.items() if k in ("titre", "texte") and HEX.match(str(v or ""))}


def _defauts_marque(cfg: dict) -> dict:
    """Thème et typographie par défaut d'un nouveau projet : ceux de la marque s'ils sont réglés."""
    m = (cfg or {}).get("marque") or {}
    d = {}
    if couleurs_marque(cfg):
        d.update(theme="marque", couleurs=couleurs_marque(cfg))
    if m.get("typo") in TYPOS:
        d["typo"] = m["typo"]
    return d


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
NOMS_TYPOS = {"moderne": "Net", "geometrique": "Géométrique", "minimal": "Tech", "douce": "Douce", "impact": "Impact",
              "affiche": "Affiche", "brut": "Brut", "elegant": "Élégant", "classique": "Classique", "retro": "Rétro",
              "manuscrit": "Manuscrit", "signature": "Signature"}
# Palette étendue : polices figées en gras (famille « VV … » pour libass), voir static/fonts/LISEZ-MOI.txt
# id : (fichier, nom affiché, police du texte, majuscules, facteur de taille)
_TXT_SERIF, _TXT_DOUX = "LoraTexte.ttf", "NunitoTexte.ttf"
_PLUS = {
    # Moderne
    "epure": ("Outfit.ttf", "Épuré", "Poppins-Regular.ttf", False, 1.07), "futuriste": ("Sora.ttf", "Futuriste", "Poppins-Regular.ttf", False, 0.96),
    "pro": ("Manrope.ttf", "Pro", "Poppins-Regular.ttf", False, 0.99), "startup": ("PlusJakarta.ttf", "Startup", "Poppins-Regular.ttf", False, 0.97),
    "editorial": ("DMSans.ttf", "Éditorial", "DMSansTexte.ttf", False, 1.05), "urbain": ("Urbanist.ttf", "Urbain", "Poppins-Regular.ttf", False, 1.05),
    "lisible": ("Lexend.ttf", "Lisible", "Poppins-Regular.ttf", False, 1.01), "arty": ("Syne.ttf", "Arty", "Poppins-Regular.ttf", False, 1.08),
    "neutre": ("Inter.ttf", "Neutre", "DMSansTexte.ttf", False, 1.02), "amical": ("Figtree.ttf", "Amical", "Poppins-Regular.ttf", False, 1.05),
    "rond": ("Rubik.ttf", "Rond", "Poppins-Regular.ttf", False, 1.04), "sobre": ("WorkSans.ttf", "Sobre", "Poppins-Regular.ttf", False, 1.06),
    # Impact
    "gros_titre": ("Oswald.ttf", "Gros titre", "Poppins-Medium.ttf", True, 1.0), "gothique": ("LeagueGothic.ttf", "Gothique", "Poppins-Medium.ttf", True, 1.16),
    "stade": ("BigShoulders.ttf", "Stade", "Poppins-Medium.ttf", True, 1.0), "sport": ("BarlowCondensed.ttf", "Sport", "Poppins-Medium.ttf", True, 1.08),
    "energie": ("Teko.ttf", "Énergie", "Poppins-Medium.ttf", True, 1.18), "slab": ("AlfaSlab.ttf", "Slab", "Poppins-Regular.ttf", False, 0.97),
    "massif": ("BowlbyOne.ttf", "Massif", "Poppins-Medium.ttf", False, 0.92), "journal": ("FjallaOne.ttf", "Journal", "Poppins-Medium.ttf", True, 0.94),
    "pochoir": ("Staatliches.ttf", "Pochoir", "Poppins-Medium.ttf", True, 1.0), "urbain_neon": ("Bungee.ttf", "Street", "Poppins-Medium.ttf", True, 0.85),
    # Élégant
    "luxe": ("Cormorant.ttf", "Luxe", _TXT_SERIF, False, 1.26), "livre": ("Baskerville.ttf", "Livre", _TXT_SERIF, False, 0.97),
    "doux_retro": ("Fraunces.ttf", "Doux rétro", _TXT_SERIF, False, 1.1), "couture": ("Prata.ttf", "Couture", _TXT_SERIF, False, 1.0),
    "mode": ("Bodoni.ttf", "Mode", _TXT_SERIF, False, 1.06), "antique": ("Cinzel.ttf", "Antique", _TXT_SERIF, False, 0.94),
    "litteraire": ("Lora.ttf", "Littéraire", _TXT_SERIF, False, 1.04), "magazine": ("Instrument.ttf", "Magazine", _TXT_SERIF, False, 1.1),
    "vintage": ("YoungSerif.ttf", "Vintage", _TXT_SERIF, False, 1.02), "contraste": ("Gloock.ttf", "Contraste", _TXT_SERIF, False, 1.02),
    # Italique
    "italique": ("PlayfairItalique.ttf", "Italique", _TXT_SERIF, False, 1.03), "italique_luxe": ("CormorantItalique.ttf", "Italique luxe", _TXT_SERIF, False, 1.28),
    "italique_fin": ("InstrumentItalique.ttf", "Italique fin", _TXT_SERIF, False, 1.1), "italique_rond": ("FrauncesItalique.ttf", "Italique rond", _TXT_SERIF, False, 1.1),
    # Doux
    "calin": ("Nunito.ttf", "Câlin", _TXT_DOUX, False, 1.05), "bulle": ("Fredoka.ttf", "Bulle", _TXT_DOUX, False, 1.06),
    "ludique": ("Baloo.ttf", "Ludique", _TXT_DOUX, False, 1.1), "aerien": ("Comfortaa.ttf", "Aérien", _TXT_DOUX, False, 0.98),
    "simple": ("VarelaRound.ttf", "Simple", _TXT_DOUX, False, 1.05), "rond_net": ("MPlusRounded.ttf", "Rond net", _TXT_DOUX, False, 1.02),
    "bonbon": ("Sniglet.ttf", "Bonbon", _TXT_DOUX, False, 1.0), "gourmand": ("Chewy.ttf", "Gourmand", _TXT_DOUX, False, 0.95),
    # Manuscrit
    "danse": ("Dancing.ttf", "Danse", "Poppins-Regular.ttf", False, 1.18), "satin": ("Satisfy.ttf", "Satin", "Poppins-Regular.ttf", False, 1.12),
    "calligraphie": ("GreatVibes.ttf", "Calligraphie", "Poppins-Regular.ttf", False, 1.22), "carnet": ("Kalam.ttf", "Carnet", "Poppins-Regular.ttf", False, 1.04),
    "feutre": ("ShadowsIntoLight.ttf", "Feutre fin", "Poppins-Regular.ttf", False, 1.05), "marqueur": ("PermanentMarker.ttf", "Marqueur", "Poppins-Regular.ttf", False, 0.92),
    "fil": ("Sacramento.ttf", "Fil", "Poppins-Regular.ttf", False, 1.38), "craie": ("Amatic.ttf", "Craie", "Poppins-Regular.ttf", False, 1.28),
    "journal_intime": ("IndieFlower.ttf", "Journal intime", "Poppins-Regular.ttf", False, 1.1), "retro_script": ("Yellowtail.ttf", "Rétro script", "Poppins-Regular.ttf", False, 1.12),
    "pinceau": ("Kaushan.ttf", "Pinceau", "Poppins-Regular.ttf", False, 1.0), "lettre": ("Marck.ttf", "Lettre", "Poppins-Regular.ttf", False, 1.2),
    # Fun et rétro
    "lobster": ("Lobster.ttf", "Diner", "Poppins-Medium.ttf", False, 1.0), "arcade": ("Righteous.ttf", "Arcade", "Poppins-Medium.ttf", False, 1.02),
    "disco": ("Monoton.ttf", "Disco", "Poppins-Medium.ttf", True, 0.82), "bloc": ("RubikMono.ttf", "Bloc", "Poppins-Medium.ttf", True, 0.88),
    "seventies": ("Shrikhand.ttf", "Seventies", "Poppins-Medium.ttf", False, 1.04), "titan": ("TitanOne.ttf", "Titan", "Poppins-Medium.ttf", False, 0.97),
    "bd": ("LuckiestGuy.ttf", "BD", "Poppins-Medium.ttf", True, 0.9), "pixel": ("PressStart.ttf", "Pixel", "Poppins-Medium.ttf", False, 0.7),
    "large": ("Unbounded.ttf", "Large", "Poppins-Medium.ttf", False, 0.92), "cartoon": ("Rammetto.ttf", "Cartoon", "Poppins-Medium.ttf", False, 0.88),
    "enseigne": ("CarterOne.ttf", "Enseigne", "Poppins-Medium.ttf", False, 0.98), "gonfle": ("BagelFat.ttf", "Gonflé", "Poppins-Medium.ttf", False, 1.02),
    "chango": ("Chango.ttf", "Gras rétro", "Poppins-Medium.ttf", False, 0.9),
}
for _id, (_f, _n, _t, _maj, _fac) in _PLUS.items():
    TYPOS[_id] = (_f, None, _t, _maj, _fac, "VV " + _f[:-4])
    NOMS_TYPOS[_id] = _n
# Styles et leurs sous-styles (ordre d'affichage dans le studio)
STYLES_TYPO = [
    ("moderne", "Moderne", ["moderne", "geometrique", "minimal", "epure", "futuriste", "pro", "startup", "editorial", "urbain", "lisible", "arty", "neutre", "amical", "rond", "sobre"]),
    ("impact", "Impact", ["impact", "affiche", "brut", "gros_titre", "gothique", "stade", "sport", "energie", "slab", "massif", "journal", "pochoir", "urbain_neon"]),
    ("elegant", "Élégant", ["elegant", "classique", "retro", "luxe", "livre", "doux_retro", "couture", "mode", "antique", "litteraire", "magazine", "vintage", "contraste"]),
    ("italique", "Italique", ["italique", "italique_luxe", "italique_fin", "italique_rond"]),
    ("doux", "Doux", ["douce", "calin", "bulle", "ludique", "aerien", "simple", "rond_net", "bonbon", "gourmand"]),
    ("manuscrit", "Manuscrit", ["manuscrit", "signature", "danse", "satin", "calligraphie", "carnet", "feutre", "marqueur", "fil", "craie", "journal_intime", "retro_script", "pinceau", "lettre"]),
    ("fun", "Fun et rétro", ["lobster", "arcade", "disco", "bloc", "seventies", "titan", "bd", "pixel", "large", "cartoon", "enseigne", "gonfle", "chango"]),
]
STYLE_DE_TYPO = {t: s for s, _, ids in STYLES_TYPO for t in ids}
# Polices aux jambages très hauts ou très bas
INTERLIGNES = {"signature": 1.55, "manuscrit": 1.1, "affiche": 1.05, "carnet": 1.3, "feutre": 1.25, "cartoon": 1.3, "ludique": 1.22,
               "fil": 1.3, "calligraphie": 1.3, "satin": 1.25, "retro_script": 1.22, "danse": 1.2, "lettre": 1.22, "pinceau": 1.22,
               "massif": 1.2, "disco": 1.2, "craie": 1.05, "gothique": 1.02, "energie": 1.0, "pixel": 1.45, "enseigne": 1.22, "seventies": 1.22}
CASSES = ("auto", "majuscules", "normal")


def pseudo_visible(p: dict) -> str:
    """Le @ n'apparaît sur les visuels que si l'utilisatrice l'a demandé."""
    return p.get("pseudo", "") if p.get("afficher_pseudo") else ""


def reglages_typo(p: dict) -> dict:
    """Taille du titre et du texte (en %) et casse choisies pour un projet."""
    r = p.get("typo_reglages") or {}
    def pc(v):
        try:
            return max(60, min(160, int(v)))
        except (TypeError, ValueError):
            return 100
    return {"titre": pc(r.get("titre", 100)), "texte": pc(r.get("texte", 100)), "casse": r.get("casse") if r.get("casse") in CASSES else "auto"}


def typo_projet(p: dict) -> dict:
    return {"id": p.get("typo") if p.get("typo") in TYPOS else "moderne", **reglages_typo(p)}


def _typo(typo) -> dict:
    """Typographie résolue : police, majuscules, facteurs de taille (titre et texte) et interligne."""
    t = typo if isinstance(typo, dict) else {"id": typo}
    cle = t.get("id") if t.get("id") in TYPOS else "moderne"
    f_titre, poids, f_texte, maj, facteur, famille = TYPOS[cle]
    casse = t.get("casse", "auto")
    maj = True if casse == "majuscules" else False if casse == "normal" else maj
    k_titre, k_texte = (t.get("titre") or 100) / 100, (t.get("texte") or 100) / 100
    return {"cle": cle, "police": f_titre + (f"@{poids}" if poids else ""), "texte": f_texte, "maj": maj, "facteur": facteur * k_titre,
            "k_titre": k_titre, "k_texte": k_texte, "famille": famille,
            "interligne": INTERLIGNES.get(cle, 1.12 if maj else 1.18)}
POSITIONS = ("haut", "centre", "bas")
# Mot mis en valeur comme dans le modèle : police d'accent et couleur
STYLES_ACCENT = {"italique": "PlayfairDisplay-Bold.ttf", "manuscrit": "Caveat-Bold.ttf", "couleur": None}
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
            res.append({k: p.get(k) for k in ("id", "cree", "titre", "type", "statut", "miniature", "compte", "cle", "fichiers", "zip")})
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
            mp = x.get("mise_en_page") if isinstance(x.get("mise_en_page"), dict) else {}
            res.append({"titre": (x.get("adapte") or x.get("original") or "").strip(), "texte": (x.get("sous_titre") or "").strip(),
                        "photo": (x.get("photo") or "").strip(), "recherche": (x.get("recherche") or "").strip(),
                        "position": mp.get("position") if mp.get("position") in POSITIONS else "",
                        "alignement": mp.get("alignement") if mp.get("alignement") in ("gauche", "centre") else "",
                        "accent": (mp.get("accent") or "").strip() if mp.get("style_accent") != "aucun" else "",
                        "style_accent": mp.get("style_accent") if mp.get("style_accent") in STYLES_ACCENT else ""})
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
    projet.update(_defauts_marque(cfg))
    projet["nb_photos"] = sum(1 for x in projet["slides"] if x.get("photo"))
    sauve(esp, projet)
    return projet


def cree_vierge(esp: Espace, cfg: dict) -> dict:
    """Carrousel vide, écrit par l'utilisatrice elle-même (aucun appel à Claude) : disponible en formule gratuite."""
    cta = f"Commente {cfg['objectifs'].get('mot_cle_cta') or 'INFO'}"
    sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    projet = {
        "id": sid, "cree": datetime.now().isoformat(timespec="minutes"), "type": "carrousel", "titre": "Nouveau carrousel",
        "analyse_id": None, "cle": None, "compte": None, "miniature": None, "statut": "brouillon", "erreur": None,
        "hook": "", "texte_ecran": "", "script": "", "cta": cta, "dm": [], "legende": "",
        "slides": [{"titre": "", "texte": "", "photo": ""}, {"titre": "", "texte": "", "photo": ""},
                   {"titre": "", "texte": "", "photo": ""}, {"titre": cta, "texte": "", "photo": ""}],
        "images": [], "video": None, "theme": "sombre", "sous_titres": True, "source": {}, "nb_photos": 0, "copie_du_modele": False,
        "style": "ma_voix", "typo": "moderne", "pseudo": (cfg.get("mon_compte") or {}).get("instagram") or "",
        "fichiers": [], "zip": None, "vierge": True,
    }
    projet.update(_defauts_marque(cfg))
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
        raise RuntimeError("Virall.ai n'a pas proposé de slides : tes textes pré-remplis sont gardés, réessaie « Réécrire dans ce style ».")
    p = charge(esp, sid)  # relu : l'utilisateur a pu importer des fichiers pendant ce temps
    anciennes = p.get("slides") or []
    p["slides"] = [{"titre": x.get("titre", "").strip(), "texte": (x.get("texte") or "").strip(), "photo": (x.get("photo") or "").strip(),
                    "recherche": (x.get("recherche") or "").strip(),
                    "image": anciennes[k].get("image", "") if k < len(anciennes) else "",
                    # la mise en page du modèle (position, alignement) reste celle de la slide au même rang
                    **({c: anciennes[k].get(c, "") for c in ("position", "alignement", "style_accent")} if k < len(anciennes) else {})}
                   for k, x in enumerate(slides)][:10]
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


def propositions(esp: Espace, sid: str, i: int, n: int = 8) -> dict:
    """Plusieurs images de la banque pour la slide i, parmi lesquelles l'utilisatrice choisit."""
    import banque
    p = charge(esp, sid)
    if not (0 <= i < len(p["slides"])):
        return {"requete": "", "resultats": []}
    q = requete_photo(p["slides"][i])
    res = banque.photos(q, n=n)
    if len(res) < 3:
        ambiance = next((requete_photo(x) for x in p["slides"] if x.get("photo") or x.get("recherche")), "")
        if ambiance and ambiance != q:
            res += [r for r in banque.photos(ambiance, n=n) if r["id"] not in {x["id"] for x in res}]
    return {"requete": q, "resultats": res[:n]}


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
    for k in ("legende", "hook", "theme", "sous_titres", "type", "pseudo", "titre", "script", "style", "typo", "afficher_pseudo"):
        if k in champs:
            p[k] = champs[k]
    # Couverture du Reel : style, texte, image (moment de la vidéo ou une des photos)
    if champs.get("couv_style") in STYLES_COUV:
        p["couv_style"] = champs["couv_style"]
    if "couv_texte" in champs:
        p["couv_texte"] = str(champs["couv_texte"] or "")[:160]
    if "couv_temps" in champs:
        try:
            p["couv_temps"] = max(0.0, min(180.0, float(champs["couv_temps"])))
        except (TypeError, ValueError):
            pass
    if "couv_image" in champs:
        p["couv_image"] = champs["couv_image"] if champs["couv_image"] in p.get("images", []) else ""
    if isinstance(champs.get("slides"), list):
        anciennes = p.get("slides") or []
        def garde(s, i, k, n):
            return str(s.get(k, anciennes[i].get(k, "") if i < len(anciennes) else ""))[:n]
        p["slides"] = [{"titre": str(s.get("titre", ""))[:200], "texte": str(s.get("texte", ""))[:400], "photo": garde(s, i, "photo", 300),
                        "recherche": garde(s, i, "recherche", 120), "image": garde(s, i, "image", 80),
                        "position": garde(s, i, "position", 10), "alignement": garde(s, i, "alignement", 10),
                        "accent": garde(s, i, "accent", 120), "style_accent": garde(s, i, "style_accent", 12),
                        "surtitre": garde(s, i, "surtitre", 60), "note": garde(s, i, "note", 90)}
                       for i, s in enumerate(champs["slides"])][:10]
        for x in p["slides"]:
            if x["image"] not in p["images"]:
                x["image"] = ""
        p["nb_photos"] = sum(1 for x in p["slides"] if x.get("photo"))
    if isinstance(champs.get("images"), list):  # nouvel ordre des images
        p["images"] = [i for i in champs["images"] if i in p["images"]] + [i for i in p["images"] if i not in champs["images"]]
    if p["theme"] not in THEMES and p["theme"] != "marque":
        p["theme"] = "sombre"
    if p.get("style") not in STYLES:
        p["style"] = "ma_voix"
    if p.get("typo") not in TYPOS:
        p["typo"] = "moderne"
    # Style de carrousel : fond, couleurs, typographie et décors d'un coup (les couleurs choisies à la main repartent de zéro)
    if "modele" in champs:
        mid = champs["modele"] if champs["modele"] in SS.MODELES else ""
        p["modele"] = mid
        if mid:
            p["typo"] = SS.MODELES[mid]["typo"]
            p["couleurs_texte"] = {}
    if "theme" in champs and "modele" not in champs:
        p["modele"] = ""
    if isinstance(champs.get("couleurs_texte"), dict):
        ct = {**(p.get("couleurs_texte") or {}), **champs["couleurs_texte"]}
        p["couleurs_texte"] = {k: v for k, v in ct.items() if k in ("titre", "texte") and HEX.match(str(v or ""))}
    if isinstance(champs.get("typo_reglages"), dict):
        p["typo_reglages"] = reglages_typo({"typo_reglages": {**reglages_typo(p), **champs["typo_reglages"]}})
    sauve(esp, p)
    return p


# ------------------------------------------------------------
#  Texte et images (Pillow)
# ------------------------------------------------------------
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍\U000E0000-\U000E007F]+")


def propre(t: str) -> str:
    """Retire les emojis (absents de la police) et les espaces superflus."""
    return re.sub(r"[ \t]+", " ", _EMOJI.sub("", t or "").replace("…", "...")).strip()


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


def fichier_police(x: str) -> str:
    """Police désignée par un id de typographie (« feutre ») ou par un nom de fichier."""
    return TYPOS[x][0] if x in TYPOS else x


def _largeur(d, mot: str, f, serre: float = 0.0) -> float:
    w = d.textlength(mot, font=f)
    return w + serre * f.size * (len(mot) - 1) if serre and len(mot) > 1 else w


def _ecrit(d, xy, mot: str, f, couleur, serre: float = 0.0):
    """Écrit un mot, avec un approche de lettres resserrée (serre < 0) si demandé."""
    if not serre or len(mot) < 2:
        d.text(xy, mot, font=f, fill=couleur)
        return
    x, y = xy
    for k, ch in enumerate(mot):
        d.text((x + d.textlength(mot[:k], font=f) + serre * f.size * k, y), ch, font=f, fill=couleur)


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


def insecables(t: str) -> str:
    """Typographie française : « ? », « ! », « : », « ; » et « » » ne partent jamais seuls à la ligne."""
    return re.sub(r"« ", "«\u00a0", re.sub(r" ([?!:;»])", "\u00a0\\1", t))


def _mots(t: str) -> list[str]:
    return [m for m in re.split(r"[ \t\n]+", t) if m]


def _jetons(titre: str, accent: str) -> list[tuple[str, bool]]:
    """Mots du titre, ceux de l'expression d'accent étant marqués (comparaison sans tenir compte de la casse)."""
    titre = insecables(titre)
    if accent:
        k = titre.lower().find(accent.lower())
        if k >= 0:
            av, ac, ap = titre[:k], titre[k:k + len(accent)], titre[k + len(accent):]
            jetons = [(m, False) for m in _mots(av)] + [(m, True) for m in _mots(ac)]
            # ponctuation collée à l'expression (« crois. ») : elle reste accrochée au dernier mot, dans son style
            colle = re.match(r"^[^\s]+", ap)
            if colle and jetons:
                jetons[-1] = (jetons[-1][0] + colle.group(0), jetons[-1][1])
                ap = ap[colle.end():]
            return jetons + [(m, False) for m in _mots(ap)]
    return [(m, False) for m in _mots(titre)]


def _compose(d, jetons, police_titre, police_accent, largeur, hauteur, maxi, mini, interligne, serre: float = 0.0):
    """Plus grande taille pour laquelle le titre (avec ses mots d'accent) tient dans la boîte : lignes de (mot, police, accent)."""
    taille = maxi
    while True:
        pol, pol_a = _police(police_titre, taille), _police(police_accent, int(taille * 1.08)) if police_accent else None
        espace = d.textlength(" ", font=pol)
        lignes, ligne, larg = [], [], 0
        for mot, acc in jetons:
            f = pol_a if (acc and pol_a) else pol
            w = _largeur(d, mot, f, 0.0 if (acc and pol_a) else serre)
            if ligne and larg + espace + w > largeur:
                lignes.append(ligne)
                ligne, larg = [], 0
            ligne.append((mot, f, acc, w))
            larg += (espace if len(ligne) > 1 else 0) + w
        if ligne:
            lignes.append(ligne)
        h = int(len(lignes) * taille * interligne)
        if h <= hauteur or taille <= mini:
            return lignes, h, taille, espace
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


FILIGRANE = "Fait avec " + os.getenv("NOM_PRODUIT", "Virallink")


def slide(slide_: dict, i: int, n: int, image: Path | None, theme: str, pseudo: str, taille=CARROUSEL, reel: bool = False,
          typo="moderne", filigrane: bool = False):
    """Dessine une slide. Avec image : texte en bas sur un dégradé. Sans image : fond du thème ou du style de carrousel
    (papier, kraft, carnet…), avec ses décors (numéro, surtitre, note manuscrite)."""
    from PIL import Image, ImageDraw
    th = theme if isinstance(theme, dict) else THEMES.get(theme, THEMES["sombre"])
    modele = th.get("modele")
    l, h = taille
    marge = int(l * 0.085)
    ty = _typo(typo)
    police_titre, majuscules, facteur = ty["police"], ty["maj"], ty["facteur"]
    f_texte = fichier_police(th["texte_police"]) if th.get("texte_police") else ty["texte"]
    serre = th.get("serre", 0.0) if modele and ty["cle"] == th.get("typo") else 0.0
    if modele and ty["cle"] == th.get("typo"):
        facteur *= th.get("k_titre", 1.0)
    titre, texte = propre(slide_.get("titre", "")), propre(slide_.get("texte", ""))
    surtitre, note_txt = propre(slide_.get("surtitre", "")), propre(slide_.get("note", ""))
    if majuscules:
        titre = titre.upper()
    premiere, derniere = i == 0, i == n - 1
    if image and image.exists():
        fond = _couvre(Image.open(image).convert("RGB"), taille).convert("RGBA")
        fond.alpha_composite(_degrade(taille, 0.32 if (texte or premiere) else 0.45))
        couleur, couleur2 = th.get("photo_titre") or (255, 255, 255), th.get("photo_texte") or (235, 228, 238)
        accent = th["accent"] if theme != "rose" else (255, 79, 121)
        sur_photo = True
    else:
        fond = SS.fond(th.get("texture") or "uni", th["fond"], th.get("fond2") or th["fond"], taille) if modele else Image.new("RGBA", taille, th["fond"] + (255,))
        couleur, couleur2, accent = th.get("titre") or th["texte"], th.get("corps") or th["doux"], th["accent"]
        sur_photo = False
    d = ImageDraw.Draw(fond)
    largeur = l - 2 * marge
    # Mise en page : celle de la slide si elle est choisie, sinon celle du style, sinon texte en bas sur photo et centré sur fond uni
    position = slide_.get("position") if slide_.get("position") in POSITIONS else (
        "bas" if sur_photo and not modele else th.get("position") or ("bas" if sur_photo else "centre"))
    alignement = slide_.get("alignement") if slide_.get("alignement") in ("gauche", "centre") else th.get("alignement", "gauche")
    centre = alignement == "centre"
    style_acc = slide_.get("style_accent") if slide_.get("style_accent") in STYLES_ACCENT else ""
    accent_txt = propre(slide_.get("accent", ""))
    if majuscules:
        accent_txt = accent_txt.upper()
    surligne = bool(th.get("surligne")) and style_acc == "couleur"
    police_accent = STYLES_ACCENT.get(style_acc) if accent_txt else None
    couleur_acc = couleur if surligne else accent if style_acc == "couleur" else ((255, 233, 199) if sur_photo else accent) if accent_txt else couleur
    h_titre_max = int(h * (0.42 if premiere else 0.30) * max(1.0, min(1.4, ty["k_titre"])))
    maxi = int((104 if premiere else (82 if sur_photo else 96)) * facteur)
    interligne = ty["interligne"] - (0.08 if serre else 0)
    lignes_t, ht, taille_t, espace = _compose(d, _jetons(titre, accent_txt), police_titre, police_accent, largeur, h_titre_max,
                                              maxi, int(46 * facteur), interligne, serre)
    pol_x, lignes_x, hx, taille_x = (None, [], 0, 0)
    if texte:
        kx = ty["k_texte"] * th.get("k_texte", 1.0)
        pol_x, lignes_x, hx, taille_x = _ajuste(d, texte, f_texte, largeur, int(h * 0.26 * max(1.0, min(1.4, kx))), int(46 * kx), int(30 * kx), 1.32)
    # Numéro « (01) » (slides de contenu) et surtitre « à faire »
    numero = ""
    if th.get("numero") and n > 2 and not premiere and not (derniere and n > 3):
        try:
            numero = th["numero"].format(i)
        except (ValueError, IndexError):
            numero = str(i)
    pol_num = _police("Medium", int(36 * ty["k_texte"])) if numero else None
    h_num = int(pol_num.size * 1.9) if numero else 0
    style_sur = th.get("surtitre", "petit")
    pol_sur, h_sur = None, 0
    if surtitre:
        if style_sur == "grand":
            pol_sur = _police(police_titre, int(taille_t * 1.3))
            h_sur = int(pol_sur.size * 1.15)
        else:
            pol_sur = _police("Bold" if style_sur == "etiquette" else "Medium", int(30 * ty["k_texte"]))
            h_sur = int(pol_sur.size * (2.3 if style_sur == "etiquette" else 1.9))
    barre = th.get("barre", True) and not surtitre and not numero
    ecart = int(taille_t * 0.55) if texte else 0
    bloc = h_num + h_sur + ht + ecart + hx + int(h * 0.025)
    y = {"haut": int(h * (0.2 if modele else 0.17)), "centre": (h - bloc) // 2, "bas": h - int(h * 0.12) - bloc}[position]
    y = max(y, int(h * 0.1))
    if sur_photo and position != "bas":  # texte en haut ou au centre d'une photo : voile sombre léger pour la lisibilité
        voile = Image.new("RGBA", taille, (15, 10, 18, (110 if modele else 70) if position == "centre" else 0))
        if position == "haut":
            voile = _degrade(taille, 0.0, 170).transpose(Image.FLIP_TOP_BOTTOM)
        fond.alpha_composite(voile)
        d = ImageDraw.Draw(fond)

    def x_de(larg):
        return (l - larg) // 2 if centre else marge
    if numero:
        d.text((x_de(d.textlength(numero, font=pol_num)), y), numero, font=pol_num, fill=couleur2)
        y += h_num
    if surtitre:
        if style_sur == "grand":
            w = _largeur(d, surtitre, pol_sur, serre)
            _ecrit(d, (x_de(w), y), surtitre, pol_sur, couleur, serre)
        elif style_sur == "etiquette":
            w = d.textlength(surtitre.upper(), font=pol_sur)
            x = x_de(w + pol_sur.size * 1.2)
            d.rounded_rectangle([x, y, x + w + pol_sur.size * 1.2, y + pol_sur.size * 1.7], radius=int(pol_sur.size * 0.85), fill=accent)
            d.text((x + pol_sur.size * 0.6, y + pol_sur.size * 0.3), surtitre.upper(), font=pol_sur, fill=SS.lisible_sur(accent))
        else:
            ecart_l = int(pol_sur.size * 0.12)
            w = d.textlength(surtitre.upper(), font=pol_sur) + ecart_l * len(surtitre)
            _ecrit(d, (x_de(w), y), surtitre.upper(), pol_sur, accent if not sur_photo else couleur2, ecart_l / pol_sur.size)
        y += h_sur
    if barre:  # barre d'accent au-dessus du titre (alignée comme le texte)
        xb = (l - 86) // 2 if centre else marge
        d.rounded_rectangle([xb, y - 34, xb + 86, y - 22], radius=6, fill=accent)
    for ligne in lignes_t:
        larg = sum(w for _, _, _, w in ligne) + espace * (len(ligne) - 1)
        x = x_de(larg)
        for mot, f, acc, w in ligne:
            if acc and surligne:  # mot surligné au feutre
                d.rectangle([x - 6, y + taille_t * 0.42, x + w + 6, y + taille_t * 1.02], fill=accent)
            _ecrit(d, (x, y + (int(-taille_t * 0.06) if acc and police_accent else 0)), mot, f, couleur_acc if acc else couleur,
                   0.0 if (acc and police_accent) else serre)
            x += w + espace
        y += int(taille_t * interligne)
    y += ecart
    for ligne in lignes_x:
        d.text((x_de(d.textlength(ligne, font=pol_x)), y), ligne, font=pol_x, fill=couleur2)
        y += int(taille_x * 1.32)
    # Note manuscrite (entourée, post-it, flèche ou soulignée)
    style_note = th.get("note") or "cercle"
    if note_txt:
        bas = h - int(h * (0.13 if reel else 0.06))
        base_note = 44 * ty["k_texte"] * _typo(th.get("note_police") or "feutre")["facteur"]
        for k in (1.0, 0.85, 0.72, 0.6):  # la note se fait plus petite s'il le faut pour tenir sous le texte
            pol_note = _police(fichier_police(th.get("note_police") or "feutre"), int(base_note * k))
            calque = SS.note(note_txt, style_note, pol_note, couleur, accent, th["fond"], int(l * 0.42))
            cw, ch = calque.size
            if bas - ch >= y - int(h * 0.01):
                break
        yn = max(min(max(y + int(h * 0.02), int(h * 0.55)), bas - ch), int(h * 0.1))
        xn = l - marge - cw + 30 if not centre else (l - cw) // 2
        fond.alpha_composite(calque, (int(max(0, xn)), int(max(0, yn))))
        d = ImageDraw.Draw(fond)
    # Compteur, pseudo, invitation à faire glisser
    petit = _police("Medium", 30)
    haut = int(h * (0.09 if reel else 0.045))  # en Reel, on laisse la place à l'interface d'Instagram
    if pseudo:
        d.text((marge, haut), "@" + pseudo.lstrip("@"), font=petit, fill=couleur2)
    if n > 1 and not derniere and not reel and not note_txt:  # flèche seule pour inviter à faire glisser
        c_g = accent if not sur_photo else couleur
        x_f, y_m = l - marge - 56, h - int(h * 0.065) + 22
        d.line([(x_f, y_m), (x_f + 54, y_m)], fill=c_g, width=5)
        d.line([(x_f + 38, y_m - 15), (x_f + 55, y_m), (x_f + 38, y_m + 15)], fill=c_g, width=5, joint="curve")
    if filigrane:  # formule gratuite : discret, en bas à gauche (« Glisse » est en bas à droite)
        fil = _police("Medium", 24)
        d.text((marge, h - int(h * 0.065) + 4), FILIGRANE, font=fil, fill=couleur2)
    return fond.convert("RGB")


def vignette_modele(mid: str, largeur: int = 270) -> bytes:
    """Aperçu d'un style de carrousel sur un exemple de slide (mis en cache)."""
    import io
    cache = DATA / "cache" / "modeles"
    f = cache / f"{mid}-{largeur}-v2.jpg"
    if f.exists():
        return f.read_bytes()
    m = SS.MODELES[mid]
    th = {**m, "texte": m["titre"], "doux": m["texte"], "titre": m["titre"], "corps": m["texte"], "modele": mid}
    exemple = {"titre": "J'ai arrêté d'attendre de me sentir prête", "texte": "Si j'attendais d'être sûre à 100 %, je ne partirais jamais.",
               "note": "commence avant d'être prête" if m.get("note") else "", "accent": "prête" if m.get("surligne") else "",
               "style_accent": "couleur" if m.get("surligne") else ""}
    im = slide(exemple, 1, 8, None, th, "", typo={"id": m["typo"]})
    im.thumbnail((largeur, largeur * 2))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    cache.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b.getvalue())
    return b.getvalue()


# ------------------------------------------------------------
#  Couverture du Reel (image de la vidéo ou photo + texte, plusieurs mises en page)
#  Tout le texte reste dans la zone 3:4 centrale : il n'est pas coupé dans la grille du profil Instagram.
# ------------------------------------------------------------
STYLES_COUV = {"hook": "Hook en bas", "centre": "Titre centré", "bandeau": "Bandeau", "magazine": "Magazine", "etiquette": "Étiquettes",
               "cadre": "Cadre", "split": "Moitié couleur"}
ZONE_GRILLE = (240, 1680)  # en 1080x1920, la grille du profil montre la bande 3:4 du milieu


def image_couverture(p: dict, d: Path, temps: float | None = None, image: str | None = None) -> Path | None:
    """Image de fond de la couverture : une photo choisie, sinon l'image de la vidéo au moment choisi, sinon la 1re photo."""
    nom = p.get("couv_image") if image is None else image
    if nom and nom in p.get("images", []) and (d / "sources" / nom).exists():
        return d / "sources" / nom
    if p.get("video") and (d / "sources" / p["video"]).exists():
        t = float(p.get("couv_temps", 0.6) if temps is None else temps)
        dossier_c = d / "couv_cadres"
        dossier_c.mkdir(exist_ok=True)
        f = dossier_c / f"{t:.1f}.jpg"
        if not f.exists():
            src = d / "sources" / p["video"]
            vf = (TONEMAP + "format=yuvj420p,") if _hdr(src) else ""
            for filtre in (vf + "scale=1080:-2", "scale=1080:-2"):
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", filtre,
                                "-q:v", "3", str(f)], capture_output=True, timeout=90)
                if f.exists():
                    break
        if f.exists():
            return f
    if p.get("images"):
        return d / "sources" / p["images"][0]
    return None


def couverture(p: dict, fond_img: Path | None, style: str | None = None, texte: str | None = None):
    """Couverture 1080x1920 dans le style choisi."""
    from PIL import Image, ImageDraw
    style = style or p.get("couv_style") or "hook"
    titre = propre(texte if texte is not None else (p.get("couv_texte") or p.get("hook") or ""))
    theme, typo = theme_de(p), typo_projet(p)
    if style == "hook":
        return slide({"titre": titre, "texte": ""}, 0, 1, fond_img, theme, "", VERTICAL, reel=True, typo=typo)
    th = theme if isinstance(theme, dict) else THEMES.get(theme, THEMES["sombre"])
    l, h = VERTICAL
    ty = _typo(typo)
    police, majuscules, facteur = ty["police"], ty["maj"], ty["facteur"]
    interligne = INTERLIGNES.get(ty["cle"], 1.1 if majuscules else 1.16)
    if majuscules:
        titre = titre.upper()
    haut, bas = ZONE_GRILLE
    marge = 90
    if fond_img and fond_img.exists():
        fond = _couvre(Image.open(fond_img).convert("RGB"), VERTICAL).convert("RGBA")
    else:
        fond = SS.fond(th["texture"], th["fond"], th.get("fond2") or th["fond"], VERTICAL) if th.get("texture") else Image.new("RGBA", VERTICAL, th["fond"] + (255,))
    accent = th["accent"] if theme != "rose" else (255, 255, 255)
    d = ImageDraw.Draw(fond)

    def bloc_texte(x0, y0, largeur, hauteur, maxi, couleur, centre=True, ombre=False):
        nonlocal d
        lignes, ht, taille, espace = _compose(d, _jetons(titre, ""), police, None, largeur, hauteur, int(maxi * facteur), int(48 * facteur), interligne)
        y = y0 + (hauteur - ht) // 2
        for ligne in lignes:
            larg = sum(w for _, _, _, w in ligne) + espace * (len(ligne) - 1)
            x = x0 + ((largeur - larg) // 2 if centre else 0)
            for mot, f, _, w in ligne:
                if ombre:
                    d.text((x + 3, y + 4), mot, font=f, fill=(0, 0, 0, 120))
                d.text((x, y), mot, font=f, fill=couleur)
                x += w + espace
            y += int(taille * interligne)
        return lignes, ht, taille, espace

    if style == "centre":
        fond.alpha_composite(Image.new("RGBA", VERTICAL, (12, 8, 16, 120)))
        d = ImageDraw.Draw(fond)
        d.rounded_rectangle([(l - 120) // 2, 640, (l + 120) // 2, 654], radius=7, fill=accent)
        bloc_texte(marge, 690, l - 2 * marge, 620, 150, (255, 255, 255), ombre=True)
    elif style == "bandeau":
        lignes, ht, taille, espace = _compose(d, _jetons(titre, ""), police, None, l - 2 * marge - 60, 420, int(110 * facteur), int(46 * facteur), interligne)
        y_b = 1180
        d.rounded_rectangle([marge - 10, y_b, l - marge + 10, y_b + ht + 90], radius=26, fill=th["accent"] + (245,))
        coul = (255, 255, 255) if sum(th["accent"]) < 600 else (30, 20, 30)
        y = y_b + 45
        for ligne in lignes:
            larg = sum(w for _, _, _, w in ligne) + espace * (len(ligne) - 1)
            x = (l - larg) // 2
            for mot, f, _, w in ligne:
                d.text((x, y), mot, font=f, fill=coul)
                x += w + espace
            y += int(taille * interligne)
    elif style == "magazine":
        voile = _degrade(VERTICAL, 0.0, 200).transpose(Image.FLIP_TOP_BOTTOM)
        fond.alpha_composite(voile)
        d = ImageDraw.Draw(fond)
        petit = _police("Bold", 34)
        kicker = "NOUVEAU"
        d.rounded_rectangle([marge, haut + 70, marge + d.textlength(kicker, font=petit) + 40, haut + 128], radius=29, fill=accent)
        d.text((marge + 20, haut + 78), kicker, font=petit, fill=(255, 255, 255) if sum(accent) < 600 else (30, 20, 30))
        bloc_texte(marge, haut + 160, l - 2 * marge, 560, 132, (255, 255, 255), centre=False, ombre=True)
        if pseudo_visible(p):
            pol = _police("Medium", 34)
            d.text((marge, bas - 110), "@" + p["pseudo"].lstrip("@"), font=pol, fill=(255, 255, 255))
    elif style == "etiquette":
        fond.alpha_composite(Image.new("RGBA", VERTICAL, (0, 0, 0, 40)))
        d = ImageDraw.Draw(fond)
        lignes, ht, taille, espace = _compose(d, _jetons(titre, ""), police, None, l - 2 * marge - 50, 640, int(92 * facteur), int(44 * facteur), 1.42)
        y = 960 - ht // 2
        for ligne in lignes:
            larg = sum(w for _, _, _, w in ligne) + espace * (len(ligne) - 1)
            x = (l - larg) // 2
            d.rounded_rectangle([x - 26, y - int(taille * .14), x + larg + 26, y + int(taille * 1.16)], radius=18, fill=(255, 255, 255, 245))
            for mot, f, _, w in ligne:
                d.text((x, y), mot, font=f, fill=(25, 18, 28))
                x += w + espace
            y += int(taille * 1.42)
    elif style == "cadre":
        fond.alpha_composite(_degrade(VERTICAL, 0.45, 220))
        d = ImageDraw.Draw(fond)
        d.rounded_rectangle([46, haut + 30, l - 46, bas - 30], radius=36, outline=(255, 255, 255), width=7)
        bloc_texte(marge + 20, bas - 640, l - 2 * marge - 40, 520, 118, (255, 255, 255), centre=False, ombre=True)
    elif style == "split":
        coupe = 1000
        haut_img = fond.crop((0, 0, l, coupe)) if fond_img else None
        fond = SS.fond(th["texture"], th["fond"], th.get("fond2") or th["fond"], VERTICAL) if th.get("texture") else Image.new("RGBA", VERTICAL, th["fond"] + (255,))
        if haut_img is not None:
            fond.paste(_couvre(haut_img.convert("RGB"), (l, coupe)).convert("RGBA"), (0, 0))
        d = ImageDraw.Draw(fond)
        d.rectangle([0, coupe - 8, l, coupe + 8], fill=th["accent"])
        bloc_texte(marge, coupe + 70, l - 2 * marge, bas - coupe - 130, 118, th["texte"])
    return fond.convert("RGB")


def couvertures(p: dict, d: Path, sortie: Path) -> list[str]:
    """couverture.jpg (9:16) et couverture_grille.jpg (3:4, telle qu'elle apparaît dans la grille du profil)."""
    im = couverture(p, image_couverture(p, d))
    im.save(sortie / "couverture.jpg", "JPEG", quality=91)
    im.crop((0, ZONE_GRILLE[0], 1080, ZONE_GRILLE[1])).save(sortie / "couverture_grille.jpg", "JPEG", quality=91)
    return ["couverture.jpg", "couverture_grille.jpg"]


def apercu_couverture(esp: Espace, sid: str, style: str | None, temps: float | None, image: str | None, texte: str | None, grille: bool = False,
                      largeur: int = 540) -> bytes:
    import io
    p = charge(esp, sid)
    d = dossier(esp, sid)
    p["couleurs"] = couleurs_marque(esp.lit_config()) if p.get("theme") == "marque" else p.get("couleurs")
    im = couverture(p, image_couverture(p, d, temps, image), style if style in STYLES_COUV else None, texte)
    if grille:
        im = im.crop((0, ZONE_GRILLE[0], 1080, ZONE_GRILLE[1]))
    im.thumbnail((largeur, largeur * 2))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=80)
    return b.getvalue()


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


def _ass_couleur(c: tuple) -> str:
    return "&H00%02X%02X%02X" % (c[2], c[1], c[0])


def fichier_ass(hook: str, duree_hook: float, blocs: list, chemin: Path, typo="moderne", couleurs: dict | None = None):
    ty = _typo(typo)
    majuscules, facteur, famille = ty["maj"], ty["facteur"], ty["famille"]
    facteur_sous = facteur / ty["k_titre"] * ty["k_texte"]
    if majuscules:
        hook = hook.upper()
    hook = insecables(hook)
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
""".replace("{famille}", famille).replace("{taille_hook}", str(int(74 * facteur))).replace("{taille_sous}", str(int(82 * facteur_sous)))
    couleurs = couleurs or {}
    if couleurs.get("titre"):  # hook dans la couleur choisie, sur un cadre clair ou foncé selon ce qui reste lisible
        c = _rgb(couleurs["titre"])
        cadre = (39, 27, 45) if SS.lisible_sur(c) == (20, 20, 20) else (255, 255, 255)
        entete = entete.replace("Style: Hook,{0},{1},&H002D1B27,&H000000FF,&H00FFFFFF,&H00FFFFFF".format(famille, int(74 * facteur)),
                                "Style: Hook,{0},{1},{2},&H000000FF,{3},{3}".format(famille, int(74 * facteur), _ass_couleur(c), _ass_couleur(cadre)))
    if couleurs.get("texte"):
        c = _rgb(couleurs["texte"])
        entete = entete.replace("Style: Sous,{0},{1},&H00FFFFFF".format(famille, int(82 * facteur_sous)),
                                "Style: Sous,{0},{1},{2}".format(famille, int(82 * facteur_sous), _ass_couleur(c)))
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
    fichier_ass(propre(p.get("hook") or ""), min(3.5, duree or 3.5), blocs, d / "sous.ass", typo_projet(p), _couleurs_texte(p))
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
    log("Je crée la couverture…")
    try:
        return ["reel.mp4", *couvertures(p, d, sortie)]
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️  Couverture impossible ({str(e)[:100]})")
        return ["reel.mp4"]


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
        slide(s, i, len(slides), img, theme_de(p), pseudo_visible(p), VERTICAL, reel=True,
              typo=typo_projet(p)).save(plans / f"{i:02d}.jpg", "JPEG", quality=92)
    liste_ = "".join(f"file 'plans/{i:02d}.jpg'\nduration {SLIDE_DIAPORAMA_S}\n" for i in range(len(slides)))
    liste_ += f"file 'plans/{len(slides) - 1:02d}.jpg'\n"
    (d / "plans.txt").write_text(liste_, encoding="utf-8")
    log("Montage du diaporama…")
    duree = SLIDE_DIAPORAMA_S * len(slides)
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "plans.txt", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-vf", "fps=30,format=yuv420p,setsar=1", "-t", f"{duree:.1f}", "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "64k",
             *ENCODAGE, str(sortie / "reel.mp4")], d)
    shutil.rmtree(plans, ignore_errors=True)
    return ["reel.mp4", *couvertures(p, d, sortie)]


# ------------------------------------------------------------
#  Génération + package
# ------------------------------------------------------------
def genere(esp: Espace, sid: str, demo: bool = False, filigrane: bool = False) -> dict:
    p = charge(esp, sid)
    d = dossier(esp, sid)
    sortie = d / "sortie"
    shutil.rmtree(sortie, ignore_errors=True)
    sortie.mkdir()
    p.update(statut="en_cours", erreur=None)
    if p.get("theme") == "marque":  # couleurs de la marque telles qu'elles sont réglées aujourd'hui
        p["couleurs"] = couleurs_marque(esp.lit_config())
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
                slide(s, i, n, img, theme_de(p), pseudo_visible(p), typo=typo_projet(p), filigrane=filigrane).save(
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
                                      if p["type"] == "carrousel" else "Reel, et choisis reel.mp4. Touche « Modifier la couverture » > « Ajouter depuis la pellicule » et prends couverture.jpg "
                                         "(couverture_grille.jpg montre ce qui apparaîtra dans la grille de ton profil)."),
        "2. Colle la légende de « legende.txt ».",
        _ligne_son(p),
        "4. Active la réponse automatique au mot-clé avec le premier message de « messages-prives.txt ».",
        "5. Publie, puis colle le lien du post dans Virallink (« J'ai publié ») pour suivre ses résultats.", "",
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
def apercu(esp: Espace, sid: str, i: int, filigrane: bool = False) -> bytes:
    """Image JPEG de la slide i telle qu'elle sera créée (ou de la couverture du Reel monté sur la vidéo)."""
    import io
    p = charge(esp, sid)
    d = dossier(esp, sid)
    p["couleurs"] = couleurs_marque(esp.lit_config()) if p.get("theme") == "marque" else p.get("couleurs")
    theme, typo, pseudo = theme_de(p), typo_projet(p), pseudo_visible(p)
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
        im = slide(slides[i], i, len(slides), images[i], theme, pseudo, VERTICAL if reel else CARROUSEL, reel=reel, typo=typo,
                   filigrane=filigrane and not reel)
    im.thumbnail((540, 960))
    tampon = io.BytesIO()
    im.save(tampon, "JPEG", quality=82)
    return tampon.getvalue()
