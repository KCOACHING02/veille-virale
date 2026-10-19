"""Mise en page du guide PDF (aimant à e-mails ou produit payant) aux couleurs et polices de la boutique — reportlab, format A5 (lecture sur téléphone)."""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Paragraph, BaseDocTemplate, Spacer,
                                Table, TableStyle)

POLICES = Path(__file__).resolve().parent / "static" / "fonts"
FICHIERS_TITRE = {
    "Poppins": "Poppins-Bold.ttf", "Montserrat": "Montserrat-ExtraBold.ttf", "Space Grotesk": "SpaceGrotesk-Bold.ttf", "Quicksand": "Quicksand-Bold.ttf",
    "Anton": "Anton-Regular.ttf", "Bebas Neue": "BebasNeue-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf",
    "DM Serif Display": "DMSerifDisplay-Regular.ttf", "Playfair Display": "PlayfairDisplay-Bold.ttf", "Abril Fatface": "AbrilFatface-Regular.ttf",
    "Caveat": "Caveat-Bold.ttf", "Pacifico": "Pacifico-Regular.ttf",
}
# Polices Google (non embarquées) : la plus proche parmi les polices du dossier
PROCHES = {"classique": "PlayfairDisplay-Bold.ttf", "moderne": "Poppins-Bold.ttf", "douce": "Quicksand-Bold.ttf", "affiche": "Anton-Regular.ttf",
           "futuriste": "SpaceGrotesk-Bold.ttf", "manuscrite": "Caveat-Bold.ttf"}
_ENREG: set[str] = set()


def _police(fichier: str) -> str:
    nom = Path(fichier).stem
    if nom not in _ENREG:
        pdfmetrics.registerFont(TTFont(nom, str(POLICES / fichier)))
        _ENREG.add(nom)
    return nom


def _propre(t: str) -> str:
    """Sans emojis (absents des polices) et échappé pour reportlab."""
    t = re.sub(r"[\U00010000-\U0010FFFF☀-➿️‍]", "", t or "")
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").strip()


def _clair(h: str) -> bool:
    h = h[:7]
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return (r * 299 + g * 587 + b * 114) / 1000 > 150


