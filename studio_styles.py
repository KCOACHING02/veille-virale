"""
Styles de carrousel du studio : fonds texturés (papier, kraft, lin, carnet…), couleurs, typographies associées
et éléments décoratifs (numéro « (01) », surtitre, note manuscrite entourée, post-it, flèche…).
Tout est dessiné avec Pillow et numpy : aucune image externe.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

# ------------------------------------------------------------
#  Fonds texturés
# ------------------------------------------------------------
TEXTURES = {"uni": "Uni", "papier": "Papier", "kraft": "Kraft", "lin": "Lin", "grain": "Grain", "beton": "Béton", "carnet": "Carnet ligné",
            "quadrille": "Quadrillé", "pointille": "Pointillé", "degrade": "Dégradé", "aurore": "Aurore", "ardoise": "Ardoise"}


def _bruit(h: int, w: int, echelle: int, graine: int):
    """Bruit lissé (valeurs autour de 0, écart-type ~1) : agrandissement d'un bruit grossier."""
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(graine)
    petit = rng.standard_normal((max(2, h // echelle), max(2, w // echelle))).astype("float32")
    im = Image.fromarray(petit, mode="F").resize((w, h), Image.BICUBIC)
    a = np.asarray(im)
    return (a - a.mean()) / (a.std() + 1e-6)


@lru_cache(maxsize=48)
def _texture(nom: str, c1: tuple, c2: tuple, taille: tuple):
    import numpy as np
    from PIL import Image, ImageFilter
    w, h = taille
    base = np.empty((h, w, 3), dtype="float32")
    base[:] = c1
    rng = np.random.default_rng(7)
    if nom in ("papier", "kraft", "beton", "ardoise"):
        fort = {"papier": 5.0, "kraft": 9.0, "beton": 12.0, "ardoise": 7.0}[nom]
        nuages = _bruit(h, w, 160, 1) * fort + _bruit(h, w, 40, 2) * fort * 0.5
        base += nuages[..., None]
        fibres = rng.standard_normal((h, w)).astype("float32")
        fibres = (fibres + np.roll(fibres, 1, 0) + np.roll(fibres, 1, 1)) / 1.7
        base += (fibres * {"papier": 6.0, "kraft": 10.0, "beton": 9.0, "ardoise": 6.0}[nom])[..., None]
        if nom == "kraft":  # fibres allongées
            trait = np.asarray(Image.fromarray(rng.standard_normal((h, w // 6)).astype("float32"), mode="F").resize((w, h), Image.BILINEAR))
            base += (trait * 5)[..., None]
        if nom == "beton":  # petits trous
            trous = rng.random((h, w)) > 0.9985
            base[trous] -= 45
    elif nom == "lin":
        lignes_h = np.asarray(Image.fromarray(rng.standard_normal((h, 1)).astype("float32"), mode="F").resize((w, h)))
        lignes_v = np.asarray(Image.fromarray(rng.standard_normal((1, w)).astype("float32"), mode="F").resize((w, h)))
        base += ((lignes_h + lignes_v) * 5 + rng.standard_normal((h, w)) * 3)[..., None]
    elif nom in ("degrade", "aurore"):
        yy, xx = np.mgrid[0:h, 0:w].astype("float32")
        if nom == "degrade":
            t = (yy / h * 0.8 + xx / w * 0.2)[..., None]
            base = np.asarray(c1, "float32") * (1 - t) + np.asarray(c2, "float32") * t
        else:  # taches de couleur floues
            c3 = tuple(min(255, int(v * 0.5 + 255 * 0.5)) for v in c2)
            for (cx, cy, r, c) in ((0.15, 0.2, 0.75, c2), (0.9, 0.75, 0.8, c3), (0.7, 0.05, 0.5, c2)):
                d = np.sqrt((xx / w - cx) ** 2 + (yy / h - cy) ** 2) / r
                a = np.clip(1 - d, 0, 1)[..., None] ** 1.6
                base = base * (1 - a) + np.asarray(c, "float32") * a
        base += rng.standard_normal((h, w, 1)).astype("float32") * 5
    elif nom == "grain":
        base += rng.standard_normal((h, w, 1)).astype("float32") * 7
    if nom in ("carnet", "quadrille", "pointille"):
        base += (_bruit(h, w, 160, 3) * 3 + rng.standard_normal((h, w)) * 4)[..., None]
    im = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "RGB")
    if nom in ("carnet", "quadrille", "pointille"):
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        pas = int(w * 0.055)
        trait = tuple(int(a * 0.82 + b * 0.18) for a, b in zip(c1, c2))
        if nom == "carnet":
            for y in range(int(h * 0.12), h, pas):
                d.line([(0, y), (w, y)], fill=trait, width=2)
            d.line([(int(w * 0.07), 0), (int(w * 0.07), h)], fill=(226, 120, 120), width=3)
        elif nom == "quadrille":
            for y in range(0, h, pas // 2):
                d.line([(0, y), (w, y)], fill=trait, width=1)
            for x in range(0, w, pas // 2):
                d.line([(x, 0), (x, h)], fill=trait, width=1)
        else:
            for y in range(pas // 2, h, pas):
                for x in range(pas // 2, w, pas):
                    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=trait)
    if nom == "ardoise":  # légères traces de craie
        voile = Image.new("L", (w, h), 0)
        from PIL import ImageDraw
        dv = ImageDraw.Draw(voile)
        r = random.Random(3)
        for _ in range(14):
            x, y = r.randint(0, w), r.randint(0, h)
            dv.arc([x - 300, y - 120, x + 300, y + 120], r.randint(0, 180), r.randint(200, 360), fill=26, width=60)
        voile = voile.filter(ImageFilter.GaussianBlur(28))
        im = Image.composite(Image.new("RGB", (w, h), (235, 235, 235)), im, voile)
    return im


def fond(nom: str, c1: tuple, c2: tuple, taille: tuple):
    """Fond texturé au format demandé (RGBA, copie modifiable)."""
    from PIL import Image
    if nom not in TEXTURES or nom == "uni":
        return Image.new("RGBA", taille, tuple(c1) + (255,))
    return _texture(nom, tuple(c1), tuple(c2), tuple(taille)).convert("RGBA")


# ------------------------------------------------------------
#  Styles de carrousel
# ------------------------------------------------------------
def _h(x: str) -> tuple:
    return tuple(int(x[i:i + 2], 16) for i in (1, 3, 5))


# fond, fond2 (motif/dégradé), titre, texte, accent, typo du titre, police du texte (id de typo ou fichier), décor
MODELES = {
    "papier_edito": dict(k_titre=1.3, nom="Papier éditorial", texture="papier", fond="#EEEAE2", fond2="#C9C2B4", titre="#141414", texte="#1C1C1C", accent="#141414",
                         typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.045, numero="({:02d})", barre=False, note="cercle", note_police="feutre",
                         surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "ciel_script": dict(k_titre=1.1, nom="Nuit & script", texture="aurore", fond="#1B2433", fond2="#3E4A63", titre="#F4EEDC", texte="#F4EEDC", accent="#F4EEDC",
                        typo="neutre", texte_police="feutre", k_texte=1.25, serre=-0.04, numero=None, barre=False, note="souligne", note_police="feutre",
                        surtitre="grand", position="centre", alignement="centre", compteur=False, photo_titre="#F4EEDC", photo_texte="#F4EEDC"),
    "kraft": dict(nom="Kraft", texture="kraft", fond="#C49A6C", fond2="#8A6A45", titre="#1E1712", texte="#2B2118", accent="#B3261E",
                  typo="gros_titre", texte_police="Poppins-Medium.ttf", numero="N°{}", barre=False, note="postit", note_police="marqueur",
                  surtitre="etiquette", position="centre", alignement="gauche", compteur=False),
    "carnet": dict(nom="Carnet ligné", texture="carnet", fond="#FBFAF4", fond2="#9DB6D9", titre="#1F3A93", texte="#24324F", accent="#D64545",
                   typo="carnet", texte_police="carnet", k_texte=1.1, numero="{}.", barre=False, note="cercle", note_police="carnet",
                   surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "bullet": dict(nom="Bullet journal", texture="pointille", fond="#F7F4EE", fond2="#B9B2A5", titre="#2E3B32", texte="#3B463F", accent="#7C9A82",
                   typo="editorial", texte_police="DMSansTexte.ttf", serre=-0.02, numero="{:02d}.", barre=False, note="fleche", note_police="journal_intime",
                   surtitre="etiquette", position="haut", alignement="gauche", compteur=False),
    "quadrille": dict(nom="Cahier quadrillé", texture="quadrille", fond="#FDFDFB", fond2="#9FC3E0", titre="#111111", texte="#222222", accent="#FFD43B",
                      typo="marqueur", texte_police="Poppins-Regular.ttf", numero="#{}", barre=False, note="postit", note_police="journal_intime",
                      surtitre="petit", position="centre", alignement="gauche", compteur=False, surligne=True),
    "beton": dict(nom="Béton brut", texture="beton", fond="#C9C7C2", fond2="#8E8B85", titre="#121212", texte="#1E1E1E", accent="#E8471C",
                  typo="brut", texte_police="Poppins-Medium.ttf", serre=-0.03, numero="N°{:02d}", barre=True, note="fleche", note_police="marqueur",
                  surtitre="etiquette", position="bas", alignement="gauche", compteur=False),
    "lin": dict(nom="Lin naturel", texture="lin", fond="#E6DCCB", fond2="#B8A88E", titre="#3E2C1F", texte="#4E3B2D", accent="#9C6B43",
                typo="luxe", texte_police="LoraTexte.ttf", numero="— {} —", barre=False, note="souligne", note_police="lettre",
                surtitre="petit", position="centre", alignement="centre", compteur=False),
    "nuit_grain": dict(k_titre=1.2, nom="Nuit granuleuse", texture="grain", fond="#141218", fond2="#141218", titre="#FFFFFF", texte="#CFC8D8", accent="#FF4F79",
                       typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.045, numero="{:02d}", barre=False, note="cercle", note_police="feutre",
                       surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "aurore": dict(nom="Aurore pastel", texture="aurore", fond="#F6E6EE", fond2="#C9B6F2", titre="#3B1F4A", texte="#4E3560", accent="#E2557E",
                   typo="epure", texte_police="NunitoTexte.ttf", serre=-0.02, numero=None, barre=False, note="cercle", note_police="danse",
                   surtitre="etiquette", position="centre", alignement="centre", compteur=True),
    "sable": dict(nom="Sable & sérif", texture="grain", fond="#E9DFD1", fond2="#E9DFD1", titre="#2A211B", texte="#3C3129", accent="#A05A3B",
                  typo="magazine", texte_police="LoraTexte.ttf", k_titre=1.12, numero="({:02d})", barre=False, note="souligne", note_police="satin",
                  surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "minimal": dict(k_titre=1.3, nom="Blanc minimal", texture="grain", fond="#FAFAF7", fond2="#FAFAF7", titre="#0E0E0E", texte="#2A2A2A", accent="#0E0E0E",
                    typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.05, numero="{:02d}", barre=False, note=None, note_police="feutre",
                    surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "pop": dict(nom="Pop jaune", texture="uni", fond="#FFE14D", fond2="#FFE14D", titre="#111111", texte="#1A1A1A", accent="#FF4F79",
                typo="massif", texte_police="Poppins-Medium.ttf", numero="{}/", barre=False, note="postit", note_police="marqueur",
                surtitre="etiquette", position="centre", alignement="gauche", compteur=False),
    "sauge": dict(nom="Sauge douce", texture="papier", fond="#DDE3D3", fond2="#A9B59A", titre="#24382B", texte="#33473A", accent="#6F8F6B",
                  typo="doux_retro", texte_police="NunitoTexte.ttf", numero="({:02d})", barre=False, note="cercle", note_police="danse",
                  surtitre="petit", position="centre", alignement="gauche", compteur=False),
    "poudre": dict(nom="Rose poudré", texture="papier", fond="#F4E1DE", fond2="#D9B8B3", titre="#6B1F2E", texte="#5A2A33", accent="#B4475C",
                   typo="italique", texte_police="LoraTexte.ttf", numero=None, barre=False, note="cercle", note_police="calligraphie",
                   surtitre="petit", position="centre", alignement="centre", compteur=True),
    "noir_or": dict(nom="Noir & or", texture="grain", fond="#101010", fond2="#101010", titre="#D8B46A", texte="#E9E1CF", accent="#D8B46A",
                    typo="mode", texte_police="LoraTexte.ttf", numero="N°{}", barre=False, note="souligne", note_police="calligraphie",
                    surtitre="petit", position="centre", alignement="centre", compteur=False, photo_titre="#E9CF94"),
    "terracotta": dict(nom="Terracotta", texture="grain", fond="#C4623A", fond2="#C4623A", titre="#FFF4E6", texte="#FBE3CF", accent="#2B1A12",
                       typo="gros_titre", texte_police="Poppins-Regular.ttf", numero="{:02d}", barre=False, note="cercle", note_police="feutre",
                       surtitre="grand", position="centre", alignement="gauche", compteur=False),
    "ardoise": dict(nom="Tableau noir", texture="ardoise", fond="#26302E", fond2="#26302E", titre="#F5F3EA", texte="#E6E4DA", accent="#F2D16B",
                    typo="craie", texte_police="craie", k_texte=1.35, numero="{}.", barre=False, note="fleche", note_police="craie",
                    surtitre="petit", position="centre", alignement="centre", compteur=False),
}
for _m in MODELES.values():
    for _k in ("fond", "fond2", "titre", "texte", "accent", "photo_titre", "photo_texte"):
        if _m.get(_k):
            _m[_k] = _h(_m[_k])


def lisible_sur(c: tuple) -> tuple:
    """Couleur de texte lisible sur un fond donné (noir doux ou blanc)."""
    lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    return (20, 20, 20) if lum > 150 else (255, 255, 255)


# ------------------------------------------------------------
#  Éléments décoratifs
# ------------------------------------------------------------
def _gribouille_ellipse(d, boite, couleur, epaisseur, graine=1, tours=2):
    """Ellipse tracée à la main : deux passages légèrement décalés qui ne se referment pas parfaitement."""
    r = random.Random(graine)
    x0, y0, x1, y1 = boite
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    for t in range(tours):
        depart = r.uniform(-0.6, 0.2)
        fin = depart + 2 * math.pi * r.uniform(1.04, 1.12)
        dx, dy, k = r.uniform(-6, 6), r.uniform(-4, 4), r.uniform(0.96, 1.05)
        pts = []
        n = 90
        for j in range(n + 1):
            a = depart + (fin - depart) * j / n
            pts.append((cx + dx + rx * k * math.cos(a), cy + dy + ry * (2 - k) * math.sin(a)))
        d.line(pts, fill=couleur, width=epaisseur, joint="curve")


def note(texte: str, style: str, police, couleur: tuple, accent: tuple, fond: tuple, largeur_max: int):
    """Calque RGBA d'une note manuscrite (entourée, post-it, flèche ou soulignée), déjà inclinée."""
    from PIL import Image, ImageDraw
    mesure = ImageDraw.Draw(Image.new("L", (1, 1)))
    mots, lignes, ligne = texte.split(), [], ""
    for m in mots:
        essai = (ligne + " " + m).strip()
        if mesure.textlength(essai, font=police) > largeur_max and ligne:
            lignes.append(ligne)
            ligne = m
        else:
            ligne = essai
    if ligne:
        lignes.append(ligne)
    t = police.size
    hl = int(t * 1.15)
    lt = int(max(mesure.textlength(x, font=police) for x in lignes))
    ht = hl * len(lignes)
    pad = {"cercle": (int(t * 1.3), int(t * 1.0)), "postit": (int(t * 0.8), int(t * 0.8)), "fleche": (int(t * 0.4), int(t * 0.4)),
           "souligne": (int(t * 0.3), int(t * 0.6))}.get(style, (20, 20))
    marge_fleche = int(t * 2.6) if style == "fleche" else 0
    W, H = lt + 2 * pad[0] + marge_fleche, ht + 2 * pad[1]
    calque = Image.new("RGBA", (W + 40, H + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    ox, oy = 20 + marge_fleche, 20
    if style == "postit":
        papier = accent if sum(accent) > 300 else (255, 233, 120)
        ombre = Image.new("RGBA", calque.size, (0, 0, 0, 0))
        ImageDraw.Draw(ombre).rectangle([ox + 6, oy + 10, ox + W - marge_fleche + 6, oy + H + 10], fill=(0, 0, 0, 45))
        from PIL import ImageFilter
        calque.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(8)))
        d.rectangle([ox, oy, ox + W - marge_fleche, oy + H], fill=papier + (255,))
        couleur = lisible_sur(papier)
    for k, x in enumerate(lignes):
        lx = ox + pad[0] + (lt - mesure.textlength(x, font=police)) / 2
        d.text((lx, oy + pad[1] + k * hl), x, font=police, fill=couleur)
    ep = max(3, int(t * 0.07))
    if style == "cercle":
        _gribouille_ellipse(d, (ox + 4, oy + 4, ox + W - marge_fleche - 4, oy + H - 4), couleur, ep, graine=len(texte))
    elif style == "souligne":
        y = oy + pad[1] + ht + int(t * 0.15)
        pts = [(ox + pad[0] + j * 6, y + math.sin(j * 0.55) * t * 0.08) for j in range(int(lt / 6) + 1)]
        d.line(pts, fill=accent, width=ep, joint="curve")
    elif style == "fleche":  # flèche courbe dessinée à gauche, qui pointe vers le texte
        x0, y0 = 22, oy + H * 0.15
        x1, y1 = ox + pad[0] - 10, oy + H * 0.55
        pts = [(x0 + (x1 - x0) * s, y0 + (y1 - y0) * s - math.sin(math.pi * s) * t * 0.9) for s in [j / 30 for j in range(31)]]
        d.line(pts, fill=couleur, width=ep, joint="curve")
        ang = math.atan2(pts[-1][1] - pts[-4][1], pts[-1][0] - pts[-4][0])
        for da in (2.5, -2.5):
            d.line([pts[-1], (pts[-1][0] - t * 0.45 * math.cos(ang + da / 3.2), pts[-1][1] - t * 0.45 * math.sin(ang + da / 3.2))], fill=couleur, width=ep)
    return calque.rotate({"cercle": 8, "postit": -4, "fleche": 4, "souligne": 3}.get(style, 0), resample=Image.BICUBIC, expand=True)
