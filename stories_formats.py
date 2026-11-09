"""Formats de story : de vraies mises en page (pas seulement un effet sur le texte).

Chaque format compose des calques (photo, cartes, lignes de texte) qui entrent chacun à leur moment :
note de téléphone, magazine, scrapbook, messagerie, verre dépoli, affiche, publication, bento, karaoké, étiquettes.
`classe(s, photo, rang, total)` les range du plus adapté au moins adapté pour une story (l'écran en propose 5 à la fois),
`choisis(slides, photos)` en donne un par story sans répétition (« Virall.ai choisit »).
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

import studio

TAILLE = studio.VERTICAL
FPS = 30
M = 84      # marge de côté
HAUT = 250  # sous la barre d'Instagram

FORMATS = {
    "note": {"nom": "Note", "aide": "Comme une note écrite dans ton téléphone, cochée ligne par ligne"},
    "magazine": {"nom": "Magazine", "aide": "Grande photo et titre de couverture qui se révèle ligne par ligne"},
    "scrapbook": {"nom": "Scrapbook", "aide": "Papier, photo scotchée et titre écrit à la main"},
    "conversation": {"nom": "Messages", "aide": "Ton texte arrive en bulles, comme dans une messagerie"},
    "verre": {"nom": "Givré", "aide": "Carte de verre dépoli sur fond flou, halo de couleur"},
    "affiche": {"nom": "Affiche", "aide": "Mots géants qui claquent un par un, bandeau qui défile"},
    "publication": {"nom": "Post", "aide": "Ton texte dans une carte de publication, avec ton @"},
    "bento": {"nom": "Bento", "aide": "Tuiles arrondies qui s'assemblent en cascade"},
    "soustitres": {"nom": "Karaoké", "aide": "Les mots arrivent un par un, surlignés comme les sous-titres d'un Reel"},
    "autocollants": {"nom": "Étiquettes", "aide": "Chaque ligne du titre est une étiquette collée de travers"},
}
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
# Temps que met chaque format à tout faire entrer (avant de laisser lire)
ENTREE = {"note": 1.8, "magazine": 2.2, "scrapbook": 3.0, "conversation": 2.0, "verre": 1.8, "affiche": 2.0, "publication": 2.4,
          "bento": 1.4, "soustitres": 1.0, "autocollants": 1.8}


def _lignes_texte(s: dict, maxi: int = 4) -> list[str]:
    t = studio.propre(s.get("texte") or "")
    return [x.strip(" -•·") for x in re.split(r"\n|·|;|(?<=[.!?])\s+", t) if x.strip(" -•·")][:maxi]


def classe(s: dict, photo: bool, rang: int = 0, total: int = 1) -> list[str]:
    """Tous les formats, du plus adapté au moins adapté à cette story (contenu, photo, place dans la suite)."""
    titre = s.get("titre") or ""
    n, mots = len(_lignes_texte(s, 5)), len(titre.split())
    note = {f: 0.0 for f in FORMATS}

    def plus(v, *fs):
        for f in fs:
            note[f] += v
    if n >= 2:  # plusieurs phrases : ce qui se lit point par point
        plus(3, "note")
        plus(2.5, "bento")
        plus(1.5, "conversation")
    if "?" in titre:
        plus(3, "conversation")
        plus(1, "publication")
    if photo:
        plus(3, "magazine")
        plus(2.5, "scrapbook", "soustitres")
        plus(2, "verre")
        plus(1, "bento")
    else:
        plus(2, "affiche")
        plus(1.5, "autocollants")
        plus(1, "verre", "note")
    if mots <= 6:
        plus(2.5, "affiche")
        plus(2, "autocollants")
    if mots <= 10:
        plus(1.5, "soustitres")
    if len(titre) > 70:
        plus(2, "publication")
        plus(1, "note")
        plus(-2, "affiche", "autocollants")
        plus(-1, "soustitres")
    if total > 1 and rang == 0:  # l'accroche : ce qui arrête le pouce
        plus(1.5, "affiche", "soustitres")
        plus(1, "magazine")
    if total > 1 and rang == total - 1:  # la dernière : l'appel à l'action
        plus(1, "verre", "publication")
        plus(0.5, "autocollants")
    if s.get("sticker"):  # moins de place en bas
        plus(-1.5, "scrapbook")
        plus(-1, "bento")
        plus(-0.5, "note")
    return sorted(FORMATS, key=lambda f: (-note[f], list(FORMATS).index(f)))


def choisis(slides: list[dict], photos: list[bool]) -> list[str]:
    """Un format par story : le mieux adapté qui n'a pas encore servi dans la suite."""
    res = []
    for i, (s, ph) in enumerate(zip(slides, photos)):
        ordre = classe(s, ph, i, len(slides))
        res.append(next((f for f in ordre if f not in res), None) or next(f for f in ordre if not res or f != res[-1]))
    return res


def duree(s: dict, fmt: str) -> float:
    """Le temps que tout entre, puis celui de lire."""
    n = len(_lignes_texte(s))
    mt = len((s.get("titre") or "").split())
    mots = mt + len((s.get("texte") or "").split())
    entree = ENTREE.get(fmt, 2.0) + {"note": 0.75 * n, "conversation": 0.85 * n, "bento": 0.3 * n, "soustitres": 0.26 * mt}.get(fmt, 0)
    return round(max(5.0, min(10.0, entree + max(2.4, mots * 0.17))), 1)


