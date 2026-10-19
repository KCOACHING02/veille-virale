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


@lru_cache(maxsize=6)  # ~4 Mo par fond : peu en mémoire
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
    "papier_edito": dict(couleur="blanc", k_titre=1.3, nom="Papier éditorial", texture="papier", fond="#EEEAE2", fond2="#C9C2B4", titre="#141414", texte="#1C1C1C", accent="#141414",
                         typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.045, numero="({:02d})", barre=False, note="cercle", note_police="feutre",
                         surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "ciel_script": dict(couleur="bleu", k_titre=1.1, nom="Nuit & script", texture="aurore", fond="#1B2433", fond2="#3E4A63", titre="#F4EEDC", texte="#F4EEDC", accent="#F4EEDC",
                        typo="neutre", texte_police="feutre", k_texte=1.25, serre=-0.04, numero=None, barre=False, note="souligne", note_police="feutre",
                        surtitre="grand", position="centre", alignement="centre", compteur=False, photo_titre="#F4EEDC", photo_texte="#F4EEDC"),
    "kraft": dict(couleur="beige", nom="Kraft", texture="kraft", fond="#C49A6C", fond2="#8A6A45", titre="#1E1712", texte="#2B2118", accent="#B3261E",
                  typo="gros_titre", texte_police="Poppins-Medium.ttf", numero="N°{}", barre=False, note="postit", note_police="marqueur",
                  surtitre="etiquette", position="centre", alignement="gauche", compteur=False),
    "carnet": dict(couleur="blanc", nom="Carnet ligné", texture="carnet", fond="#FBFAF4", fond2="#9DB6D9", titre="#1F3A93", texte="#24324F", accent="#D64545",
                   typo="carnet", texte_police="carnet", k_texte=1.1, numero="{}.", barre=False, note="cercle", note_police="carnet",
                   surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "bullet": dict(couleur="blanc", nom="Bullet journal", texture="pointille", fond="#F7F4EE", fond2="#B9B2A5", titre="#2E3B32", texte="#3B463F", accent="#7C9A82",
                   typo="editorial", texte_police="DMSansTexte.ttf", serre=-0.02, numero="{:02d}.", barre=False, note="fleche", note_police="journal_intime",
                   surtitre="etiquette", position="haut", alignement="gauche", compteur=False),
    "quadrille": dict(couleur="blanc", nom="Cahier quadrillé", texture="quadrille", fond="#FDFDFB", fond2="#9FC3E0", titre="#111111", texte="#222222", accent="#FFD43B",
                      typo="marqueur", texte_police="Poppins-Regular.ttf", numero="#{}", barre=False, note="postit", note_police="journal_intime",
                      surtitre="petit", position="centre", alignement="gauche", compteur=False, surligne=True),
    "beton": dict(couleur="gris", nom="Béton brut", texture="beton", fond="#C9C7C2", fond2="#8E8B85", titre="#121212", texte="#1E1E1E", accent="#E8471C",
                  typo="brut", texte_police="Poppins-Medium.ttf", serre=-0.03, numero="N°{:02d}", barre=True, note="fleche", note_police="marqueur",
                  surtitre="etiquette", position="bas", alignement="gauche", compteur=False),
    "lin": dict(couleur="beige", nom="Lin naturel", texture="lin", fond="#E6DCCB", fond2="#B8A88E", titre="#3E2C1F", texte="#4E3B2D", accent="#9C6B43",
                typo="luxe", texte_police="LoraTexte.ttf", numero="— {} —", barre=False, note="souligne", note_police="lettre",
                surtitre="petit", position="centre", alignement="centre", compteur=False),
    "nuit_grain": dict(couleur="noir", k_titre=1.2, nom="Nuit granuleuse", texture="grain", fond="#141218", fond2="#141218", titre="#FFFFFF", texte="#CFC8D8", accent="#FF4F79",
                       typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.045, numero="{:02d}", barre=False, note="cercle", note_police="feutre",
                       surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "aurore": dict(couleur="violet", nom="Aurore pastel", texture="aurore", fond="#F6E6EE", fond2="#C9B6F2", titre="#3B1F4A", texte="#4E3560", accent="#E2557E",
                   typo="epure", texte_police="NunitoTexte.ttf", serre=-0.02, numero=None, barre=False, note="cercle", note_police="danse",
                   surtitre="etiquette", position="centre", alignement="centre", compteur=True),
    "sable": dict(couleur="beige", nom="Sable & sérif", texture="grain", fond="#E9DFD1", fond2="#E9DFD1", titre="#2A211B", texte="#3C3129", accent="#A05A3B",
                  typo="magazine", texte_police="LoraTexte.ttf", k_titre=1.12, numero="({:02d})", barre=False, note="souligne", note_police="satin",
                  surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "minimal": dict(couleur="blanc", k_titre=1.3, nom="Blanc minimal", texture="grain", fond="#FAFAF7", fond2="#FAFAF7", titre="#0E0E0E", texte="#2A2A2A", accent="#0E0E0E",
                    typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.05, numero="{:02d}", barre=False, note=None, note_police="feutre",
                    surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "pop": dict(couleur="orange", nom="Pop jaune", texture="uni", fond="#FFE14D", fond2="#FFE14D", titre="#111111", texte="#1A1A1A", accent="#FF4F79",
                typo="massif", texte_police="Poppins-Medium.ttf", numero="{}/", barre=False, note="postit", note_police="marqueur",
                surtitre="etiquette", position="centre", alignement="gauche", compteur=False),
    "sauge": dict(couleur="vert", nom="Sauge douce", texture="papier", fond="#DDE3D3", fond2="#A9B59A", titre="#24382B", texte="#33473A", accent="#6F8F6B",
                  typo="doux_retro", texte_police="NunitoTexte.ttf", numero="({:02d})", barre=False, note="cercle", note_police="danse",
                  surtitre="petit", position="centre", alignement="gauche", compteur=False),
    "poudre": dict(couleur="rose", nom="Rose poudré", texture="papier", fond="#F4E1DE", fond2="#D9B8B3", titre="#6B1F2E", texte="#5A2A33", accent="#B4475C",
                   typo="italique", texte_police="LoraTexte.ttf", numero=None, barre=False, note="cercle", note_police="calligraphie",
                   surtitre="petit", position="centre", alignement="centre", compteur=True),
    "noir_or": dict(couleur="noir", nom="Noir & or", texture="grain", fond="#101010", fond2="#101010", titre="#D8B46A", texte="#E9E1CF", accent="#D8B46A",
                    typo="mode", texte_police="LoraTexte.ttf", numero="N°{}", barre=False, note="souligne", note_police="calligraphie",
                    surtitre="petit", position="centre", alignement="centre", compteur=False, photo_titre="#E9CF94"),
    "terracotta": dict(couleur="rouge", nom="Terracotta", texture="grain", fond="#C4623A", fond2="#C4623A", titre="#FFF4E6", texte="#FBE3CF", accent="#2B1A12",
                       typo="gros_titre", texte_police="Poppins-Regular.ttf", numero="{:02d}", barre=False, note="cercle", note_police="feutre",
                       surtitre="grand", position="centre", alignement="gauche", compteur=False),
    "ardoise": dict(couleur="noir", nom="Tableau noir", texture="ardoise", fond="#26302E", fond2="#26302E", titre="#F5F3EA", texte="#E6E4DA", accent="#F2D16B",
                    typo="craie", texte_police="craie", k_texte=1.35, numero="{}.", barre=False, note="fleche", note_police="craie",
                    surtitre="petit", position="centre", alignement="centre", compteur=False),
}
# Familles de couleurs (ordre d'affichage) et gabarits de mise en page réutilisés par les palettes ci-dessous
FAMILLES = [("blanc", "Blanc & crème", "#F7F3EA"), ("beige", "Beige & sable", "#D9C3A5"), ("rose", "Rose", "#F3A6BC"),
            ("rouge", "Rouge & terracotta", "#C8452F"), ("orange", "Orange & jaune", "#F6A93B"), ("vert", "Vert", "#5E8C5A"),
            ("bleu", "Bleu", "#3D6FB6"), ("violet", "Violet & lilas", "#9C85E0"), ("gris", "Gris", "#9A9A96"), ("noir", "Noir", "#141414")]
GABARITS = {
    "edito": dict(typo="neutre", texte_police="DMSansTexte.ttf", serre=-0.045, k_titre=1.3, numero="({:02d})", barre=False, note="cercle",
                  note_police="feutre", surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "script": dict(typo="neutre", texte_police="feutre", k_texte=1.25, serre=-0.04, k_titre=1.1, numero=None, barre=False, note="souligne",
                   note_police="feutre", surtitre="grand", position="centre", alignement="centre", compteur=False),
    "luxe": dict(typo="luxe", texte_police="LoraTexte.ttf", numero="— {} —", barre=False, note="souligne", note_police="lettre",
                 surtitre="petit", position="centre", alignement="centre", compteur=False),
    "mode": dict(typo="mode", texte_police="LoraTexte.ttf", numero="N°{}", barre=False, note="souligne", note_police="calligraphie",
                 surtitre="petit", position="centre", alignement="centre", compteur=False),
    "italique": dict(typo="italique", texte_police="LoraTexte.ttf", numero=None, barre=False, note="cercle", note_police="calligraphie",
                     surtitre="petit", position="centre", alignement="centre", compteur=True),
    "carnet": dict(typo="carnet", texte_police="carnet", k_texte=1.1, numero="{}.", barre=False, note="cercle", note_police="carnet",
                   surtitre="petit", position="haut", alignement="gauche", compteur=False),
    "marqueur": dict(typo="marqueur", texte_police="Poppins-Regular.ttf", numero="#{}", barre=False, note="postit", note_police="journal_intime",
                     surtitre="petit", position="centre", alignement="gauche", compteur=False, surligne=True),
    "massif": dict(typo="massif", texte_police="Poppins-Medium.ttf", numero="{}/", barre=False, note="postit", note_police="marqueur",
                   surtitre="etiquette", position="centre", alignement="gauche", compteur=False),
    "brut": dict(typo="brut", texte_police="Poppins-Medium.ttf", serre=-0.03, numero="N°{:02d}", barre=True, note="fleche", note_police="marqueur",
                 surtitre="etiquette", position="bas", alignement="gauche", compteur=False),
    "sport": dict(typo="gros_titre", texte_police="Poppins-Regular.ttf", numero="{:02d}", barre=False, note="cercle", note_police="feutre",
                  surtitre="grand", position="centre", alignement="gauche", compteur=False),
    "doux": dict(typo="epure", texte_police="NunitoTexte.ttf", serre=-0.02, numero=None, barre=False, note="cercle", note_police="danse",
                 surtitre="etiquette", position="centre", alignement="centre", compteur=True),
    "retro": dict(typo="doux_retro", texte_police="NunitoTexte.ttf", numero="({:02d})", barre=False, note="cercle", note_police="danse",
                  surtitre="petit", position="centre", alignement="gauche", compteur=False),
    "craie": dict(typo="craie", texte_police="craie", k_texte=1.35, numero="{}.", barre=False, note="fleche", note_police="craie",
                  surtitre="petit", position="centre", alignement="centre", compteur=False),
    "bulle": dict(typo="bulle", texte_police="NunitoTexte.ttf", numero=None, barre=False, note="postit", note_police="journal_intime",
                  surtitre="etiquette", position="centre", alignement="centre", compteur=True),
    "seventies": dict(typo="seventies", texte_police="Poppins-Medium.ttf", numero=None, barre=False, note="cercle", note_police="retro_script",
                      surtitre="grand", position="centre", alignement="centre", compteur=False),
    "tech": dict(typo="minimal", texte_police="DMSansTexte.ttf", serre=-0.02, numero="[{:02d}]", barre=False, note="fleche", note_police="feutre",
                 surtitre="etiquette", position="haut", alignement="gauche", compteur=False),
}
# (id, nom, texture, fond, fond2, titre, texte, accent, gabarit)
_PALETTES = {
    "blanc": [("blanc_rose", "Blanc & rose", "grain", "#FBFAF8", "#FBFAF8", "#111111", "#2B2B2B", "#FF4F79", "edito"),
              ("creme_script", "Crème & script", "papier", "#F5EFE3", "#D9CDB6", "#2C2418", "#3A3022", "#2C2418", "script"),
              ("ivoire_luxe", "Ivoire", "papier", "#F8F4EA", "#DDD3BF", "#2B2A26", "#45423B", "#B08D57", "luxe"),
              ("carnet_vert", "Carnet vert", "carnet", "#FCFCF7", "#B8D3C2", "#1E5B3F", "#24473A", "#E06A4E", "carnet"),
              ("blanc_tech", "Blanc tech", "quadrille", "#FFFFFF", "#D6DCE5", "#0B0B0F", "#2A2E38", "#2F6BFF", "tech"),
              ("feutre_fluo", "Feutre fluo", "pointille", "#FFFFFF", "#C9C9C9", "#111111", "#222222", "#B6FF5C", "marqueur"),
              ("nacre", "Nacre", "grain", "#F7F3F0", "#F7F3F0", "#3A2E39", "#4E4350", "#C48B9F", "italique"),
              ("blanc_couture", "Blanc couture", "grain", "#FDFCFA", "#FDFCFA", "#0F0F0F", "#3B3B3B", "#0F0F0F", "mode"),
              ("blanc_bulle", "Blanc bulle", "pointille", "#FFFFFF", "#E3D9F7", "#3A2A6B", "#4B4270", "#FFB4C8", "bulle")],
    "beige": [("beige_edito", "Beige éditorial", "papier", "#E9E1D3", "#C8BBA4", "#1D1A16", "#2E2922", "#1D1A16", "edito"),
              ("sable_script", "Sable & script", "grain", "#E3D3BC", "#E3D3BC", "#3B2A1A", "#4A3726", "#8C5A35", "script"),
              ("latte", "Latte", "papier", "#D9C3A5", "#B39B7B", "#2E2015", "#3B2B1E", "#8C4B2A", "retro"),
              ("camel", "Camel", "grain", "#C8A27A", "#C8A27A", "#FFF8EE", "#FFF1DE", "#3B2416", "mode"),
              ("kraft_feutre", "Kraft & feutre", "kraft", "#BF9467", "#8A6A45", "#14110D", "#1F1A14", "#FFF06A", "marqueur"),
              ("lin_carnet", "Lin carnet", "lin", "#E8DFCF", "#BCAE95", "#4A3426", "#55402F", "#C0573E", "carnet"),
              ("beige_brut", "Beige brut", "beton", "#D8CFC2", "#A69C8E", "#1A1714", "#26221E", "#D9481C", "brut"),
              ("biscuit", "Biscuit", "papier", "#EADCC2", "#CDB894", "#5A3A1E", "#5E4430", "#E07A3F", "doux"),
              ("taupe", "Taupe", "grain", "#B9AC9C", "#B9AC9C", "#FFFFFF", "#F6F2EC", "#2B231C", "luxe")],
    "rose": [("rose_edito", "Rose éditorial", "papier", "#F6DDE0", "#E2B7BE", "#3A0F1C", "#4A1E2A", "#3A0F1C", "edito"),
             ("rose_script", "Rose & script", "aurore", "#F3C6D2", "#E79AB4", "#4A1430", "#5A2140", "#4A1430", "script"),
             ("bonbon", "Rose bonbon", "uni", "#FF5FA2", "#FF5FA2", "#FFFFFF", "#FFF0F7", "#1B0B14", "massif"),
             ("rose_bulle", "Rose bulle", "pointille", "#FFE4EE", "#F5B6CD", "#C2185B", "#8E2453", "#FFD54F", "bulle"),
             ("blush", "Blush", "grain", "#EBC3C0", "#EBC3C0", "#5C1A24", "#6E2F37", "#5C1A24", "mode"),
             ("framboise", "Framboise", "grain", "#B0164E", "#B0164E", "#FFE3EC", "#FFD0DF", "#FFE3EC", "sport"),
             ("carnet_rose", "Carnet rose", "carnet", "#FFF7F8", "#F3C1CB", "#B4234F", "#7A2A42", "#B4234F", "carnet"),
             ("vieux_rose", "Vieux rose", "papier", "#D8A7A7", "#B98585", "#3E1E22", "#4C2A2E", "#7A2E36", "retro"),
             ("rose_70", "Rose seventies", "grain", "#F7A8B8", "#F7A8B8", "#7A1F3D", "#6B2A3F", "#FF6F3C", "seventies")],
    "rouge": [("rouge_edito", "Rouge éditorial", "grain", "#C8102E", "#C8102E", "#FFFFFF", "#FFE6E9", "#FFFFFF", "edito"),
              ("brique", "Brique", "beton", "#A84A35", "#7E3424", "#FFF1E6", "#FFE2D1", "#1B0F0A", "brut"),
              ("cerise_script", "Cerise & script", "aurore", "#6E0F1F", "#B0283C", "#FFE8E3", "#FFDCD5", "#FFE8E3", "script"),
              ("terre_cuite", "Terre cuite", "papier", "#D27954", "#B65D3B", "#FFF6EC", "#FFEBDD", "#3A1A0C", "luxe"),
              ("rouille", "Rouille", "grain", "#9C3D1B", "#9C3D1B", "#F8E7D2", "#F1D8BE", "#F8C46B", "retro"),
              ("bordeaux", "Bordeaux", "grain", "#5A0F1F", "#5A0F1F", "#F2D6A2", "#EED9C4", "#F2D6A2", "mode"),
              ("rouge_pop", "Rouge pop", "uni", "#FF3B30", "#FF3B30", "#FFFFFF", "#FFF0EE", "#FFE14D", "massif"),
              ("tomette", "Tomette", "kraft", "#C66A47", "#94492D", "#2A120A", "#311A10", "#FFF3D6", "marqueur"),
              ("corail", "Corail", "grain", "#FF7F66", "#FF7F66", "#3A0E05", "#4A1B10", "#3A0E05", "doux")],
    "orange": [("moutarde", "Moutarde", "grain", "#E1AD21", "#E1AD21", "#1E1608", "#2A200E", "#1E1608", "sport"),
               ("orange_edito", "Orange éditorial", "papier", "#F6A04D", "#D9803A", "#1A0E05", "#2A1A0D", "#1A0E05", "edito"),
               ("citron", "Citron", "pointille", "#FFF6B8", "#F0D95A", "#5B4A00", "#4F4310", "#FF6FA8", "bulle"),
               ("abricot_script", "Abricot & script", "aurore", "#FFD3A8", "#FF9F6E", "#5A2A10", "#6A3A1E", "#5A2A10", "script"),
               ("mandarine", "Mandarine", "uni", "#FF8A1F", "#FF8A1F", "#FFFFFF", "#FFF3E6", "#2A0F00", "massif"),
               ("miel", "Miel", "papier", "#F2C66D", "#D9A441", "#4A2C05", "#553712", "#B23A1E", "retro"),
               ("soleil_70", "Soleil 70's", "grain", "#FFB627", "#FFB627", "#8A2C02", "#7A3410", "#E8572A", "seventies"),
               ("carnet_jaune", "Carnet jaune", "carnet", "#FFFBE6", "#F2DE8A", "#2C2C2C", "#3A3A3A", "#FF8A1F", "carnet"),
               ("ocre", "Ocre", "grain", "#C98B2B", "#C98B2B", "#FFF8E8", "#FFF0D6", "#2A1A05", "luxe")],
    "vert": [("vert_edito", "Vert éditorial", "papier", "#DCE5D5", "#B3C2A6", "#10261A", "#1F3326", "#10261A", "edito"),
             ("olive", "Olive", "grain", "#5E6B3A", "#5E6B3A", "#F3EED8", "#E9E3C8", "#F3EED8", "mode"),
             ("foret_script", "Forêt & script", "aurore", "#13261C", "#2E5038", "#E7F0DF", "#DCE8D2", "#E7F0DF", "script"),
             ("menthe", "Menthe", "pointille", "#DFF5EA", "#9FD8BC", "#0F5A3C", "#1E5C43", "#FF7FA0", "bulle"),
             ("pistache", "Pistache", "grain", "#BFD8A0", "#BFD8A0", "#22361A", "#2E4424", "#22361A", "doux"),
             ("vert_pop", "Vert pop", "uni", "#22C55E", "#22C55E", "#062B14", "#0B3A1D", "#FFFFFF", "massif"),
             ("emeraude", "Émeraude", "grain", "#0F4D3A", "#0F4D3A", "#E9D8A6", "#EFE6CC", "#E9D8A6", "luxe"),
             ("tableau_vert", "Tableau vert", "ardoise", "#2B4A3A", "#2B4A3A", "#F5F3EA", "#E6E4DA", "#FFE38A", "craie"),
             ("kaki", "Kaki", "beton", "#8C8A62", "#6A6848", "#141410", "#1E1E18", "#F3E9C6", "brut")],
    "bleu": [("bleu_edito", "Bleu éditorial", "papier", "#DCE6F2", "#B3C5DD", "#0B1F3A", "#1B2E4A", "#0B1F3A", "edito"),
             ("marine", "Marine", "grain", "#0E1B33", "#0E1B33", "#F1E7D0", "#E6DDC8", "#D9B26A", "mode"),
             ("ciel", "Ciel", "pointille", "#E3F1FF", "#A9D1F7", "#123A6B", "#24476F", "#FF9AB8", "bulle"),
             ("bleu_klein", "Bleu Klein", "uni", "#1F3BD6", "#1F3BD6", "#FFFFFF", "#E8ECFF", "#FFE14D", "massif"),
             ("denim", "Denim", "lin", "#3D5A80", "#2B4566", "#F5F1E6", "#E9E4D6", "#F5C84B", "sport"),
             ("carnet_bleu", "Carnet bleu", "quadrille", "#FFFFFF", "#BFD6F2", "#1F3A93", "#24324F", "#E54848", "carnet"),
             ("canard", "Bleu canard", "grain", "#0F5964", "#0F5964", "#EAF6F4", "#D6ECE9", "#FFB86B", "doux"),
             ("lagon_script", "Lagon & script", "aurore", "#0B3D5C", "#1E7FA6", "#E8F6FF", "#D7EEFA", "#E8F6FF", "script"),
             ("bleu_tech", "Bleu tech", "quadrille", "#0D1B2A", "#26384D", "#E0F2FF", "#BFD8EE", "#5EEAD4", "tech")],
    "violet": [("lilas_edito", "Lilas éditorial", "papier", "#E6DDF2", "#C6B6DE", "#24123F", "#33224D", "#24123F", "edito"),
               ("lavande_script", "Lavande & script", "aurore", "#C9B6F2", "#9C85E0", "#2A1450", "#35205C", "#2A1450", "script"),
               ("prune", "Prune", "grain", "#3B1C3F", "#3B1C3F", "#F3D9E8", "#E9D2E0", "#F3D9E8", "mode"),
               ("violet_pop", "Violet pop", "uni", "#7C3AED", "#7C3AED", "#FFFFFF", "#F1EBFF", "#FFE14D", "massif"),
               ("mauve", "Mauve", "papier", "#B79AB8", "#987A99", "#2C1730", "#3A2440", "#5A2C60", "luxe"),
               ("lilas_bulle", "Lilas bulle", "pointille", "#F1EAFF", "#CDB9F5", "#4B2A99", "#4F3A85", "#FF8FB1", "bulle"),
               ("aubergine", "Aubergine", "grain", "#2A1230", "#2A1230", "#FFFFFF", "#DCC8E6", "#C77DFF", "edito"),
               ("violet_70", "Violet 70's", "grain", "#B88AE6", "#B88AE6", "#2E0F4F", "#3A1E5A", "#FF7A59", "seventies"),
               ("iris", "Iris", "papier", "#CFC6F2", "#A99CDC", "#2B2366", "#38306B", "#E25A8A", "retro")],
    "gris": [("gris_edito", "Gris éditorial", "papier", "#E4E4E2", "#BDBDBA", "#121212", "#262626", "#121212", "edito"),
             ("perle", "Perle", "grain", "#D9D9D6", "#D9D9D6", "#1E1E1E", "#3A3A3A", "#8A7A5A", "luxe"),
             ("anthracite", "Anthracite", "beton", "#3A3B3D", "#2A2B2D", "#F2F2F0", "#D9D9D6", "#FF5A36", "brut"),
             ("acier", "Acier", "quadrille", "#C9CED6", "#A4ABB6", "#0E1116", "#1F242C", "#2F6BFF", "tech"),
             ("galet_script", "Galet & script", "aurore", "#8E8E8A", "#C2C1BA", "#FFFFFF", "#F4F4F2", "#FFFFFF", "script"),
             ("gris_doux", "Gris doux", "papier", "#CFCBC6", "#ABA6A0", "#3A332E", "#47403A", "#C2573C", "retro"),
             ("carnet_gris", "Carnet gris", "carnet", "#F4F4F2", "#CFCFCB", "#2A2A2A", "#3A3A3A", "#2F6BFF", "carnet"),
             ("argent", "Argent", "grain", "#BFC0C2", "#BFC0C2", "#111111", "#2A2A2A", "#111111", "mode"),
             ("ciment_feutre", "Ciment & feutre", "beton", "#B7B5AF", "#8E8B85", "#111111", "#1D1D1D", "#FFE14D", "marqueur")],
    "noir": [("noir_edito", "Noir éditorial", "grain", "#0F0F10", "#0F0F10", "#FFFFFF", "#CFCFCF", "#FFFFFF", "edito"),
             ("noir_script", "Noir & script", "aurore", "#0B0B0D", "#2A2730", "#F4EEDC", "#EDE6D2", "#F4EEDC", "script"),
             ("noir_rose", "Noir & rose", "grain", "#121014", "#121014", "#FF4F79", "#F2D5DE", "#FF4F79", "sport"),
             ("noir_jaune", "Noir & jaune", "uni", "#0E0E0E", "#0E0E0E", "#FFE14D", "#F2F2F2", "#FFE14D", "massif"),
             ("neon", "Néon", "grain", "#0A0A12", "#0A0A12", "#5EEAD4", "#C8F7EF", "#FF4FD8", "tech"),
             ("encre", "Encre", "papier", "#1A1A1E", "#2C2C33", "#EDE6D6", "#D9D2C2", "#C9A45C", "luxe"),
             ("charbon_craie", "Charbon", "ardoise", "#1E1F21", "#1E1F21", "#F5F3EA", "#E6E4DA", "#FF8FA3", "craie"),
             ("noir_italique", "Noir italique", "grain", "#141414", "#141414", "#F2E6D8", "#E3D7C9", "#D99A6C", "italique"),
             ("nuit_etoilee", "Nuit étoilée", "pointille", "#121633", "#3A4170", "#FFE9A8", "#E8E2FF", "#FF9AB8", "bulle")],
}
for _fam, _liste in _PALETTES.items():
    for _id, _nom, _tex, _f1, _f2, _ti, _tx, _ac, _gab in _liste:
        assert _id not in MODELES, _id
        MODELES[_id] = dict(GABARITS[_gab], couleur=_fam, nom=_nom, texture=_tex, fond=_f1, fond2=_f2, titre=_ti, texte=_tx, accent=_ac)
# ordre d'affichage : par famille de couleurs
_RANG = {f: k for k, (f, _, _) in enumerate(FAMILLES)}
MODELES = dict(sorted(MODELES.items(), key=lambda kv: _RANG.get(kv[1]["couleur"], 99)))
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
