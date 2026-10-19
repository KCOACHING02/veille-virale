"""
Boutique en lien dans la bio : une page publique par client (veille-virale…/@pseudo) avec liens, réseaux,
produits numériques vendus via le Stripe de la cliente (Stripe Connect), capture d'e-mails et kit média.

Données : DATA/espaces/<id>/boutique/
    page.json      contenu, design, produits, kit média
    images/        photo, couverture, visuels (réduits)
    fichiers/      produits à télécharger (jamais servis sans jeton)
    inscrits.json  e-mails capturés        ventes.json  achats        stats.json  vues et clics
Le pseudo est unique : table « boutiques » de app.db.
"""

from __future__ import annotations

import colorsys
import html
import json
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

import abonnements as ab
from espace import DATA

E = html.escape
CSS_COMMUN = (Path(__file__).resolve().parent / "static" / "boutique.css").read_text(encoding="utf-8")
VERROUS: dict[int, threading.Lock] = {}
_v = threading.Lock()


def verrou(uid: int) -> threading.Lock:
    with _v:
        return VERROUS.setdefault(int(uid), threading.Lock())


# ------------------------------------------------------------
#  Pseudo unique
# ------------------------------------------------------------
RESERVES = {"app", "api", "admin", "static", "media", "connexion", "cgv", "confidentialite", "mentions-legales", "boutique",
            "studio", "aide", "support", "veille", "veillevirale", "kit", "www", "root", "contact"}
MOTIF_PSEUDO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")


def init():
    with ab._verrou, ab._db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS boutiques(pseudo TEXT PRIMARY KEY, uid INTEGER UNIQUE NOT NULL)")


def nettoie_pseudo(p: str) -> str:
    import unicodedata
    p = unicodedata.normalize("NFKD", (p or "").strip().lstrip("@").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9._-]+", "", p.replace(" ", "-"))).strip("-.")[:30]


def uid_de(pseudo: str) -> int | None:
    with ab._db() as c:
        r = c.execute("SELECT uid FROM boutiques WHERE pseudo=?", (pseudo.lower(),)).fetchone()
    return r["uid"] if r else None


def pseudo_de(uid: int) -> str | None:
    with ab._db() as c:
        r = c.execute("SELECT pseudo FROM boutiques WHERE uid=?", (uid,)).fetchone()
    return r["pseudo"] if r else None


def pseudo_libre(pseudo: str, uid: int | None = None) -> str | None:
    """None si le pseudo est utilisable, sinon la raison."""
    if not MOTIF_PSEUDO.match(pseudo or ""):
        return "3 à 30 caractères : lettres sans accent, chiffres, point, tiret ou tiret bas."
    if pseudo in RESERVES:
        return "Ce nom est réservé, choisis-en un autre."
    autre = uid_de(pseudo)
    if autre and autre != uid:
        return "Ce nom est déjà pris, essaie une variante."
    return None


def reserve_pseudo(uid: int, pseudo: str) -> str | None:
    err = pseudo_libre(pseudo, uid)
    if err:
        return err
    with ab._verrou, ab._db() as c:
        c.execute("DELETE FROM boutiques WHERE uid=?", (uid,))
        c.execute("INSERT INTO boutiques(pseudo, uid) VALUES(?, ?)", (pseudo, uid))
    return None


# ------------------------------------------------------------
#  Stockage
# ------------------------------------------------------------
def dossier(uid: int) -> Path:
    d = DATA / "espaces" / str(uid) / "boutique"
    for s in ("images", "fichiers"):
        (d / s).mkdir(parents=True, exist_ok=True)
    return d


def _lit(f: Path, defaut):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defaut


def _ecrit(f: Path, donnees):
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


# Réglages qui dépendent de la formule de la propriétaire (fournis par app.py, qui connaît les abonnements)
AVEC_MARQUE = lambda uid: True       # noqa: E731  mention « Créé avec Veille virale » (formule gratuite)
TAUX_COMMISSION = lambda uid: None   # noqa: E731  % prélevé sur les ventes ; None = BOUTIQUE_COMMISSION


def lit_page(uid: int) -> dict | None:
    p = _lit(dossier(uid) / "page.json", None)
    if p:
        p.pop("_marque", None)
        p["design"] = {**DESIGN_DEFAUT, **(p.get("design") or {})}
        p.setdefault("produits", []); p.setdefault("blocs", []); p.setdefault("reseaux", {}); p.setdefault("kit", {})
        try:
            p["_marque"] = bool(AVEC_MARQUE(uid))
        except Exception:  # noqa: BLE001
            p["_marque"] = True
    return p


def ecrit_page(uid: int, page: dict):
    page["maj"] = datetime.now().isoformat(timespec="seconds")
    _ecrit(dossier(uid) / "page.json", {k: v for k, v in page.items() if k != "_marque"})


def nouvel_id() -> str:
    return uuid.uuid4().hex[:8]


# ------------------------------------------------------------
#  Polices, thèmes, design
# ------------------------------------------------------------
# clé : (famille CSS, source, catégorie) ; source = fichiers locaux (OFL, static/fonts) ou spécification Google Fonts
POLICES = {
    "Poppins": ("Poppins", "local", "moderne"),
    "Montserrat": ("Montserrat", "local", "moderne"),
    "Space Grotesk": ("Space Grotesk", "local", "moderne"),
    "Quicksand": ("Quicksand", "local", "douce"),
    "Anton": ("Anton", "local", "affiche"),
    "Bebas Neue": ("Bebas Neue", "local", "affiche"),
    "Archivo Black": ("Archivo Black", "local", "affiche"),
    "DM Serif Display": ("DM Serif Display", "local", "classique"),
    "Playfair Display": ("Playfair Display", "local", "classique"),
    "Abril Fatface": ("Abril Fatface", "local", "classique"),
    "Caveat": ("Caveat", "local", "manuscrite"),
    "Pacifico": ("Pacifico", "local", "manuscrite"),
    "Libre Baskerville": ("Libre Baskerville", "Libre+Baskerville:wght@400;700", "classique"),
    "Fraunces": ("Fraunces", "Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800", "classique"),
    "Cormorant Garamond": ("Cormorant Garamond", "Cormorant+Garamond:wght@500;700", "classique"),
    "Instrument Serif": ("Instrument Serif", "Instrument+Serif", "classique"),
    "Gloock": ("Gloock", "Gloock", "classique"),
    "DM Sans": ("DM Sans", "DM+Sans:wght@400;500;700", "moderne"),
    "Inter": ("Inter", "Inter:wght@400;500;700", "moderne"),
    "Outfit": ("Outfit", "Outfit:wght@400;500;700", "moderne"),
    "Nunito": ("Nunito", "Nunito:wght@400;600;800", "douce"),
    "Lora": ("Lora", "Lora:wght@400;600", "classique"),
    "Syne": ("Syne", "Syne:wght@500;700;800", "futuriste"),
    "Unbounded": ("Unbounded", "Unbounded:wght@500;700", "futuriste"),
    "Righteous": ("Righteous", "Righteous", "futuriste"),
    "Space Mono": ("Space Mono", "Space+Mono:wght@400;700", "futuriste"),
    "Shrikhand": ("Shrikhand", "Shrikhand", "affiche"),
    "Bricolage Grotesque": ("Bricolage Grotesque", "Bricolage+Grotesque:opsz,wght@12..96,400;12..96,700;12..96,800", "moderne"),
}
POLICES_TEXTE = ["Poppins", "DM Sans", "Inter", "Outfit", "Nunito", "Lora", "Libre Baskerville", "Cormorant Garamond", "Space Mono", "Fraunces"]
LOCALES = {
    "Poppins": [("Poppins-Regular.ttf", 400), ("Poppins-Medium.ttf", 500), ("Poppins-Bold.ttf", 700)],
    "Montserrat": [("Montserrat-ExtraBold.ttf", 800)], "Space Grotesk": [("SpaceGrotesk-Bold.ttf", 700)],
    "Quicksand": [("Quicksand-Bold.ttf", 700)], "Anton": [("Anton-Regular.ttf", 400)], "Bebas Neue": [("BebasNeue-Regular.ttf", 400)],
    "Archivo Black": [("ArchivoBlack-Regular.ttf", 400)], "DM Serif Display": [("DMSerifDisplay-Regular.ttf", 400)],
    "Playfair Display": [("PlayfairDisplay-Bold.ttf", 700)], "Abril Fatface": [("AbrilFatface-Regular.ttf", 400)],
    "Caveat": [("Caveat-Bold.ttf", 700)], "Pacifico": [("Pacifico-Regular.ttf", 400)],
}

ENTETES = {"minimal": "Minimal", "banniere": "Bannière", "portrait": "Portrait", "arche": "Arche", "cote": "Côte à côte", "magazine": "Magazine"}
FORMES = {"rond": "Rond", "arrondi": "Arrondi", "arche": "Arche", "fleur": "Fleur", "goutte": "Galet", "etoile": "Étoile",
          "hexagone": "Hexagone", "losange": "Losange", "coeur": "Cœur", "polaroid": "Polaroïd", "anneau": "Anneaux"}
FONDS = {"uni": "Uni", "degrade": "Dégradé", "image": "Image", "motif": "Motif", "anime": "Animé"}
MOTIFS = {"points": "Points", "grille": "Grille", "vagues": "Vagues", "grain": "Grain", "damier": "Damier", "rayures": "Rayures",
          "vichy": "Vichy", "zigzag": "Zigzag", "etoiles": "Étoiles", "losanges": "Losanges"}
BOUTONS = {"plein": "Plein", "contour": "Contour", "decale": "Ombre décalée", "doux": "Ombre douce", "verre": "Verre", "degrade": "Dégradé",
           "neon": "Néon", "relief": "Relief 3D", "double": "Double trait", "pointille": "Pointillés", "cadre": "Cadre décalé", "pastel": "Pastel",
           "holo": "Holographique", "papier": "Papier", "surligneur": "Surligneur", "souligne": "Souligné"}
FORMES_BOUTON = {"arrondi": "Arrondi", "pilule": "Pilule", "carre": "Carré", "feuille": "Feuille", "galet": "Galet", "croquis": "Dessiné main",
                 "capsule": "Capsule", "coin": "Coins opposés", "bulle": "Bulle", "parallelo": "Penché", "biseau": "Biseauté",
                 "etiquette": "Étiquette", "fleche": "Flèche", "ticket": "Ticket", "festons": "Festons", "onde": "Rideau", "pixel": "Pixel"}
FORMES_DECOUPEES = {"biseau", "etiquette", "fleche", "ticket", "festons", "onde", "pixel"}
SURVOLS = {"soulever": "Soulever", "grossir": "Grossir", "incliner": "Basculer 3D", "enfoncer": "Enfoncer", "rebond": "Rebond", "tourner": "Pencher", "aucun": "Aucun"}
TAILLES_BOUTON = {"compact": "Compact", "normal": "Normal", "grand": "Généreux"}
ALIGNEMENTS = {"centre": "Centré", "gauche": "À gauche"}
DECORS = {"aucun": "Aucun", "etincelles": "Étincelles", "bulles": "Bulles floues", "confettis": "Confettis", "coeurs": "Cœurs", "formes": "Formes géométriques"}
FORMES_IMAGE = {"carre": "Arrondi", "arche": "Arche", "rond": "Rond", "galet": "Galet", "biseau": "Biseauté", "fenetre": "Fenêtre", "polaroid": "Polaroïd", "fleur": "Fleur"}
STYLES_PRIX = {"texte": "Texte", "pastille": "Pastille", "etiquette": "Étiquette", "bouton": "Bouton", "surligne": "Surligné"}
CADRES_CARTE = {"ombre": "Ombre", "contour": "Contour", "decale": "Décalé", "verre": "Verre", "flottant": "Flottant", "sans": "Sans cadre"}
ANIMATIONS = {"aucune": "Aucune", "pulse": "Pulsation", "secousse": "Secousse", "brillance": "Reflet"}
VUES_PRODUITS = {"grille": "Grille", "liste": "Liste", "vitrine": "Vitrine", "carrousel": "Carrousel", "bento": "Bento", "polaroid": "Polaroïds",
                 "zigzag": "Zigzag", "mini": "Compacte"}
TAILLES_TITRE = {"s": 26, "m": 32, "l": 40, "xl": 52}

