"""
Lecture d'une page produit à partir de son lien (affiliation, formation sur Systeme.io/Podia, Etsy, Amazon…).

On récupère ce que la page déclare elle-même pour les réseaux sociaux et les moteurs de recherche :
balises Open Graph / Twitter, données structurées JSON-LD (Product, Offer, Course…) et, à défaut, le <title>.
Aucun appel d'IA : gratuit et instantané. Protégé contre les adresses internes (SSRF) et les pages trop lourdes.
"""

from __future__ import annotations

import io
import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

ENTETES = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
           "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
MAX_PAGE = 3_000_000
MAX_IMAGE = 8_000_000


class LienInvalide(ValueError):
    pass


def _adresse_publique(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise LienInvalide("Colle un lien complet, qui commence par https://")
    try:
        ips = {i[4][0] for i in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))}
    except socket.gaierror:
        raise LienInvalide("Ce site est introuvable : vérifie le lien.") from None
    for ip in ips:
        a = ipaddress.ip_address(ip.split("%")[0])
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
            raise LienInvalide("Ce lien n'est pas accessible.")


def _telecharge(url: str, limite: int, accepte: tuple[str, ...]) -> tuple[bytes, str, str]:
    """Suit les redirections une par une en revérifiant chaque adresse ; renvoie (contenu, type, url finale)."""
    for _ in range(6):
        _adresse_publique(url)
        r = requests.get(url, headers=ENTETES, timeout=12, stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            r.close()
            continue
        if r.status_code >= 400:
            r.close()
            raise LienInvalide(f"Le site a refusé la lecture de la page (code {r.status_code}). Remplis les informations à la main.")
        typ = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if accepte and not any(typ.startswith(a) for a in accepte):
            r.close()
            raise LienInvalide("Ce lien ne mène pas à une page web.")
        morceaux, total = [], 0
        for m in r.iter_content(65536):
            total += len(m)
            if total > limite:
                break
            morceaux.append(m)
        r.close()
        return b"".join(morceaux), typ, url
    raise LienInvalide("Trop de redirections sur ce lien.")


class _Lecteur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.titre = ""
        self.images: list[str] = []
        self._dans = None
        self._tampon: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            cle = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if cle and a.get("content") and cle not in self.meta:
                self.meta[cle] = a["content"].strip()
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._dans, self._tampon = "ld", []
        elif tag == "title" and not self.titre:
            self._dans, self._tampon = "titre", []
        elif tag == "link" and a.get("rel", "").lower() in ("image_src",) and a.get("href"):
            self.images.append(a["href"])
        elif tag == "img" and len(self.images) < 12 and a.get("src") and not a["src"].startswith("data:"):
            self.images.append(a["src"])

    def handle_data(self, data):
        if self._dans:
            self._tampon.append(data)

    def handle_endtag(self, tag):
        if self._dans == "ld" and tag == "script":
            self.jsonld.append("".join(self._tampon))
            self._dans = None
        elif self._dans == "titre" and tag == "title":
            self.titre = " ".join("".join(self._tampon).split())
            self._dans = None


def _objets(x):
    """Parcourt récursivement un JSON-LD (listes, @graph) et rend chaque objet."""
    if isinstance(x, list):
        for y in x:
            yield from _objets(y)
    elif isinstance(x, dict):
        yield x
        for k in ("@graph", "mainEntity", "itemListElement", "hasVariant"):
            if k in x:
                yield from _objets(x[k])


def _texte(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl") or v.get("name") or ""
    return unescape(str(v or "")).strip()


def _prix(v) -> float | None:
    if v in (None, ""):
        return None
    s = re.sub(r"[^\d,.]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:          # 1.299,00 ou 1,299.00
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        p = float(s)
    except ValueError:
        return None
    return p if 0 < p < 100_000 else None


def lit_page(url: str) -> dict:
    """Infos du produit déclarées par la page : titre, description, image (URL), prix (€), devise, site."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    brut, _, finale = _telecharge(url, MAX_PAGE, ("text/html", "application/xhtml"))
    enc = "utf-8"
    m = re.search(rb'charset=["\']?([\w-]+)', brut[:4000], re.I)
    if m:
        enc = m.group(1).decode("ascii", "ignore") or "utf-8"
    try:
        html = brut.decode(enc, errors="replace")
    except LookupError:
        html = brut.decode("utf-8", errors="replace")
    L = _Lecteur()
    try:
        L.feed(html)
    except Exception:  # noqa: BLE001  (HTML trop cassé : on garde ce qui a été lu)
        pass
    M = L.meta
    titre = M.get("og:title") or M.get("twitter:title") or L.titre
    desc = M.get("og:description") or M.get("twitter:description") or M.get("description") or ""
    image = M.get("og:image") or M.get("og:image:secure_url") or M.get("twitter:image") or M.get("twitter:image:src") or ""
    prix = _prix(M.get("product:price:amount") or M.get("og:price:amount") or M.get("price"))
    devise = (M.get("product:price:currency") or M.get("og:price:currency") or M.get("pricecurrency") or "").upper()
    # Données structurées : souvent plus précises pour le prix et le nom du produit
    for bloc in L.jsonld:
        try:
            donnees = json.loads(bloc.strip().rstrip(";"))
        except ValueError:
            continue
        for o in _objets(donnees):
            t = o.get("@type")
            types = {t} if isinstance(t, str) else set(t or [])
            if not types & {"Product", "Course", "Book", "Event", "Service", "CreativeWork", "SoftwareApplication", "IndividualProduct"}:
                continue
            titre = _texte(o.get("name")) or titre
            desc = desc or _texte(o.get("description"))
            image = image or _texte(o.get("image"))
            for off in _objets(o.get("offers") or []):
                p = _prix(off.get("price") or off.get("lowPrice"))
                if p and not prix:
                    prix, devise = p, (_texte(off.get("priceCurrency")) or devise).upper()
            if prix:
                break
    if not image and L.images:
        image = L.images[0]
    titre = re.sub(r"\s*[|–—-]\s*[^|–—-]{2,40}$", "", unescape(titre or "")).strip() if titre and len(titre) > 25 else unescape(titre or "").strip()
    desc = " ".join(unescape(desc).split())
    if len(desc) > 160:
        desc = desc[:157].rsplit(" ", 1)[0] + "…"
    hote = urlparse(finale).hostname or ""
    return {"titre": titre[:120], "sous_titre": desc, "image_url": urljoin(finale, image) if image else "",
            "prix": prix, "devise": devise or ("EUR" if prix else ""), "site": hote.removeprefix("www."), "url": url}


def telecharge_image(url: str) -> io.BytesIO | None:
    try:
        brut, typ, _ = _telecharge(url, MAX_IMAGE, ("image/",))
    except (LienInvalide, requests.RequestException):
        return None
    return io.BytesIO(brut) if brut else None
