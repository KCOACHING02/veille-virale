"""Mises en page « Appli » et « Marque » de la boutique : sortir du simple « lien dans la bio ».

- Appli (façon application mobile, MyGlow) : barre du haut avec nom et photo, grand carrousel de mise en avant,
  raccourcis ronds « De quoi as-tu envie ? », rail de produits avec bouton rond, carte « Une question ? », barre d'onglets en bas.
- Marque (façon site de marque, FitClem) : en-tête avec logo et menu rond, rail de grandes cartes verticales (stories),
  manifeste en grand texte avec le nom en italique, grille de produits, bulle de contact flottante.

Tout vient de ce que la cliente a déjà rempli (produits, photo, bio, réseaux, blocs) : rien d'inventé, aucun chiffre ni promesse.
Les autres blocs (texte, capture d'e-mails, témoignages, FAQ, liens…) gardent leur rendu habituel sous les sections.
"""

from __future__ import annotations

import boutique as bq
from boutique import E

ICO_SAC = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8h12l-1 12H7L6 8z" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linejoin="round"/><path d="M9 8V6a3 3 0 016 0v2" fill="none" stroke="currentColor" stroke-width="2"/></svg>')
ICO_PLUS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>'
ICO_FLECHE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
ICO_MAISON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>'
ICO_LIENS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" '
             'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')
ICO_BULLE = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linejoin="round"/></svg>')
ICO_PROFIL = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="2"/>'
              '<path d="M4 21a8 8 0 0116 0" fill="none" stroke="currentColor" stroke-width="2"/></svg>')
ICO_LECTURE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>'
ICO_HAUT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>'

DEJA_DANS_LA_PAGE = ("produits", "produit", "section")  # rendus par les sections de la mise en page

# Sections propres à chaque format Appli / Marque. Elles deviennent des blocs « section » que la cliente déplace,
# masque ou supprime ; « produits » marque la place du (ou des) bloc(s) Produits. Une section du format qui n'a pas
# encore de bloc se place d'elle-même : avant les produits si elle est listée avant, après sinon.
SECTIONS = {
    "appli": [("ap_hero", "Bannière défilante"), ("ap_ronds", "« De quoi as-tu envie ? »"), ("produits", ""), ("contact", "« Une question ? »")],
    "appli_stories": [("st_ronds", "Ronds de stories"), ("st_profil", "Carte de présentation"), ("produits", ""), ("contact", "« Une question ? »")],
    "appli_catalogue": [("ca_recherche", "Recherche et filtres"), ("ca_banniere", "Bannière mise en avant"), ("produits", ""), ("contact", "« Une question ? »")],
    "appli_une": [("un_grandes", "Grandes cartes « À la une »"), ("produits", ""), ("un_profil", "Carte de présentation"), ("contact", "« Une question ? »")],
    "marque": [("mq_stories", "Grandes cartes verticales"), ("mq_manif", "Manifeste (nom + présentation)"), ("produits", "")],
}
LIBELLES_SECTIONS = {k: l for v in SECTIONS.values() for k, l in v if k != "produits"}


def _prods_du_bloc(page: dict, b: dict | None) -> list[dict]:
    prods = _produits(page)
    if not b:
        return prods
    if b.get("type") == "produit":
        return [p for p in prods if p["id"] == b.get("produit")]
    ids = b.get("ids") or []
    return [p for p in prods if p["id"] in ids] if ids else prods


def _groupe_appli(inner: str, premier: bool) -> str:
    return f'<div class="blocs ap-blocs"{' id="liens"' if premier else ""}>{inner}</div>'


def _assemble(page: dict, pseudo: str, mep: str, sections: dict, rendu_prods, groupe_html=_groupe_appli) -> str:
    """Le corps de la page dans l'ordre des blocs de la cliente : sections du format, produits et blocs ordinaires.

    Page qui n'a encore aucun bloc « section » de ce format (boutique d'avant) : rendu d'origine à l'identique
    (sections, tous les produits, sections d'après, autres blocs, « Une question ? »)."""
    ordre = [k for k, _ in SECTIONS[mep]]
    i = ordre.index("produits")
    blocs = [b for b in page.get("blocs") or [] if b.get("visible", True)]
    refs = {b.get("section") for b in page.get("blocs") or [] if b.get("type") == "section"} & set(ordre)
    avant = [k for k in ordre[:i] if k not in refs]
    apres = [k for k in ordre[i + 1:] if k not in refs and k != "contact"]
    fin = ["contact"] if "contact" in ordre and "contact" not in refs else []

    # Liste des éléments à rendre : ("section", clé) / ("produits", bloc ou None) / ("bloc", bloc)
    if not refs:
        elems = [("produits", None)] + [("bloc", b) for b in blocs if b.get("type") not in DEJA_DANS_LA_PAGE]
    else:
        elems = []
        for b in blocs:
            t = b.get("type")
            elems.append(("section", b.get("section")) if t == "section" else ("produits", b) if t in ("produits", "produit") else ("bloc", b))
        if not any(e[0] == "produits" for e in elems):
            elems.insert(0, ("produits", None))
    out = [sections.get(k, "") for k in avant]
    groupe: list[str] = []
    etat = {"premier": True, "apres": False, "liens": False}

    def vide():
        if groupe:
            out.append(groupe_html("".join(groupe), not etat["liens"]))
            etat["liens"] = True
            groupe.clear()

    for genre, x in elems:
        if genre == "section":
            vide()
            out.append(sections.get(x, ""))
        elif genre == "produits":
            vide()
            if x is None:
                titre, liste = _titre_boutique(page), _produits(page)
            else:
                titre = x.get("titre") or ("" if x.get("type") == "produit" else "La boutique")
                liste = _prods_du_bloc(page, x)
            out.append(rendu_prods(liste, titre, etat["premier"]))
            etat["premier"] = False
            if not etat["apres"]:
                out.extend(sections.get(k, "") for k in apres)
                etat["apres"] = True
        else:
            groupe.append(bq._bloc_enveloppe(x, page, pseudo))
    vide()
    if not etat["apres"]:
        out.extend(sections.get(k, "") for k in apres)
    out.extend(sections.get(k, "") for k in fin)
    return "".join(out)


def _ancre(premier: bool) -> str:
    return ' id="boutique"' if premier else ""


def _produits(page: dict) -> list[dict]:
    return [p for p in page.get("produits") or [] if p.get("visible", True)]


def _lien_produit(page: dict, pseudo: str, p: dict) -> str:
    tn = bq.tunnel_du_produit(page, p["id"])
    return f'/@{pseudo}/t/{tn["id"]}' if tn else f'/@{pseudo}/p/{p["id"]}'


def _prix(p: dict) -> tuple[str, str, str]:
    """(prix affiché, prix barré, pastille) — la pastille ne dit que ce qui est vrai : gratuit, promo, offre limitée."""
    from boutique_ventes import prix_effectif
    pe = prix_effectif(p)
    dev = p.get("devise", "eur")
    prix = "Gratuit" if not pe["prix"] else bq.prix_txt(pe["prix"], dev)
    barre = bq.prix_txt(pe["barre"], dev) if pe["barre"] else ""
    if pe["barre"] and pe["prix"]:
        pastille = f"-{round(100 - pe['prix'] * 100 / pe['barre'])} %"
    elif not pe["prix"]:
        pastille = "Offert"
    elif pe["fin"]:
        pastille = "Offre limitée"
    else:
        pastille = ""
    return prix, barre, pastille