DESIGN_DEFAUT = {
    "theme": "sable", "entete": "minimal", "photo_forme": "rond", "photo_taille": 112, "photo_contour": False,
    "fond_type": "uni", "fond1": "#F4EDE4", "fond2": "#E8D9C8", "fond_image": "", "fond_voile": 25, "motif": "points",
    "texte": "#2A211C", "bouton_fond": "#DDBEA4", "bouton_texte": "#2A211C", "bouton_ombre": "#C9A588",
    "bloc_fond": "#FFFFFF", "bloc_texte": "#2A211C", "accent": "#B4693E",
    "police_titre": "Libre Baskerville", "police_texte": "Poppins", "taille_titre": "l",
    "bouton_style": "plein", "rayon": 16, "animation": "pulse", "apparition": True, "produits_vue": "grille",
    "bouton_forme": "arrondi", "survol": "soulever", "bouton_taille": "normal", "alignement": "centre", "decor": "aucun",
    "image_forme": "carre", "prix_style": "texte", "carte_cadre": "ombre",
}

# Thèmes prêts à l'emploi, regroupés par ambiance (comme les « looks » de Beacons, en plus poussé)
def _t(nom, ambiance, **d):
    return {"nom": nom, "ambiance": ambiance, "design": d}


THEMES = {
    # Classique
    "sable": _t("Sable", "Classique", entete="minimal", fond_type="uni", fond1="#F4EDE4", texte="#2A211C", bouton_fond="#DDBEA4", bouton_texte="#2A211C",
                bouton_ombre="#C9A588", bloc_fond="#FFFFFF", bloc_texte="#2A211C", accent="#B4693E", police_titre="Libre Baskerville",
                police_texte="Poppins", bouton_style="plein", rayon=16, photo_forme="rond"),
    "encre": _t("Encre", "Classique", entete="portrait", fond_type="uni", fond1="#0E0E0E", texte="#F5F2EC", bouton_fond="#F5F2EC", bouton_texte="#0E0E0E",
                bouton_ombre="#000000", bloc_fond="#1B1B1B", bloc_texte="#F5F2EC", accent="#D9C3A5", police_titre="DM Serif Display",
                police_texte="DM Sans", bouton_style="contour", rayon=4, photo_forme="rond"),
    "papier": _t("Papier", "Classique", entete="arche", fond_type="motif", motif="grain", fond1="#F7F4EF", fond2="#EDE6DA", texte="#1F2A44",
                 bouton_fond="#1F2A44", bouton_texte="#F7F4EF", bouton_ombre="#1F2A44", bloc_fond="#FFFFFF", bloc_texte="#1F2A44", accent="#B5523B",
                 police_titre="Cormorant Garamond", police_texte="Lora", bouton_style="plein", rayon=999, photo_forme="arche"),
    "minuit": _t("Minuit", "Classique", entete="magazine", fond_type="degrade", fond1="#141B34", fond2="#2B3A67", texte="#F3F1EA", bouton_fond="#F3F1EA",
                 bouton_texte="#141B34", bouton_ombre="#0A0F1F", bloc_fond="#1E2748", bloc_texte="#F3F1EA", accent="#E8C27A",
                 police_titre="Playfair Display", police_texte="Inter", bouton_style="doux", rayon=12, photo_forme="arrondi"),
    # Vibrant
    "bonbon": _t("Bonbon", "Vibrant", entete="minimal", fond_type="degrade", fond1="#FFD6E8", fond2="#C9B8FF", texte="#3A1859", bouton_fond="#9D7BFF",
                 bouton_texte="#FFFFFF", bouton_ombre="#6B47D6", bloc_fond="#FFFFFFCC", bloc_texte="#3A1859", accent="#FF4F9A",
                 police_titre="Pacifico", police_texte="Nunito", bouton_style="decale", rayon=999, photo_forme="fleur", photo_contour=True),
    "neon": _t("Néon", "Vibrant", entete="minimal", fond_type="motif", motif="grille", fond1="#101418", fond2="#1D252C", texte="#E9FFF5",
               bouton_fond="#13161A", bouton_texte="#3DFFB0", bouton_ombre="#3DFFB0", bloc_fond="#161C21", bloc_texte="#E9FFF5", accent="#3DFFB0",
               police_titre="Righteous", police_texte="Space Mono", bouton_style="contour", rayon=10, photo_forme="rond", photo_contour=True),
    "pop": _t("Pop", "Vibrant", entete="cote", fond_type="motif", motif="points", fond1="#FFE14D", fond2="#FFD000", texte="#111111", bouton_fond="#FFFFFF",
              bouton_texte="#111111", bouton_ombre="#111111", bloc_fond="#FFFFFF", bloc_texte="#111111", accent="#FF3D7F",
              police_titre="Archivo Black", police_texte="DM Sans", bouton_style="decale", rayon=14, photo_forme="goutte", photo_contour=True),
    "couchant": _t("Couchant", "Vibrant", entete="banniere", fond_type="degrade", fond1="#FF9A62", fond2="#E8457C", texte="#FFFFFF", bouton_fond="#FFFFFF",
                   bouton_texte="#C2335F", bouton_ombre="#9E2149", bloc_fond="#FFFFFF26", bloc_texte="#FFFFFF", accent="#FFE07A",
                   police_titre="Montserrat", police_texte="Outfit", bouton_style="verre", rayon=18, photo_forme="rond", photo_contour=True),
    # Cosy
    "terracotta": _t("Terracotta", "Cosy", entete="arche", fond_type="uni", fond1="#EBD9C6", texte="#5A2E1C", bouton_fond="#C4683F", bouton_texte="#FFF6EE",
                     bouton_ombre="#8E4527", bloc_fond="#F6EBDF", bloc_texte="#5A2E1C", accent="#C4683F",
                     police_titre="Fraunces", police_texte="DM Sans", bouton_style="plein", rayon=999, photo_forme="arche"),
    "sauge": _t("Sauge", "Cosy", entete="minimal", fond_type="motif", motif="vagues", fond1="#DCE3D3", fond2="#C9D4BD", texte="#2F3B2A", bouton_fond="#F7F5EE",
                bouton_texte="#2F3B2A", bouton_ombre="#AEBB9F", bloc_fond="#F7F5EE", bloc_texte="#2F3B2A", accent="#6E8B5A",
                police_titre="Gloock", police_texte="Nunito", bouton_style="doux", rayon=22, photo_forme="goutte"),
    "lin": _t("Lin", "Cosy", entete="portrait", fond_type="uni", fond1="#EFE8DE", texte="#3E3530", bouton_fond="#E2D6C6", bouton_texte="#3E3530",
              bouton_ombre="#CBBBA6", bloc_fond="#F8F4EE", bloc_texte="#3E3530", accent="#9C7B5B",
              police_titre="Instrument Serif", police_texte="Inter", bouton_style="souligne", rayon=0, photo_forme="rond"),
    "cacao": _t("Cacao", "Cosy", entete="cote", fond_type="degrade", fond1="#3B2A22", fond2="#5B4034", texte="#F6E7D8", bouton_fond="#F6E7D8",
                bouton_texte="#3B2A22", bouton_ombre="#24180F", bloc_fond="#4A362C", bloc_texte="#F6E7D8", accent="#E2A76F",
                police_titre="Abril Fatface", police_texte="Lora", bouton_style="plein", rayon=12, photo_forme="arrondi"),
    # Audacieux
    "affiche": _t("Affiche", "Audacieux", entete="magazine", fond_type="uni", fond1="#E63B2E", texte="#FFF4E6", bouton_fond="#FFF4E6", bouton_texte="#E63B2E",
                  bouton_ombre="#8C1C14", bloc_fond="#C92F23", bloc_texte="#FFF4E6", accent="#FFD84D",
                  police_titre="Bebas Neue", police_texte="Space Grotesk", bouton_style="plein", rayon=0, photo_forme="arrondi"),
    "brutal": _t("Brutal", "Audacieux", entete="cote", fond_type="motif", motif="damier", fond1="#FAFAF7", fond2="#EFEFEA", texte="#0A0A0A",
                 bouton_fond="#B8FF5C", bouton_texte="#0A0A0A", bouton_ombre="#0A0A0A", bloc_fond="#FFFFFF", bloc_texte="#0A0A0A", accent="#5C5CFF",
                 police_titre="Space Grotesk", police_texte="Space Mono", bouton_style="decale", rayon=0, photo_forme="etoile"),
    "aurore": _t("Aurore", "Audacieux", entete="minimal", fond_type="anime", fond1="#7F5CFF", fond2="#00C2A8", texte="#FFFFFF", bouton_fond="#FFFFFF",
                 bouton_texte="#2B1D6B", bouton_ombre="#2B1D6B", bloc_fond="#FFFFFF2E", bloc_texte="#FFFFFF", accent="#FFE45C",
                 police_titre="Unbounded", police_texte="Outfit", bouton_style="verre", rayon=20, photo_forme="rond", photo_contour=True),
    "chrome": _t("Chrome", "Audacieux", entete="banniere", fond_type="anime", fond1="#111111", fond2="#5B5B66", texte="#FFFFFF", bouton_fond="#FFFFFF1F",
                 bouton_texte="#FFFFFF", bouton_ombre="#000000", bloc_fond="#FFFFFF14", bloc_texte="#FFFFFF", accent="#C6F432",
                 police_titre="Syne", police_texte="Inter", bouton_style="verre", rayon=28, photo_forme="rond"),
}
# Formes et finitions propres à chaque thème
_FINITIONS = {
    "sable": dict(bouton_forme="arrondi", survol="soulever", image_forme="carre", carte_cadre="ombre"),
    "encre": dict(bouton_forme="carre", survol="enfoncer", image_forme="fenetre", carte_cadre="contour", prix_style="surligne", produits_vue="vitrine"),
    "papier": dict(bouton_forme="pilule", survol="soulever", image_forme="arche", carte_cadre="sans"),
    "minuit": dict(bouton_forme="capsule", survol="incliner", image_forme="carre", carte_cadre="flottant", produits_vue="bento"),
    "bonbon": dict(bouton_forme="galet", survol="rebond", image_forme="galet", carte_cadre="decale", prix_style="pastille", decor="coeurs"),
    "neon": dict(bouton_style="neon", bouton_forme="biseau", survol="grossir", image_forme="biseau", carte_cadre="contour", decor="etincelles", prix_style="etiquette"),
    "pop": dict(bouton_forme="arrondi", survol="enfoncer", image_forme="rond", carte_cadre="decale", prix_style="pastille", decor="confettis"),
    "couchant": dict(bouton_forme="pilule", survol="soulever", image_forme="arche", carte_cadre="verre", decor="bulles", produits_vue="carrousel"),
    "terracotta": dict(bouton_forme="feuille", survol="soulever", image_forme="arche", carte_cadre="ombre", prix_style="bouton"),
    "sauge": dict(bouton_style="papier", bouton_forme="croquis", survol="tourner", image_forme="galet", carte_cadre="sans", produits_vue="zigzag"),
    "lin": dict(bouton_forme="carre", survol="aucun", alignement="gauche", image_forme="carre", carte_cadre="sans", produits_vue="liste"),
    "cacao": dict(bouton_forme="capsule", survol="soulever", image_forme="fenetre", carte_cadre="flottant"),
    "affiche": dict(bouton_forme="carre", survol="tourner", bouton_taille="grand", image_forme="carre", carte_cadre="contour", prix_style="etiquette", produits_vue="vitrine"),
    "brutal": dict(bouton_forme="carre", survol="enfoncer", image_forme="carre", carte_cadre="decale", prix_style="surligne", decor="formes", produits_vue="bento"),
    "aurore": dict(bouton_forme="pilule", survol="grossir", image_forme="rond", carte_cadre="verre", decor="bulles"),
    "chrome": dict(bouton_forme="pilule", survol="incliner", image_forme="carre", carte_cadre="verre", decor="etincelles", produits_vue="carrousel"),
}
for _cle, _fin in _FINITIONS.items():
    THEMES[_cle]["design"].update(_fin)