# ------------------------------------------------------------
#  Outils de dessin
# ------------------------------------------------------------
def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _rebond(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _clair(c) -> bool:
    return _lum(c) > 160


def _contraste(a, b) -> float:
    return abs(_lum(a) - _lum(b))


def _sur(c) -> tuple:
    """Couleur de texte lisible sur la couleur c."""
    return (24, 18, 28) if _clair(c) else (255, 255, 255)


def _mix(a, b, k: float) -> tuple:
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def _vif(pal) -> tuple:
    """La couleur d'accent, sauf si elle est blanche ou noire (elle ne ferait pas ressortir une bulle ou une pastille)."""
    a = tuple(pal["accent"])
    if min(a) > 225 or max(a) < 40:
        return tuple(pal["bas"]) if min(pal["bas"]) <= 225 and max(pal["bas"]) >= 40 else tuple(pal["titre"])
    return a


def _echelles(x: dict, k: float):
    """Tailles de titre et de texte : réglages de la cliente × réduction pour que tout tienne."""
    return (lambda v: max(22, int(v * k * x["kt"]))), (lambda v: max(20, int(v * k * x["kx"])))


def _coupe(d, texte: str, pol, largeur: int) -> list[str]:
    """Mise à la ligne qui respecte les espaces insécables (« ? », « ! » et « : » ne partent jamais seuls à la ligne)."""
    res = []
    for paragraphe in texte.split("\n"):
        ligne = ""
        for mot in paragraphe.split(" "):
            if not mot:
                continue
            essai = (ligne + " " + mot) if ligne else mot
            if not ligne or d.textlength(essai, font=pol) <= largeur:
                ligne = essai
            else:
                res.append(ligne)
                ligne = mot
        if ligne:
            res.append(ligne)
    return res


def _bloc(texte: str, graisse: str, largeur: int, taille: int, couleur, interligne: float = 1.16, centre: bool = False, mot: str = "",
          couleur_mot=None, par_ligne: bool = False, contour=None, ombre: bool = False):
    """Texte mis à la ligne, en calque RGBA et sa hauteur (ou la liste des calques, un par ligne, et le pas vertical)."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    pol = studio._police(graisse, taille)
    lignes = _coupe(d, studio.insecables(texte), pol, largeur) or [""]
    pas = int(taille * interligne)
    ep = max(2, taille // 14) if contour else 0
    bord = tuple(contour) + (255,) if contour else None
    res = []
    for ligne in lignes:
        lw = int(d.textlength(ligne, font=pol)) + 8 + 2 * ep
        im = Image.new("RGBA", (largeur + 2 * ep if centre else max(8, lw), pas + int(taille * 0.3)), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        x = (im.size[0] - lw) // 2 + ep if centre else ep
        y = int(taille * 0.08)
        if ombre:
            dd.text((x + 2, y + 3), ligne, font=pol, fill=(0, 0, 0, 170))
        dd.text((x, y), ligne, font=pol, fill=tuple(couleur) + (255,), stroke_width=ep, stroke_fill=bord)
        if mot and couleur_mot and mot.lower() in ligne.lower():
            i0 = ligne.lower().index(mot.lower())
            dd.text((x + d.textlength(ligne[:i0], font=pol), y), ligne[i0:i0 + len(mot)], font=pol, fill=tuple(couleur_mot) + (255,),
                    stroke_width=ep, stroke_fill=bord)
        res.append(im)
    if par_ligne:
        return res, pas
    tout = Image.new("RGBA", (max(i.size[0] for i in res), pas * len(res) + int(taille * 0.3)), (0, 0, 0, 0))
    for i, im in enumerate(res):
        tout.alpha_composite(im, (0, i * pas))
    return tout, pas * len(res)


def _carte(taille, rayon: int, fond, contour=None, ombre: int = 0):
    """Rectangle arrondi (avec ombre portée éventuelle) et la marge ajoutée autour pour l'ombre."""
    from PIL import Image, ImageDraw, ImageFilter
    L, H = taille
    m = 40 if ombre else 0
    im = Image.new("RGBA", (L + 2 * m, H + 2 * m), (0, 0, 0, 0))
    if ombre:
        o = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(o).rounded_rectangle((m, m + 14, m + L, m + H + 14), radius=rayon, fill=(0, 0, 0, ombre))
        im.alpha_composite(o.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(im).rounded_rectangle((m, m, m + L - 1, m + H - 1), radius=rayon, fill=tuple(fond), outline=contour, width=3 if contour else 0)
    return im, m


def _photo_arrondie(image, taille, rayon: int):
    from PIL import Image, ImageDraw
    im = studio._couvre(Image.open(image).convert("RGB"), taille).convert("RGBA")
    m = Image.new("L", taille, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, taille[0] - 1, taille[1] - 1), radius=rayon, fill=255)
    im.putalpha(m)
    return im


def _degrade(haut, bas, taille=TAILLE):
    from PIL import Image
    b = Image.new("RGB", (1, 256))
    for y in range(256):
        b.putpixel((0, y), _mix(haut, bas, y / 255))
    return b.resize(taille, Image.BILINEAR)


def _papier(couleur):
    """Fond papier légèrement granuleux."""
    from PIL import Image
    bruit = Image.effect_noise((TAILLE[0] // 2, TAILLE[1] // 2), 22).resize(TAILLE, Image.BILINEAR)
    return Image.blend(Image.new("RGB", TAILLE, tuple(couleur)), Image.merge("RGB", [bruit] * 3), 0.09)


def _agrandi():
    return int(TAILLE[0] * 1.12), int(TAILLE[1] * 1.12)


def _fond_photo(x: dict, voile: int, debut: float, alpha: int):
    """La photo plein cadre (agrandie pour le zoom lent), voilée et assombrie vers le bas."""
    from PIL import Image
    cle = ("photo", voile, debut, alpha)
    if cle not in x["_cache"]:
        W, H = _agrandi()
        im = studio._couvre(Image.open(x["photo"]).convert("RGB"), (W, H)).convert("RGBA")
        im.alpha_composite(Image.new("RGBA", (W, H), (8, 6, 10, voile)))
        im.alpha_composite(studio._degrade((W, H), debut, alpha))
        x["_cache"][cle] = ("zoom", im.convert("RGB"))
    return x["_cache"][cle]


def _fond_flou(x: dict, voile: int = 90):
    """La photo très floue, ou sans photo un dégradé avec des halos de couleur (agrandi pour le zoom lent)."""
    from PIL import Image, ImageDraw, ImageFilter
    cle = ("flou", voile)
    if cle in x["_cache"]:
        return x["_cache"][cle]
    pal, (W, H) = x["pal"], _agrandi()
    if x["photo"]:
        im = studio._couvre(Image.open(x["photo"]).convert("RGB"), (W // 4, H // 4)).filter(ImageFilter.GaussianBlur(9))
        im = im.resize((W, H), Image.BILINEAR).convert("RGBA")
        im.alpha_composite(Image.new("RGBA", (W, H), (10, 8, 16, voile)))
    else:
        petit = _degrade(pal["haut"], pal["bas"], (270, 480)).convert("RGBA")
        halo = Image.new("RGBA", (270, 480), (0, 0, 0, 0))
        d = ImageDraw.Draw(halo)
        d.ellipse((-40, 40, 180, 260), fill=tuple(pal["accent"]) + (150,))
        d.ellipse((120, 250, 330, 470), fill=_mix(pal["accent"], pal["haut"], 0.5) + (170,))
        petit.alpha_composite(halo.filter(ImageFilter.GaussianBlur(46)))
        im = petit.resize((W, H), Image.BICUBIC)
    x["_cache"][cle] = ("zoom", im.convert("RGB"))
    return x["_cache"][cle]


def _eclat(r: int, couleur, bord=(255, 255, 255)):
    """Étincelle à 4 branches, détourée comme un autocollant."""
    from PIL import Image, ImageDraw
    t = r * 2 + 44
    im = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def pts(R, Ri):
        return [(t / 2 + (R if i % 2 == 0 else Ri) * math.cos(i * math.pi / 4 - math.pi / 2),
                 t / 2 + (R if i % 2 == 0 else Ri) * math.sin(i * math.pi / 4 - math.pi / 2)) for i in range(8)]
    d.polygon(pts(r + 18, r * 0.3 + 13), fill=tuple(bord) + (255,))
    d.polygon(pts(r, r * 0.3), fill=tuple(couleur) + (255,))
    return im


def _etoile_main(r: int, couleur):
    """Étoile tracée au feutre (contour seulement)."""
    from PIL import Image, ImageDraw
    t = r * 2 + 30
    im = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    pts = [(t / 2 + (r if i % 2 == 0 else r * 0.46) * math.cos(i * math.pi / 5 - math.pi / 2 + 0.12),
            t / 2 + (r if i % 2 == 0 else r * 0.46) * math.sin(i * math.pi / 5 - math.pi / 2 + 0.12)) for i in range(10)]
    ImageDraw.Draw(im).line(pts + pts[:2], fill=tuple(couleur) + (255,), width=8, joint="curve")
    return im


def _coeur(couleur, plein: bool):
    from PIL import Image, ImageDraw
    c = Image.new("RGBA", (72, 66), (0, 0, 0, 0))
    pts = [(36 + 30.4 * math.sin(a) ** 3, 30 - 1.9 * (13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)))
           for a in [i * math.pi / 30 for i in range(60)]]
    ImageDraw.Draw(c).polygon(pts, fill=tuple(couleur) + (255,) if plein else None, outline=tuple(couleur) + (255,), width=5)
    return c


class C:
    """Un calque qui entre à t0 (secondes) avec une animation, et sort éventuellement à `fin`."""

    def __init__(self, im, x, y, t0=0.0, anim="fondu", dur=0.5, fin=None):
        self.im, self.x, self.y, self.t0, self.anim, self.dur, self.fin = im, int(x), int(y), t0, anim, dur, fin


def _colle(base, im, x: int, y: int):
    """Pose im sur base en (x, y), en coupant ce qui dépasse du cadre."""
    W, H = base.size
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(im.size[0], W - x), min(im.size[1], H - y)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (0, 0) + im.size:
        im = im.crop((x0, y0, x1, y1))
    base.alpha_composite(im, (x + x0, y + y0))


def _pose(base, c: C, t: float):  # noqa: C901
    from PIL import Image
    if t < c.t0 or (c.fin is not None and t >= c.fin):
        return
    a = (t - c.t0) / c.dur
    im, x, y = c.im, c.x, c.y
    e = _ease(a)
    if c.anim == "fondu":
        y += int(46 * (1 - e))
    elif c.anim == "pop":
        if a < 1:
            k = 0.55 + 0.45 * _rebond(a)
            L, H = im.size
            im = im.resize((max(2, int(L * k)), max(2, int(H * k))), Image.BILINEAR)
            x += (L - im.size[0]) // 2
            y += (H - im.size[1]) // 2
        e = _ease(a * 2.5)
    elif c.anim == "gauche":
        x -= int(320 * (1 - e))
    elif c.anim == "bas":
        y += int(900 * (1 - _rebond(a))) if a < 1 else 0
        e = 1.0
    elif c.anim == "chute":
        y -= int(700 * (1 - _rebond(a))) if a < 1 else 0
        e = 1.0
    elif c.anim == "volet":  # se dévoile de gauche à droite (écriture)
        if a < 1:
            im = im.crop((0, 0, max(1, int(im.size[0] * e)), im.size[1]))
        e = 1.0
    elif c.anim == "ligne":  # monte de derrière un cache (titre de magazine)
        if a < 1:
            H = im.size[1]
            vis = max(1, int(H * e))
            im = im.crop((0, 0, im.size[0], vis))
            y += H - vis
        e = 1.0
    elif c.anim == "fixe":
        e = 1.0
    if e < 1:
        im = im.copy()
        im.putalpha(im.split()[3].point(lambda v, e=e: int(v * e)))
    _colle(base, im, x, y)


# ------------------------------------------------------------
#  Les formats : chacun renvoie (fond, calques, crochet par image ou None, (haut, bas) occupés)
#  fond : image RGB fixe, ou ("zoom", image agrandie de 12 %) pour un zoom lent
#  k : réduction appliquée aux tailles quand tout ne tient pas (voir _compose)
# ------------------------------------------------------------
def _f_note(x, k):
    from PIL import Image, ImageDraw
    pal = x["pal"]
    T, X = _echelles(x, k)
    sombre = not _clair(pal["haut"])
    fond_c, encre, gris = ((28, 28, 30), (255, 255, 255), (152, 152, 159)) if sombre else ((250, 248, 242), (28, 28, 30), (138, 138, 142))
    acc = _vif(pal)
    if _contraste(acc, fond_c) < 60:
        acc = (255, 204, 0) if sombre else (214, 140, 0)
    fond = Image.new("RGB", TAILLE, fond_c)
    cal, L = [], TAILLE[0] - 2 * M
    ent = Image.new("RGBA", (L, 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(ent)
    d.text((0, 6), "‹ Notes", font=studio._police("Medium", 44), fill=acc + (255,))
    d.text((L - d.textlength("Terminé", font=studio._police("Bold", 44)), 6), "Terminé", font=studio._police("Bold", 44), fill=acc + (255,))
    cal.append(C(ent, M, HAUT, 0.0, "fixe"))
    j = datetime.now()
    date, _ = _bloc(f"{j.day} {MOIS[j.month - 1]} {j.year}", "Regular", L, 36, gris, centre=True)
    cal.append(C(date, M, HAUT + 100, 0.0, "fixe"))
    y, t = HAUT + 190, 0.3
    n = len(x["titre"])
    lignes_t, pas = _bloc(x["titre"], "Inter.ttf", L, T(92 if n <= 50 else 78 if n <= 90 else 66), encre, 1.14, mot=x["mot"], couleur_mot=acc, par_ligne=True)
    for im in lignes_t:  # le titre se tape ligne par ligne
        cal.append(C(im, M, y, t, "volet", 0.45))
        y += pas
        t += 0.42
    y += 50
    if len(x["lignes"]) >= 2:  # une case à cocher par phrase
        rond = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        ImageDraw.Draw(rond).ellipse((4, 4, 62, 62), outline=gris + (255,), width=4)
        coche = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        dc = ImageDraw.Draw(coche)
        dc.ellipse((4, 4, 62, 62), fill=acc + (255,))
        dc.line((20, 34, 30, 45, 47, 23), fill=_sur(acc) + (255,), width=6, joint="curve")
        for it in x["lignes"]:
            bl, hb = _bloc(it, "Medium", L - 96, X(50), encre, 1.28)
            cal += [C(rond, M, y + 2, t, "fondu", 0.3), C(bl, M + 96, y, t, "fondu", 0.35), C(coche, M, y + 2, t + 0.55, "pop", 0.35)]
            y += max(hb, 72) + 30
            t += 0.75
    elif x["texte"]:
        bl, hb = _bloc(x["texte"], "Medium", L, X(52), encre, 1.34)
        cal.append(C(bl, M, y, t + 0.1, "fondu", 0.5))
        y += hb
    return fond, cal, None, (HAUT, y)


def _f_magazine(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    if x["photo"]:
        fond, encre, sous = _fond_photo(x, 50, 0.3, 235), (255, 255, 255), (236, 232, 240)
    else:
        fond, encre, sous = _degrade(pal["haut"], pal["bas"]), tuple(pal["titre"]), tuple(pal["texte"])
    acc = _vif(pal) if x["photo"] or _contraste(_vif(pal), pal["bas"]) > 50 else encre
    cal, L = [], w - 2 * M
    sur, _ = _bloc(("@" + x["pseudo"]).upper() if x["pseudo"] else "À LA UNE", "Inter.ttf", L, 34, encre)
    cal.append(C(sur, M, HAUT, 0.2, "fondu", 0.5))
    txt, ht = _bloc(x["texte"], "Regular", L, X(46), sous, 1.34) if x["texte"] else (None, 0)
    n = len(x["titre"])
    lignes_t, pas = _bloc(x["titre"], "PlayfairDisplay-Bold.ttf", L, T(150 if n <= 40 else 122 if n <= 75 else 98), encre, 1.06,
                          mot=x["mot"], couleur_mot=acc, par_ligne=True)
    y = y0 = x["bas"] - ht - (60 if txt else 0) - pas * len(lignes_t) - 50
    if not x["photo"] and y0 - HAUT > 560:  # sans photo : le numéro de la story en très grand, comme un numéro de magazine
        pol = studio._police("PlayfairDisplay-Bold.ttf", 430)
        num = f"{x['numero']:02d}"
        lw = int(ImageDraw.Draw(Image.new("RGBA", (8, 8))).textlength(num, font=pol))
        gros = Image.new("RGBA", (lw + 20, 470), (0, 0, 0, 0))
        ImageDraw.Draw(gros).text((0, -40), num, font=pol, fill=tuple(acc) + (70,))
        cal.append(C(gros, w - M - lw, HAUT + 70, 0.1, "fondu", 0.9))
    cal.append(C(Image.new("RGBA", (L, 5), tuple(acc) + (255,)), M, y, 0.35, "volet", 0.6))
    y += 40
    t = 0.5
    for im in lignes_t:
        cal.append(C(im, M, y, t, "ligne", 0.55))
        y += pas
        t += 0.22
    if txt:
        cal.append(C(txt, M, y + 50, t + 0.25, "fondu", 0.6))
    return fond, cal, None, (y0 - 90, x["bas"])


def _f_scrapbook(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    papier, encre = (244, 238, 226), (40, 32, 28)
    acc = _vif(pal)
    if _contraste(acc, papier) < 70:
        acc = tuple(pal["bas"]) if _contraste(pal["bas"], papier) >= 70 else (200, 90, 70)
    fond = _papier(papier)
    L = w - 2 * M
    n = len(x["titre"])
    lignes_t, pas = _bloc(x["titre"], "Caveat-Bold.ttf", L, T(124 if n <= 40 else 104 if n <= 80 else 88), encre, 1.0, centre=True,
                          mot=x["mot"], couleur_mot=acc, par_ligne=True)
    bl, hb = _bloc(x["texte"], "Kalam.ttf", L, X(46), (70, 60, 56), 1.3, centre=True) if x["texte"] else (None, 0)
    h_txt = pas * len(lignes_t) + 60 + (10 + hb if bl else 0)
    # Le texte garde sa taille : la photo prend la place qui reste (jusqu'à la moitié de sa taille, ensuite tout réduit)
    kp = max(0.5, min(1.0, (x["bas"] - HAUT - h_txt - 150) / 840))
    cal = []
    PL, PH = int(700 * kp), int(760 * kp)
    b, pied = int(32 * kp), int(158 * kp)  # bord blanc, bande du bas
    pola = Image.new("RGBA", (PL + 80, PH + 80), (0, 0, 0, 0))
    carte, m = _carte((PL, PH), 6, (255, 255, 255, 255), ombre=70)
    pola.alpha_composite(carte, (40 - m, 40 - m))
    cadre = (PL - 2 * b, PH - b - pied)
    if x["photo"]:
        pola.alpha_composite(_photo_arrondie(x["photo"], cadre, 2), (40 + b, 40 + b))
    else:  # sans photo : le mot fort (ou le premier chiffre) écrit en grand à la main sur un aplat de couleur
        bloc = _degrade(pal["haut"], pal["bas"], cadre).convert("RGBA")
        chiffre = re.search(r"\d+\s?[%€k]?", x["titre"])
        gros = x["mot"] or (chiffre.group(0) if chiffre else "") or next((v for v in x["titre"].split() if len(v) > 3), x["titre"].strip())
        if gros.strip():
            d0 = ImageDraw.Draw(bloc)
            taille = int(300 * kp)
            while taille > 60 and d0.textlength(gros, font=studio._police("Caveat-Bold.ttf", taille)) > cadre[0] - 60:
                taille -= 10
            d0.text((cadre[0] / 2, cadre[1] / 2), gros, font=studio._police("Caveat-Bold.ttf", taille), anchor="mm",
                    fill=_sur(_mix(pal["haut"], pal["bas"], 0.5)) + (255,))
        pola.alpha_composite(bloc, (40 + b, 40 + b))
    if x["pseudo"]:
        lg, _ = _bloc("@" + x["pseudo"], "Caveat-Bold.ttf", PL - 2 * b, int(56 * kp), (90, 80, 76), centre=True)
        pola.alpha_composite(lg, (40 + b, 40 + PH - pied + int(34 * kp)))
    scotch = Image.new("RGBA", (int(260 * kp), int(70 * kp)), tuple(acc) + (150,)).rotate(4, expand=True, resample=Image.BICUBIC)
    pola.alpha_composite(scotch, ((pola.size[0] - scotch.size[0]) // 2, 2))
    pola = pola.rotate(-4.5, expand=True, resample=Image.BICUBIC)
    px = (w - pola.size[0]) // 2
    cal.append(C(pola, px, HAUT, 0.15, "chute", 0.7))
    cal.append(C(_etoile_main(int(54 * kp), acc), px + pola.size[0] - int(96 * kp), HAUT + int(24 * kp), 1.0, "pop", 0.35))
    y = HAUT + pola.size[1] + 4
    t = 0.9
    for im in lignes_t:
        cal.append(C(im, M, y, t, "volet", 0.5))
        y += pas
        t += 0.45
    trait = Image.new("RGBA", (460, 40), (0, 0, 0, 0))
    ImageDraw.Draw(trait).line([(6 + i * 9, 20 + 7 * math.sin(i / 4.5)) for i in range(50)], fill=tuple(acc) + (255,), width=8, joint="curve")
    cal.append(C(trait, (w - 460) // 2, y + 8, t, "volet", 0.4))
    y += 60
    if bl:
        cal.append(C(bl, M, y + 10, t + 0.4, "fondu", 0.5))
        y += 10 + hb
    return fond, cal, None, (HAUT, y)


def _f_conversation(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    fond = _fond_flou(x, 120)
    acc = _vif(pal)
    cal = []
    nom = x["pseudo"] or "Moi"
    ent = Image.new("RGBA", (w - 2 * M, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(ent)
    d.ellipse((0, 5, 100, 105), fill=tuple(acc) + (255,))
    d.text((50, 55), nom[0].upper(), font=studio._police("Bold", 54), anchor="mm", fill=_sur(acc) + (255,))
    ent_c = (255, 255, 255) if x["photo"] else _sur(_mix(pal["haut"], pal["bas"], 0.2))
    d.text((126, 14), nom, font=studio._police("Bold", 42), fill=ent_c + (255,))
    d.text((126, 64), "en ligne", font=studio._police("Regular", 30), fill=ent_c + (190,))
    cal.append(C(ent, M, HAUT, 0.0, "fixe"))
    y, t = HAUT + 170, 0.35
    bulles = [(x["titre"], False)] + [(v, True) for v in (x["lignes"] or ([x["texte"]] if x["texte"] else []))][:4]
    n = len(x["titre"])
    for i, (txt, moi) in enumerate(bulles):
        bl, hb = _bloc(txt, "Medium" if moi else "Inter.ttf", 700, X(48) if moi else T(62 if n <= 60 else 52), _sur(acc) if moi else (24, 18, 28), 1.22)
        lb = min(708, max(bl.getbbox()[2] if bl.getbbox() else 200, 120))
        carte, m = _carte((lb + 72, hb + 64), 46, tuple(acc) + (255,) if moi else (255, 255, 255, 255), ombre=45)
        carte.alpha_composite(bl, (m + 36, m + 26))
        if i == 1:  # « … » juste avant la première réponse
            pts, mp = _carte((150, 84), 42, tuple(acc) + (255,), ombre=30)
            dp = ImageDraw.Draw(pts)
            for j in range(3):
                dp.ellipse((mp + 36 + j * 30, mp + 32, mp + 54 + j * 30, mp + 50), fill=_sur(acc) + (220,))
            cal.append(C(pts, w - M - 150 - mp, y - mp, t, "pop", 0.25, fin=t + 0.7))
            t += 0.7
        cal.append(C(carte, (w - M - lb - 72 if moi else M) - m, y - m, t, "pop", 0.38))
        y += hb + 64 + 30
        t += 0.85
    return fond, cal, None, (HAUT, y - 30)


def _f_verre(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    fond = _fond_flou(x, 70)
    L = w - 2 * 70
    pale = not x["photo"] and _clair(_mix(pal["haut"], pal["bas"], 0.5))  # fond clair : texte foncé, verre plus laiteux
    encre, sous, vif = ((36, 24, 40), (70, 56, 76), _vif(pal)) if pale else ((255, 255, 255), (240, 238, 246), _vif(pal))
    n = len(x["titre"])
    titre, ht = _bloc(x["titre"], "Sora.ttf", L - 120, T(96 if n <= 45 else 80 if n <= 85 else 66), encre, 1.14, mot=x["mot"],
                      couleur_mot=vif if _clair(vif) != pale else None)
    txt, hx = _bloc(x["texte"], "Regular", L - 120, X(46), sous, 1.36) if x["texte"] else (None, 0)
    H = 150 + ht + (50 + hx if txt else 0) + 80
    carte = Image.new("RGBA", (L, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(carte)
    d.rounded_rectangle((0, 0, L - 1, H - 1), radius=64, fill=(255, 255, 255, 120 if pale else 44), outline=(255, 255, 255, 200 if pale else 130), width=3)
    reflet = Image.new("RGBA", (L, H), (0, 0, 0, 0))
    ImageDraw.Draw(reflet).rounded_rectangle((3, 3, L - 4, max(70, H // 3)), radius=62, fill=(255, 255, 255, 22))
    carte.alpha_composite(reflet)
    y0 = HAUT + 10 + max(0, (x["bas"] - HAUT - 10 - H) // 2)
    f = studio._police("Bold", 30)
    lib = ("@" + x["pseudo"])[:26] if x["pseudo"] else "À retenir"
    lp = int(d.textlength(lib, font=f)) + 56
    pastille, _ = _carte((lp, 66), 33, tuple(vif) + (255,))
    ImageDraw.Draw(pastille).text((28, 12), lib, font=f, fill=_sur(vif) + (255,))
    cal = [C(carte, 70, y0, 0.15, "bas", 0.75), C(pastille, 130, y0 + 56, 0.75, "pop", 0.35), C(titre, 130, y0 + 150, 0.85, "fondu", 0.55)]
    if txt:
        cal.append(C(txt, 130, y0 + 150 + ht + 50, 1.25, "fondu", 0.55))
    return fond, cal, None, (y0, y0 + H)


def _f_affiche(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    fond_c = tuple(pal["haut"])
    encre = tuple(pal["titre"]) if _contraste(pal["titre"], fond_c) > 90 else _sur(fond_c)
    acc = _vif(pal) if _contraste(_vif(pal), fond_c) > 55 else encre
    if x["photo"]:
        im = studio._couvre(Image.open(x["photo"]).convert("RGB"), TAILLE).convert("L").convert("RGBA")  # photo en noir et blanc, teintée
        im.alpha_composite(Image.new("RGBA", TAILLE, fond_c + (205,)))
        fond = im.convert("RGB")
    else:
        fond = Image.new("RGB", TAILLE, fond_c)
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    for limite in (9, 12, 15, 19, 24, 30, 40):  # 1 à 2 mots courts par ligne ; des lignes plus longues si le titre est long (7 lignes au plus)
        lignes, cur = [], ""
        for m in studio.insecables(x["titre"]).upper().split(" "):
            if cur and len(cur) + len(m) <= limite:
                cur += " " + m
            else:
                lignes += [cur] if cur else []
                cur = m
        lignes += [cur] if cur else []
        if len(lignes) <= 7:
            break
    L = w - 2 * 60
    dispo = x["bas"] - HAUT - 200
    par = max(60, min(int(300 * k * x["kt"]), int(dispo / (1.06 * max(1, len(lignes))))))
    cal, y, t = [], HAUT, 0.2
    motx = x["mot"].upper()
    for i, lg in enumerate(lignes):
        taille = par
        while taille > 56 and d0.textlength(lg, font=studio._police("Anton-Regular.ttf", taille)) > L:
            taille -= 6
        pol = studio._police("Anton-Regular.ttf", taille)
        im = Image.new("RGBA", (int(d0.textlength(lg, font=pol)) + 12, int(taille * 1.22)), (0, 0, 0, 0))
        col = acc if (motx and motx in lg) or (not motx and i == len(lignes) - 1) else encre
        ImageDraw.Draw(im).text((4, 0), lg, font=pol, fill=tuple(col) + (255,))
        cal.append(C(im, 60, y, t, "pop" if i % 2 == 0 else "gauche", 0.28))
        y += int(taille * 1.04)
        t += 0.24
    # Bandeau incliné où le texte défile
    ruban_c = acc if acc != encre else (_vif(pal) if _contraste(_vif(pal), fond_c) > 25 else encre)
    msg = (x["texte"] or x["titre"]).upper().replace("\n", " ") + "   •   "
    pol = studio._police("Bold", 46)
    lm = max(1, int(d0.textlength(msg, font=pol)))
    nb = (w * 2) // lm + 3
    ruban = Image.new("RGBA", (lm * nb, 96), tuple(ruban_c) + (255,))
    dr = ImageDraw.Draw(ruban)
    for j in range(nb):
        dr.text((j * lm, 16), msg, font=pol, fill=_sur(ruban_c) + (255,))
    yb = min(x["bas"] - 100, y + 110)

    def crochet(im, t_):
        if t_ < 0.5:
            return
        dec = int((t_ * 150) % lm)
        _colle(im, ruban.crop((dec, 0, dec + w + 260, 96)).rotate(-4, expand=True, resample=Image.BICUBIC), -120, yb - 60)
    return fond, cal, crochet, (HAUT, yb + 70)


def _f_publication(x, k):
    from PIL import ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    fond = _fond_flou(x, 60)
    acc, encre, gris = _vif(pal), (22, 20, 28), (120, 118, 130)
    L = w - 2 * 70
    n = len(x["titre"])
    titre, ht = _bloc(x["titre"], "Inter.ttf", L - 112, T(84 if n <= 60 else 70 if n <= 100 else 58), encre, 1.18, mot=x["mot"],
                      couleur_mot=acc if _contraste(acc, (255, 255, 255)) > 70 else None)
    txt, hx = _bloc(x["texte"], "Medium", L - 112, X(46), (58, 56, 68), 1.36) if x["texte"] else (None, 0)
    H = 56 + 110 + 44 + ht + (36 + hx if txt else 0) + 150
    carte, m = _carte((L, H), 54, (255, 255, 255, 255), ombre=80)
    d = ImageDraw.Draw(carte)
    nom = x["pseudo"] or "Moi"
    d.ellipse((m + 56, m + 56, m + 156, m + 156), fill=tuple(acc) + (255,))
    d.text((m + 106, m + 106), nom[0].upper(), font=studio._police("Bold", 52), anchor="mm", fill=_sur(acc) + (255,))
    d.text((m + 180, m + 62), nom, font=studio._police("Bold", 40), fill=encre + (255,))
    d.text((m + 180, m + 112), ("@" + nom + " · " if x["pseudo"] else "") + "à l'instant", font=studio._police("Regular", 30), fill=gris + (255,))
    carte.alpha_composite(titre, (m + 56, m + 210))
    if txt:
        carte.alpha_composite(txt, (m + 56, m + 210 + ht + 36))
    yb = m + H - 104
    d.line((m + 56, yb - 26, m + L - 56, yb - 26), fill=(232, 230, 238, 255), width=2)
    d.rounded_rectangle((m + 150, yb + 6, m + 206, yb + 50), radius=12, outline=gris + (255,), width=5)   # commentaire
    d.polygon([(m + 250, yb + 28), (m + 304, yb + 6), (m + 290, yb + 52)], outline=gris + (255,), width=5)  # partage
    y0 = HAUT + max(0, (x["bas"] - HAUT - H) // 2)
    rouge = acc if _contraste(acc, (255, 255, 255)) > 70 else (237, 73, 86)
    cal = [C(carte, 70 - m, y0 - m, 0.15, "pop", 0.5), C(_coeur(gris, False), 70 + 56, y0 - m + yb - 4, 0.6, "fixe", 0.1, fin=2.0),
           C(_coeur(rouge, True), 70 + 56, y0 - m + yb - 4, 2.0, "pop", 0.4)]
    return fond, cal, None, (y0, y0 + H)


def _f_bento(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    fond_c = _mix(pal["haut"], (0, 0, 0) if not _clair(pal["haut"]) else (255, 255, 255), 0.25)
    fond = Image.new("RGB", TAILLE, fond_c)
    acc, e = _vif(pal), 24
    L = w - 2 * 60
    haut, bas = HAUT, x["bas"]
    cal, t = [], 0.15
    items = x["lignes"][:3] if len(x["lignes"]) >= 2 else ([x["texte"]] if x["texte"] else [])
    h1 = int((bas - haut) * (0.42 if items or x["photo"] else 0.8))
    d0 = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    def tuile(taille, couleur, texte, graisse, maxi, mini, mot=""):
        c, _ = _carte(taille, 52, tuple(couleur) + (255,))
        if texte:  # la plus grande taille pour laquelle le texte tient dans la tuile
            _, _, _, t_ = studio._ajuste(d0, studio.insecables(texte), graisse, taille[0] - 88, taille[1] - 72, maxi, mini, 1.14)
            bl, hb = _bloc(texte, graisse, taille[0] - 88, t_, _sur(couleur), 1.14, mot=mot, couleur_mot=acc if _contraste(acc, couleur) > 60 else None)
            c.alpha_composite(bl, (44, max(26, (taille[1] - hb) // 2 - int(t_ * 0.1))))
        return c
    c1 = acc if _contraste(acc, fond_c) > 40 else tuple(pal["bas"]) if _contraste(pal["bas"], fond_c) > 25 else _sur(fond_c)
    cal.append(C(tuile((L, h1), c1, x["titre"], "Sora.ttf", T(150), 44, x["mot"]), 60, haut, t, "pop", 0.4))
    t += 0.3
    y = haut + h1 + e
    reste = bas - y
    autres = [tuple(pal["bas"]) if c1 != tuple(pal["bas"]) else _mix(pal["bas"], pal["haut"], 0.5), _mix(pal["haut"], pal["accent"], 0.35),
              (255, 255, 255) if not _clair(fond_c) else (30, 26, 36)]
    if x["photo"] and reste > 200 and not (len(items) >= 3 and reste < 620):
        lp = (L - e) // 2 if items else L
        cal.append(C(_photo_arrondie(x["photo"], (lp, reste), 52), 60, y, t, "pop", 0.4))
        t += 0.3
        if items:
            hi = (reste - e * (len(items) - 1)) // len(items)
            for i, it in enumerate(items):
                cal.append(C(tuile((lp, hi), autres[i % 3], it, "Medium", X(46), 26), 60 + lp + e, y + i * (hi + e), t, "pop", 0.4))
                t += 0.3
    elif items and reste > 160:
        if len(items) == 1:
            cal.append(C(tuile((L, reste), autres[0], items[0], "Medium", X(54), 30), 60, y, t, "pop", 0.4))
        else:
            la = (L - e) // 2
            hi = reste if len(items) == 2 else (reste - e) // 2
            for i, it in enumerate(items[:2]):
                cal.append(C(tuile((la, hi), autres[i], it, "Medium", X(48), 26), 60 + i * (la + e), y, t, "pop", 0.4))
                t += 0.3
            if len(items) == 3:
                cal.append(C(tuile((L, hi), autres[2], items[2], "Medium", X(50), 28), 60, y + hi + e, t, "pop", 0.4))
    return fond, cal, None, (haut, bas)


def _f_soustitres(x, k):  # noqa: C901
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    milieu = _mix(pal["haut"], pal["bas"], 0.5)
    if x["photo"]:
        fond, encre, contour, sous = _fond_photo(x, 70, 0.25, 200), (255, 255, 255), (0, 0, 0), (240, 238, 244)
    else:
        fond, contour = _degrade(pal["haut"], pal["bas"]), None
        encre = tuple(pal["titre"]) if _contraste(pal["titre"], milieu) > 90 else _sur(milieu)
        sous = tuple(pal["texte"]) if _contraste(pal["texte"], milieu) > 70 else encre
    vif = _vif(pal)
    if not x["photo"] and _contraste(vif, milieu) < 55:
        vif = encre
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    L = w - 2 * 80
    titre = studio.insecables(x["titre"]).upper()
    n = len(titre)
    taille = T(128 if n <= 36 else 108 if n <= 70 else 88)
    pol = studio._police("Montserrat-ExtraBold.ttf", taille)
    lignes = _coupe(d, titre, pol, L)
    pas = int(taille * 1.26)
    _, t_h, _, b_h = d.textbbox((0, 0), "H", font=pol)
    padx, pad_b, pad_h = int(taille * 0.16), int(taille * 0.14), int(taille * 0.28)  # place au-dessus pour les accents des capitales
    ep = max(4, taille // 13) if contour else 0
    txt, hx = _bloc(x["texte"], "Medium", L, X(44), sous, 1.34, centre=True, ombre=bool(x["photo"])) if x["texte"] else (None, 0)
    total = pas * len(lignes) + (40 + hx if txt else 0)
    y0 = int(HAUT + 60 + max(0, x["bas"] - HAUT - 60 - total) * 0.55)
    mots = []  # (mot, x, y, calque simple, calque surligné)
    for i, lg in enumerate(lignes):
        lx = (w - d.textlength(lg, font=pol)) / 2
        idx = 0
        for mot in lg.split(" "):
            if mot:
                ww = int(d.textlength(mot, font=pol))
                Wi, Hi = ww + 2 * padx, (b_h - t_h) + pad_h + pad_b
                simple = Image.new("RGBA", (Wi, Hi), (0, 0, 0, 0))
                ImageDraw.Draw(simple).text((padx, pad_h - t_h), mot, font=pol, fill=tuple(encre) + (255,), stroke_width=ep,
                                            stroke_fill=tuple(contour) + (255,) if contour else None)
                fort = Image.new("RGBA", (Wi, Hi), (0, 0, 0, 0))
                df = ImageDraw.Draw(fort)
                df.rounded_rectangle((0, pad_h - pad_b, Wi - 1, Hi - 1), radius=max(10, taille // 6), fill=tuple(vif) + (255,))
                df.text((padx, pad_h - t_h), mot, font=pol, fill=_sur(vif) + (255,))
                mots.append((mot, int(lx + d.textlength(lg[:idx], font=pol)) - padx, y0 + i * pas + t_h - pad_h, simple, fort))
            idx += len(mot) + 1
    net = [re.sub(r"[^\w]", "", m[0]).lower() for m in mots]
    cible = [c for c in (re.sub(r"[^\w]", "", m).lower() for m in x["mot"].split()) if c]
    forts = set()
    for j in range(len(net) - len(cible) + 1) if cible else []:
        if net[j:j + len(cible)] == cible:
            forts = set(range(j, j + len(cible)))
            break
    forts = forts or ({len(mots) - 1} if mots else set())
    pas_t = 0.26
    fin = 0.35 + pas_t * max(0, len(mots) - 1) + 0.5  # tous les mots sont passés : le surlignage revient sur le mot fort
    cal = []
    for i, (_, mx, my, simple, fort) in enumerate(mots):
        ti = 0.35 + pas_t * i
        suivant = ti + pas_t if i < len(mots) - 1 else fin
        cal.append(C(fort, mx, my, ti, "pop", 0.16, fin=suivant))                       # le mot arrive surligné…
        cal.append(C(simple, mx, my, suivant, "fixe", fin=fin if i in forts else None))  # … puis le surlignage passe au suivant
        if i in forts:
            cal.append(C(fort, mx, my, fin, "pop", 0.22))
    y = y0 + pas * len(lignes)
    if txt:
        cal.append(C(txt, (w - txt.size[0]) // 2, y + 40, fin + 0.2, "fondu", 0.5))
        y += 40 + hx
    return fond, cal, None, (y0 + t_h - pad_h, y)


def _f_autocollants(x, k):
    from PIL import Image, ImageDraw
    pal, w = x["pal"], TAILLE[0]
    T, X = _echelles(x, k)
    fond = _fond_photo(x, 60, 0.6, 120) if x["photo"] else _fond_flou(x, 0)
    vif, sombre, blanc = _vif(pal), (28, 22, 34), (255, 255, 255)
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    n = len(x["titre"])
    taille = T(118 if n <= 30 else 96 if n <= 60 else 78)
    pol = studio._police("TitanOne.ttf", taille)
    lignes = _coupe(d, studio.insecables(x["titre"]), pol, 800)
    mot = x["mot"].lower()
    cycle = [blanc, sombre] if mot and any(mot in lg.lower() for lg in lignes) else [vif, blanc, sombre]
    angles, decal = (-3.0, 2.2, -1.6, 2.8, -2.2, 1.4), (-26, 30, -8, 24, -18, 10)
    cal, y, t, j = [], HAUT + 80, 0.2, 0
    coins, etiquettes = [], []
    for i, lg in enumerate(lignes):
        if mot and mot in lg.lower():
            c = vif
        else:
            c = cycle[j % len(cycle)]
            j += 1
        Lb, Hb = int(d.textlength(lg, font=pol)) + int(taille * 0.7) + 20, int(taille * 1.42) + 20
        carte, m = _carte((Lb, Hb), 36, blanc + (255,), ombre=75)  # liseré blanc, comme un autocollant découpé
        dc = ImageDraw.Draw(carte)
        dc.rounded_rectangle((m + 10, m + 10, m + Lb - 11, m + Hb - 11), radius=27, fill=tuple(c) + (255,))
        dc.text((m + Lb / 2, m + Hb / 2), lg, font=pol, anchor="mm", fill=_sur(c) + (255,))
        etiquettes.append((carte.rotate(angles[i % 6], expand=True, resample=Image.BICUBIC), Lb, Hb, Lb / 2 * math.sin(math.radians(abs(angles[i % 6])))))
    for i, (rot, Lb, Hb, bout) in enumerate(etiquettes):
        cx = w // 2 + decal[i % 6]
        cx = max(Lb // 2 + 24, min(w - Lb // 2 - 24, cx))
        cal.append(C(rot, cx - rot.size[0] // 2, y + Hb // 2 - rot.size[1] // 2, t, "pop", 0.3))
        coins.append((cx - Lb // 2, cx + Lb // 2, y, y + Hb))
        suivant = etiquettes[i + 1][3] if i + 1 < len(etiquettes) else 0
        y += Hb - 8 + max(0, int(bout + suivant) - 22)  # les bouts d'étiquettes larges ne se recouvrent pas
        t += 0.24
    if x["texte"]:
        bl, hb = _bloc(x["texte"], "Medium", 760, X(42), sombre, 1.3, centre=True)
        carte, m = _carte((840, hb + 60), 32, blanc + (255,), ombre=60)
        carte.alpha_composite(bl, (m + 40, m + 26))
        rot = carte.rotate(1.2, expand=True, resample=Image.BICUBIC)
        y += 34
        cal.append(C(rot, (w - rot.size[0]) // 2, y + (hb + 60) // 2 - rot.size[1] // 2, t + 0.15, "pop", 0.35))
        y += hb + 60
        t += 0.4
    if coins:  # deux étincelles collées aux coins du titre
        _, d0, h0, _ = coins[0]
        g1, _, _, b1 = coins[-1]
        e1, e2 = _eclat(int(56 * k), vif if _contraste(vif, blanc) > 30 else sombre), _eclat(int(34 * k), blanc, sombre)
        cal.append(C(e1, min(w - e1.size[0] - 10, d0 - e1.size[0] // 2), h0 - e1.size[1] // 2 - 6, t + 0.1, "pop", 0.3))
        cal.append(C(e2, max(10, g1 - e2.size[0] // 2), b1 - e2.size[1] // 2, t + 0.3, "pop", 0.3))
    return fond, cal, None, (HAUT, y)


_RENDUS = {"note": _f_note, "magazine": _f_magazine, "scrapbook": _f_scrapbook, "conversation": _f_conversation, "verre": _f_verre,
           "affiche": _f_affiche, "publication": _f_publication, "bento": _f_bento, "soustitres": _f_soustitres,
           "autocollants": _f_autocollants}


def _compose(fmt: str, x: dict):
    """La mise en page à la plus grande taille pour laquelle tout tient entre la barre d'Instagram et le bas (ou le sticker)."""
    for k in (1.0, 0.88, 0.78, 0.69, 0.61, 0.54):
        fond, cal, crochet, (y0, y1) = _RENDUS[fmt](x, k)
        if y0 >= HAUT - 14 and y1 <= x["bas"] + 10:
            break
    return fond, cal, crochet


def images(fmt: str, p: dict, s: dict, image, pal: dict, duree_s: float, reg: dict | None = None, numero: int = 1, seulement: set | None = None):
    """Générateur des images (PIL RGB) d'une story dans le format demandé."""
    from PIL import Image, ImageDraw
    reg = reg or {}
    w, h = TAILLE
    vitesse = {"lente": 1.6, "rapide": 0.6}.get(reg.get("vitesse"), 1.0)
    x = {"titre": studio.propre(s.get("titre") or "") or " ", "texte": studio.propre(s.get("texte") or ""), "lignes": _lignes_texte(s),
         "mot": studio.propre(s.get("mot") or "").strip(), "photo": image if image and Path(image).is_file() else None,
         "pseudo": (p.get("pseudo") or "").lstrip("@"), "bas": 1190 if s.get("sticker") else 1640, "pal": pal, "numero": max(1, numero),
         "kt": float(reg.get("taille_titre") or 1.0), "kx": float(reg.get("taille_texte") or 1.0), "_cache": {}}
    fond, calques, crochet = _compose(fmt, x)
    zoom = isinstance(fond, tuple)
    fixe = None if zoom else fond.convert("RGBA")
    signe = None
    if reg.get("signature") and x["pseudo"] and fmt in ("note", "affiche", "bento", "soustitres", "autocollants"):
        signe = Image.new("RGBA", (w, 60), (0, 0, 0, 0))
        ImageDraw.Draw(signe).text((w / 2, 30), "@" + x["pseudo"], font=studio._police("Medium", 36), anchor="mm", fill=(255, 255, 255, 235),
                                   stroke_width=2, stroke_fill=(0, 0, 0, 150))
    for k in range(int(duree_s * FPS)):
        if seulement is not None and k not in seulement:
            continue
        t = k / FPS
        if zoom:  # zoom lent sur la photo ou le fond flou
            f = fond[1]
            z = 1.0 + 0.10 * (t / duree_s)
            W, H = f.size
            cw, ch = int(W / 1.12 / z), int(H / 1.12 / z)
            cx, cy = (W - cw) // 2, (H - ch) // 2
            im = f.crop((cx, cy, cx + cw, cy + ch)).resize(TAILLE, Image.BILINEAR).convert("RGBA")
        else:
            im = fixe.copy()
        ta = t / vitesse
        for c in calques:
            _pose(im, c, ta)
        if crochet:
            crochet(im, ta)
        if signe:
            im.alpha_composite(signe, (0, h - 170))
        if t > duree_s - 0.25:  # fondu de sortie
            im.alpha_composite(Image.new("RGBA", TAILLE, (0, 0, 0, int(255 * (t - (duree_s - 0.25)) / 0.25 * 0.6))))
        yield im.convert("RGB")
