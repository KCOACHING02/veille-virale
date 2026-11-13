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

DEJA_DANS_LA_PAGE = ("produits", "produit")  # rendus par les sections de la mise en page


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
def rendu_appli(page: dict, pseudo: str, apercu: bool = False) -> str:
    nom = page.get("nom") or pseudo
    prods = _produits(page)
    avec_image = [p for p in prods if p.get("image")]
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
    haut = (f'<header class="ap-haut" id="haut"><div class="ap-id"><p class="ap-logo">{logo}</p>{salut}</div>'
            f'<div class="ap-icones">{boutons}{avatar}</div></header>')

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

    # Rail de produits
    cartes = []
    for p in prods:
        prix, barre, pastille = _prix(p)
        img = f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>'
        cartes.append(f'<a class="ap-carte" href="{_lien_produit(page, pseudo, p)}">{f"<span class=ap-pastille>{E(pastille)}</span>" if pastille else ""}'
                      f'<span class="ap-img">{img}<span class="ap-sac" aria-hidden="true">{ICO_SAC}</span></span>'
                      f'<b>{E(p.get("titre") or "")}</b><span class="ap-prix">{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span></a>')
    rail = (f'<h2 class="ap-t" id="boutique">{E(_titre_boutique(page))}</h2><div class="ap-rail">{"".join(cartes)}</div>' if cartes
            else '<span id="boutique"></span>')

    autres, a_des_liens = _autres_blocs(page, pseudo)
    autres = f'<div class="blocs ap-blocs" id="liens">{autres}</div>' if autres else ""
    contact = _contact(page)
    conseil = (f'<a class="ap-conseil" href="{E(contact[0])}" target="_blank" rel="noopener"><span><b>Une question ?</b>'
               f'<small>{E(contact[1])}</small></span><i>{ICO_FLECHE}</i></a>') if contact else ""
    onglets = [("#haut", "Accueil", ICO_MAISON, True), ("#boutique", "Boutique", ICO_SAC, False)]
    if a_des_liens:
        onglets.append(("#liens", "Liens", ICO_LIENS, False))
    if contact:
        onglets.append((contact[0], "Contact", ICO_BULLE, False))
    nav = '<nav class="ap-nav">' + "".join(
        f'<a href="{E(u)}"{" target=_blank rel=noopener" if u.startswith("http") or u.startswith("mailto") else ""}'
        f'{" aria-current=page" if actif else ""}>{ico}<span>{E(t)}</span></a>'
        for u, t, ico, actif in onglets if t != "Boutique" or cartes) + "</nav>"
    return (f'<div class="ap">{haut}{hero}{ronds}{rail}{autres}{conseil}</div>{bq.badge(page)}{nav}'
            f'{SCRIPT_CARROUSEL}{SCRIPT_ONGLETS}')


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
    if a_des_liens or autres:
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

    grille = []
    for p in prods:
        prix, barre, pastille = _prix(p)
        img = f'<img src="{bq._img(pseudo, p["image"])}" alt="" loading="lazy">' if p.get("image") else '<i class="ap-vide"></i>'
        st = f'<small>{E(p["sous_titre"])}</small>' if p.get("sous_titre") else ""
        grille.append(f'<a class="mq-prod" href="{_lien_produit(page, pseudo, p)}"><span class="mq-img">{img}'
                      f'{f"<span class=mq-pastille>{E(pastille)}</span>" if pastille else ""}<i class="mq-plus">{ICO_PLUS}</i></span>'
                      f'<b>{E(p.get("titre") or "")}</b>{st}'
                      f'<span class="mq-prix">{E(prix)}{f" <s>{E(barre)}</s>" if barre else ""}</span></a>')
    boutique = (f'<section class="mq-boutique" id="boutique"><h2>{E(_titre_boutique(page))}</h2><div class="mq-grille">{"".join(grille)}</div></section>'
                if grille else "")
    plus = f'<section class="mq-plus-sec" id="plus"><div class="blocs">{autres}</div></section>' if autres else ""
    bulle = (f'<a class="mq-bulle" href="{E(contact[0])}" target="_blank" rel="noopener" aria-label="{E(contact[1])}">{ICO_BULLE}</a>' if contact else "")
    return (f'{haut}{stories}{manif}{boutique}{plus}{bq.badge(page)}'
            f'<div class="mq-flottants">{bulle}<a class="mq-haut-btn" href="#haut" aria-label="Revenir en haut">{ICO_HAUT}</a></div>')


CSS = """
/* ===== Appli ===== */
body.mp-appli .page{max-width:600px;padding:18px 16px 120px}
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
.ap-blocs{margin-top:28px}
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
body.mp-appli .marque{margin-bottom:10px}
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