THEMES.update({
    "ticket": _t("Ticket rétro", "Créatif", entete="minimal", fond_type="motif", motif="rayures", fond1="#F6ECD9", fond2="#EFDFC2", texte="#2E2A24",
                 bouton_fond="#D9483B", bouton_texte="#FFF6E5", bouton_ombre="#8F2A21", bloc_fond="#FFF9EE", bloc_texte="#2E2A24", accent="#D9483B",
                 police_titre="Abril Fatface", police_texte="DM Sans", bouton_style="plein", bouton_forme="ticket", rayon=10, photo_forme="polaroid",
                 survol="tourner", image_forme="polaroid", prix_style="etiquette", carte_cadre="contour", produits_vue="polaroid"),
    "y2k": _t("Y2K", "Créatif", entete="minimal", fond_type="anime", fond1="#FFB8E6", fond2="#B8E1FF", texte="#3B1A5A", bouton_fond="#FFFFFF",
              bouton_texte="#3B1A5A", bouton_ombre="#9B6BFF", bloc_fond="#FFFFFFB3", bloc_texte="#3B1A5A", accent="#9B6BFF",
              police_titre="Righteous", police_texte="Nunito", bouton_style="holo", bouton_forme="bulle", rayon=20, photo_forme="coeur",
              survol="rebond", image_forme="fleur", prix_style="pastille", carte_cadre="verre", decor="etincelles", produits_vue="grille"),
    "arcade": _t("Arcade", "Créatif", entete="cote", fond_type="motif", motif="grille", fond1="#1A1033", fond2="#2A1B4D", texte="#F8F1FF",
                 bouton_fond="#FF4FA3", bouton_texte="#1A1033", bouton_ombre="#00E5FF", bloc_fond="#24164A", bloc_texte="#F8F1FF", accent="#00E5FF",
                 police_titre="Space Grotesk", police_texte="Space Mono", bouton_style="decale", bouton_forme="pixel", rayon=0, photo_forme="hexagone",
                 survol="enfoncer", image_forme="biseau", prix_style="bouton", carte_cadre="decale", decor="formes", produits_vue="mini"),
    "boheme": _t("Bohème", "Créatif", entete="arche", fond_type="motif", motif="grain", fond1="#EFE3D3", fond2="#E4D3BD", texte="#4A3426",
                 bouton_fond="#F8F0E4", bouton_texte="#4A3426", bouton_ombre="#B08868", bloc_fond="#F8F0E4", bloc_texte="#4A3426", accent="#B5643C",
                 police_titre="Caveat", police_texte="Lora", bouton_style="papier", bouton_forme="croquis", rayon=18, photo_forme="arche",
                 survol="tourner", image_forme="arche", prix_style="surligne", carte_cadre="sans", produits_vue="zigzag"),
    "luxe": _t("Luxe", "Classique", entete="minimal", fond_type="uni", fond1="#0F0F0F", texte="#EADBC0", bouton_fond="#0F0F0F",
               bouton_texte="#EADBC0", bouton_ombre="#000000", bloc_fond="#171615", bloc_texte="#EADBC0", accent="#C9A86A",
               police_titre="Cormorant Garamond", police_texte="Inter", bouton_style="double", bouton_forme="carre", rayon=0, photo_forme="anneau",
               survol="aucun", image_forme="fenetre", prix_style="texte", carte_cadre="contour", produits_vue="vitrine"),
})
AMBIANCES = ["Classique", "Vibrant", "Cosy", "Audacieux", "Créatif"]

COULEUR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


def design_propre(d: dict) -> dict:
    """Ne garde que des valeurs sûres (elles finissent dans le CSS de la page publique)."""
    r = dict(DESIGN_DEFAUT)
    for k, v in (d or {}).items():
        if k not in DESIGN_DEFAUT:
            continue
        defaut = DESIGN_DEFAUT[k]
        if isinstance(defaut, bool):
            r[k] = bool(v)
        elif isinstance(defaut, int):
            try:
                r[k] = max(0, min(999, int(v)))
            except (TypeError, ValueError):
                pass
        elif k in ("fond1", "fond2", "texte", "bouton_fond", "bouton_texte", "bouton_ombre", "bloc_fond", "bloc_texte", "accent"):
            if isinstance(v, str) and COULEUR.match(v):
                r[k] = v
        else:
            choix = {"entete": ENTETES, "photo_forme": FORMES, "fond_type": FONDS, "motif": MOTIFS, "bouton_style": BOUTONS,
                     "animation": ANIMATIONS, "produits_vue": VUES_PRODUITS, "bouton_forme": FORMES_BOUTON, "survol": SURVOLS,
                     "bouton_taille": TAILLES_BOUTON, "alignement": ALIGNEMENTS, "decor": DECORS, "image_forme": FORMES_IMAGE,
                     "prix_style": STYLES_PRIX, "carte_cadre": CADRES_CARTE, "taille_titre": TAILLES_TITRE, "theme": {**THEMES, "perso": 1},
                     "police_titre": POLICES, "police_texte": POLICES}.get(k)
            if choix is not None and v in choix:
                r[k] = v
            elif k == "fond_image" and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{12}\.(jpg|png|webp)", v or "x"):
                r[k] = v
            elif k == "fond_image" and v == "":
                r[k] = ""
    r["photo_taille"] = max(64, min(200, r["photo_taille"]))
    r["rayon"] = max(0, min(999, r["rayon"]))
    r["fond_voile"] = max(0, min(80, r["fond_voile"]))
    return r


def applique_theme(design: dict, theme: str) -> dict:
    base = {k: v for k, v in DESIGN_DEFAUT.items() if k not in ("photo_taille", "fond_image", "fond_voile", "animation", "apparition", "produits_vue")}
    t = THEMES.get(theme)
    if not t:
        return design
    return design_propre({**design, **base, "fond2": t["design"].get("fond2", t["design"].get("fond1")), "photo_contour": False,
                          **t["design"], "theme": theme})


# ------------------------------------------------------------
#  Couleurs tirées de la photo (aucun appel d'API)
# ------------------------------------------------------------
def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(x)))) for x in rgb)


def _hls(rgb):
    return colorsys.rgb_to_hls(*(x / 255 for x in rgb))


def _de_hls(h, l, s):
    return _hex(tuple(x * 255 for x in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))))


def palettes_photo(f: Path) -> list[dict]:
    """Trois palettes harmonieuses (claire, profonde, vive) construites à partir des couleurs dominantes de la photo."""
    from PIL import Image
    im = Image.open(f).convert("RGB").resize((80, 80))
    q = im.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    compte = sorted(q.getcolors(), reverse=True)
    couleurs = [tuple(pal[i * 3:i * 3 + 3]) for _, i in compte]
    # couleur « signature » : la plus saturée parmi les dominantes pas trop sombres ni trop claires
    vives = sorted(couleurs, key=lambda c: (_hls(c)[2] * (1 - abs(_hls(c)[1] - .5) * 1.6)), reverse=True)
    h, l, s = _hls(vives[0])
    s = max(s, .35)
    h2 = _hls(couleurs[0])[0]
    claire = {"nom": "Douce", "fond_type": "degrade", "fond1": _de_hls(h2, .95, .35), "fond2": _de_hls(h, .88, .4), "texte": _de_hls(h, .16, .35),
              "bouton_fond": _de_hls(h, .74, s * .8), "bouton_texte": _de_hls(h, .14, .4), "bouton_ombre": _de_hls(h, .55, s),
              "bloc_fond": "#FFFFFF", "bloc_texte": _de_hls(h, .16, .35), "accent": _de_hls(h, .45, s)}
    profonde = {"nom": "Profonde", "fond_type": "uni", "fond1": _de_hls(h, .13, s * .6), "fond2": _de_hls(h, .2, s * .6), "texte": _de_hls(h, .94, .3),
                "bouton_fond": _de_hls(h, .82, s * .7), "bouton_texte": _de_hls(h, .13, s * .6), "bouton_ombre": "#000000",
                "bloc_fond": _de_hls(h, .19, s * .55), "bloc_texte": _de_hls(h, .94, .3), "accent": _de_hls(h, .68, min(1, s + .2))}
    vive = {"nom": "Vive", "fond_type": "degrade", "fond1": _de_hls(h, .52, min(1, s + .25)), "fond2": _de_hls((h + .08) % 1, .45, min(1, s + .2)),
            "texte": "#FFFFFF", "bouton_fond": "#FFFFFF", "bouton_texte": _de_hls(h, .3, min(1, s + .2)), "bouton_ombre": _de_hls(h, .25, s),
            "bloc_fond": "#FFFFFF29", "bloc_texte": "#FFFFFF", "accent": _de_hls((h + .5) % 1, .75, .9)}
    return [claire, profonde, vive]


# ------------------------------------------------------------
#  Page par défaut (préremplie avec le profil analysé)
# ------------------------------------------------------------
def page_initiale(uid: int, profil: dict | None, prenom: str = "") -> dict:
    bio = ((profil or {}).get("bio") or {})
    ig, tt = (profil or {}).get("instagram") or "", (profil or {}).get("tiktok") or ""
    prop = (profil or {}).get("proposition") or {}
    nom = (bio.get("instagram") or {}).get("nom") or (bio.get("tiktok") or {}).get("nom") or prop.get("nom_marque") or prenom or "Ma boutique"
    texte_bio = ((bio.get("instagram") or {}).get("bio") or (bio.get("tiktok") or {}).get("bio") or "").strip()
    nom = re.sub(r"^\[démo\]\s*", "", nom)
    texte_bio = re.sub(r"^\[démo\]\s*", "", texte_bio)
    return {
        "version": 1, "publie": False, "nom": nom[:60], "bio": texte_bio[:280], "photo": "", "couverture": "",
        "reseaux": {k: v for k, v in (("instagram", ig), ("tiktok", tt)) if v},
        "blocs": [], "produits": [], "design": dict(DESIGN_DEFAUT),
        "kit": {"actif": True, "a_propos": "", "tarifs": [], "marques": "", "contact": "", "chiffres_perso": []},
        "seo": {"titre": "", "description": ""}, "cree": datetime.now().isoformat(timespec="seconds"),
    }


