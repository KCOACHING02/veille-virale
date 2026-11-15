"""
Reproduction fidèle d'un carrousel viral.

Virall.ai relève le plan exact de chaque slide du modèle (format, fond, blocs de texte avec leur place, taille, couleur,
police, formes, photos, en-tête façon tweet, numéro de page…) : c'est la « fiche de reproduction » (`propre` la nettoie).
Ce module redessine chaque slide à l'identique avec les textes adaptés à la marque, sa photo de profil, son @ et des photos
qui montrent la même chose (banque d'images ou photos de la cliente).

Coordonnées : en % de la largeur (x, w) et de la hauteur (y, h) de la slide, origine en haut à gauche.
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

POLICES = Path(__file__).resolve().parent / "static" / "fonts"

FORMATS = {"4:5": (1080, 1350), "1:1": (1080, 1080), "9:16": (1080, 1920), "3:4": (1080, 1440)}

# Polices proposées à Virall.ai pour coller au modèle : clé → (fichier, description donnée à l'IA)
POLICES_REPRO = {
    "sans_normal": ("Poppins-Regular.ttf", "sans-serif ronde, graisse normale (texte courant)"),
    "sans_medium": ("Poppins-Medium.ttf", "sans-serif ronde, graisse moyenne"),
    "sans_gras": ("Poppins-Bold.ttf", "sans-serif ronde, grasse (titres Instagram classiques)"),
    "sans_texte": ("DMSansTexte.ttf", "sans-serif neutre et fine, façon application / tweet"),
    "neutre_gras": ("Inter.ttf", "sans-serif neutre grasse, façon Helvetica / tweet en gras"),
    "geometrique": ("Outfit.ttf", "sans-serif géométrique grasse et large"),
    "sans_noir": ("Montserrat-ExtraBold.ttf", "sans-serif très épaisse, larges capitales"),
    "ultra": ("ArchivoBlack-Regular.ttf", "sans-serif ultra-noire, très compacte"),
    "condense": ("BebasNeue-Regular.ttf", "capitales condensées hautes (affiche)"),
    "condense_gras": ("Anton-Regular.ttf", "capitales condensées très grasses"),
    "condense_moyen": ("Oswald.ttf", "condensée grasse, minuscules possibles"),
    "serif_texte": ("LoraTexte.ttf", "à empattements, texte courant"),
    "serif_gras": ("PlayfairDisplay-Bold.ttf", "à empattements contrastée, grasse (magazine)"),
    "serif_italique": ("PlayfairItalique.ttf", "à empattements, italique élégante"),
    "serif_elegant": ("Cormorant.ttf", "à empattements fine et élégante (luxe)"),
    "serif_elegant_italique": ("CormorantItalique.ttf", "à empattements fine, italique"),
    "serif_moderne": ("Fraunces.ttf", "à empattements moderne et douce"),
    "serif_moderne_italique": ("FrauncesItalique.ttf", "à empattements moderne, italique"),
    "serif_display": ("DMSerifDisplay-Regular.ttf", "à empattements display, titres éditoriaux"),
    "didone": ("Bodoni.ttf", "Didot / Bodoni, mode"),
    "serif_noir": ("AbrilFatface-Regular.ttf", "à empattements très grasse (titres rétro)"),
    "manuscrit": ("Caveat-Bold.ttf", "écriture manuscrite naturelle"),
    "manuscrit_feutre": ("PermanentMarker.ttf", "feutre / marqueur épais"),
    "manuscrit_leger": ("Kalam.ttf", "écriture manuscrite légère"),
    "script": ("Dancing.ttf", "script attaché"),
    "signature": ("GreatVibes.ttf", "signature calligraphiée"),
    "arrondie": ("Nunito.ttf", "sans-serif arrondie et douce"),
    "fun": ("Fredoka.ttf", "arrondie ludique"),
    "technique": ("SpaceGrotesk-Bold.ttf", "sans-serif technique / startup"),
}
TYPES_FOND = ("uni", "degrade", "photo")
ROLES = ("titre", "sous_titre", "corps", "liste", "numero", "signature", "bouton", "citation", "etiquette")
FORMES = ("rect", "arrondi", "pastille", "cercle", "ligne")
COULEUR = re.compile(r"^#[0-9a-fA-F]{6}$")


# ------------------------------------------------------------
#  Nettoyage de la fiche (sortie de Virall.ai)
# ------------------------------------------------------------
def _boite(v, defaut=(8, 8, 84, 30)) -> list[float]:
    try:
        x, y, w, h = (float(a) for a in (v or defaut)[:4])
    except (TypeError, ValueError):
        x, y, w, h = defaut
    x, y = min(max(x, 0), 98), min(max(y, 0), 98)
    return [x, y, min(max(w, 2), 100 - x), min(max(h, 1), 100 - y)]


def _coul(v, defaut="#111111") -> str:
    return v.upper() if isinstance(v, str) and COULEUR.match(v) else defaut


def _txt(v, n=600) -> str:
    return re.sub(r"[ \t]+", " ", str(v or "")).strip()[:n]


def propre(fiche: dict) -> dict:
    """Fiche de reproduction sûre et complète (valeurs bornées, couleurs valides)."""
    import json
    if isinstance(fiche.get("slides"), str):  # certains modèles renvoient le tableau en texte JSON
        try:
            fiche = {**fiche, "slides": json.loads(fiche["slides"])}
        except ValueError:
            fiche = {**fiche, "slides": []}
    fmt = fiche.get("format") if fiche.get("format") in FORMATS else "4:5"
    slides = []
    for s in (fiche.get("slides") or [])[:10]:
        if not isinstance(s, dict):
            continue
        for cle in ("fond", "elements"):
            if isinstance(s.get(cle), str):
                try:
                    s = {**s, cle: json.loads(s[cle])}
                except ValueError:
                    pass
        f = s.get("fond") if isinstance(s.get("fond"), dict) else {}
        fond = {"type": f.get("type") if f.get("type") in TYPES_FOND else "uni",
                "couleurs": [_coul(c, "#FFFFFF") for c in (f.get("couleurs") or ["#FFFFFF"])[:3]] or ["#FFFFFF"],
                "voile": max(0, min(85, int(f.get("voile") or 0))),
                "description": _txt(f.get("description"), 300), "recherche": _txt(f.get("recherche"), 120),
                "image": _txt(f.get("image"), 80), "vues": [str(v)[:80] for v in (f.get("vues") or [])][:30]}
        elements = []
        for e in (s.get("elements") or [])[:16]:
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            base = {"type": t, "boite": _boite(e.get("boite"))}
            if t == "texte":
                base.update(role=e.get("role") if e.get("role") in ROLES else "corps", original=_txt(e.get("original")),
                            adapte=_txt(e.get("adapte") or e.get("original")), police=e.get("police") if e.get("police") in POLICES_REPRO else "sans_gras",
                            couleur=_coul(e.get("couleur")), taille=max(1.2, min(16.0, float(e.get("taille") or 5))),
                            align=e.get("align") if e.get("align") in ("gauche", "centre", "droite") else "gauche",
                            valign=e.get("valign") if e.get("valign") in ("haut", "centre", "bas") else "haut",
                            majuscules=bool(e.get("majuscules")), surlignage=_coul(e.get("surlignage"), "") if e.get("surlignage") else "",
                            interligne=max(0.9, min(1.8, float(e.get("interligne") or 1.18))),
                            accent=_txt(e.get("accent"), 120), accent_couleur=_coul(e.get("accent_couleur"), "") if e.get("accent_couleur") else "",
                            accent_police=e.get("accent_police") if e.get("accent_police") in POLICES_REPRO else "",
                            accent_style=e.get("accent_style") if e.get("accent_style") in ("couleur", "surligne", "souligne", "police") else "")
            elif t == "forme":
                base.update(forme=e.get("forme") if e.get("forme") in FORMES else "rect", couleur=_coul(e.get("couleur"), "#000000"),
                            opacite=max(5, min(100, int(e.get("opacite") or 100))), contour=_coul(e.get("contour"), "") if e.get("contour") else "")
            elif t == "image":
                base.update(forme=e.get("forme") if e.get("forme") in ("rect", "arrondi", "cercle") else "arrondi",
                            description=_txt(e.get("description"), 300), recherche=_txt(e.get("recherche"), 120), image=_txt(e.get("image"), 80),
                            vues=[str(v)[:80] for v in (e.get("vues") or [])][:30])
            elif t == "entete":  # en-tête façon tweet / publication : photo ronde, nom, @, badge
                base.update(couleur=_coul(e.get("couleur"), "#0F1419"), couleur2=_coul(e.get("couleur2"), "#536471"), certifie=bool(e.get("certifie")))
            elif t == "avatar":
                base.update(contour=_coul(e.get("contour"), "") if e.get("contour") else "")
            elif t == "fleche":
                base.update(couleur=_coul(e.get("couleur")), texte=_txt(e.get("texte"), 40))
            else:
                continue
            elements.append(base)
        slides.append({"fond": fond, "elements": elements})
    return {"format": fmt, "slides": slides}


# ------------------------------------------------------------
#  Dessin
# ------------------------------------------------------------
def _rgb(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def police(cle: str, taille: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(POLICES / POLICES_REPRO.get(cle, POLICES_REPRO["sans_gras"])[0]), max(8, int(taille)))


def _couvre(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.4))


def _masque(w: int, h: int, forme: str, rayon: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if forme == "cercle":
        d.ellipse((0, 0, w - 1, h - 1), fill=255)
    else:
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=rayon if forme in ("arrondi", "pastille") else 0, fill=255)
    return m


def _fond(s: dict, W: int, H: int, images: dict) -> Image.Image:
    f = s["fond"]
    c = [_rgb(x) for x in f["couleurs"]]
    if f["type"] == "photo" and images.get("fond"):
        try:
            img = _couvre(Image.open(images["fond"]), W, H)
        except Exception:  # noqa: BLE001
            img = Image.new("RGB", (W, H), c[0])
        if f["voile"]:
            img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), f["voile"] / 100)
        return img
    if f["type"] == "degrade" and len(c) > 1:
        haut, bas = c[0], c[-1]
        g = Image.linear_gradient("L").resize((W, H))
        return Image.composite(Image.new("RGB", (W, H), bas), Image.new("RGB", (W, H), haut), g)
    return Image.new("RGB", (W, H), c[0])


def _remplace(t: str, profil: dict) -> str:
    return t.replace("{pseudo}", profil.get("pseudo") or "").replace("{nom}", profil.get("nom") or "")


def _lisible(fond: tuple) -> tuple:
    return (20, 20, 20) if (fond[0] * 299 + fond[1] * 587 + fond[2] * 114) / 1000 > 150 else (255, 255, 255)


def _mots(texte: str, accent: str) -> list[list[tuple[str, bool]]]:
    """Paragraphes → mots, chacun marqué s'il fait partie de l'expression mise en valeur (même coupée sur deux lignes)."""
    cible = [m.lower() for m in accent.split()] if accent else []
    res = []
    for para in texte.split("\n"):
        mots = para.split(" ")
        drap = [False] * len(mots)
        if cible:
            bas = [re.sub(r"[^\w%€$]", "", m.lower()) for m in mots]
            cb = [re.sub(r"[^\w%€$]", "", m) for m in cible]
            for k in range(len(mots) - len(cb) + 1):
                if bas[k:k + len(cb)] == cb:
                    for j in range(k, k + len(cb)):
                        drap[j] = True
        res.append(list(zip(mots, drap)))
    return res


def _texte(img: Image.Image, e: dict, W: int, H: int, profil: dict, i: int, n: int):
    d = ImageDraw.Draw(img)
    x, y, w, h = (e["boite"][0] * W / 100, e["boite"][1] * H / 100, e["boite"][2] * W / 100, e["boite"][3] * H / 100)
    texte = _remplace(e["adapte"], profil)
    if e["majuscules"]:
        texte = texte.upper()
    if not texte.strip():
        return
    accent = (e["accent"].upper() if e["majuscules"] else e["accent"]) if e["accent"] else ""
    paras = _mots(texte, accent)
    pad = 0.012 * W if e["surlignage"] else 0
    taille = e["taille"] * H / 100
    # Taille relevée sur le modèle, réduite seulement si le texte adapté ne tient pas dans la boîte (12 % de marge)
    while True:
        f = police(e["police"], taille)
        fa = police(e["accent_police"], taille) if accent and e["accent_style"] == "police" and e["accent_police"] else f
        esp = d.textlength(" ", font=f)
        lignes = []
        for para in paras:
            cour, larg = [], 0.0
            for mot, ac in para:
                lm = d.textlength(mot, font=fa if ac else f)
                if cour and larg + esp + lm > w - 2 * pad:
                    lignes.append((cour, larg))
                    cour, larg = [], 0.0
                larg += (esp if cour else 0) + lm
                cour.append((mot, ac, lm))
            lignes.append((cour, larg))
        pas = taille * e["interligne"]
        haut_total = pas * len(lignes)
        if (haut_total <= h * 1.12 and max(lg for _, lg in lignes) <= w * 1.02) or taille < 14:
            break
        taille *= 0.94
    asc, desc = f.getmetrics()
    y0 = y if e["valign"] == "haut" else y + (h - haut_total) / 2 if e["valign"] == "centre" else y + h - haut_total
    c = _rgb(e["couleur"])
    for k, (mots, lw) in enumerate(lignes):
        lx = x + pad if e["align"] == "gauche" else x + (w - lw) / 2 if e["align"] == "centre" else x + w - lw - pad
        ly = y0 + k * pas + (pas - (asc + desc)) / 2
        if e["surlignage"] and mots:
            d.rounded_rectangle((lx - pad, ly - pad * 0.4, lx + lw + pad, ly + asc + desc + pad * 0.2), radius=int(pad * 0.8), fill=_rgb(e["surlignage"]))
        cx = lx
        for j, (mot, ac, lm) in enumerate(mots):
            if j:
                cx += esp
            if ac and e["accent_style"] == "surligne":
                fond = _rgb(e["accent_couleur"] or "#FFE066")
                fin = cx + lm + (esp if j + 1 < len(mots) and mots[j + 1][1] else 0)
                d.rectangle((cx - 3, ly + asc * 0.12, fin + 3, ly + asc + desc * 0.55), fill=fond)
                d.text((cx, ly), mot, font=f, fill=_lisible(fond))
            elif ac:
                ca = _rgb(e["accent_couleur"]) if e["accent_couleur"] else c
                fo = fa if e["accent_style"] == "police" else f
                d.text((cx, ly + (asc - fo.getmetrics()[0])), mot, font=fo, fill=ca)
                if e["accent_style"] == "souligne":
                    d.line((cx, ly + asc + 6, cx + lm, ly + asc + 6), fill=ca, width=max(3, int(taille / 14)))
            else:
                d.text((cx, ly), mot, font=f, fill=c)
            cx += lm


def _forme(img: Image.Image, e: dict, W: int, H: int):
    x, y, w, h = (int(e["boite"][0] * W / 100), int(e["boite"][1] * H / 100), int(e["boite"][2] * W / 100), int(e["boite"][3] * H / 100))
    calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    c = (*_rgb(e["couleur"]), int(255 * e["opacite"] / 100))
    contour = (*_rgb(e["contour"]), 255) if e["contour"] else None
    if e["forme"] == "cercle":
        d.ellipse((x, y, x + w, y + h), fill=c, outline=contour, width=4)
    elif e["forme"] == "ligne":
        d.rectangle((x, y, x + w, y + max(2, h)), fill=c)
    else:
        r = min(w, h) // 2 if e["forme"] == "pastille" else int(min(w, h) * 0.12) if e["forme"] == "arrondi" else 0
        d.rounded_rectangle((x, y, x + w, y + h), radius=r, fill=c, outline=contour, width=4)
    img.paste(Image.alpha_composite(img.convert("RGBA"), calque).convert("RGB"))


def _image(img: Image.Image, e: dict, W: int, H: int, chemin):
    x, y, w, h = (int(e["boite"][0] * W / 100), int(e["boite"][1] * H / 100), int(e["boite"][2] * W / 100), int(e["boite"][3] * H / 100))
    try:
        ph = _couvre(Image.open(chemin), w, h) if chemin else None
    except Exception:  # noqa: BLE001
        ph = None
    if ph is None:  # place réservée en attendant la photo
        ph = Image.new("RGB", (w, h), (225, 222, 230))
        ImageDraw.Draw(ph).text((w / 2, h / 2), "Ta photo", font=police("sans_medium", max(18, w // 12)), fill=(140, 135, 150), anchor="mm")
    img.paste(ph, (x, y), _masque(w, h, e["forme"], int(min(w, h) * 0.06)))


def _avatar(profil: dict, taille: int) -> Image.Image:
    if profil.get("photo") and Path(profil["photo"]).exists():
        try:
            return _couvre(Image.open(profil["photo"]), taille, taille)
        except Exception:  # noqa: BLE001
            pass
    a = Image.new("RGB", (taille, taille), _rgb(profil.get("couleur") or "#B4693E"))
    ImageDraw.Draw(a).text((taille / 2, taille / 2), (profil.get("nom") or "?")[:1].upper(), font=police("sans_gras", taille // 2),
                           fill=(255, 255, 255), anchor="mm")
    return a


def _entete(img: Image.Image, e: dict, W: int, H: int, profil: dict):
    x, y, w, h = (int(e["boite"][0] * W / 100), int(e["boite"][1] * H / 100), int(e["boite"][2] * W / 100), int(e["boite"][3] * H / 100))
    t = h
    av = _avatar(profil, t)
    img.paste(av, (x, y), _masque(t, t, "cercle", 0))
    d = ImageDraw.Draw(img)
    fn, fp = police("neutre_gras", int(t * 0.34)), police("sans_texte", int(t * 0.3))
    nom = profil.get("nom") or profil.get("pseudo") or ""
    nx = x + t + int(t * 0.28)
    d.text((nx, y + t * 0.12), nom, font=fn, fill=_rgb(e["couleur"]))
    if e["certifie"]:  # badge bleu certifié
        bx, by, r = nx + d.textlength(nom, font=fn) + t * 0.12, y + t * 0.16, int(t * 0.16)
        d.ellipse((bx, by, bx + 2 * r, by + 2 * r), fill=(29, 155, 240))
        d.line((bx + r * 0.55, by + r * 1.05, bx + r * 0.9, by + r * 1.4, bx + r * 1.5, by + r * 0.65), fill=(255, 255, 255), width=max(2, r // 4))
    d.text((nx, y + t * 0.56), "@" + (profil.get("pseudo") or "").lstrip("@"), font=fp, fill=_rgb(e["couleur2"]))


def _fleche(img: Image.Image, e: dict, W: int, H: int):
    x, y, w, h = (e["boite"][0] * W / 100, e["boite"][1] * H / 100, e["boite"][2] * W / 100, e["boite"][3] * H / 100)
    d = ImageDraw.Draw(img)
    c = _rgb(e["couleur"])
    ep = max(3, int(h * 0.1))
    texte = re.sub(r"\s*[→➜➔⟶>»]+\s*$", "", e["texte"])
    if texte:  # « Swipe » puis une flèche dessinée (les polices n'ont pas toutes le caractère →)
        f = police("sans_medium", int(h * 0.62))
        lf = h * 1.1
        d.text((x + w - lf - h * 0.25, y + h / 2), texte, font=f, fill=c, anchor="rm")
        x, w = x + w - lf, lf
    d.line((x, y + h / 2, x + w, y + h / 2), fill=c, width=ep)
    d.line((x + w - h * 0.4, y + h * 0.1, x + w, y + h / 2, x + w - h * 0.4, y + h * 0.9), fill=c, width=ep, joint="curve")


def slide(fiche: dict, i: int, images: dict | None = None, profil: dict | None = None) -> Image.Image:
    """Slide i redessinée d'après la fiche. images : {"fond": chemin, <index de l'élément>: chemin} ; profil : nom, pseudo, photo, couleur."""
    W, H = FORMATS[fiche["format"]]
    s = fiche["slides"][i]
    images, profil = images or {}, profil or {}
    img = _fond(s, W, H, images)
    n = len(fiche["slides"])
    for k, e in enumerate(s["elements"]):
        if e["type"] == "forme":
            _forme(img, e, W, H)
        elif e["type"] == "image":
            _image(img, e, W, H, images.get(k) or images.get(str(k)))
        elif e["type"] == "texte":
            _texte(img, e, W, H, profil, i, n)
        elif e["type"] == "entete":
            _entete(img, e, W, H, profil)
        elif e["type"] == "avatar":
            x, y, w = (int(e["boite"][0] * W / 100), int(e["boite"][1] * H / 100), int(e["boite"][2] * W / 100))
            img.paste(_avatar(profil, w), (x, y), _masque(w, w, "cercle", 0))
        elif e["type"] == "fleche":
            _fleche(img, e, W, H)
    return img.filter(ImageFilter.SMOOTH_MORE) if False else img


# ------------------------------------------------------------
#  Pipeline : publication des Tendances → projet du Studio reproduit
# ------------------------------------------------------------
def images_du_post(post: dict) -> list[str]:
    """Slides du modèle : celles préparées par la bibliothèque virale (la même publication pour toutes les clientes)."""
    try:
        import bibliotheque
        e = bibliotheque.publications().get(str(post.get("id") or ""))
        if e:
            return [str(bibliotheque.MEDIA / r) for r in e.get("images") or [] if (bibliotheque.MEDIA / r).is_file()]
    except Exception:  # noqa: BLE001
        pass
    return [x for x in post.get("images") or [] if Path(x).is_file()]


def profil_marque(esp, cfg: dict) -> dict:
    """Nom, @, photo et couleur de la marque, pour l'en-tête et l'avatar des slides."""
    mc = cfg.get("mon_compte") or {}
    pseudo = (mc.get("instagram") or "").lstrip("@")
    nom = (cfg.get("niche") or {}).get("nom") or pseudo
    photo, couleur = "", "#B4693E"
    try:
        import boutique as bq
        uid = int(esp.racine.name)
        page = bq.lit_page(uid) or {}
        nom = page.get("nom") or nom
        pseudo = pseudo or bq.pseudo_de(uid) or ""
        if page.get("photo") and (bq.dossier(uid) / "images" / page["photo"]).is_file():
            photo = str(bq.dossier(uid) / "images" / page["photo"])
        couleur = (page.get("design") or {}).get("accent", couleur)[:7]
    except Exception:  # noqa: BLE001
        pass
    return {"nom": nom, "pseudo": pseudo, "photo": photo, "couleur": couleur}


def _fiche_demo(n: int, post: dict) -> dict:
    """Démo sans clé : une fiche plausible (en-tête façon tweet, puis slides texte sur fond crème avec photo)."""
    hook = ((post.get("adaptation") or {}).get("hook_viral") or "Personne ne te le dit, mais tes premières ventes viennent de tes stories.")
    slides = [{"fond": {"type": "uni", "couleurs": ["#FFFFFF"]}, "elements": [
        {"type": "entete", "boite": [7, 8, 60, 7], "certifie": True},
        {"type": "texte", "role": "titre", "original": hook, "adapte": hook, "police": "sans_texte", "couleur": "#0F1419", "taille": 4.4, "boite": [7, 20, 86, 60]}]}]
    for k in range(1, max(2, n)):
        slides.append({"fond": {"type": "uni", "couleurs": ["#F3EBDD"]}, "elements": [
            {"type": "texte", "role": "numero", "adapte": f"{k}/{max(1, n - 1)}", "police": "serif_italique", "couleur": "#8A6A4F", "taille": 3, "boite": [8, 6, 20, 5]},
            {"type": "texte", "role": "titre", "adapte": f"Étape {k} : une idée claire, écrite comme dans le modèle", "police": "serif_gras", "couleur": "#2A211C",
             "taille": 6, "boite": [8, 14, 84, 28], "accent": "comme dans le modèle", "accent_style": "police", "accent_police": "serif_italique", "accent_couleur": "#B4693E"},
            {"type": "image", "boite": [8, 46, 84, 36], "forme": "arrondi", "recherche": "woman laptop cozy", "description": "femme à son ordinateur"},
            {"type": "texte", "role": "corps", "adapte": "Le texte du modèle, traduit fidèlement pour ta niche.", "police": "sans_normal", "couleur": "#4A3E36", "taille": 2.6, "boite": [8, 85, 84, 9]}]})
    return {"format": "4:5", "slides": slides}


def prepare(esp, cfg: dict, post: dict, sid: str, demo: bool = False) -> dict:
    """Tâche « Reproduction du carrousel » : plan exact du modèle, textes adaptés, photos équivalentes, slides dessinées."""
    import studio
    try:
        return _prepare(esp, cfg, post, sid, demo)
    except Exception as e:
        p = studio.charge(esp, sid)
        if not p.get("reproduction"):  # échec avant la fiche : le projet ne reste pas « en cours »
            p.pop("reproduction_en_cours", None)
            p.update(statut="erreur", erreur=str(e)[:300])
            studio.sauve(esp, p)
        raise


def _prepare(esp, cfg: dict, post: dict, sid: str, demo: bool = False) -> dict:
    import shutil
    import studio
    from modele import log
    images = images_du_post(post)
    if not images and not demo:
        raise ValueError("Les slides de ce carrousel ne sont pas disponibles : choisis-en un autre dans Tendances.")
    log(f"Virall.ai relève la mise en page de tes {len(images) or 'n'} slides…")
    if demo:
        brut = _fiche_demo(len(images) or 6, post)
    else:
        import ia
        from apprentissage import voix
        brut = ia.plan_reproduction(cfg, voix(cfg, esp.racine, []), images, post.get("legende") or "", post.get("compte") or "")
        if brut.get("erreur"):
            raise ValueError(brut["erreur"])
    fiche = propre(brut)
    if not fiche["slides"]:
        raise ValueError("Virall.ai n'a pas pu lire ces slides : réessaie ou choisis un autre carrousel.")
    p = studio.charge(esp, sid)
    d = studio.dossier(esp, sid)
    (d / "modele").mkdir(parents=True, exist_ok=True)
    for x in images:  # le modèle, pour la comparaison côte à côte dans l'éditeur
        shutil.copy(x, d / "modele" / Path(x).name)
    # Textes simples aussi rangés dans les slides habituelles (légende, aperçus, plan du mois)
    p.pop("reproduction_en_cours", None)
    titre = next((e["adapte"] for e in fiche["slides"][0]["elements"] if e["type"] == "texte" and e["role"] in ("titre", "citation")), "")
    if titre and p.get("titre") in ("", "Sans titre"):
        p["titre"] = re.sub(r"\s+", " ", titre)[:90]
    p.update(reproduction=fiche, modele_slides=[Path(x).name for x in images], copie_du_modele=True,
             slides=[{"titre": next((e["adapte"] for e in s["elements"] if e["type"] == "texte" and e["role"] == "titre"), ""), "texte": "", "photo": ""}
                     for s in fiche["slides"]])
    studio.sauve(esp, p)
    log("Je cherche des photos qui montrent la même chose…")
    photos_banque(esp, sid, demo)
    log("Je dessine tes slides…")
    return studio.genere(esp, sid, demo=demo)


def photos_banque(esp, sid: str, demo: bool = False):
    """Pour chaque photo du modèle (fond ou cadre), une photo de la banque qui montre la même scène."""
    import banque
    import studio
    from modele import log
    p = studio.charge(esp, sid)
    fiche = p["reproduction"]
    d = studio.dossier(esp, sid)
    (d / "sources").mkdir(exist_ok=True)
    utilises = set()
    for i, s in enumerate(fiche["slides"]):
        cibles = ([("fond", s["fond"])] if s["fond"]["type"] == "photo" else []) + \
                 [(k, e) for k, e in enumerate(s["elements"]) if e["type"] == "image"]
        for cle, e in cibles:
            if e.get("image") and (d / "sources" / e["image"]).is_file():
                continue
            req = e.get("recherche") or e.get("description") or ""
            if not req or not (banque.active() or demo):
                continue
            try:
                bx = e.get("boite") or [0, 0, 1, 1]
                sens = "portrait" if cle == "fond" or bx[3] * 1.25 >= bx[2] else "landscape"  # cadre plus haut que large → photo verticale
                res = [r for r in banque.photos(req, n=12, orientation=sens) if r["id"] not in utilises]
            except Exception as ex:  # noqa: BLE001
                log(f"  ⚠️  Banque d'images : {str(ex)[:100]}")
                return
            if res:
                utilises.add(res[0]["id"])
                nom = f"repro_{i}_{cle}_{res[0]['id']}.jpg"
                banque.telecharge(res[0], d / "sources" / nom)
                e["image"] = nom
    studio.sauve(esp, p)


def dessine(esp, p: dict, d: Path, sortie: Path, filigrane: bool = False) -> list[str]:
    """Slides du projet reproduit, enregistrées dans sortie/ (appelé par studio.genere)."""
    fiche = p["reproduction"]
    profil = profil_marque(esp, esp.lit_config())
    fichiers = []
    for i, s in enumerate(fiche["slides"]):
        imgs = {}
        if s["fond"].get("image"):
            imgs["fond"] = str(d / "sources" / s["fond"]["image"])
        for k, e in enumerate(s["elements"]):
            if e["type"] == "image" and e.get("image"):
                imgs[k] = str(d / "sources" / e["image"])
        img = slide(fiche, i, imgs, profil)
        if filigrane:
            dr = ImageDraw.Draw(img)
            dr.text((img.width - 24, img.height - 24), "Virallink", font=police("sans_medium", 26), fill=(255, 255, 255), anchor="rd")
        nom = f"slide_{i + 1:02d}.jpg"
        img.save(sortie / nom, "JPEG", quality=92)
        fichiers.append(nom)
    return fichiers