def genere(contenu: dict, design: dict, sortie: Path, marque: str, url: str, image: Path | None = None, categorie_titre: str = "classique") -> Path:
    titre_f = _police(FICHIERS_TITRE.get(design.get("police_titre"), PROCHES.get(categorie_titre, "PlayfairDisplay-Bold.ttf")))
    texte_f, texte_m, texte_b = _police("Poppins-Regular.ttf"), _police("Poppins-Medium.ttf"), _police("Poppins-Bold.ttf")
    accent = HexColor(design.get("accent", "#B4693E")[:7])
    fond = design.get("fond1", "#F4EDE4")[:7]
    encre = HexColor(design.get("texte", "#2A211C")[:7]) if _clair(fond) else HexColor("#2A211C")
    fond_page = HexColor(fond) if _clair(fond) else HexColor("#FBF8F4")
    fond_couv = HexColor(fond)
    encre_couv = HexColor(design.get("texte", "#2A211C")[:7])
    doux = HexColor(design.get("bouton_fond", "#DDBEA4")[:7])
    texte_doux = HexColor(design.get("bouton_texte", "#2A211C")[:7])
    W, H = A5

    def couverture(c, doc):
        c.saveState()
        c.setFillColor(fond_couv); c.rect(0, 0, W, H, stroke=0, fill=1)
        if image and image.exists():
            try:
                ir = ImageReader(str(image)); iw, ih = ir.getSize()
                hauteur = H * .52; echelle = max(W / iw, hauteur / ih)
                c.saveState(); p = c.beginPath(); p.rect(0, H - hauteur, W, hauteur); c.clipPath(p, stroke=0, fill=0)
                c.drawImage(ir, (W - iw * echelle) / 2, H - hauteur + (hauteur - ih * echelle) / 2, iw * echelle, ih * echelle)
                c.restoreState()
            except Exception:  # noqa: BLE001
                pass
        else:
            c.setFillColor(accent); c.circle(W * .82, H * .86, 60 * mm, stroke=0, fill=1)
            c.setFillColor(doux); c.circle(W * .1, H * .62, 26 * mm, stroke=0, fill=1)
        c.setFillColor(accent); c.rect(14 * mm, 27 * mm, 18 * mm, 1.6 * mm, stroke=0, fill=1)
        c.setFillColor(encre_couv); c.setFont(texte_m, 9); c.drawString(14 * mm, 20 * mm, _propre(marque).replace("&amp;", "&"))
        c.setFont(texte_f, 7.5); c.drawString(14 * mm, 15 * mm, url.replace("https://", "").replace("http://", ""))
        c.restoreState()

    def courante(c, doc):
        c.saveState()
        c.setFillColor(fond_page); c.rect(0, 0, W, H, stroke=0, fill=1)
        c.setFillColor(accent); c.rect(0, H - 4 * mm, W, 4 * mm, stroke=0, fill=1)
        c.setFillColor(encre); c.setFont(texte_f, 7)
        c.drawString(14 * mm, 9 * mm, _propre(contenu.get("titre", "")).replace("&amp;", "&")[:60])
        c.drawRightString(W - 14 * mm, 9 * mm, str(doc.page - 1))
        c.restoreState()

    st = {
        "couv_titre": ParagraphStyle("ct", fontName=titre_f, fontSize=27, leading=31, textColor=encre_couv),
        "couv_sous": ParagraphStyle("cs", fontName=texte_f, fontSize=11, leading=15, textColor=encre_couv, spaceBefore=8),
        "h1": ParagraphStyle("h1", fontName=titre_f, fontSize=19, leading=23, textColor=encre, spaceAfter=8),
        "num": ParagraphStyle("num", fontName=texte_b, fontSize=8, leading=10, textColor=accent, spaceAfter=3),
        "p": ParagraphStyle("p", fontName=texte_f, fontSize=10, leading=15.5, textColor=encre, spaceAfter=7),
        "intro": ParagraphStyle("in", fontName=texte_f, fontSize=11, leading=17, textColor=encre, spaceAfter=8),
        "box_t": ParagraphStyle("bt", fontName=texte_b, fontSize=8.5, leading=11, textColor=texte_doux, spaceAfter=4),
        "box": ParagraphStyle("bx", fontName=texte_m, fontSize=9.5, leading=13.5, textColor=texte_doux, leftIndent=9, bulletIndent=0, spaceAfter=2),
        "cta": ParagraphStyle("cta", fontName=titre_f, fontSize=15, leading=20, textColor=white, alignment=TA_CENTER),
        "cta_url": ParagraphStyle("cu", fontName=texte_m, fontSize=9, leading=12, textColor=white, alignment=TA_CENTER, spaceBefore=6),
    }
    doc = BaseDocTemplate(str(sortie), pagesize=A5, title=contenu.get("titre", ""), author=marque, leftMargin=14 * mm, rightMargin=14 * mm,
                          topMargin=16 * mm, bottomMargin=16 * mm)
    cadre_couv = Frame(14 * mm, 34 * mm, W - 28 * mm, H * .40 - 30 * mm, id="couv")
    cadre = Frame(14 * mm, 16 * mm, W - 28 * mm, H - 34 * mm, id="corps")
    doc.addPageTemplates([PageTemplate("couv", [cadre_couv], onPage=couverture), PageTemplate("page", [cadre], onPage=courante)])

    def paras(texte: str, style) -> list:
        return [Paragraph(_propre(x).replace("\n", "<br/>"), style) for x in re.split(r"\n\s*\n", texte or "") if x.strip()]

    def boite(titre: str, points: list[str]):
        lignes = [Paragraph(_propre(titre).upper(), st["box_t"])] + [Paragraph(_propre(p), st["box"], bulletText="•") for p in points if p.strip()]
        t = Table([[lignes]], colWidths=[W - 28 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), doux), ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                               ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("ROUNDEDCORNERS", [8, 8, 8, 8])]))
        return t

    h = [Paragraph(_propre(contenu.get("titre", "")), st["couv_titre"]), Paragraph(_propre(contenu.get("sous_titre", "")), st["couv_sous"]),
         NextPageTemplate("page"), PageBreak()]
    h += [Paragraph("Avant de commencer", st["h1"]), *paras(contenu.get("introduction", ""), st["intro"])]
    parties = contenu.get("parties") or []
    h += [Spacer(1, 6), boite("Au programme", [f"{i}. {p.get('titre', '')}" for i, p in enumerate(parties, 1)]), PageBreak()]
    for i, p in enumerate(parties, 1):
        bloc = [Paragraph(f"PARTIE {i}", st["num"]), Paragraph(_propre(p.get("titre", "")), st["h1"])]
        corps = paras(p.get("texte", ""), st["p"])
        h += [KeepTogether(bloc + corps[:1]), *corps[1:]]
        if p.get("a_retenir"):
            h += [Spacer(1, 4), KeepTogether([boite("À retenir", p["a_retenir"])])]
        h.append(Spacer(1, 16))
    h += [PageBreak(), Paragraph("Pour conclure", st["h1"]), *paras(contenu.get("conclusion", ""), st["intro"]), Spacer(1, 14)]
    cta = Table([[[Paragraph(_propre(contenu.get("appel_action", "")), st["cta"]),
                   Paragraph(url.replace("https://", "").replace("http://", ""), st["cta_url"])]]], colWidths=[W - 28 * mm])
    cta.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), accent), ("TOPPADDING", (0, 0), (-1, -1), 16), ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
                             ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("ROUNDEDCORNERS", [10, 10, 10, 10])]))
    h.append(KeepTogether([cta]))
    doc.build(h)
    return sortie