# ------------------------------------------------------------
#  Réseaux sociaux : liens et icônes
# ------------------------------------------------------------
RESEAUX = {
    "instagram": ("Instagram", "https://instagram.com/{}"), "tiktok": ("TikTok", "https://www.tiktok.com/@{}"),
    "youtube": ("YouTube", "https://youtube.com/@{}"), "x": ("X", "https://x.com/{}"), "threads": ("Threads", "https://www.threads.net/@{}"),
    "facebook": ("Facebook", "https://facebook.com/{}"), "linkedin": ("LinkedIn", "https://www.linkedin.com/in/{}"),
    "pinterest": ("Pinterest", "https://pinterest.com/{}"), "snapchat": ("Snapchat", "https://snapchat.com/add/{}"),
    "whatsapp": ("WhatsApp", "https://wa.me/{}"), "email": ("E-mail", "mailto:{}"), "site": ("Site", "{}"),
}
ICONES = {
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.2"/>',
    "tiktok": '<path d="M16.5 3c.3 2.2 1.7 3.8 4 4v3.1c-1.5 0-2.9-.4-4-1.2V15a6 6 0 11-6-6c.3 0 .7 0 1 .1v3.2a2.9 2.9 0 10 2 2.7V3h3z"/>',
    "youtube": '<path d="M22 8.2a3 3 0 00-2.1-2.1C18 5.6 12 5.6 12 5.6s-6 0-7.9.5A3 3 0 002 8.2 31 31 0 001.6 12 31 31 0 002 15.8a3 3 0 002.1 2.1c1.9.5 7.9.5 7.9.5s6 0 7.9-.5a3 3 0 002.1-2.1 31 31 0 00.4-3.8 31 31 0 00-.4-3.8zM10 15V9l5.2 3z"/>',
    "x": '<path d="M17.8 3h3.1l-6.8 7.8 8 10.2h-6.3l-4.9-6.4L5.3 21H2.2l7.3-8.3L1.9 3h6.4l4.4 5.9zm-1.1 16.2h1.7L7.4 4.7H5.6z"/>',
    "threads": '<path d="M12.2 22c-5.6 0-9-3.6-9-10s3.4-10 9-10c4.4 0 7.4 2.2 8.5 6.2l-2.3.6C17.6 5.8 15.4 4.3 12.2 4.3 8 4.3 5.6 7.1 5.6 12s2.4 7.7 6.6 7.7c3.2 0 5.5-1.6 5.5-4.2 0-1.6-.9-2.7-2.4-3.2-.3 2.6-1.8 4.3-4.4 4.3-2.3 0-4-1.4-4-3.4 0-2.2 1.9-3.6 4.7-3.6.7 0 1.3 0 1.9.1-.3-1.3-1.1-1.9-2.4-1.9-1 0-1.8.4-2.3 1.1l-1.8-1.3C7.9 6.3 9.3 5.6 11 5.6c2.6 0 4.2 1.6 4.6 4.3 2.6.7 4.3 2.6 4.3 5.4 0 4-3.2 6.7-7.7 6.7zm-.6-9c-1.7 0-2.5.6-2.5 1.4 0 .8.8 1.3 1.8 1.3 1.4 0 2.3-.9 2.4-2.6-.5-.1-1.1-.1-1.7-.1z"/>',
    "facebook": '<path d="M14 8V6.3c0-.8.2-1.3 1.4-1.3H17V2h-2.6C11.3 2 10.2 3.6 10.2 6.1V8H8v3h2.2v11H14V11h2.7l.4-3z"/>',
    "linkedin": '<path d="M4.98 3.5a2.5 2.5 0 11-.01 5 2.5 2.5 0 01.01-5zM3 9.5h4V21H3zM9.5 9.5h3.8v1.6h.1c.5-1 1.8-2 3.7-2 4 0 4.7 2.6 4.7 6V21h-4v-5.2c0-1.2 0-2.8-1.7-2.8s-2 1.3-2 2.7V21h-4z"/>',
    "pinterest": '<path d="M12 2a10 10 0 00-3.6 19.3c-.1-.8-.2-2 0-2.9l1.2-5s-.3-.6-.3-1.5c0-1.4.8-2.4 1.8-2.4.9 0 1.3.6 1.3 1.4 0 .9-.6 2.2-.8 3.4-.2 1 .5 1.9 1.6 1.9 1.9 0 3.3-2 3.3-4.9 0-2.6-1.8-4.4-4.5-4.4-3 0-4.8 2.3-4.8 4.6 0 .9.4 1.9.8 2.4l.1.4-.3 1.2c0 .2-.2.3-.4.2-1.4-.7-2.2-2.7-2.2-4.3 0-3.5 2.5-6.7 7.3-6.7 3.8 0 6.8 2.7 6.8 6.4 0 3.8-2.4 6.9-5.8 6.9-1.1 0-2.2-.6-2.5-1.3l-.7 2.6c-.2 1-.9 2.2-1.4 2.9A10 10 0 1012 2z"/>',
    "snapchat": '<path d="M12 2.5c2.8 0 5 2.1 5 5.2v2.1c.5.2 1.2-.2 1.6-.1.6.1.8.8.2 1.2-.6.4-1.9.6-1.9 1.3 0 1.2 2 3.6 4.1 4 .4.1.5.6.1.8-.9.5-2 .5-2.3.9-.2.4-.1 1.1-.6 1.2-.8.2-1.7-.3-2.9.3-1.1.6-1.8 1.8-3.3 1.8s-2.2-1.2-3.3-1.8c-1.2-.6-2.1-.1-2.9-.3-.5-.1-.4-.8-.6-1.2-.3-.4-1.4-.4-2.3-.9-.4-.2-.3-.7.1-.8 2.1-.4 4.1-2.8 4.1-4 0-.7-1.3-.9-1.9-1.3-.6-.4-.4-1.1.2-1.2.4-.1 1.1.3 1.6.1V7.7c0-3.1 2.2-5.2 5-5.2z"/>',
    "whatsapp": '<path d="M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 18.2c-1.5 0-3-.4-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1112 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 01-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.5l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 00-.7.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.8 11.8 0 004.5 4c1.7.7 2.3.8 3.2.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.3-.2-.5-.3z"/>',
    "email": '<path d="M3 5h18a1 1 0 011 1v12a1 1 0 01-1 1H3a1 1 0 01-1-1V6a1 1 0 011-1zm9 7.2L4 7v.1l8 5.2 8-5.2V7z" />',
    "site": '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm6.9 6h-3a15.6 15.6 0 00-1.4-3.8A8 8 0 0118.9 8zM12 4c.8 1.2 1.5 2.5 1.9 4h-3.8c.4-1.5 1.1-2.8 1.9-4zM4.3 14a8 8 0 010-4h3.4a16.5 16.5 0 000 4zm.8 2h3a15.6 15.6 0 001.4 3.8A8 8 0 015.1 16zm3-8h-3a8 8 0 014.4-3.8C8.9 5.4 8.4 6.7 8.1 8zM12 20c-.8-1.2-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.8-1.9 4zm2.3-6H9.7a14.7 14.7 0 010-4h4.6a14.7 14.7 0 010 4zm.3 5.8c.6-1.2 1.1-2.5 1.4-3.8h3a8 8 0 01-4.4 3.8zm1.7-5.8a16.5 16.5 0 000-4h3.4a8 8 0 010 4z"/>',
}


def lien_reseau(cle: str, valeur: str) -> str | None:
    v = (valeur or "").strip()
    if not v or cle not in RESEAUX:
        return None
    if cle == "email":
        return "mailto:" + v if "@" in v and " " not in v else None
    if cle == "whatsapp":
        n = re.sub(r"[^0-9]", "", v)
        return "https://wa.me/" + n if n else None
    if re.match(r"^https?://", v):
        return url_sure(v)
    if cle == "site":
        return url_sure("https://" + v)
    return RESEAUX[cle][1].format(quote(v.lstrip("@"), safe="._-"))


def url_sure(u: str) -> str | None:
    u = (u or "").strip()
    if not u:
        return None
    if re.match(r"^(mailto:|tel:)", u):
        return u
    if not re.match(r"^https?://", u):
        u = "https://" + u
    try:
        p = urlparse(u)
    except ValueError:
        return None
    return u if p.scheme in ("http", "https") and p.netloc and "." in p.netloc else None


def prix_txt(centimes: int, devise: str = "eur") -> str:
    if not centimes:
        return "Gratuit"
    v = centimes / 100
    s = (f"{v:,.2f}".replace(",", " ").replace(".", ",")).replace(",00", "")
    return s + ({"eur": " €", "usd": " $", "chf": " CHF", "cad": " $ CA", "gbp": " £"}.get(devise, " " + devise.upper()))


# ------------------------------------------------------------
#  Rendu HTML de la page publique
# ------------------------------------------------------------
def _polices_css(d: dict) -> tuple[str, str]:
    faces, google = [], []
    for nom in dict.fromkeys([d["police_titre"], d["police_texte"]]):
        fam, src, _ = POLICES[nom]
        if src == "local":
            for fichier, poids in LOCALES[nom]:
                faces.append(f"@font-face{{font-family:'{fam}';src:url('/static/fonts/{fichier}') format('truetype');font-weight:{poids};font-display:swap}}")
        else:
            google.append(src)
    lien = (f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" '
            f'href="https://fonts.googleapis.com/css2?{"&".join("family=" + g for g in google)}&display=swap">') if google else ""
    return "\n".join(faces), lien


def _clair(hexa: str) -> bool:
    r, g_, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    return (r * 299 + g_ * 587 + b * 114) / 1000 > 150


FORMES_CSS = {
    "rond": "border-radius:50%",
    "arrondi": "border-radius:28%",
    "arche": "border-radius:999px 999px 18px 18px;aspect-ratio:3/4!important;height:auto!important",
    "fleur": "-webkit-mask:var(--fleur) center/100% 100% no-repeat;mask:var(--fleur) center/100% 100% no-repeat;border-radius:0",
    "goutte": "border-radius:62% 38% 55% 45% / 48% 60% 40% 52%",
    "hexagone": "", "losange": "", "coeur": "", "polaroid": "", "anneau": "",
    "etoile": "clip-path:polygon(50% 0,61% 13%,78% 7%,80% 24%,96% 30%,88% 45%,100% 58%,84% 66%,86% 84%,69% 84%,60% 100%,50% 88%,40% 100%,31% 84%,14% 84%,16% 66%,0 58%,12% 45%,4% 30%,20% 24%,22% 7%,39% 13%);border-radius:0",
}


