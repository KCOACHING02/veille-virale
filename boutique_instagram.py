"""Boutique préparée à partir du profil Instagram public de la cliente : photo, nom, présentation, lien de sa bio.

Une seule lecture du profil (collecte.profil_reseaux, environ 0,2 centime), lancée par la file de tâches du studio.
Rien n'est écrit dans la boutique : le résultat pré-remplit la création pas à pas, la cliente vérifie et corrige.
Si le profil est illisible (compte introuvable, collecte indisponible), elle continue à la main : jamais de blocage.
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boutique as bq
from modele import log

MOTIF_COMPTE = re.compile(r"^[a-z0-9._]{1,30}$")
# Morceaux d'adresse Instagram qui ne sont pas des comptes (lien d'une publication collé par erreur…)
PAS_UN_COMPTE = {"p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct", "about", "legal", "developer", "web"}
# Pages « lien en bio » d'autres outils : inutile d'y renvoyer depuis sa nouvelle boutique
AGREGATEURS = ("linktr.ee", "beacons.ai", "beacons.page", "stan.store", "lnk.bio", "bio.link", "linkin.bio", "taplink.cc", "taplink.at",
               "campsite.bio", "msha.ke", "solo.to", "allmylinks.com", "komi.io", "hoo.be", "linkpop.com", "snipfeed.co", "flow.page",
               "withkoji.com", "milkshake.app", "tap.bio", "bio.site", "link.me", "lnk.to", "virallink.fr", "instagram.com")
# Image que met Instagram quand le compte n'a pas de photo : pas un logo
PHOTO_VIDE = "44884218_345707102882519_2446069589734326272"
TITRES_LIENS = (("youtube.", "Ma chaîne YouTube"), ("youtu.be", "Ma chaîne YouTube"), ("wa.me", "Écris-moi sur WhatsApp"),
                ("whatsapp.", "Écris-moi sur WhatsApp"), ("t.me", "Mon canal Telegram"), ("calendly.", "Prendre rendez-vous"),
                ("spotify.", "Mon podcast"), ("podcasts.apple", "Mon podcast"), ("tiktok.", "Mon TikTok"), ("pinterest.", "Mon Pinterest"),
                ("facebook.", "Ma page Facebook"), ("etsy.", "Ma boutique Etsy"), ("amazon.", "Ma sélection Amazon"), ("amzn.", "Ma sélection Amazon"))


def nettoie_compte(v) -> str:
    """« @Nom », « instagram.com/nom/?hl=fr »… → « nom ». Chaîne vide si ce n'est pas un nom de compte."""
    v = str(v or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?instagram\.com/([^/?#\s]+)", v, re.I)
    if m:
        v = m.group(1)
    v = v.lstrip("@").strip().rstrip("/").lower()
    return v if MOTIF_COMPTE.match(v) and v not in PAS_UN_COMPTE else ""


def nom_propre(nom, compte: str) -> str:
    nom = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(nom or ""))).strip()
    if not nom:  # pas de nom affiché : « lina.coach » → « Lina Coach »
        nom = " ".join(m.capitalize() for m in re.split(r"[._]+", compte) if m)
    return nom[:60].strip()


def texte_propre(t, limite: int = 280) -> str:
    t = re.sub(r"[ \t]+", " ", re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", " ", str(t or "")))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l.strip() for l in t.split("\n"))).strip()[:limite].strip()


def lien_utile(url) -> str:
    """Le lien de la bio, s'il mène à un vrai site (pas à une autre page « lien en bio »)."""
    url = str(url or "").strip()
    try:
        p = urlparse(url)
        if p.hostname in ("l.instagram.com", "l.facebook.com"):  # lien de redirection d'Instagram : la vraie adresse est dans ?u=
            url = (parse_qs(p.query).get("u") or [""])[0]
            p = urlparse(url)
    except ValueError:
        return ""
    hote = (p.hostname or "").lower().removeprefix("www.")
    if p.scheme not in ("http", "https") or "." not in hote or len(url) > 500:
        return ""
    if any(hote == a or hote.endswith("." + a) for a in AGREGATEURS):
        return ""
    return url


def titre_lien(url: str) -> str:
    hote = (urlparse(url).hostname or "").lower()
    return next((t for motif, t in TITRES_LIENS if motif in hote), "Mon site")


def adresse_libre(compte: str, bid) -> str:
    """Adresse de boutique proposée : le nom du compte s'il est libre, sinon sa première variante libre."""
    base = bq.nettoie_pseudo(compte).lstrip("_.-")
    if len(base) < 3:
        base = (base + "-shop")[:30]
    if not bq.pseudo_libre(base, bid):
        return base
    for suffixe in ("shop", "boutique", "officiel", *map(str, range(2, 30))):
        v = bq.nettoie_pseudo(f"{base[:30 - len(suffixe) - 1]}-{suffixe}")
        if v and not bq.pseudo_libre(v, bid):
            return v
    return ""


def _avatar_demo(nom: str) -> io.BytesIO:
    """Démo : une photo de profil fictive (dégradé et initiale), pour montrer les couleurs reprises dans le design."""
    from PIL import Image, ImageDraw, ImageFont
    cote = 480
    im = Image.new("RGB", (cote, cote))
    haut, bas = (255, 122, 150), (255, 190, 120)
    d = ImageDraw.Draw(im)
    for y in range(cote):
        k = y / (cote - 1)
        d.line([(0, y), (cote, y)], fill=tuple(round(haut[i] + (bas[i] - haut[i]) * k) for i in range(3)))
    try:
        police = ImageFont.truetype(str(Path(__file__).resolve().parent / "static" / "fonts" / "Poppins-Bold.ttf"), 230)
    except OSError:
        police = ImageFont.load_default()
    d.text((cote / 2, cote / 2), (nom.strip()[:1] or "V").upper(), font=police, fill=(255, 255, 255), anchor="mm")
    flux = io.BytesIO()
    im.save(flux, "JPEG", quality=90)
    flux.seek(0)
    return flux


def _profil_demo(compte: str) -> dict | None:
    if compte.startswith("introuvable"):
        return None
    return {"nom": nom_propre("", compte), "abonnes": 12400, "categorie": "Créateur de contenu", "prive": False, "photo": "",
            "bio": "J'aide les débutantes à lancer leur business en ligne depuis leur téléphone 📱\nSans se montrer, sans prise de tête",
            "lien": "https://exemple.fr/ma-formation"}


def prepare(bid, cfg: dict, token: str | None, compte: str, demo: bool = False) -> dict:
    """Lit le profil public et prépare ce que la création de la boutique pré-remplit.
    Renvoie {"trouve": False} si le profil est illisible : la cliente continue à la main."""
    compte = nettoie_compte(compte)
    rien = {"trouve": False, "compte": compte}
    if not compte:
        return rien
    log("Lecture de ton profil Instagram…")
    flux = None
    if demo:
        time.sleep(1.5)
        prof = _profil_demo(compte)
        if prof:
            flux = _avatar_demo(prof["nom"])
    else:
        if not token:
            return rien
        from collecte import profil_reseaux
        prof = profil_reseaux(cfg, token, instagram=compte, timeout_min=1.5, pause=3, essais=2).get("instagram")
        if prof and prof.get("photo") and PHOTO_VIDE not in prof["photo"]:
            import import_lien
            flux = import_lien.telecharge_image(prof["photo"])
    if not prof:
        return rien
    lien = lien_utile(prof.get("lien"))
    res = {"trouve": True, "compte": compte, "nom": nom_propre(prof.get("nom"), compte), "bio": texte_propre(prof.get("bio")),
           "abonnes": prof.get("abonnes"), "prive": bool(prof.get("prive")), "photo": "", "palettes": [],
           "lien": lien, "lien_titre": titre_lien(lien) if lien else "", "pseudo": adresse_libre(compte, bid)}
    if flux:
        log("Récupération de ta photo et de ses couleurs…")
        try:
            res["photo"] = bq.enregistre_image(bid, flux, 700)
            res["palettes"] = bq.palettes_photo(bq.dossier(bid) / "images" / res["photo"])
        except Exception:  # noqa: BLE001  (photo illisible : elle ajoutera son logo elle-même)
            pass
    return res