def _contact(page: dict) -> tuple[str, str] | None:
    """Le meilleur moyen de lui écrire : message privé Instagram, WhatsApp, puis e-mail."""
    r = page.get("reseaux") or {}
    if r.get("instagram"):
        compte = bq.lien_reseau("instagram", r["instagram"]) or ""
        nom = compte.rstrip("/").rsplit("/", 1)[-1]
        if nom:
            return f"https://ig.me/m/{nom}", "Écris-moi sur Instagram"
    for cle, texte in (("whatsapp", "Écris-moi sur WhatsApp"), ("email", "Écris-moi un e-mail")):
        u = bq.lien_reseau(cle, r.get(cle) or "")
        if u:
            return u, texte
    return None


def _autres_blocs(page: dict, pseudo: str) -> tuple[str, bool]:
    """Les blocs qui ne sont pas déjà des sections de la mise en page, avec leur rendu habituel. (html, il y a des liens)"""
    blocs = [b for b in page.get("blocs") or [] if b.get("visible", True) and b.get("type") not in DEJA_DANS_LA_PAGE]
    html_ = "".join(bq._bloc_enveloppe(b, page, pseudo) for b in blocs)
    return html_, any(b.get("type") == "lien" for b in blocs)


def _titre_boutique(page: dict) -> str:
    b = next((b for b in page.get("blocs") or [] if b.get("type") == "produits" and b.get("visible", True) and b.get("titre")), None)
    return (b or {}).get("titre") or "La boutique"


def _phrase(bio: str, n: int = 90) -> str:
    bio = (bio or "").strip()
    if len(bio) <= n:
        return bio
    coupe = bio[:n].rsplit(" ", 1)[0]
    return coupe.rstrip(",;:—-") + "…"


SCRIPT_CARROUSEL = """
<script>
document.querySelectorAll("[data-carrousel]").forEach(c => {
  const piste = c.querySelector("[data-piste]"), points = [...c.querySelectorAll("[data-point]")];
  if (!piste || points.length < 2) return;
  let i = 0, t;
  const montre = k => { i = (k + points.length) % points.length; piste.scrollTo({left: piste.children[i].offsetLeft - piste.offsetLeft, behavior: "smooth"}); };
  const auto = () => { clearInterval(t); t = setInterval(() => montre(i + 1), 4500); };
  piste.addEventListener("scroll", () => { const k = Math.round(piste.scrollLeft / piste.clientWidth);
    points.forEach((p, j) => p.setAttribute("aria-current", j === k)); i = k; }, {passive: true});
  points.forEach((p, j) => p.addEventListener("click", () => { montre(j); auto(); }));
  piste.addEventListener("pointerdown", () => clearInterval(t));
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) auto();
});
</script>"""


# ------------------------------------------------------------
#  Appli
# ------------------------------------------------------------
def _cartes(page: dict) -> str:
    """Taille des cartes produits des modèles Appli (réglage « cartes_appli » du design)."""
    c = (page.get("design") or {}).get("cartes_appli") or "grande"
    return "deux" if c == "grille" else c  # « deux » : évite les règles existantes qui visent les classes contenant « grille »


def _haut_appli(page: dict, pseudo: str) -> str:
    """Barre du haut commune aux modèles Appli : nom (dernier mot en couleur), phrase de présentation, réseau et photo ronde."""
    nom = page.get("nom") or pseudo
    photo = page.get("photo")
    avatar = (f'<img class="ap-avatar" src="{bq._img(pseudo, photo)}" alt="">' if photo
              else f'<span class="ap-avatar vide">{E(nom[:1].upper())}</span>')
    reseaux = page.get("reseaux") or {}
    boutons = ""
    for cle in ("instagram", "tiktok", "youtube"):
        u = bq.lien_reseau(cle, reseaux.get(cle) or "")
        if u:
            boutons += (f'<a class="ap-rond" href="{E(u)}" target="_blank" rel="noopener" aria-label="{E(bq.RESEAUX[cle][0])}">'
                        f'<svg viewBox="0 0 24 24">{bq.ICONES[cle]}</svg></a>')
            break
    mots = nom.split()
    logo = E(nom) if len(mots) < 2 else f'{E(" ".join(mots[:-1]))} <em>{E(mots[-1])}</em>'
    salut = f'<p class="ap-salut">{E(_phrase(page.get("bio") or "", 70))}</p>' if page.get("bio") else ""
    return (f'<header class="ap-haut" id="haut"><div class="ap-id"><p class="ap-logo">{logo}</p>{salut}</div>'
            f'<div class="ap-icones">{boutons}{avatar}</div></header>')


def _bas_appli(page: dict, pseudo: str, avec_boutique: bool) -> str:
    """Autres blocs, carte « Une question ? » et onglets du bas, communs aux modèles Appli."""
    a_des_liens = any(b.get("type") == "lien" and b.get("visible", True) for b in page.get("blocs") or [])
    contact = _contact(page)
    onglets = [("#haut", "Accueil", ICO_MAISON, True)]
    if avec_boutique:
        onglets.append(("#boutique", "Boutique", ICO_SAC, False))
    if a_des_liens:
        onglets.append(("#liens", "Liens", ICO_LIENS, False))
    if contact:
        onglets.append((contact[0], "Contact", ICO_BULLE, False))
    nav = '<nav class="ap-nav">' + "".join(
        f'<a href="{E(u)}"{" target=_blank rel=noopener" if u.startswith("http") or u.startswith("mailto") else ""}'
        f'{" aria-current=page" if actif else ""}>{ico}<span>{E(t)}</span></a>' for u, t, ico, actif in onglets) + "</nav>"
    return f'</div>{bq.badge(page)}{nav}{SCRIPT_ONGLETS}'


def _section_contact(page: dict) -> str:
    contact = _contact(page)
    return (f'<a class="ap-conseil" href="{E(contact[0])}" target="_blank" rel="noopener"><span><b>Une question ?</b>'
            f'<small>{E(contact[1])}</small></span><i>{ICO_FLECHE}</i></a>') if contact else ""