def _css(d: dict) -> str:
    rayon = d["rayon"]
    r = f"{rayon}px" if rayon < 999 else "999px"
    clair = _clair(d["fond1"])
    fond = {
        "uni": f"background:{d['fond1']}",
        "degrade": f"background:linear-gradient(160deg,{d['fond1']},{d['fond2']})",
        "image": f"background:{d['fond1']}",
        "anime": f"background:linear-gradient(120deg,{d['fond1']},{d['fond2']},{d['accent']},{d['fond1']});background-size:300% 300%;animation:aurore 18s ease infinite",
        "motif": f"background-color:{d['fond1']}",
    }[d["fond_type"]]
    c2 = d["fond2"]
    motif = {
        "points": f"background-image:radial-gradient({c2} 1.6px,transparent 1.8px);background-size:18px 18px",
        "grille": f"background-image:linear-gradient({c2} 1px,transparent 1px),linear-gradient(90deg,{c2} 1px,transparent 1px);background-size:26px 26px",
        "vagues": f"background-image:radial-gradient(circle at 100% 50%,transparent 20%,{c2} 21%,{c2} 34%,transparent 35%,transparent),radial-gradient(circle at 0 50%,transparent 20%,{c2} 21%,{c2} 34%,transparent 35%,transparent);background-size:36px 52px",
        "grain": "background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 .09 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        "damier": f"background-image:conic-gradient({c2} 25%,transparent 0 50%,{c2} 0 75%,transparent 0);background-size:40px 40px",
        "rayures": f"background-image:repeating-linear-gradient(45deg,{c2} 0 10px,transparent 10px 22px)",
        "vichy": f"background-image:linear-gradient(90deg,color-mix(in srgb,{c2} 55%,transparent) 50%,transparent 0),linear-gradient(color-mix(in srgb,{c2} 55%,transparent) 50%,transparent 0);background-size:30px 30px",
        "zigzag": f"background:linear-gradient(135deg,{c2} 25%,transparent 25%) -15px 0/30px 30px,linear-gradient(225deg,{c2} 25%,transparent 25%) -15px 0/30px 30px,linear-gradient(315deg,{c2} 25%,transparent 25%) 0 0/30px 30px,linear-gradient(45deg,{c2} 25%,transparent 25%) 0 0/30px 30px",
        "etoiles": "background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60'%3E%3Cpath fill='" + c2.replace("#", "%23")[:7] + "' d='M15 4l2.4 7.2H25l-6.1 4.5 2.3 7.3L15 18.5 8.8 23l2.3-7.3L5 11.2h7.6zM45 34l1.6 4.8h5l-4 3 1.5 4.8-4.1-3-4.1 3 1.5-4.8-4-3h5z'/%3E%3C/svg%3E\")",
        "losanges": f"background-image:linear-gradient(45deg,{c2} 25%,transparent 25% 75%,{c2} 75%),linear-gradient(-45deg,{c2} 25%,transparent 25% 75%,{c2} 75%);background-size:34px 34px;opacity:.55",
    }[d["motif"]] if d["fond_type"] == "motif" else ""
    bt = d["bouton_style"]
    taille = TAILLES_TITRE[d["taille_titre"]]
    tf = POLICES[d["police_titre"]][0]
    tx = POLICES[d["police_texte"]][0]
    capitales = d["police_titre"] in ("Bebas Neue", "Anton")
    sur_accent = "#1A1A1A" if _clair(d["accent"][:7]) else "#FFFFFF"
    cadre = {
        "ombre": "box-shadow:0 1px 2px rgba(0,0,0,.05),0 10px 30px -18px rgba(0,0,0,.35)",
        "contour": "border:1.5px solid color-mix(in srgb,var(--kt) 24%,transparent)",
        "decale": "border:2px solid var(--bo);box-shadow:4px 4px 0 var(--bo)",
        "verre": "background:color-mix(in srgb,var(--k) 60%,transparent);border:1px solid rgba(255,255,255,.35);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)",
        "flottant": "box-shadow:0 28px 40px -24px rgba(0,0,0,.55),0 2px 6px rgba(0,0,0,.06)",
        "sans": "background:transparent;padding-left:0!important;padding-right:0!important",
    }[d["carte_cadre"]]
    return CSS_COMMUN + f"""
:root{{--ac:{sur_accent};--f1:{d['fond1']};--f2:{d['fond2']};--t:{d['texte']};--b:{d['bouton_fond']};--bt:{d['bouton_texte']};--bo:{d['bouton_ombre']};
--k:{d['bloc_fond']};--kt:{d['bloc_texte']};--a:{d['accent']};--r:{r};--rk:{min(rayon, 26)}px;--ph:{d['photo_taille']}px;
--fleur:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='-6 -6 112 112'%3E%3Cpath d='M50 0C62 0 66 14 75 18s25-2 29 10-8 20-8 22 12 10 8 22-20 6-29 18-13 18-25 18-16-14-25-18-25 2-29-10 8-20 8-22-12-10-8-22 20-6 29-18S38 0 50 0z'/%3E%3C/svg%3E");--tf:'{tf}',Georgia,serif;--tx:'{tx}',system-ui,-apple-system,'Segoe UI',sans-serif;--tt:{taille}px}}
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
body{{margin:0;min-height:100vh;color:var(--t);font:15.5px/1.5 var(--tx);{fond};-webkit-font-smoothing:antialiased}}
.fond{{position:fixed;inset:0;z-index:-1;pointer-events:none;{motif}}}
.fond-img{{position:fixed;inset:0;z-index:-2;background-size:cover;background-position:center}}
.fond-img::after{{content:"";position:absolute;inset:0;background:{'#000' if not clair else '#fff'};opacity:{d['fond_voile'] / 100}}}
@keyframes aurore{{0%,100%{{background-position:0% 50%}}50%{{background-position:100% 50%}}}}
a{{color:inherit}}
.page{{max-width:560px;margin:0 auto;padding:28px 18px 40px;position:relative}}
.tete{{text-align:center;margin-bottom:22px}}
.photo{{width:var(--ph);height:var(--ph);object-fit:cover;display:block;margin:0 auto 14px;{FORMES_CSS[d['photo_forme']]};
  {'outline:3px solid var(--a);outline-offset:4px;' if d['photo_contour'] and d['photo_forme'] in ('rond', 'arrondi', 'goutte', 'arche') else ''}{'filter:drop-shadow(0 0 0 var(--a)) drop-shadow(3px 3px 0 var(--a));' if d['photo_contour'] and d['photo_forme'] in ('fleur', 'etoile') else ''}}}
.photo.vide{{background:var(--a);display:grid;place-items:center;color:var(--f1);font:700 calc(var(--ph)*.38)/1 var(--tf)}}
h1{{font:400 var(--tt)/1.08 var(--tf);margin:0 0 8px;letter-spacing:-.01em;{'text-transform:uppercase;letter-spacing:.02em;' if capitales else ''}{'font-weight:700;' if POLICES[d['police_titre']][2] in ('moderne', 'futuriste') else ''}overflow-wrap:anywhere}}
.bio{{margin:0 auto 14px;max-width:42ch;opacity:.85;white-space:pre-line;font-size:15px}}
.reseaux{{display:flex;justify-content:center;flex-wrap:wrap;gap:6px}}
.reseaux a{{width:40px;height:40px;display:grid;place-items:center;border-radius:50%;color:var(--t);transition:transform .15s}}
.reseaux a:hover{{transform:scale(1.12)}}
.reseaux svg{{width:21px;height:21px;fill:currentColor}}
/* En-têtes */
.e-banniere .couv,.e-portrait .couv,.e-magazine .couv{{display:block;width:calc(100% + 36px);margin:-28px -18px 0;object-fit:cover}}
.e-banniere .couv{{height:170px;border-radius:0 0 var(--rk) var(--rk)}}
.e-banniere .photo{{margin-top:calc(var(--ph) / -2);border:4px solid var(--f1)}}
.e-banniere .photo.forme-fleur,.e-banniere .photo.forme-etoile{{border:0}}
.e-portrait .couv{{height:min(62vh,440px);-webkit-mask-image:linear-gradient(#000 62%,transparent);mask-image:linear-gradient(#000 62%,transparent)}}
.e-portrait .photo{{display:none}}.e-portrait h1{{margin-top:-46px;position:relative}}
.e-arche .photo{{width:min(78%,300px);height:auto;aspect-ratio:4/5;border-radius:999px 999px 0 0;clip-path:none}}
.e-cote .tete{{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center;text-align:left}}
.e-cote .photo{{margin:0;width:min(var(--ph),104px);height:min(var(--ph),104px)}}.e-cote .reseaux{{justify-content:flex-start;margin-left:-8px}}.e-cote .bio{{margin:0 0 8px}}
.e-cote .tete .bio-l{{grid-column:1/-1}}
.e-magazine .couv{{height:min(70vh,500px)}}
.e-magazine .tete{{position:relative}}.e-magazine .titre-mag{{position:absolute;left:0;right:0;bottom:16px;padding:0 4px;color:#fff;text-shadow:0 2px 18px rgba(0,0,0,.45)}}
.e-magazine .titre-mag h1{{font-size:calc(var(--tt) * 1.35);margin:0}}
.e-magazine .photo{{display:none}}
/* Blocs */
.blocs{{display:flex;flex-direction:column;gap:12px}}
.lien{{display:flex;align-items:center;gap:12px;min-height:58px;padding:10px 18px;text-decoration:none;font-weight:600;text-align:center;justify-content:center}}
.tb-compact .lien{{min-height:48px;font-size:14.5px;padding:8px 16px}}.tb-grand .lien{{min-height:72px;font-size:17px}}
.al-gauche .lien{{justify-content:flex-start;text-align:left}}.al-gauche .lien span{{padding:0 6px}}.al-gauche .lien:has(.vig) span,.al-gauche .lien:has(.emo) span{{padding-left:44px}}
.lien .reflet{{display:none}}
.anim-brillance .lien.avant .reflet{{display:block;position:absolute;inset:0;border-radius:var(--r);overflow:hidden;pointer-events:none}}
.anim-brillance .lien.avant .reflet::after{{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 35%,rgba(255,255,255,.55) 50%,transparent 65%);transform:translateX(-120%);animation:reflet 3.2s ease-in-out infinite}}
.lien .vig{{position:absolute;left:7px;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:calc(var(--rk) * .7);object-fit:cover}}
.lien .emo{{position:absolute;left:18px;font-size:22px}}
.lien span{{padding:0 40px}}
.lien.avant{{min-height:66px;font-size:16.5px}}
.anim-pulse .lien.avant{{animation:pulse 2.2s ease-in-out infinite}}
.anim-secousse .lien.avant{{animation:secousse 3.5s ease-in-out infinite}}
@keyframes pulse{{50%{{transform:scale(1.03)}}}}
@keyframes secousse{{0%,86%,100%{{transform:rotate(0)}}88%{{transform:rotate(-2deg)}}92%{{transform:rotate(2deg)}}96%{{transform:rotate(-1deg)}}}}
@keyframes reflet{{60%,100%{{transform:translateX(120%)}}}}
.carte{{background:var(--k);color:var(--kt);border-radius:var(--rk);padding:16px;{cadre}}}
.sec{{font:400 calc(var(--tt) * .62)/1.15 var(--tf);margin:14px 0 0;text-align:center;{'text-transform:uppercase;' if capitales else ''}}}
.txt{{text-align:center;white-space:pre-line;opacity:.9;margin:0}}
.video{{aspect-ratio:16/9;width:100%;border:0;border-radius:var(--rk);display:block}}
/* Produits */
.produits{{display:grid;gap:12px}}
.prod{{display:flex;gap:12px;align-items:center;text-decoration:none;padding:10px;transition:transform .2s}}
.prod:hover{{transform:translateY(-3px)}}
.pimg{{position:relative;flex-shrink:0;display:block}}
.pimg img,.pimg .pas-img{{display:block;width:86px;height:86px;object-fit:cover;background:var(--a);border-radius:calc(var(--rk) * .7)}}
.prod b{{display:block;font-size:15.5px;line-height:1.3}}.prod small{{display:block;opacity:.75;font-size:13px;margin-top:2px}}
.ptxt{{min-width:0}}.pnote{{margin-top:2px}}
.px{{display:inline-block;margin-top:6px;font-weight:700;color:var(--a);font-size:14.5px}}
.px s{{opacity:.55;font-weight:500;margin-left:6px;color:inherit}}
.pp-etiquette{{background:var(--a);color:var(--ac);padding:3px 12px 3px 18px;clip-path:polygon(11px 0,100% 0,100% 100%,11px 100%,0 50%);font-size:13.5px}}
.pp-bouton{{background:var(--b);color:var(--bt);padding:4px 12px;border-radius:999px;font-size:13.5px}}
.pp-surligne{{color:inherit;background:linear-gradient(transparent 55%,color-mix(in srgb,var(--a) 55%,transparent) 55% 92%,transparent 92%);padding:0 2px}}
.pp-pastille{{position:absolute;top:-9px;right:-9px;margin:0;width:62px;height:62px;border-radius:50%;background:var(--a);color:var(--ac);display:grid;place-content:center;text-align:center;
  font-size:13px;line-height:1.05;transform:rotate(12deg);box-shadow:0 5px 12px -5px rgba(0,0,0,.45);z-index:2;padding:4px}}
.pp-pastille s{{display:block;font-size:10.5px;margin:0}}
.v-liste .pp-pastille{{width:44px;height:44px;font-size:10.5px;top:-7px;right:-7px}}.v-liste .pp-pastille s{{display:none}}
.v-grille,.v-bento,.v-polaroid{{grid-template-columns:1fr 1fr}}
.v-grille .prod,.v-vitrine .prod,.v-carrousel .prod,.v-bento .prod,.v-polaroid .prod{{flex-direction:column;align-items:stretch;padding:8px 8px 12px}}
.v-grille .ptxt,.v-vitrine .ptxt,.v-carrousel .ptxt,.v-bento .ptxt,.v-polaroid .ptxt{{padding:0 4px}}
.v-grille .pimg img,.v-grille .pas-img,.v-bento .pimg img,.v-bento .pas-img,.v-polaroid .pimg img,.v-polaroid .pas-img{{width:100%;height:auto;aspect-ratio:1}}
.v-vitrine .pimg img,.v-vitrine .pas-img{{width:100%;height:auto;aspect-ratio:16/10}}
.v-vitrine .prod b{{font:400 calc(var(--tt) * .6)/1.15 var(--tf)}}
.v-carrousel{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;margin:0 -18px;padding:6px 18px 14px;scrollbar-width:none}}
.v-carrousel::-webkit-scrollbar{{display:none}}
.v-carrousel .prod{{flex:0 0 70%;scroll-snap-align:center}}
.v-carrousel .pimg img,.v-carrousel .pas-img{{width:100%;height:auto;aspect-ratio:4/5}}
.v-bento .prod:first-child{{grid-column:1/-1}}
.v-bento .prod:first-child .pimg img,.v-bento .prod:first-child .pas-img{{aspect-ratio:16/9}}
.v-bento .prod:first-child b{{font:400 calc(var(--tt) * .58)/1.15 var(--tf)}}
.v-polaroid{{gap:20px 14px;padding:4px 6px 8px}}
.v-polaroid .prod{{background:#fff!important;color:#222!important;border-radius:3px!important;padding:8px 8px 14px!important;border:0!important;box-shadow:0 10px 20px -10px rgba(0,0,0,.45)!important;transform:rotate(-2deg)}}
.v-polaroid .prod:nth-child(even){{transform:rotate(2.2deg);margin-top:12px}}
.v-polaroid .prod:hover{{transform:rotate(0) scale(1.03)}}
.v-polaroid .pimg img,.v-polaroid .pas-img{{border-radius:0!important;clip-path:none!important;-webkit-mask:none!important;mask:none!important;border:0!important;box-shadow:none!important;transform:none!important}}
.v-polaroid .prod b{{font-family:var(--tf);font-size:16px}}
.v-zigzag .prod{{padding:0!important;overflow:hidden;align-items:stretch;min-height:150px}}
.v-zigzag .prod:nth-child(even){{flex-direction:row-reverse}}
.v-zigzag .pimg{{width:44%}}
.v-zigzag .pimg img,.v-zigzag .pas-img{{width:100%;height:100%;border-radius:0!important;clip-path:none!important;-webkit-mask:none!important;mask:none!important;border:0!important;box-shadow:none!important;transform:none!important;outline:0!important}}
.v-zigzag .ptxt{{padding:16px 14px;align-self:center;flex:1}}
.v-zigzag .prod b{{font:400 calc(var(--tt) * .55)/1.15 var(--tf)}}
.v-mini{{gap:8px}}
.v-mini .prod{{padding:6px 12px 6px 6px}}
.v-mini .pimg img,.v-mini .pas-img{{width:48px;height:48px}}
.v-mini .prod small{{display:none}}
.v-mini .ptxt{{flex:1;display:flex;justify-content:space-between;align-items:center;gap:8px}}
.v-mini .px{{margin:0;white-space:nowrap}}.v-mini .px s{{display:none}}
/* Décor */
.decor{{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}}
.page{{z-index:1}}
.decor i{{position:absolute;display:block}}
.d-etincelles i{{width:calc(16px * var(--s));height:calc(16px * var(--s));background:var(--a);clip-path:polygon(50% 0,61% 39%,100% 50%,61% 61%,50% 100%,39% 61%,0 50%,39% 39%);animation:scint 3.4s ease-in-out infinite}}
.d-etincelles i:nth-child(3n){{background:var(--b)}}
.d-bulles i{{width:calc(150px * var(--s));height:calc(150px * var(--s));border-radius:50%;background:var(--a);opacity:.2;filter:blur(24px);animation:flotte 16s ease-in-out infinite}}
.d-bulles i:nth-child(even){{background:var(--b)}}
.d-confettis i{{top:-20px!important;width:7px;height:13px;background:var(--a);border-radius:2px;opacity:.8;animation:tombe calc(9s + var(--s) * 4s) linear infinite}}
.d-confettis i:nth-child(3n){{background:var(--b)}}.d-confettis i:nth-child(3n+1){{background:var(--f2);height:7px;border-radius:50%}}
.d-coeurs i{{width:calc(20px * var(--s));height:calc(18px * var(--s));background:var(--a);-webkit-mask:var(--coeur) center/contain no-repeat;mask:var(--coeur) center/contain no-repeat;opacity:.45;animation:flotte 12s ease-in-out infinite}}
.d-formes i{{width:calc(46px * var(--s));height:calc(46px * var(--s));border:2px solid var(--a);opacity:.35;border-radius:50%;animation:tourne 30s linear infinite}}
.d-formes i:nth-child(3n){{border-radius:0}}.d-formes i:nth-child(3n+1){{border:0;background:linear-gradient(var(--a) 0 0) center/100% 2px no-repeat,linear-gradient(var(--a) 0 0) center/2px 100% no-repeat}}
@keyframes scint{{0%,100%{{transform:scale(.25);opacity:.15}}50%{{transform:scale(1) rotate(45deg);opacity:.95}}}}
@keyframes flotte{{50%{{transform:translate(24px,-34px)}}}}
@keyframes tombe{{to{{transform:translateY(115vh) rotate(600deg)}}}}
@keyframes tourne{{to{{transform:rotate(1turn)}}}}
.capture h2{{font:400 calc(var(--tt) * .58)/1.15 var(--tf);margin:0 0 4px}}.capture p{{margin:0 0 12px;opacity:.85;font-size:14.5px}}
.champ{{display:flex;gap:8px;flex-wrap:wrap}}
.champ input{{flex:1 1 180px;min-width:0;border:1.5px solid color-mix(in srgb,var(--kt) 25%,transparent);background:transparent;color:var(--kt);border-radius:var(--r);padding:12px 14px;font:inherit}}
.bouton{{padding:12px 18px;font:600 15px var(--tx);cursor:pointer}}
.capture .ok{{font-weight:600;margin:0}}
.kit-lien{{display:flex;justify-content:space-between;align-items:center;text-decoration:none}}
.kit-lien b{{font:400 calc(var(--tt) * .55)/1.15 var(--tf)}}
.marque{{display:flex;justify-content:center;margin-top:34px}}
.marque a{{font-size:12px;text-decoration:none;opacity:.6;border:1px solid currentColor;border-radius:99px;padding:5px 12px}}
.apparition .blocs>*{{animation:monte .5s both}}
{''.join(f'.apparition .blocs>*:nth-child({i}){{animation-delay:{i * 0.05:.2f}s}}' for i in range(1, 16))}
@keyframes monte{{from{{opacity:0;transform:translateY(12px)}}}}
/* Fiche produit et pages secondaires */
.retour{{display:inline-flex;align-items:center;gap:6px;text-decoration:none;opacity:.8;margin-bottom:14px;font-size:14px}}
.fiche img.couv-p{{width:100%;border-radius:var(--rk);display:block;margin-bottom:16px;aspect-ratio:1;object-fit:cover}}
.fiche h1{{font-size:calc(var(--tt) * .85)}}
.fiche .px{{font-size:22px;font-weight:700;color:var(--a);margin:4px 0 14px}}
.fiche .px s{{opacity:.5;font-size:16px;margin-left:8px;color:var(--t)}}
.fiche .desc{{white-space:pre-line;margin:18px 0;line-height:1.6}}
.fiche .bouton{{width:100%;font-size:16.5px;padding:15px}}
.note{{font-size:13px;opacity:.7;text-align:center;margin-top:10px}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.stats .carte b{{display:block;font:400 calc(var(--tt) * .8)/1.05 var(--tf)}}.stats .carte span{{font-size:12.5px;text-transform:uppercase;letter-spacing:.06em;opacity:.75}}
.tops{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}}.tops img{{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:calc(var(--rk) * .6);display:block}}
.tops div{{position:relative}}.tops small{{position:absolute;left:6px;bottom:6px;color:#fff;font-weight:700;text-shadow:0 1px 6px rgba(0,0,0,.6);font-size:12px}}
.tarifs div{{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid color-mix(in srgb,var(--kt) 15%,transparent)}}.tarifs div:last-child{{border:0}}
h2.t2{{font:400 calc(var(--tt) * .6)/1.15 var(--tf);margin:26px 0 10px}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
"""


def _img(uid_pseudo: str, nom: str) -> str:
    return f"/@{uid_pseudo}/i/{quote(nom)}"


def _tete(page: dict, pseudo: str) -> str:
    d = page["design"]
    nom = E(page.get("nom") or "")
    photo = page.get("photo")
    initiale = E((page.get("nom") or "?").strip()[:1].upper())
    fp = d["photo_forme"]
    img_photo = (f'<img class="photo forme-{fp} ph-{fp}" src="{_img(pseudo, photo)}" alt="">' if photo
                 else f'<div class="photo vide forme-{fp} ph-{fp}">{initiale}</div>')
    reseaux = "".join(
        f'<a href="{E(u)}" target="_blank" rel="noopener" aria-label="{E(RESEAUX[k][0])}"><svg viewBox="0 0 24 24">{ICONES[k]}</svg></a>'
        for k, v in (page.get("reseaux") or {}).items() if (u := lien_reseau(k, v)))
    reseaux = f'<nav class="reseaux">{reseaux}</nav>' if reseaux else ""
    bio = f'<p class="bio">{E(page.get("bio") or "")}</p>' if page.get("bio") else ""
    couv_nom = page.get("couverture") or photo
    couv = f'<img class="couv" src="{_img(pseudo, couv_nom)}" alt="">' if couv_nom else ""
    e = d["entete"]
    if e == "cote":
        return f'<header class="tete">{img_photo}<div><h1>{nom}</h1>{reseaux}</div><div class="bio-l">{bio}</div></header>'
    if e == "magazine":
        return f'{couv}<header class="tete"><div class="titre-mag"><h1>{nom}</h1></div></header><header class="tete">{bio}{reseaux}</header>' if couv else \
               f'<header class="tete">{img_photo}<h1>{nom}</h1>{bio}{reseaux}</header>'
    if e in ("banniere", "portrait"):
        return f'{couv}<header class="tete">{img_photo}<h1>{nom}</h1>{bio}{reseaux}</header>'
    return f'<header class="tete">{img_photo}<h1>{nom}</h1>{bio}{reseaux}</header>'


def _youtube(u: str) -> str | None:
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/))([A-Za-z0-9_-]{11})", u or "")
    return m.group(1) if m else None


def _carte_produit(p: dict, pseudo: str, d: dict, vue: str, notes: dict | None = None) -> str:
    from boutique_ventes import prix_effectif
    pe = prix_effectif(p)
    forme = f'pi-{d.get("image_forme", "carre")}'
    img = f'<img class="{forme}" src="{_img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else f'<span class="pas-img {forme}"></span>'
    barre = f'<s>{E(prix_txt(pe["barre"], p.get("devise", "eur")))}</s>' if pe["barre"] else ""
    n = (notes or {}).get(p["id"])
    st = f'<small>{E(p["sous_titre"])}</small>' if p.get("sous_titre") else ""
    if n:
        st += f'<small class="pnote"><span style="color:var(--a)">★</span> {str(n[0]).replace(".", ",")} ({n[1]})</small>'
    if pe["fin"]:
        st += '<small class="pnote" style="color:var(--a);font-weight:700">Offre limitée</small>'
    style_prix = d.get("prix_style", "texte")
    if style_prix == "pastille" and vue in ("mini", "zigzag"):
        style_prix = "bouton"
    px = f'<span class="px pp-{style_prix}">{E(prix_txt(pe["prix"], p.get("devise", "eur")))}{barre}</span>'
    dans_image, sous_titre = (px, "") if style_prix == "pastille" else ("", px)
    return (f'<a class="prod carte" href="/@{pseudo}/p/{p["id"]}"><span class="pimg">{img}{dans_image}</span>'
            f'<div class="ptxt"><b>{E(p.get("titre") or "")}</b>{st}{sous_titre}</div></a>')


def _bloc(b: dict, page: dict, pseudo: str) -> str:
    t = b.get("type")
    d = page["design"]
    prods = {p["id"]: p for p in page.get("produits", []) if p.get("visible", True)}
    if t == "lien":
        u = url_sure(b.get("url"))
        if not u:
            return ""
        vig = f'<img class="vig" src="{_img(pseudo, b["image"])}" alt="">' if b.get("image") else (f'<i class="emo">{E(b["emoji"])}</i>' if b.get("emoji") else "")
        return (f'<a class="lien{" avant" if b.get("en_avant") else ""}" href="/@{pseudo}/l/{b["id"]}" data-url="{E(u)}" target="_blank" rel="noopener">'
                f'{vig}<span>{E(b.get("titre") or u)}</span><i class="reflet"></i></a>')
    if t == "titre":
        return f'<h2 class="sec">{E(b.get("texte") or "")}</h2>'
    if t == "texte":
        return f'<p class="txt">{E(b.get("texte") or "")}</p>'
    if t == "video":
        vid = _youtube(b.get("url"))
        return (f'<iframe class="video" src="https://www.youtube-nocookie.com/embed/{vid}" title="Vidéo" loading="lazy" '
                f'allow="accelerometer; encrypted-media; picture-in-picture" allowfullscreen></iframe>') if vid else ""
    if t == "produit":
        p = prods.get(b.get("produit"))
        return f'<div class="produits v-vitrine">{_carte_produit(p, pseudo, d, "vitrine", page.get("_avis"))}</div>' if p else ""
    if t == "produits":
        liste = [prods[i] for i in (b.get("ids") or [p["id"] for p in page["produits"]]) if i in prods]
        if not liste:
            return ""
        titre = f'<h2 class="sec">{E(b["titre"])}</h2>' if b.get("titre") else ""
        v = d["produits_vue"]
        return f'{titre}<div class="produits v-{v}">{"".join(_carte_produit(p, pseudo, d, v, page.get("_avis")) for p in liste)}</div>'
    if t == "capture":
        txt = f'<p>{E(b["texte"])}</p>' if b.get("texte") else ""
        btn = E(b.get("bouton") or "Je m’inscris")
        return (f'<form class="capture carte" method="post" action="/@{pseudo}/inscription" data-capture>'
                f'<h2>{E(b.get("titre") or "Reste en contact")}</h2>{txt}'
                f'<input type="hidden" name="bloc" value="{E(b["id"])}"><div class="champ"><input type="email" name="email" required placeholder="Ton e-mail" aria-label="Ton e-mail">'
                f'<button class="bouton">{btn}</button></div></form>')
    if t == "kit":
        return (f'<a class="kit-lien carte" href="/@{pseudo}/kit"><span><b>{E(b.get("titre") or "Kit média")}</b><br>'
                f'<small>{E(b.get("texte") or "Mes chiffres et collaborations")}</small></span><span aria-hidden="true">→</span></a>')
    return ""


SCRIPT_PUBLIC = """
<script>
document.querySelectorAll("[data-capture]").forEach(f => f.addEventListener("submit", async e => {
  e.preventDefault(); const b = f.querySelector("button"); b.disabled = true;
  try {
    const r = await fetch(f.action, {method: "POST", body: new FormData(f)}); const j = await r.json();
    if (!r.ok) throw new Error(j.erreur || "Erreur");
    if (j.url) { location.href = j.url; return; }
    f.querySelector(".champ").outerHTML = '<p class="ok">' + (j.message || "C'est noté, merci !") + '</p>';
  } catch (er) { b.disabled = false; alert(er.message); }
}));
</script>"""
SCRIPT_APERCU = """
<script>
document.addEventListener("click", e => { const a = e.target.closest("a"); if (a) { e.preventDefault(); } });
document.addEventListener("submit", e => e.preventDefault());
</script>"""