def rendu_appli(page: dict, pseudo: str, apercu: bool = False) -> str:
    nom = page.get("nom") or pseudo
    prods = _produits(page)
    avec_image = [p for p in prods if p.get("image")]
    photo = page.get("photo")
    haut = _haut_appli(page, pseudo)

    # Carrousel de mise en avant : les produits avec une image (3 au plus), sinon la couverture
    slides = []
    for p in avec_image[:3]:
        prix, _, pastille = _prix(p)
        sous = p.get("sous_titre") or (f"{pastille} · {prix}" if pastille else prix)
        slides.append(f'<a class="ap-slide" href="{_lien_produit(page, pseudo, p)}"><div class="ap-slide-txt"><h2>{E(p.get("titre") or "")}</h2>'
                      f'<p>{E(sous)}</p><span class="ap-cta">Je découvre</span></div>'
                      f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy"></a>')
    if not slides:
        couv = page.get("couverture") or photo
        img = f'<img src="{bq._img(pseudo, couv)}" alt="">' if couv else ""
        slides.append(f'<a class="ap-slide" href="#boutique"><div class="ap-slide-txt"><h2>{E(nom)}</h2>'
                      f'<p>{E(_phrase(page.get("bio") or "", 110))}</p><span class="ap-cta">Je découvre</span></div>{img}</a>')
    points = "".join(f'<button type="button" data-point aria-label="Diapositive {i + 1}" aria-current="{str(i == 0).lower()}"></button>'
                     for i in range(len(slides))) if len(slides) > 1 else ""
    hero = (f'<section class="ap-hero" data-carrousel><div class="ap-piste" data-piste>{"".join(slides)}</div>'
            f'{f"<div class=ap-points>{points}</div>" if points else ""}</section>')

    # Raccourcis ronds : 3 à 6 produits
    ronds = ""
    if len(avec_image) >= 3:
        ronds = ('<h2 class="ap-t">De quoi as-tu envie ?</h2><div class="ap-ronds">' + "".join(
            f'<a class="ap-rond-p r{i % 6}" href="{_lien_produit(page, pseudo, p)}"><span><img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy"></span>'
            f'<b>{E(p.get("titre") or "")}</b></a>' for i, p in enumerate(avec_image[:6])) + "</div>")

    # Rail de produits (un par bloc Produits)
    def rail(liste, titre, premier):
        cartes = []
        for p in liste:
            prix, barre, pastille = _prix(p)
            img = f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>'
            cartes.append(f'<a class="ap-carte" href="{_lien_produit(page, pseudo, p)}">{f"<span class=ap-pastille>{E(pastille)}</span>" if pastille else ""}'
                          f'<span class="ap-img">{img}<span class="ap-sac" aria-hidden="true">{ICO_SAC}</span></span>'
                          f'<b>{E(p.get("titre") or "")}</b><span class="ap-prix">{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span></a>')
        if not cartes:
            return f'<span{_ancre(premier)}></span>'
        return f'{f"<h2 class=\"ap-t\"{_ancre(premier)}>{E(titre)}</h2>" if titre else ""}<div class="ap-rail"{"" if titre else _ancre(premier)}>{"".join(cartes)}</div>'

    corps = _assemble(page, pseudo, "appli", {"ap_hero": hero, "ap_ronds": ronds, "contact": _section_contact(page)}, rail)
    return f'<div class="ap ca-{_cartes(page)}">{haut}{corps}{_bas_appli(page, pseudo, bool(prods))}{SCRIPT_CARROUSEL}'


SCRIPT_ONGLETS = """
<script>
(() => { const l = [...document.querySelectorAll(".ap-nav a[href^='#']")]; if (!l.length) return;
  const cibles = l.map(a => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  addEventListener("scroll", () => { let k = 0; cibles.forEach((c, j) => { if (c.getBoundingClientRect().top < innerHeight * .45) k = j; });
    l.forEach((a, j) => a.toggleAttribute("aria-current", j === k)); }, {passive: true}); })();
</script>"""


# ------------------------------------------------------------
#  Marque
# ------------------------------------------------------------
def rendu_marque(page: dict, pseudo: str, apercu: bool = False) -> str:
    nom = page.get("nom") or pseudo
    prods = _produits(page)
    photo = page.get("photo")
    logo = f'<img class="mq-logo" src="{bq._img(pseudo, photo)}" alt="">' if photo else ""
    autres, a_des_liens = _autres_blocs(page, pseudo)
    contact = _contact(page)
    menu_liens = [("#boutique", _titre_boutique(page))] if prods else []
    if autres.strip():
        menu_liens.append(("#plus", "Liens et infos"))
    for cle, (libelle, _) in bq.RESEAUX.items():
        u = bq.lien_reseau(cle, (page.get("reseaux") or {}).get(cle) or "")
        if u:
            menu_liens.append((u, libelle))
    menu = ('<details class="mq-menu"><summary aria-label="Menu"><i></i><i></i></summary><nav>' + "".join(
        f'<a href="{E(u)}"{" target=_blank rel=noopener" if not u.startswith("#") else ""}>{E(t)}</a>' for u, t in menu_liens)
        + "</nav></details>") if menu_liens else ""
    haut = f'<header class="mq-haut" id="haut"><a class="mq-nom" href="#haut">{logo}<span>{E(nom)}</span></a>{menu}</header>'

    # Grandes cartes verticales : vidéos YouTube, images des galeries, puis produits
    cartes = []
    for b in page.get("blocs") or []:
        if not b.get("visible", True):
            continue
        if b.get("type") == "video" and (vid := bq._youtube(b.get("url"))):
            cartes.append(f'<a class="mq-story" href="https://www.youtube.com/watch?v={vid}" target="_blank" rel="noopener">'
                          f'<img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy"><i class="mq-lecture">{ICO_LECTURE}</i></a>')
        elif b.get("type") == "galerie":
            cartes += [f'<span class="mq-story"><img src="{bq._img(pseudo, i)}" alt="" loading="lazy"></span>' for i in (b.get("images") or [])[:6] if i]
    for p in prods:
        if p.get("image"):
            cartes.append(f'<a class="mq-story" href="{_lien_produit(page, pseudo, p)}"><img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">'
                          f'<b>{E(p.get("titre") or "")}</b></a>')
    stories = f'<section class="mq-stories">{"".join(cartes[:10])}</section>' if cartes else ""

    # Manifeste : le nom en italique dans la couleur d'accent, la présentation en grand
    reseaux = "".join(f'<a href="{E(u)}" target="_blank" rel="noopener" aria-label="{E(bq.RESEAUX[k][0])}"><svg viewBox="0 0 24 24">{bq.ICONES[k]}</svg></a>'
                      for k, v in (page.get("reseaux") or {}).items() if k in bq.ICONES and (u := bq.lien_reseau(k, v)))
    bio = (page.get("bio") or "").strip()
    manif = (f'<section class="mq-manif">{f"<nav class=mq-reseaux>{reseaux}</nav>" if reseaux else ""}'
             f'<p><em>{E(nom)}</em>{f" · {E(bio)}" if bio else ""}</p></section>')

    def boutique(liste, titre, premier):
      grille = []
      for p in liste:
        prix, barre, pastille = _prix(p)
        img = f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>'
        st = f'<small>{E(p["sous_titre"])}</small>' if p.get("sous_titre") else ""
        grille.append(f'<a class="mq-prod" href="{_lien_produit(page, pseudo, p)}"><span class="mq-img">{img}'
                      f'{f"<span class=mq-pastille>{E(pastille)}</span>" if pastille else ""}<i class="mq-plus">{ICO_PLUS}</i></span>'
                      f'<b>{E(p.get("titre") or "")}</b>{st}'
                      f'<span class="mq-prix">{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span></a>')
      if not grille:
          return f'<span{_ancre(premier)}></span>'
      return (f'<section class="mq-boutique"{_ancre(premier)}>{f"<h2>{E(titre)}</h2>" if titre else ""}'
              f'<div class="mq-grille">{"".join(grille)}</div></section>')

    def plus(inner, premier):
        return f'<section class="mq-plus-sec"{' id="plus"' if premier else ""}><div class="blocs">{inner}</div></section>'

    corps = _assemble(page, pseudo, "marque", {"mq_stories": stories, "mq_manif": manif}, boutique, plus)
    bulle = (f'<a class="mq-bulle" href="{E(contact[0])}" target="_blank" rel="noopener" aria-label="{E(contact[1])}">{ICO_BULLE}</a>' if contact else "")
    return (f'{haut}{corps}{bq.badge(page)}'
            f'<div class="mq-flottants">{bulle}<a class="mq-haut-btn" href="#haut" aria-label="Revenir en haut">{ICO_HAUT}</a></div>')


CSS = """
/* ===== Appli ===== */
.ap-haut{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin:6px 0 18px}
.ap-logo{font:800 30px/1.05 var(--tf);margin:0;letter-spacing:-.02em}.ap-logo em{font-style:normal;color:var(--a)}
.ap-salut{margin:6px 0 0;opacity:.7;font-size:.98em}
.ap-icones{display:flex;gap:8px;flex:none}
.ap-rond,.ap-avatar{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background:var(--k);color:var(--kt);
  box-shadow:0 8px 22px -14px rgba(0,0,0,.45);object-fit:cover;flex:none}
.ap-rond svg{width:22px;height:22px;fill:currentColor}.ap-avatar.vide{background:var(--a);color:var(--ac);font:700 20px var(--tf)}
.ap-hero{margin:0 -2px 8px}
.ap-piste{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;gap:12px;border-radius:28px}
.ap-piste::-webkit-scrollbar{display:none}
.ap-slide{flex:0 0 100%;scroll-snap-align:center;position:relative;min-height:330px;border-radius:28px;overflow:hidden;text-decoration:none;
  display:flex;flex-direction:column;justify-content:space-between;padding:26px 22px 22px;color:color-mix(in srgb,var(--a) 72%,#000);
  background:linear-gradient(165deg,color-mix(in srgb,var(--a) 10%,var(--k)),color-mix(in srgb,var(--a) 32%,var(--k)))}
.ap-slide-txt{position:relative;z-index:1;max-width:62%}
.ap-slide h2{font:800 clamp(26px,7.4vw,40px)/.98 var(--tf);margin:0 0 10px;text-transform:uppercase;letter-spacing:-.02em;overflow-wrap:anywhere}
.ap-slide p{margin:0 0 18px;font-weight:600;color:var(--kt);opacity:.85}
.ap-cta{display:inline-block;background:color-mix(in srgb,var(--a) 75%,#000);color:#fff;font-weight:800;letter-spacing:.06em;
  text-transform:uppercase;font-size:14px;padding:14px 24px;border-radius:999px}
.ap-slide img{position:absolute;right:-6%;bottom:-4%;width:58%;height:78%;object-fit:contain;filter:drop-shadow(0 18px 24px rgba(0,0,0,.28))}
.ap-points{display:flex;justify-content:center;gap:6px;margin:12px 0 0}
.ap-points button{width:22px;height:5px;border:0;border-radius:3px;background:color-mix(in srgb,var(--t) 18%,transparent);padding:0;cursor:pointer}
.ap-points button[aria-current=true]{width:42px;background:var(--t)}
.ap-t{font:800 26px/1.1 var(--tf);margin:30px 0 16px;letter-spacing:-.02em}
.ap-ronds{display:grid;grid-template-columns:repeat(3,1fr);gap:18px 12px}
.ap-rond-p{text-decoration:none;text-align:center;display:flex;flex-direction:column;align-items:center;gap:10px}
.ap-rond-p span{width:100%;aspect-ratio:1;border-radius:50%;display:grid;place-items:center;overflow:hidden;
  background:color-mix(in srgb,var(--a) 16%,var(--k))}
.ap-rond-p.r1 span{background:color-mix(in srgb,var(--b) 30%,var(--k))}.ap-rond-p.r2 span{background:color-mix(in srgb,var(--a) 8%,#FCE3DC)}
.ap-rond-p.r3 span{background:color-mix(in srgb,var(--a) 8%,#FFF1C9)}.ap-rond-p.r4 span{background:color-mix(in srgb,var(--a) 8%,#E7E2FA)}
.ap-rond-p.r5 span{background:color-mix(in srgb,var(--a) 8%,#DDF2E6)}
.ap-rond-p img{width:74%;height:74%;object-fit:contain}
.ap-rond-p b{font-size:13px;letter-spacing:.08em;text-transform:uppercase;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ap-rail{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;margin:0 -16px;padding:4px 16px 8px}
.ap-rail::-webkit-scrollbar{display:none}
.ap-carte{flex:0 0 min(62%,240px);scroll-snap-align:start;position:relative;text-decoration:none;text-align:center;border-radius:28px;
  padding:14px 14px 20px;background:color-mix(in srgb,var(--a) 5%,var(--k));color:var(--kt);display:flex;flex-direction:column;gap:6px}
.ap-pastille{position:absolute;top:12px;left:12px;z-index:2;background:var(--t);color:var(--f1);font-weight:700;font-size:13px;padding:6px 12px;border-radius:999px}
.ap-img{position:relative;aspect-ratio:1/1.05;display:grid;place-items:center;margin-bottom:6px}
.ap-img img{width:84%;height:92%;object-fit:contain}
.ap-vide{width:70%;aspect-ratio:1;border-radius:20px;background:color-mix(in srgb,var(--a) 18%,transparent)}
.ap-sac{position:absolute;right:0;bottom:4px;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;background:var(--a);color:var(--ac);
  box-shadow:0 10px 22px -10px var(--a)}.ap-sac svg{width:24px;height:24px}
.ap-carte b{font-size:1.08em;line-height:1.2}.ap-prix{font:800 1.3em var(--tf)}.ap-prix s,.mq-prix s{font-size:.7em;opacity:.5;font-weight:500}
.ap-blocs{margin:28px 0}.ap-blocs+.ap-conseil,.ap-blocs:last-child{margin-bottom:0}
.ap-conseil{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:28px 0 8px;padding:22px 22px;border-radius:28px;
  background:var(--t);color:var(--f1);text-decoration:none}
.ap-conseil span{display:flex;flex-direction:column;gap:4px}.ap-conseil b{font:800 1.4em/1.1 var(--tf)}.ap-conseil small{opacity:.75;font-size:1em}
.ap-conseil i{width:54px;height:54px;flex:none;border-radius:50%;display:grid;place-items:center;background:color-mix(in srgb,var(--a) 30%,#fff);color:#111}
.ap-conseil i svg{width:24px}
.ap-nav{position:fixed;left:50%;transform:translateX(-50%);bottom:max(12px,env(safe-area-inset-bottom));z-index:20;width:min(568px,calc(100% - 24px));
  display:flex;gap:4px;padding:8px;border-radius:30px;background:var(--t);box-shadow:0 18px 40px -16px rgba(0,0,0,.6)}
.ap-nav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:9px 4px;border-radius:22px;text-decoration:none;
  color:color-mix(in srgb,var(--f1) 70%,transparent);font-size:12.5px;font-weight:600}
.ap-nav a svg{width:24px;height:24px}
.ap-nav a[aria-current]{background:color-mix(in srgb,var(--a) 28%,var(--f1));color:var(--t)}
/* ===== Marque ===== */
body.mp-marque .page{max-width:1080px;padding:0 0 90px}
.mq-haut{position:sticky;top:0;z-index:15;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;
  background:color-mix(in srgb,var(--f1) 88%,transparent);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
.mq-nom{display:flex;align-items:center;gap:10px;text-decoration:none;font:600 26px/1 var(--tf);letter-spacing:-.01em}
.mq-logo{width:46px;height:46px;border-radius:12px;object-fit:cover}
.mq-menu{position:relative}.mq-menu summary{list-style:none;cursor:pointer;width:56px;height:56px;border-radius:50%;background:var(--a);
  display:flex;flex-direction:column;justify-content:center;align-items:center;gap:7px}
.mq-menu summary::-webkit-details-marker{display:none}.mq-menu summary i{display:block;width:24px;height:2.5px;border-radius:2px;background:var(--ac)}
.mq-menu nav{position:absolute;right:0;top:64px;min-width:220px;display:flex;flex-direction:column;padding:8px;border-radius:18px;background:var(--k);
  box-shadow:0 22px 50px -20px rgba(0,0,0,.45)}
.mq-menu nav a{padding:12px 14px;border-radius:12px;text-decoration:none;font-weight:600;color:var(--kt)}
.mq-menu nav a:hover{background:color-mix(in srgb,var(--a) 12%,transparent)}
.mq-stories{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;padding:6px 18px 26px}
.mq-stories::-webkit-scrollbar{display:none}
.mq-story{flex:0 0 min(46%,260px);aspect-ratio:9/15;scroll-snap-align:start;position:relative;border-radius:18px;overflow:hidden;
  background:color-mix(in srgb,var(--a) 12%,var(--k));box-shadow:0 14px 28px -18px rgba(0,0,0,.5);text-decoration:none}
.mq-story img{width:100%;height:100%;object-fit:cover;display:block}
.mq-story b{position:absolute;left:12px;right:12px;bottom:12px;color:#fff;font:700 1.05em/1.2 var(--tf);text-shadow:0 2px 12px rgba(0,0,0,.6)}
.mq-story:has(b)::after{content:"";position:absolute;inset:55% 0 0;background:linear-gradient(transparent,rgba(0,0,0,.55))}
.mq-story b{z-index:1}
.mq-lecture{position:absolute;inset:0;margin:auto;width:60px;height:60px;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,255,255,.85);color:#111}.mq-lecture svg{width:26px;fill:currentColor;margin-left:3px}
.mq-manif{background:color-mix(in srgb,var(--a) 7%,var(--f1));padding:44px 22px 46px}
.mq-reseaux{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:26px}
.mq-reseaux a{width:58px;height:58px;display:grid;place-items:center;border-radius:18px;border:2px solid var(--t);color:var(--t);
  background:linear-gradient(135deg,transparent 55%,var(--a) 55%)}
.mq-reseaux svg{width:28px;height:28px;fill:currentColor}
.mq-manif p{margin:0;font:400 clamp(26px,6.6vw,44px)/1.22 var(--tx);letter-spacing:-.01em;max-width:900px}
.mq-manif em{font-family:'Playfair Display',var(--tf),Georgia,serif;font-style:italic;color:var(--a);font-weight:600}
.mq-boutique{padding:34px 18px 10px}
.mq-boutique h2{font:600 clamp(26px,6vw,40px)/1.05 var(--tf);margin:0 0 18px;letter-spacing:-.01em}
.mq-grille{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 14px}
@media (min-width:760px){.mq-grille{grid-template-columns:repeat(4,minmax(0,1fr))}.mq-story{flex-basis:230px}}
.mq-prod{text-decoration:none;display:flex;flex-direction:column;gap:5px}
.mq-img{position:relative;aspect-ratio:4/5;border-radius:16px;overflow:hidden;background:color-mix(in srgb,var(--a) 9%,var(--k));display:grid;place-items:center}
.mq-img img{width:100%;height:100%;object-fit:cover}
.mq-pastille{position:absolute;top:10px;left:10px;background:var(--a);color:var(--ac);font-weight:700;font-size:12.5px;padding:5px 10px;border-radius:999px}
.mq-plus{position:absolute;right:10px;bottom:10px;width:40px;height:40px;border-radius:50%;background:var(--k);color:var(--kt);display:grid;place-items:center;
  box-shadow:0 6px 16px -8px rgba(0,0,0,.5)}.mq-plus svg{width:20px}
.mq-prod b{font-weight:600;line-height:1.25;margin-top:6px}.mq-prod small{opacity:.65;font-size:.88em;line-height:1.3}
.mq-prix{font-weight:700}
.mq-plus-sec{padding:20px 18px 0;max-width:620px;margin:0 auto}
.mq-flottants{position:fixed;right:16px;bottom:max(16px,env(safe-area-inset-bottom));z-index:20;display:flex;flex-direction:column;align-items:center;gap:12px}
.mq-bulle{width:60px;height:60px;border-radius:50%;display:grid;place-items:center;background:var(--b);color:var(--bt);box-shadow:0 14px 30px -12px rgba(0,0,0,.45)}
.mq-bulle svg{width:26px}
.mq-haut-btn{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;background:var(--k);color:var(--kt);box-shadow:0 8px 20px -10px rgba(0,0,0,.4)}
.mq-haut-btn svg{width:22px}
body.mp-marque .marque{margin-top:30px}
"""


# ------------------------------------------------------------
#  Autres modèles Appli (même barre du haut, même carte « Une question ? », mêmes onglets en bas)
# ------------------------------------------------------------
def _carte_info(p: dict) -> tuple[str, str, str, str]:
    prix, barre, pastille = _prix(p)
    return prix, barre, pastille, p.get("sous_titre") or ""


def rendu_appli_stories(page: dict, pseudo: str, apercu: bool = False) -> str:
    """Façon Instagram : ronds de stories en haut, carte de profil, puis un fil de publications (une par produit)."""
    nom = page.get("nom") or pseudo
    prods = _produits(page)
    photo = page.get("photo")
    mini = (f'<img src="{bq._img(pseudo, photo)}" alt="">' if photo else f'<span>{E(nom[:1].upper())}</span>')
    ronds = [f'<a class="st-rond" href="#profil"><i>{mini}</i><b>À propos</b></a>'] + [
        f'<a class="st-rond" href="{_lien_produit(page, pseudo, p)}"><i>'
        + (f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else f'<span>{E((p.get("titre") or "?")[:1].upper())}</span>')
        + f'</i><b>{E(p.get("titre") or "")}</b></a>'
        for p in prods][:10]
    sans_profil = (page.get("design") or {}).get("profil_appli") == "masquer"
    if sans_profil:
        ronds = ronds[1:]
    profil = "" if sans_profil else (f'<section class="st-profil" id="profil"><i class="st-pp">{mini}</i><div><b>{E(nom)}</b>'
              f'<p>{E(page.get("bio") or "")}</p>'
              f'<a class="st-suivre" href="#boutique">Voir la boutique</a></div></section>')
    def fil(liste, titre, premier):
      posts = []
      for p in liste:
        prix, barre, pastille, sous = _carte_info(p)
        img = (f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>')
        posts.append(f'<article class="st-post" id="p-{E(p["id"])}"><header><i class="st-mini">{mini}</i><b>{E(nom)}</b>'
                     f'{f"<span class=st-pastille>{E(pastille)}</span>" if pastille else ""}</header>'
                     f'<a class="st-img" href="{_lien_produit(page, pseudo, p)}">{img}</a>'
                     f'<div class="st-pied"><div><b>{E(p.get("titre") or "")}</b>{f"<p>{E(sous)}</p>" if sous else ""}</div>'
                     f'<a class="st-voir" href="{_lien_produit(page, pseudo, p)}"><span>{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span>Voir l\'offre</a></div></article>')
      if not posts:
          return f'<span{_ancre(premier)}></span>'
      t = f'<h2 class="ap-t">{E(titre)}</h2>' if titre and not premier else ""
      return f'{t}<section class="st-fil"{_ancre(premier)}>{"".join(posts)}</section>'

    corps = _assemble(page, pseudo, "appli_stories", {"st_ronds": f'<nav class="st-ronds">{"".join(ronds)}</nav>' if ronds else "",
                                                     "st_profil": profil, "contact": _section_contact(page)}, fil)
    return f'<div class="ap ca-{_cartes(page)}">{_haut_appli(page, pseudo)}{corps}{_bas_appli(page, pseudo, bool(prods))}'


SCRIPT_CATALOGUE = """
<script>
(() => { const q = document.querySelector("[data-cherche]"), puces = [...document.querySelectorAll("[data-filtre]")],
    cartes = [...document.querySelectorAll("[data-cats]")], vide = document.querySelector("[data-aucun]");
  if (!cartes.length) return; let filtre = "tout";
  const maj = () => { const t = (q?.value || "").trim().toLowerCase(); let n = 0;
    cartes.forEach(c => { const ok = (filtre === "tout" || c.dataset.cats.split(" ").includes(filtre)) && (!t || c.dataset.nom.includes(t));
      c.hidden = !ok; n += ok; }); if (vide) vide.hidden = n > 0; };
  q?.addEventListener("input", maj);
  puces.forEach(p => p.addEventListener("click", () => { filtre = p.dataset.filtre;
    puces.forEach(x => x.setAttribute("aria-pressed", x === p)); maj(); }));
})();
</script>"""


def rendu_appli_catalogue(page: dict, pseudo: str, apercu: bool = False) -> str:
    """Façon appli de shopping : recherche, puces de filtres, bannière de mise en avant, grille de produits sur deux colonnes."""
    prods = _produits(page)
    cats_vues: dict[str, str] = {}

    def infos(p):
        prix, barre, pastille, sous = _carte_info(p)
        cats = []
        if prix == "Gratuit":
            cats.append("gratuit")
        if barre:
            cats.append("promo")
        if p.get("type") == "rdv":
            cats.append("seance")
        if p.get("type") == "pack":
            cats.append("pack")
        if p.get("externe"):
            cats.append("partenaire")
        return prix, barre, pastille, sous, cats

    for p in prods:
        for c in infos(p)[4]:
            cats_vues[c] = 1

    def grille(liste, titre, premier):
      cartes = []
      for p in liste:
        prix, barre, pastille, sous, cats = infos(p)
        img = (f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>')
        cartes.append(f'<a class="ca-carte" href="{_lien_produit(page, pseudo, p)}" data-cats="{" ".join(cats)}" data-nom="{E((p.get("titre") or "").lower())}">'
                      f'<span class="ca-img">{img}{f"<span class=ca-pastille>{E(pastille)}</span>" if pastille else ""}'
                      f'<i class="ca-plus">{ICO_PLUS}</i></span><b>{E(p.get("titre") or "")}</b>{f"<small>{E(sous)}</small>" if sous else ""}'
                      f'<span class="ca-prix">{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span></a>')
      if not cartes:
          return f'<span{_ancre(premier)}></span>'
      return (f'{f"<h2 class=\"ap-t\"{_ancre(premier)}>{E(titre)}</h2>" if titre else ""}<div class="ca-grille"{"" if titre else _ancre(premier)}>{"".join(cartes)}</div>'
              + ('<p class="ca-aucun" data-aucun hidden>Aucun produit ne correspond.</p>' if premier else ""))

    noms = {"gratuit": "Gratuits", "promo": "Promos", "seance": "Séances", "pack": "Packs", "partenaire": "Partenaires"}
    puces = ('<div class="ca-puces"><button type="button" data-filtre="tout" aria-pressed="true">Tout</button>'
             + "".join(f'<button type="button" data-filtre="{k}" aria-pressed="false">{v}</button>' for k, v in noms.items() if k in cats_vues)
             + "</div>") if cats_vues and len(prods) > 3 else ""
    cherche = ('<label class="ca-cherche"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/>'
               '<path d="M20 20l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
               '<input data-cherche type="search" placeholder="Rechercher un produit" aria-label="Rechercher un produit"></label>') if len(prods) > 4 else ""
    une = next((p for p in prods if p.get("image")), None)
    banniere = ""
    if une:
        prix, barre, pastille, sous = _carte_info(une)
        banniere = (f'<a class="ca-banniere" href="{_lien_produit(page, pseudo, une)}"><div><small>{E(pastille or "À découvrir")}</small>'
                    f'<b>{E(une.get("titre") or "")}</b><em>{E(prix)}</em><span class="ap-cta">Je découvre</span></div>'
                    f'<img src="{bq._img(pseudo, une["image"])}" alt="" loading="lazy"></a>')
    corps = _assemble(page, pseudo, "appli_catalogue", {"ca_recherche": cherche + puces, "ca_banniere": banniere,
                                                       "contact": _section_contact(page)}, grille)
    return (f'<div class="ap">{_haut_appli(page, pseudo)}{corps}'
            f'{_bas_appli(page, pseudo, bool(prods))}{SCRIPT_CATALOGUE}')


MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def rendu_appli_une(page: dict, pseudo: str, apercu: bool = False) -> str:
    """Façon « Aujourd'hui » de l'App Store : la date, de grandes cartes illustrées, puis la liste compacte de toutes les offres."""
    from datetime import date
    nom = page.get("nom") or pseudo
    prods = _produits(page)
    photo = page.get("photo")
    d = date.today()
    avatar = (f'<img class="ap-avatar" src="{bq._img(pseudo, photo)}" alt="">' if photo
              else f'<span class="ap-avatar vide">{E(nom[:1].upper())}</span>')
    haut = (f'<header class="un-haut" id="haut"><div><small>{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}</small>'
            f'<h1>{E(nom)}</h1></div><a href="#profil" aria-label="À propos">{avatar}</a></header>')
    icone = (f'<img src="{bq._img(pseudo, photo)}" alt="">' if photo else f'<span>{E(nom[:1].upper())}</span>')
    grandes = []
    for p in [p for p in prods if p.get("image")][:4]:
        prix, barre, pastille, sous = _carte_info(p)
        grandes.append(f'<a class="un-carte" href="{_lien_produit(page, pseudo, p)}"><span class="un-visuel">'
                       f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy"><span class="un-txt"><small>{E(pastille or "À la une")}</small>'
                       f'<b>{E(p.get("titre") or "")}</b>{f"<em>{E(sous)}</em>" if sous else ""}</span></span>'
                       f'<span class="un-bas"><i class="un-ico">{icone}</i><span><b>{E(nom)}</b><small>{E(prix)}{f" · au lieu de {E(barre)}" if barre else ""}</small></span>'
                       f'<span class="un-voir">Voir</span></span></a>')
    def liste(prods_bloc, titre, premier):
        lignes = []
        for p in prods_bloc:
            prix, barre, pastille, sous = _carte_info(p)
            img = (f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else f'<span>{E((p.get("titre") or "?")[:1])}</span>')
            lignes.append(f'<a class="un-ligne" href="{_lien_produit(page, pseudo, p)}"><i class="un-ico">{img}</i><span><b>{E(p.get("titre") or "")}</b>'
                          f'<small>{E(sous or prix)}</small></span><span class="un-voir">{E("Gratuit" if prix == "Gratuit" else prix)}</span></a>')
        if not lignes:
            return f'<span{_ancre(premier)}></span>'
        return f'{f"<h2 class=\"ap-t\"{_ancre(premier)}>{E(titre)}</h2>" if titre else ""}<div class="un-liste"{"" if titre else _ancre(premier)}>{"".join(lignes)}</div>'
    profil = '<span id="profil"></span>' if (page.get("design") or {}).get("profil_appli") == "masquer" else (f'<section class="un-profil" id="profil"><i class="un-ico">{icone}</i><div><b>{E(nom)}</b><p>{E(page.get("bio") or "")}</p></div></section>'
              if page.get("bio") else '<span id="profil"></span>')
    corps = _assemble(page, pseudo, "appli_une", {"un_grandes": "".join(grandes), "un_profil": profil, "contact": _section_contact(page)}, liste)
    return f'<div class="ap ca-{_cartes(page)}">{haut}{corps}{_bas_appli(page, pseudo, bool(prods))}'


CSS_CARTES = """
/* Taille des cartes produits (réglage du design) — préfixe .ap pour passer devant les règles de base */
.ap .st-pied p,.ap .un-txt em{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:5;overflow:hidden}
.ap .st-pied b{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.ap .st-voir{white-space:nowrap}
/* Moyenne */
.ap.ca-moyenne .st-img{aspect-ratio:4/3}.ap.ca-moyenne .st-pied p{-webkit-line-clamp:4}
.ap.ca-moyenne .un-visuel{aspect-ratio:4/3}.ap.ca-moyenne .ap-slide{min-height:240px}
.ap.ca-moyenne .ap-carte{flex-basis:min(48%,200px)}
/* Compacte : une ligne par produit */
.ap.ca-compacte .st-fil{gap:12px}
.ap.ca-compacte .st-post{display:grid;grid-template-columns:96px minmax(0,1fr);align-items:stretch;border-radius:20px;padding:8px;gap:12px}
.ap.ca-compacte .st-post header{display:none}
.ap.ca-compacte .st-img{aspect-ratio:1;width:96px;height:96px;align-self:center;border-radius:14px;overflow:hidden}
.ap.ca-compacte .st-pied{flex-direction:column;align-items:flex-start;justify-content:center;gap:8px;padding:2px 4px 2px 0}
.ap.ca-compacte .st-pied>div{width:100%}.ap.ca-compacte .st-pied b{font-size:1em;line-height:1.25}
.ap.ca-compacte .st-pied p{-webkit-line-clamp:4;font-size:.86em;line-height:1.35}
.ap.ca-compacte .st-voir{flex-direction:row;align-items:center;gap:8px;padding:7px 14px;font-size:12.5px;border-radius:999px}
.ap.ca-compacte .st-voir span{font-size:1.05em}
.ap.ca-compacte .un-carte,.ap.ca-compacte .ap-hero{display:none}
.ap.ca-compacte .ap-rail{flex-direction:column;overflow:visible;margin:0;padding:0;gap:10px}
.ap.ca-compacte .ap-carte{flex:none;display:grid;grid-template-columns:76px minmax(0,1fr) auto;align-items:center;gap:2px 14px;text-align:left;padding:8px 14px 8px 8px;border-radius:20px}
.ap.ca-compacte .ap-carte .ap-img{grid-row:1 / span 2;width:76px;height:76px;margin:0;aspect-ratio:1;border-radius:14px}
.ap.ca-compacte .ap-sac{display:none}.ap.ca-compacte .ap-carte b{align-self:end;font-size:1em}
.ap.ca-compacte .ap-carte .ap-prix{grid-column:2;align-self:start;font-size:1em}
.ap.ca-compacte .ap-pastille{position:static;grid-column:3;grid-row:1 / span 2;font-size:11px;padding:4px 9px}
/* 2 par ligne */
.ap.ca-deux .st-fil{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.ap.ca-deux .st-post{border-radius:20px;display:flex;flex-direction:column}
.ap.ca-deux .st-post header{display:none}
.ap.ca-deux .st-img{aspect-ratio:1}
.ap.ca-deux .st-pied{flex:1;flex-direction:column;align-items:stretch;justify-content:space-between;padding:10px 12px 12px;gap:10px}
.ap.ca-deux .st-pied b{font-size:.95em;line-height:1.25}.ap.ca-deux .st-pied p{-webkit-line-clamp:3;font-size:.82em;line-height:1.35}
.ap.ca-deux .st-voir{flex-direction:row;justify-content:space-between;align-items:center;gap:6px;padding:8px 12px;font-size:12px;border-radius:999px}
.ap.ca-deux .st-voir span{font-size:1.1em}
.ap.ca-deux .un-carte{display:inline-block;width:calc(50% - 6px);vertical-align:top;margin:0 0 12px}.ap.ca-deux .un-carte:nth-of-type(odd){margin-right:12px}
.ap.ca-deux .un-visuel{aspect-ratio:1}.ap.ca-deux .un-txt em,.ap.ca-deux .un-bas small{display:none}
.ap.ca-deux .ap-hero{display:none}.ap.ca-deux .ap-rail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible;margin:0;padding:0}
.ap.ca-deux .ap-carte{flex:none}
"""
CSS += CSS_CARTES

RENDUS = {"appli": rendu_appli, "appli_stories": rendu_appli_stories, "appli_catalogue": rendu_appli_catalogue,
          "appli_une": rendu_appli_une, "marque": rendu_marque}

CSS += """
body[class*="mp-appli"] .page{max-width:600px;padding:18px 16px 120px}
body[class*="mp-appli"] .marque{margin-bottom:10px}
/* ===== Appli Stories ===== */
.st-ronds{display:flex;gap:14px;overflow-x:auto;scrollbar-width:none;margin:0 -16px 18px;padding:2px 16px 6px}.st-ronds::-webkit-scrollbar{display:none}
.st-rond{flex:none;width:76px;display:flex;flex-direction:column;align-items:center;gap:6px;text-decoration:none;color:inherit;cursor:pointer;position:relative;z-index:1}
.st-rond i{width:72px;height:72px;border-radius:50%;padding:3px;background:conic-gradient(from 200deg,var(--a),var(--b),var(--a));display:grid}
.st-rond i>*{width:100%;height:100%;border-radius:50%;object-fit:cover;border:3px solid var(--f1);background:var(--k);display:grid;place-items:center;font:700 22px var(--tf)}
.st-rond b{font-size:12px;font-weight:600;max-width:76px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st-profil{display:flex;gap:16px;align-items:flex-start;padding:18px;border-radius:24px;background:var(--k);color:var(--kt);margin-bottom:22px}
.st-pp,.st-mini{flex:none;border-radius:50%;overflow:hidden;display:grid;place-items:center;background:var(--a);color:var(--ac);font:700 18px var(--tf)}
.st-pp{width:72px;height:72px}.st-pp img,.st-mini img{width:100%;height:100%;object-fit:cover}
.st-profil b{font:800 1.2em var(--tf)}.st-profil p{margin:4px 0 12px;opacity:.8;white-space:pre-line}
.st-suivre{display:inline-block;background:var(--a);color:var(--ac);font-weight:700;padding:10px 20px;border-radius:12px;text-decoration:none}
.st-fil{display:flex;flex-direction:column;gap:22px}
.st-post{background:var(--k);color:var(--kt);border-radius:24px;overflow:hidden;box-shadow:0 14px 30px -24px rgba(0,0,0,.5)}
.st-post header{display:flex;align-items:center;gap:10px;padding:12px 14px}.st-mini{width:34px;height:34px;font-size:14px}
.st-post header b{flex:1;font-size:.95em}
.st-pastille{background:var(--a);color:var(--ac);font-size:12px;font-weight:700;padding:5px 10px;border-radius:999px}
.st-img{display:block;aspect-ratio:1;background:color-mix(in srgb,var(--a) 10%,var(--k))}.st-img img{width:100%;height:100%;object-fit:cover;display:block}
.st-img .ap-vide{display:block;width:100%;height:100%;border-radius:0}
.st-pied{display:flex;align-items:center;gap:12px;padding:14px}.st-pied>div{flex:1;min-width:0}
.st-pied b{font-weight:700}.st-pied p{margin:3px 0 0;opacity:.7;font-size:.92em}
.st-voir{flex:none;display:flex;flex-direction:column;align-items:center;gap:2px;background:var(--t);color:var(--f1);text-decoration:none;
  font-weight:700;font-size:13px;padding:10px 16px;border-radius:16px}.st-voir span{font:800 1.15em var(--tf)}.st-voir s{opacity:.6;font-size:.75em}
/* ===== Appli Catalogue ===== */
.ca-cherche{display:flex;align-items:center;gap:10px;background:var(--k);color:var(--kt);border-radius:999px;padding:0 18px;margin:0 0 14px;
  box-shadow:0 8px 22px -18px rgba(0,0,0,.5)}
.ca-cherche svg{width:20px;height:20px;opacity:.6;flex:none}
.ca-cherche input{flex:1;border:0;background:none;font:inherit;color:inherit;padding:15px 0;outline:none}
.ca-puces{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;margin:0 -16px 16px;padding:0 16px}.ca-puces::-webkit-scrollbar{display:none}
.ca-puces button{flex:none;border:1.5px solid color-mix(in srgb,var(--t) 15%,transparent);background:transparent;color:var(--t);font:600 14px var(--tx);
  padding:9px 18px;border-radius:999px;cursor:pointer}
.ca-puces button[aria-pressed=true]{background:var(--t);color:var(--f1);border-color:var(--t)}
.ca-banniere{display:flex;align-items:center;gap:10px;min-height:170px;padding:22px;border-radius:26px;background:var(--t);color:var(--f1);
  text-decoration:none;overflow:hidden;position:relative}
.ca-banniere div{flex:1;position:relative;z-index:1;display:flex;flex-direction:column;gap:8px;align-items:flex-start}
.ca-banniere small{text-transform:uppercase;letter-spacing:.12em;font-weight:700;font-size:12px;color:color-mix(in srgb,var(--a) 60%,var(--f1))}
.ca-banniere b{font:800 clamp(22px,6vw,30px)/1.05 var(--tf)}
.ca-banniere .ap-cta{background:var(--a);color:var(--ac);font-size:13px;padding:11px 18px}
.ca-banniere em{font:800 1.15em var(--tf);font-style:normal;opacity:.85}
.ca-banniere img{width:42%;max-height:170px;object-fit:contain;filter:drop-shadow(0 12px 18px rgba(0,0,0,.35))}
.ca-grille{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 12px}
.ca-carte{text-decoration:none;display:flex;flex-direction:column;gap:4px}.ca-carte[hidden]{display:none}
.ca-img{position:relative;aspect-ratio:1;border-radius:20px;overflow:hidden;background:color-mix(in srgb,var(--a) 8%,var(--k));display:grid;place-items:center;margin-bottom:6px}
.ca-img img{width:86%;height:86%;object-fit:contain}
.ca-pastille{position:absolute;top:8px;left:8px;background:var(--a);color:var(--ac);font-weight:700;font-size:12px;padding:4px 9px;border-radius:999px}
.ca-plus{position:absolute;right:8px;bottom:8px;width:36px;height:36px;border-radius:50%;background:var(--t);color:var(--f1);display:grid;place-items:center}
.ca-plus svg{width:18px}
.ca-carte b{font-weight:700;line-height:1.25}.ca-carte small{opacity:.65;font-size:.86em;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ca-prix{font:800 1.1em var(--tf)}.ca-prix s{font-size:.75em;opacity:.5;font-weight:500}
.ca-aucun{text-align:center;opacity:.6;margin:20px 0}
/* ===== Appli À la une ===== */
.un-haut{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:6px 0 18px}
.un-haut small{text-transform:uppercase;letter-spacing:.06em;font-weight:700;font-size:13px;opacity:.55}
.un-haut h1{font:800 34px/1.05 var(--tf);margin:2px 0 0;letter-spacing:-.02em}
.un-carte{display:block;margin:0 0 22px;border-radius:26px;overflow:hidden;text-decoration:none;background:var(--k);color:var(--kt);
  box-shadow:0 22px 40px -26px rgba(0,0,0,.55)}
.un-visuel{position:relative;display:block;aspect-ratio:4/4.4;background:color-mix(in srgb,var(--a) 22%,var(--k))}
.un-visuel img{width:100%;height:100%;object-fit:cover;display:block}
.un-txt{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:flex-end;gap:6px;padding:22px;color:#fff;
  background:linear-gradient(180deg,transparent 40%,rgba(0,0,0,.62))}
.un-txt small{text-transform:uppercase;letter-spacing:.1em;font-weight:700;font-size:12px;opacity:.9}
.un-txt b{font:800 clamp(26px,7.4vw,36px)/1.02 var(--tf);letter-spacing:-.02em}.un-txt em{font-style:normal;opacity:.9}
.un-bas,.un-ligne{display:flex;align-items:center;gap:12px;padding:14px 16px}
.un-bas>span:not(.un-voir),.un-ligne>span:not(.un-voir){flex:1;min-width:0;display:flex;flex-direction:column}
.un-bas b,.un-ligne b{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.un-bas small,.un-ligne small{opacity:.65;font-size:.88em}
.un-ico{flex:none;width:52px;height:52px;border-radius:14px;overflow:hidden;display:grid;place-items:center;background:var(--a);color:var(--ac);font:800 20px var(--tf)}
.un-ico img{width:100%;height:100%;object-fit:cover}
.un-voir{flex:none;background:color-mix(in srgb,var(--a) 14%,var(--k));color:var(--a);font-weight:800;font-size:14px;padding:8px 18px;border-radius:999px;
  text-transform:uppercase;letter-spacing:.02em}
.un-liste{background:var(--k);color:var(--kt);border-radius:24px;overflow:hidden}
.un-ligne{text-decoration:none;border-top:1px solid color-mix(in srgb,var(--kt) 10%,transparent)}.un-ligne:first-child{border-top:0}
.un-ligne .un-voir{font-size:13px;padding:7px 14px;text-transform:none}
.un-profil{display:flex;gap:14px;align-items:flex-start;margin:22px 0;padding:18px;border-radius:24px;background:var(--k);color:var(--kt)}
.un-profil b{font:800 1.1em var(--tf)}.un-profil p{margin:4px 0 0;opacity:.8;white-space:pre-line}
"""