def document(page: dict, pseudo: str, corps: str, titre: str, description: str = "", apercu: bool = False, image_og: str = "", url: str = "") -> str:
    d = page["design"]
    faces, lien = _polices_css(d)
    fond_img = f'<div class="fond-img" style="background-image:url(\'{_img(pseudo, d["fond_image"])}\')"></div>' if d["fond_type"] == "image" and d.get("fond_image") else ""
    classes = (f'e-{d["entete"]} anim-{d["animation"]}{" apparition" if d.get("apparition") else ""} tb-{d["bouton_taille"]} al-{d["alignement"]}')
    cb = classes_bouton(d)
    if page.get("_parrain"):  # la pastille « Créé avec Veille virale » porte le lien de parrainage de la créatrice
        corps = corps.replace('<a href="/" target="_blank" rel="noopener">Créé avec', f'<a href="/?parrain={quote(page["_parrain"])}" target="_blank" rel="noopener">Créé avec')
    corps = corps.replace('class="lien', f'class="{cb} lien').replace('class="bouton"', f'class="bouton {cb}"')
    decor = ""
    if d.get("decor", "aucun") != "aucun":
        decor = f'<div class="decor d-{d["decor"]}" aria-hidden="true">' + "".join(
            f'<i style="left:{x}%;top:{y}%;--s:{t};animation-delay:-{r}s"></i>' for x, y, t, r in POSITIONS_DECOR) + "</div>"
    og = f'<meta property="og:title" content="{E(titre)}"><meta property="og:description" content="{E(description)}"><meta property="og:type" content="website">'
    if image_og:
        og += f'<meta property="og:image" content="{E(image_og)}"><meta name="twitter:card" content="summary_large_image">'
    if url:
        og += f'<meta property="og:url" content="{E(url)}">'
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{E(titre)}</title><meta name="description" content="{E(description)}">{og}<meta name="theme-color" content="{d['fond1'][:7]}">
{lien}<style>{faces}{_css(d)}</style>{'<meta name="robots" content="noindex">' if apercu else ''}</head>
<body class="{classes}">{fond_img}<div class="fond"></div>{decor}<main class="page">{corps}</main>{SCRIPT_APERCU if apercu else SCRIPT_PUBLIC}</body></html>"""


POSITIONS_DECOR = [(6, 8, 1, 0), (88, 5, .7, 1.2), (72, 22, 1.3, 2.4), (14, 34, .8, .7), (93, 41, 1, 3.1), (4, 58, 1.2, 1.8),
                   (80, 63, .6, .4), (24, 76, 1, 2.9), (62, 84, 1.4, 1.5), (90, 92, .8, 3.6), (40, 12, .6, 4.2), (50, 50, .9, 5)]


def classes_bouton(d: dict) -> str:
    f = d.get("bouton_forme", "arrondi")
    return f'lb bs-{d["bouton_style"]} bf-{f}{" bf-clip" if f in FORMES_DECOUPEES else ""} bh-{d.get("survol", "soulever")}'


def badge(page: dict | None = None) -> str:
    """Mention en bas de page : affichée en formule gratuite, retirée pour les abonnées."""
    if page is not None and not page.get("_marque", True):
        return ""
    return '<div class="marque"><a href="/" target="_blank" rel="noopener">Créé avec Veille virale</a></div>'


def rendu_page(page: dict, pseudo: str, apercu: bool = False, url: str = "") -> str:
    blocs = "".join(_bloc(b, page, pseudo) for b in page.get("blocs", []) if b.get("visible", True))
    if not blocs.strip() and apercu:
        blocs = '<p class="txt" style="opacity:.6">Ajoute tes liens et tes produits : ils apparaîtront ici.</p>'
    corps = f'{_tete(page, pseudo)}<div class="blocs">{blocs}</div>{badge(page)}'
    img = f"{url.rsplit('/@', 1)[0]}{_img(pseudo, page['photo'])}" if page.get("photo") and url else ""
    return document(page, pseudo, corps, page.get("nom") or pseudo, (page.get("bio") or "")[:160], apercu, img, url)


def rendu_produit(page: dict, pseudo: str, p: dict, message: str = "", vente_possible: bool = True) -> str:
    img = f'<img class="couv-p" src="{_img(pseudo, p["image"])}" alt="">' if p.get("image") else ""
    barre = f'<s>{E(prix_txt(p["prix_barre"], p.get("devise", "eur")))}</s>' if p.get("prix_barre") and p["prix_barre"] > p.get("prix", 0) else ""
    gratuit = not p.get("prix")
    if p.get("lien") and not p.get("fichier") and gratuit:
        action = f'<a class="bouton" style="display:block;text-align:center;text-decoration:none" href="/@{pseudo}/p/{p["id"]}/ouvrir" target="_blank" rel="noopener">{E(p.get("bouton") or "J’y vais")}</a>'
    elif gratuit:
        action = (f'<form method="post" action="/@{pseudo}/p/{p["id"]}/obtenir" data-capture><div class="champ" style="flex-direction:column">'
                  f'<input type="text" name="prenom" placeholder="Ton prénom" aria-label="Ton prénom" style="color:var(--t);border-color:color-mix(in srgb,var(--t) 30%,transparent)">'
                  f'<input type="email" name="email" required placeholder="Ton e-mail" aria-label="Ton e-mail" style="color:var(--t);border-color:color-mix(in srgb,var(--t) 30%,transparent)">'
                  f'<button class="bouton">{E(p.get("bouton") or "Je le reçois gratuitement")}</button></div></form>'
                  '<p class="note">Tu le reçois tout de suite, et aussi par e-mail.</p>')
    elif vente_possible:
        action = (f'<form method="post" action="/@{pseudo}/p/{p["id"]}/acheter"><button class="bouton">{E(p.get("bouton") or "Je le veux")} · '
                  f'{E(prix_txt(p["prix"], p.get("devise", "eur")))}</button></form><p class="note">Paiement sécurisé par Stripe</p>')
    else:
        action = '<p class="note" style="font-size:15px">Ce produit sera bientôt disponible à l’achat.</p>'
    msg = f'<div class="carte" style="margin-bottom:14px">{E(message)}</div>' if message else ""
    st = f'<p style="opacity:.8;margin:0">{E(p["sous_titre"])}</p>' if p.get("sous_titre") else ""
    corps = (f'<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a>{msg}<article class="fiche">{img}<h1>{E(p.get("titre") or "")}</h1>'
             f'{st}'
             f'<p class="px">{E(prix_txt(p.get("prix", 0), p.get("devise", "eur")))}{barre}</p>{action}'
             f'<div class="desc">{E(p.get("description") or "")}</div></article>{badge(page)}')
    return document(page, pseudo, corps, f'{p.get("titre")} · {page.get("nom")}', (p.get("sous_titre") or p.get("description") or "")[:160],
                    image_og=_img(pseudo, p["image"]) if p.get("image") else "")


def rendu_message(page: dict, pseudo: str, titre: str, texte: str, bouton: tuple[str, str] | None = None) -> str:
    b = f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:16px" href="{E(bouton[1])}">{E(bouton[0])}</a>' if bouton else ""
    corps = (f'<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a><div class="carte" style="text-align:center;padding:28px 20px">'
             f'<h1 style="font-size:calc(var(--tt) * .8)">{E(titre)}</h1><p style="margin:0">{E(texte)}</p>{b}</div>{badge(page)}')
    return document(page, pseudo, corps, titre)


def _k(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} M".replace(".", ",").replace(",0 ", " ")
    if n >= 1000:
        return f"{n / 1000:.1f} k".replace(".", ",").replace(",0 ", " ")
    return f"{int(n)}"


def chiffres_kit(profil: dict | None) -> dict:
    p = profil or {}
    bio = p.get("bio") or {}
    ch = p.get("chiffres") or {}
    ig, tt = bio.get("instagram") or {}, bio.get("tiktok") or {}
    return {"abonnes_instagram": ig.get("abonnes"), "abonnes_tiktok": tt.get("abonnes"), "publications": ig.get("publications"),
            "vues_mediane": ch.get("vues_mediane"), "vues_max": ch.get("vues_max"), "engagement": ch.get("engagement_median"),
            "date": (p.get("date") or "")[:10], "top": [t for t in (p.get("top") or []) if t.get("miniature")][:6],
            "instagram": p.get("instagram"), "tiktok": p.get("tiktok")}


def rendu_kit(page: dict, pseudo: str, profil: dict | None) -> str:
    k = page.get("kit") or {}
    c = chiffres_kit(profil)
    tot = (c["abonnes_instagram"] or 0) + (c["abonnes_tiktok"] or 0)
    tuiles = [(_k(tot) if tot else None, "Abonnés au total"), (_k(c["abonnes_instagram"]) if c["abonnes_instagram"] else None, "Instagram"),
              (_k(c["abonnes_tiktok"]) if c["abonnes_tiktok"] else None, "TikTok"), (_k(c["vues_mediane"]) if c["vues_mediane"] else None, "Vues médianes par Reel"),
              (_k(c["vues_max"]) if c["vues_max"] else None, "Meilleur Reel"),
              (f"{c['engagement'] * 100:.1f} %".replace(".", ",") if c["engagement"] else None, "Taux d'engagement")]
    tuiles += [(x.get("valeur"), x.get("libelle")) for x in k.get("chiffres_perso") or [] if x.get("valeur")]
    stats = "".join(f'<div class="carte"><span>{E(l or "")}</span><b>{E(str(v))}</b></div>' for v, l in tuiles if v)
    tops = "".join(f'<div><img src="/@{pseudo}/kit/m/{quote(t["miniature"])}" alt="" loading="lazy"><small>{_k(t.get("vues"))} vues</small></div>' for t in c["top"])
    tarifs = "".join(f'<div><span>{E(t.get("libelle") or "")}</span><b>{E(t.get("prix") or "")}</b></div>' for t in k.get("tarifs") or [] if t.get("libelle"))
    contact = k.get("contact") or (page.get("reseaux") or {}).get("email") or ""
    morceaux = [f'<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a>', _tete({**page, "bio": ""}, pseudo),
                f'<p class="txt" style="margin:-8px 0 18px;font-size:13px;letter-spacing:.08em;text-transform:uppercase">Kit média'
                f'{" · chiffres du " + E(c["date"]) if c["date"] else ""}</p>']
    if k.get("a_propos"):
        morceaux.append(f'<div class="carte" style="white-space:pre-line">{E(k["a_propos"])}</div>')
    if stats:
        morceaux.append(f'<h2 class="t2">Audience</h2><div class="stats">{stats}</div>')
    if tops:
        morceaux.append(f'<h2 class="t2">Contenus les plus vus</h2><div class="tops">{tops}</div>')
    if k.get("marques"):
        morceaux.append(f'<h2 class="t2">Ils m’ont fait confiance</h2><p class="txt" style="text-align:left">{E(k["marques"])}</p>')
    if tarifs:
        morceaux.append(f'<h2 class="t2">Tarifs</h2><div class="carte tarifs">{tarifs}</div>')
    if contact and "@" in contact:
        morceaux.append(f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:22px" '
                        f'href="mailto:{E(contact)}">Me proposer une collaboration</a>')
    corps = "".join(morceaux) + badge(page)
    return document(page, pseudo, corps, f'Kit média · {page.get("nom")}', f'Audience et collaborations de {page.get("nom")}')


# ------------------------------------------------------------
#  Statistiques, inscrits, ventes
# ------------------------------------------------------------
def compte(uid: int, cle: str, sous: str | None = None):
    f = dossier(uid) / "stats.json"
    with verrou(uid):
        s = _lit(f, {})
        jour = date.today().isoformat()
        if cle == "vue":
            s.setdefault("vues", {})[jour] = s.get("vues", {}).get(jour, 0) + 1
            # on ne garde que 120 jours
            if len(s["vues"]) > 120:
                for j in sorted(s["vues"])[:-120]:
                    del s["vues"][j]
        else:
            s.setdefault(cle, {})[sous] = s.get(cle, {}).get(sous, 0) + 1
        _ecrit(f, s)


def stats(uid: int, page: dict) -> dict:
    d = dossier(uid)
    s = _lit(d / "stats.json", {})
    ventes = _lit(d / "ventes.json", [])
    inscrits = _lit(d / "inscrits.json", [])
    vues = s.get("vues", {})
    j = date.today()
    serie = [(j - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    titres = {b["id"]: b.get("titre") or b.get("url") or "Lien" for b in page.get("blocs", []) if b.get("type") == "lien"}
    prods = {p["id"]: p.get("titre") for p in page.get("produits", [])}
    payees = [v for v in ventes if v.get("montant")]
    il_y_a_7j = (datetime.now() - timedelta(days=7)).isoformat()
    semaine = [v for v in payees if (v.get("date") or "") >= il_y_a_7j[:16]]
    return {
        "ventes_7j": len(semaine), "chiffre_7j": sum(v["montant"] for v in semaine),
        "inscrits_7j": sum(1 for x in inscrits if (x.get("date") or "")[:16] >= il_y_a_7j[:16]),
        "vues_30j": sum(vues.get(x, 0) for x in serie), "vues_7j": sum(vues.get(x, 0) for x in serie[-7:]),
        "serie": [{"jour": x, "vues": vues.get(x, 0)} for x in serie],
        "clics": sorted(({"titre": titres[k], "clics": n} for k, n in s.get("clics", {}).items() if k in titres), key=lambda x: -x["clics"]),
        "clics_total": sum(s.get("clics", {}).values()),
        "produits": sorted(({"titre": prods[k], "vues": n} for k, n in s.get("produits", {}).items() if k in prods), key=lambda x: -x["vues"]),
        "ventes": len(payees), "chiffre": sum(v["montant"] for v in payees), "devise": (payees[-1].get("devise") if payees else "eur"),
        "dernieres_ventes": [{**{k: v.get(k) for k in ("date", "email", "montant", "devise")}, "produit": prods.get(v.get("produit"), "Produit supprimé")}
                             for v in reversed(ventes[-20:])],
        "inscrits": len(inscrits), "derniers_inscrits": list(reversed(inscrits[-50:])),
    }


def ajoute_inscrit(uid: int, email: str, prenom: str = "", source: str = "") -> bool:
    f = dossier(uid) / "inscrits.json"
    with verrou(uid):
        l = _lit(f, [])
        if any(x["email"] == email for x in l):
            return False
        l.append({"email": email, "prenom": prenom[:60], "source": source, "date": datetime.now().astimezone().isoformat(timespec="minutes"),
                  "jeton": secrets.token_urlsafe(12), "etape": 0})
        _ecrit(f, l)
    return True


def inscrits_csv(uid: int) -> str:
    import csv, io
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["email", "prénom", "source", "date"])
    for x in _lit(dossier(uid) / "inscrits.json", []):
        w.writerow([x.get("email"), x.get("prenom"), x.get("source"), x.get("date")])
    return "﻿" + out.getvalue()


def enregistre_vente(uid: int, produit: dict, email: str, montant: int, devise: str, session_id: str, **extra) -> dict:
    """Idempotent (une session Stripe = une vente). Renvoie la vente avec son jeton de téléchargement."""
    f = dossier(uid) / "ventes.json"
    with verrou(uid):
        l = _lit(f, [])
        v = next((x for x in l if session_id and x.get("session") == session_id), None)
        if v:
            return {**v, "nouvelle": False}
        v = {"id": nouvel_id(), "date": datetime.now().isoformat(timespec="minutes"), "produit": produit["id"], "email": email,
             "montant": montant, "devise": devise, "session": session_id, "jeton": secrets.token_urlsafe(24),
             "expire": (datetime.now() + timedelta(days=30)).isoformat(timespec="minutes"), "telechargements": 0,
             **{k: v for k, v in extra.items() if v}}
        l.append(v)
        _ecrit(f, l)
    return {**v, "nouvelle": True}


def vente_par_jeton(uid: int, jeton: str, consomme: bool = False) -> dict | None:
    f = dossier(uid) / "ventes.json"
    with verrou(uid):
        l = _lit(f, [])
        v = next((x for x in l if x.get("jeton") and secrets.compare_digest(x["jeton"], jeton or "")), None)
        if not v or v["expire"] < datetime.now().isoformat() or v.get("telechargements", 0) >= 20:
            return None
        if consomme:
            v["telechargements"] = v.get("telechargements", 0) + 1
            _ecrit(f, l)
        return v


# ------------------------------------------------------------
#  Stripe Connect : chaque cliente encaisse sur son propre compte Stripe
# ------------------------------------------------------------
API = "https://api.stripe.com/v1"


def stripe_actif() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def _stripe(methode: str, chemin: str, compte: str | None = None, **data):
    h = {"Stripe-Account": compte} if compte else {}
    r = requests.request(methode, API + chemin, data=data or None, headers=h, auth=(os.environ["STRIPE_SECRET_KEY"], ""), timeout=30)
    j = r.json()
    if r.status_code >= 400:
        msg = (j.get("error") or {}).get("message") or f"Erreur Stripe {r.status_code}"
        if "signed up for Connect" in msg or "connect" in msg.lower() and "platform" in msg.lower():
            msg = "Stripe Connect n'est pas encore activé sur le compte Stripe de Veille virale (tableau de bord Stripe → Connect)."
        raise ValueError(msg)
    return j


def connecte_stripe(uid: int, email: str, compte: str | None, retour: str) -> tuple[str, str]:
    """Crée (si besoin) le compte Stripe de la cliente et renvoie (id du compte, lien d'inscription Stripe)."""
    if not compte:
        compte = _stripe("POST", "/accounts", **{"type": "standard", "email": email, "metadata[uid]": str(uid)})["id"]
    lien = _stripe("POST", "/account_links", account=compte, refresh_url=retour + "?stripe=relance", return_url=retour + "?stripe=retour",
                   type="account_onboarding")["url"]
    return compte, lien


def etat_stripe(compte: str) -> dict:
    a = _stripe("GET", f"/accounts/{compte}")
    return {"pret": bool(a.get("charges_enabled")), "details": bool(a.get("details_submitted")),
            "nom": ((a.get("business_profile") or {}).get("name") or (a.get("settings") or {}).get("dashboard", {}).get("display_name") or "")}


def commission(uid: int | None = None) -> float:
    """% prélevé sur chaque vente : celui de la formule de la propriétaire (plans.yaml), sinon BOUTIQUE_COMMISSION."""
    try:
        taux = TAUX_COMMISSION(uid) if uid is not None else None
        return max(0.0, min(30.0, float(os.getenv("BOUTIQUE_COMMISSION", "0") if taux is None else taux)))
    except (ValueError, TypeError):
        return 0.0


def session_achat(compte: str, produit: dict, base: str, pseudo: str, montant: int | None = None, meta: dict | None = None, email: str = "",
                  uid: int | None = None) -> str:
    montant = int(produit["prix"] if montant is None else montant)
    data = {
        "mode": "payment", "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": produit.get("devise", "eur"),
        "line_items[0][price_data][unit_amount]": montant,
        "line_items[0][price_data][product_data][name]": (produit.get("titre") or "Produit")[:250],
        "success_url": f"{base}/@{pseudo}/merci?s={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/@{pseudo}/p/{produit['id']}",
        "metadata[produit]": produit["id"], "metadata[pseudo]": pseudo, "locale": "fr",
    }
    if produit.get("sous_titre"):
        data["line_items[0][price_data][product_data][description]"] = produit["sous_titre"][:300]
    for k, v in (meta or {}).items():
        if v:
            data[f"metadata[{k}]"] = str(v)[:400]
    if email:
        data["customer_email"] = email
    c = commission(uid)
    if c:
        data["payment_intent_data[application_fee_amount]"] = int(montant * c / 100)
    return _stripe("POST", "/checkout/sessions", compte, **data)["url"]


def verifie_session(compte: str, sid: str) -> dict | None:
    s = _stripe("GET", f"/checkout/sessions/{sid}", compte)
    if s.get("payment_status") != "paid":
        return None
    return {"email": (s.get("customer_details") or {}).get("email") or s.get("customer_email") or "",
            "montant": s.get("amount_total") or 0, "devise": s.get("currency") or "eur", "produit": (s.get("metadata") or {}).get("produit"),
            "meta": s.get("metadata") or {}}


# ------------------------------------------------------------
#  E-mails aux acheteurs et aux inscrits
# ------------------------------------------------------------
def _gabarit(page: dict, titre: str, corps: str, bouton: tuple[str, str] | None = None) -> str:
    d = page["design"]
    acc = d["bouton_fond"] if not _clair(d["bouton_fond"][:7]) else d["accent"]
    b = (f'<p style="margin:26px 0"><a href="{E(bouton[1])}" style="background:{acc[:7]};color:#fff;padding:13px 22px;border-radius:10px;'
         f'text-decoration:none;font-weight:600;display:inline-block">{E(bouton[0])}</a></p>') if bouton else ""
    return f"""<!doctype html><html><body style="margin:0;background:{d['fond1'][:7]};font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#2B2420">
<div style="max-width:520px;margin:0 auto;padding:32px 20px"><p style="font-weight:700;font-size:15px;margin:0 0 18px;color:{d['texte'][:7]}">{E(page.get('nom') or '')}</p>
<div style="background:#fff;border-radius:16px;padding:28px 26px;line-height:1.55;font-size:15px"><h1 style="font-size:20px;margin:0 0 14px">{E(titre)}</h1>{corps}{b}</div>
</div></body></html>"""


def mail_livraison(page: dict, produit: dict, email: str, lien: str, gratuit: bool):
    import emails
    corps = (f"<p>{'Voici' if gratuit else 'Merci pour ton achat ! Voici'} <b>{E(produit.get('titre') or '')}</b>.</p>"
             "<p>Le lien reste valable 30 jours. Garde cet e-mail précieusement.</p>")
    emails.envoie(email, f"Ton accès : {produit.get('titre')}", _gabarit(page, "C'est à toi !", corps, ("Télécharger", lien)))


def mail_rdv(page: dict, produit: dict, email: str, lien: str, quand: str):
    import emails
    lieu = E((produit.get("rdv") or {}).get("lieu") or "")
    corps = (f"<p>Ton rendez-vous <b>{E(produit.get('titre') or '')}</b> est confirmé :</p><p style='font-size:17px'><b>{E(quand)}</b> (heure de Paris)</p>"
             f"{f'<p>{lieu}</p>' if lieu else ''}<p>Ajoute-le à ton agenda depuis la page de confirmation.</p>")
    emails.envoie(email, f"C'est réservé : {produit.get('titre')}", _gabarit(page, "À très vite !", corps, ("Voir ma réservation", lien)))


def mail_vente(email_vendeuse: str, page: dict, produit: dict, montant: int, devise: str, acheteur: str):
    import emails
    emails.envoie(email_vendeuse, f"Nouvelle vente : {produit.get('titre')} ({prix_txt(montant, devise)})", _gabarit(
        page, "Tu as vendu un produit 🎉", f"<p><b>{E(produit.get('titre') or '')}</b> vient d'être acheté par {E(acheteur)} pour {E(prix_txt(montant, devise))}.</p>"))


# ------------------------------------------------------------
#  Images envoyées par la cliente
# ------------------------------------------------------------
def enregistre_image(uid: int, flux, largeur: int = 1400) -> str:
    from PIL import Image, ImageOps
    im = Image.open(flux)
    im = ImageOps.exif_transpose(im)
    transparent = im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode == "RGBA"
    im.thumbnail((largeur, largeur * 2))
    nom = uuid.uuid4().hex[:12] + (".png" if transparent else ".jpg")
    f = dossier(uid) / "images" / nom
    if transparent:
        im.convert("RGBA").save(f, optimize=True)
    else:
        im.convert("RGB").save(f, quality=86, optimize=True, progressive=True)
    return nom


def nettoie_images(uid: int, page: dict):
    """Supprime les images qui ne sont plus utilisées (après 1 h, pour ne pas effacer un envoi en cours d'édition)."""
    utilisees = {page.get("photo"), page.get("couverture"), page["design"].get("fond_image")}
    utilisees |= {p.get("image") for p in page.get("produits", [])} | {b.get("image") for b in page.get("blocs", [])}
    for f in (dossier(uid) / "images").iterdir():
        if f.name not in utilisees and time.time() - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)
