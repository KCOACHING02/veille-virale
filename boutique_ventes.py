"""
Boutique : tout ce qui fait vendre — prix en promotion avec compte à rebours, codes promo, avis vérifiés, packs,
offre complémentaire après l'achat, rendez-vous payants, sources des visites (liens suivis, mots-clés, QR code),
séquence d'e-mails automatique et demandes d'avis.
"""

from __future__ import annotations

import io
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import boutique as bq
from boutique import E, _img, badge, document, dossier, prix_txt

FUSEAU = ZoneInfo("Europe/Paris")
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOTIF_SOURCE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def maintenant() -> datetime:
    return datetime.now(FUSEAU)


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=FUSEAU)


def date_fr(d: datetime, heure: bool = True) -> str:
    d = d.astimezone(FUSEAU)
    s = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return s + (f" à {d.strftime('%H:%M').replace(':', 'h')}" if heure else "")


# ------------------------------------------------------------
#  Prix : promotion limitée dans le temps et codes promo
# ------------------------------------------------------------
def prix_effectif(p: dict) -> dict:
    prix, barre, fin = p.get("prix", 0), p.get("prix_barre", 0), None
    f = _date(p.get("promo_fin"))
    if p.get("promo_prix") and f and f > maintenant() and p["promo_prix"] < prix:
        barre, prix, fin = max(barre, prix), p["promo_prix"], f
    return {"prix": prix, "barre": barre if barre > prix else 0, "fin": fin}


def code_valide(page: dict, p: dict, code: str, prix: int) -> tuple[int, str | None]:
    """(nouveau prix, erreur). Un code vaut pour tous les produits si sa liste est vide."""
    code = (code or "").strip().upper()
    if not code:
        return prix, None
    c = next((x for x in page.get("promos") or [] if x.get("code", "").upper() == code), None)
    if not c or (c.get("produits") and p["id"] not in c["produits"]):
        return prix, "Ce code n'existe pas ou ne s'applique pas à ce produit."
    f = _date(c.get("fin"))
    if f and f < maintenant():
        return prix, "Ce code a expiré."
    if c.get("max") and c.get("utilisations", 0) >= c["max"]:
        return prix, "Ce code a déjà été utilisé le nombre de fois prévu."
    remise = prix * c.get("valeur", 0) // 100 if c.get("type") == "pourcent" else c.get("valeur", 0)
    nouveau = max(0, prix - remise)
    return (0 if nouveau < 50 else nouveau), None  # sous le minimum Stripe, le produit devient gratuit


def utilise_code(uid: int, code: str):
    if not code:
        return
    with bq.verrou(uid):
        page = bq.lit_page(uid)
        for c in page.get("promos") or []:
            if c.get("code", "").upper() == code.upper():
                c["utilisations"] = c.get("utilisations", 0) + 1
        bq.ecrit_page(uid, page)


# ------------------------------------------------------------
#  Avis vérifiés (une acheteuse = un avis, via son lien personnel)
# ------------------------------------------------------------
def lit_avis(uid: int) -> list:
    return bq._lit(dossier(uid) / "avis.json", [])


def resume_avis(uid: int) -> dict:
    r = {}
    for a in lit_avis(uid):
        if a.get("visible", True):
            n, s = r.get(a["produit"], (0, 0))
            r[a["produit"]] = (n + 1, s + a["note"])
    return {k: (round(s / n, 1), n) for k, (n, s) in r.items()}


def ajoute_avis(uid: int, vente: dict, note: int, prenom: str, texte: str) -> bool:
    f = dossier(uid) / "avis.json"
    with bq.verrou(uid):
        l = bq._lit(f, [])
        if any(a.get("vente") == vente["id"] for a in l):
            return False
        l.append({"id": bq.nouvel_id(), "produit": vente["produit"], "vente": vente["id"], "note": max(1, min(5, int(note))),
                  "prenom": prenom.strip()[:40] or "Une cliente", "texte": texte.strip()[:800], "date": maintenant().isoformat(timespec="minutes"),
                  "visible": True})
        bq._ecrit(f, l)
    return True


def modere_avis(uid: int, aid: str, visible: bool | None = None, supprimer: bool = False):
    f = dossier(uid) / "avis.json"
    with bq.verrou(uid):
        l = bq._lit(f, [])
        if supprimer:
            l = [a for a in l if a["id"] != aid]
        else:
            for a in l:
                if a["id"] == aid:
                    a["visible"] = bool(visible)
        bq._ecrit(f, l)


def etoiles(note: float) -> str:
    plein = int(round(note))
    return "★" * plein + "☆" * (5 - plein)


# ------------------------------------------------------------
#  Rendez-vous
# ------------------------------------------------------------
RDV_DEFAUT = {"duree": 30, "jours": [0, 1, 2, 3, 4], "plages": "09:00-12:00, 14:00-18:00", "delai_h": 12, "horizon_j": 21, "lieu": "Lien de visio envoyé par e-mail"}


def _plages(txt: str) -> list[tuple[int, int]]:
    r = []
    for a, b in re.findall(r"(\d{1,2}[:h]\d{2})\s*-\s*(\d{1,2}[:h]\d{2})", txt or ""):
        h1, m1 = map(int, re.split("[:h]", a)); h2, m2 = map(int, re.split("[:h]", b))
        if 0 <= h1 < 24 and 0 <= h2 <= 24:
            r.append((h1 * 60 + m1, h2 * 60 + m2))
    return r


def lit_rdv(uid: int) -> list:
    return bq._lit(dossier(uid) / "rdv.json", [])


def _occupe(r: dict) -> bool:
    if r.get("statut") == "confirme":
        return True
    if r.get("statut") == "attente":
        return (_date(r.get("cree")) or maintenant()) > maintenant() - timedelta(minutes=20)
    return False


def creneaux(uid: int, p: dict) -> list[dict]:
    c = {**RDV_DEFAUT, **(p.get("rdv") or {})}
    duree = max(10, int(c["duree"]))
    pris = {r["debut"] for r in lit_rdv(uid) if _occupe(r)}
    debut_min = maintenant() + timedelta(hours=int(c["delai_h"]))
    jours = []
    for j in range(int(c["horizon_j"]) + 1):
        d = (maintenant() + timedelta(days=j)).date()
        if d.weekday() not in c["jours"]:
            continue
        heures = []
        for a, b in _plages(c["plages"]):
            m = a
            while m + duree <= b:
                t = datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=FUSEAU)
                if t >= debut_min and t.isoformat() not in pris:
                    heures.append({"iso": t.isoformat(), "h": t.strftime("%H:%M").replace(":", "h")})
                m += duree
        if heures:
            jours.append({"jour": d.isoformat(), "libelle": f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}", "heures": heures})
    return jours


def reserve_rdv(uid: int, p: dict, debut: str, email: str, prenom: str, confirme: bool) -> dict | None:
    if not any(h["iso"] == debut for j in creneaux(uid, p) for h in j["heures"]):
        return None
    f = dossier(uid) / "rdv.json"
    c = {**RDV_DEFAUT, **(p.get("rdv") or {})}
    with bq.verrou(uid):
        l = bq._lit(f, [])
        if any(r["debut"] == debut and _occupe(r) for r in l):
            return None
        r = {"id": bq.nouvel_id(), "produit": p["id"], "debut": debut, "duree": int(c["duree"]), "email": email, "prenom": prenom[:60],
             "statut": "confirme" if confirme else "attente", "cree": maintenant().isoformat(timespec="seconds"), "jeton": secrets.token_urlsafe(16)}
        l.append(r)
        bq._ecrit(f, l)
    return r


def confirme_rdv(uid: int, rid: str) -> dict | None:
    f = dossier(uid) / "rdv.json"
    with bq.verrou(uid):
        l = bq._lit(f, [])
        r = next((x for x in l if x["id"] == rid), None)
        if r:
            r["statut"] = "confirme"
            bq._ecrit(f, l)
    return r


def annule_rdv(uid: int, rid: str):
    f = dossier(uid) / "rdv.json"
    with bq.verrou(uid):
        l = bq._lit(f, [])
        for r in l:
            if r["id"] == rid:
                r["statut"] = "annule"
        bq._ecrit(f, l)


def ics(page: dict, r: dict, p: dict) -> str:
    d = _date(r["debut"]).astimezone(timezone.utc)
    fin = d + timedelta(minutes=r.get("duree", 30))
    f = "%Y%m%dT%H%M%SZ"
    lieu = ((p.get("rdv") or {}).get("lieu") or "").replace("\n", " ")
    nettoie = lambda s: (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")  # noqa: E731
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Virallink//Boutique//FR", "BEGIN:VEVENT",
                        f"UID:{r['id']}@veille-virale", f"DTSTAMP:{datetime.now(timezone.utc).strftime(f)}", f"DTSTART:{d.strftime(f)}",
                        f"DTEND:{fin.strftime(f)}", f"SUMMARY:{nettoie(p.get('titre'))} · {nettoie(page.get('nom'))}", f"LOCATION:{nettoie(lieu)}",
                        f"DESCRIPTION:{nettoie('Rendez-vous avec ' + (r.get('prenom') or r.get('email') or ''))}", "END:VEVENT", "END:VCALENDAR", ""])


# ------------------------------------------------------------
#  Sources des visites : liens suivis, mots-clés, QR code
# ------------------------------------------------------------
def source_propre(s: str | None) -> str:
    s = (s or "").strip().lower()[:40]
    return s if MOTIF_SOURCE.match(s) else ""


def compte_source(uid: int, src: str, champ: str, montant: int = 0):
    if not src:
        return
    f = dossier(uid) / "stats.json"
    with bq.verrou(uid):
        s = bq._lit(f, {})
        x = s.setdefault("sources", {}).setdefault(src, {"vues": 0, "inscrits": 0, "ventes": 0, "ca": 0})
        x[champ] = x.get(champ, 0) + 1
        if montant:
            x["ca"] = x.get("ca", 0) + montant
        bq._ecrit(f, s)


def nom_source(page: dict, src: str) -> str:
    noms = page.get("sources_noms") or {}
    if src in noms:
        return noms[src]
    if src.startswith("mot-"):
        return f"Mot-clé « {src[4:].upper()} »"
    return {"qr": "QR code", "bio": "Lien en bio"}.get(src, src)


def produit_par_mot(page: dict, mot: str) -> dict | None:
    mot = (mot or "").strip().upper()
    return next((p for p in page.get("produits", []) if p.get("visible", True) and (p.get("mot_cle") or "").upper() == mot), None)


def qr_png(url: str, sombre: str = "#000000", clair: str = "#FFFFFF") -> bytes:
    import segno
    b = io.BytesIO()
    segno.make(url, error="m").save(b, kind="png", scale=14, border=2, dark=sombre[:7], light=clair[:7])
    return b.getvalue()


def qr_svg(url: str, sombre: str = "#000000", clair: str = "#FFFFFF") -> bytes:
    import segno
    b = io.BytesIO()
    segno.make(url, error="m").save(b, kind="svg", scale=10, border=2, dark=sombre[:7], light=clair[:7])
    return b.getvalue()


# ------------------------------------------------------------
#  Séquence d'e-mails et demandes d'avis (envoyés par le planificateur)
# ------------------------------------------------------------
def sequence_defaut(page: dict) -> dict:
    nom = page.get("nom") or "moi"
    return {"actif": False, "depuis": "", "emails": [
        {"delai_jours": 0, "sujet": "Bienvenue, c'est noté !", "produit": "",
         "texte": f"Coucou {{prenom}},\n\nMerci de m'avoir rejointe. Je suis {nom} et je vais t'envoyer de temps en temps mes meilleurs conseils, ceux que je ne publie pas sur Instagram.\n\nÀ très vite,\n{nom}"},
        {"delai_jours": 3, "sujet": "Le conseil que j'aurais aimé recevoir plus tôt", "produit": "",
         "texte": "Coucou {prenom},\n\nAujourd'hui, un seul conseil, mais celui qui change le plus de choses : commence petit, et tiens bon une semaine.\n\nRéponds à cet e-mail pour me dire où tu en es, je lis tout."},
    ]}


def _jeton_inscrit(x: dict) -> str:
    if not x.get("jeton"):
        x["jeton"] = secrets.token_urlsafe(12)
    return x["jeton"]


def _mail_sequence(page: dict, base: str, pseudo: str, x: dict, e: dict) -> tuple[str, str]:
    prenom = (x.get("prenom") or "").strip()
    texte = (e.get("texte") or "").replace("{prenom}", prenom or "toi").replace("Coucou toi,", "Coucou,")
    corps = "".join(f"<p>{E(par).replace(chr(10), '<br>')}</p>" for par in re.split(r"\n\s*\n", texte) if par.strip())
    p = next((y for y in page.get("produits", []) if y["id"] == e.get("produit")), None)
    bouton = (p.get("bouton") or "Découvrir", f"{base}/@{pseudo}/p/{p['id']}?src=email") if p else None
    stop = f"{base}/@{pseudo}/stop/{_jeton_inscrit(x)}"
    pied = (f'<p style="font-size:12px;color:#8A7F78;margin-top:26px">Tu reçois cet e-mail car tu t\'es inscrite sur la page de {E(page.get("nom") or "")}. '
            f'<a href="{E(stop)}" style="color:#8A7F78">Se désinscrire</a></p>')
    return e.get("sujet") or "", bq._gabarit(page, e.get("sujet") or "", corps + pied, bouton)


def envoie_sequences(uid: int, base: str) -> int:
    """Un passage du planificateur : au plus un e-mail par inscrite, quand son délai est atteint. Renvoie le nombre d'e-mails envoyés."""
    import emails
    page = bq.lit_page(uid)
    pseudo = bq.pseudo_de(uid)
    if not page or not pseudo:
        return 0
    seq = page.get("sequence") or {}
    envoyes = 0
    maint = maintenant()
    f = dossier(uid) / "inscrits.json"
    if seq.get("actif") and seq.get("emails") and emails.actif():
        depuis = _date(seq.get("depuis")) or maint
        a_envoyer = []
        with bq.verrou(uid):
            l = bq._lit(f, [])
            for x in l:
                d = _date(x.get("date"))
                if x.get("desinscrit") or not d or d < depuis - timedelta(minutes=5):
                    continue
                etape = x.get("etape", 0)
                if etape < len(seq["emails"]) and maint >= d + timedelta(days=int(seq["emails"][etape].get("delai_jours", 0))):
                    a_envoyer.append((x, seq["emails"][etape]))
                    x["etape"] = etape + 1
            bq._ecrit(f, l)
        for x, e in a_envoyer:
            sujet, h = _mail_sequence(page, base, pseudo, x, e)
            emails.envoie(x["email"], sujet, h, attendre=True)
            envoyes += 1
    # demandes d'avis : 3 jours après un achat payant
    if emails.actif():
        fv = dossier(uid) / "ventes.json"
        demandes = []
        with bq.verrou(uid):
            ventes = bq._lit(fv, [])
            for v in ventes:
                d = _date(v.get("date"))
                if (v.get("montant") and not v.get("avis_demande") and v.get("email") and "demo" not in v["email"]
                        and d and maint - d >= timedelta(days=3) and maint - d < timedelta(days=20)):
                    v["avis_demande"] = True
                    demandes.append(dict(v))
            bq._ecrit(fv, ventes)
        for v in demandes:
            p = next((y for y in page.get("produits", []) if y["id"] == v["produit"]), {"titre": "ton achat"})
            lien = f"{base}/@{pseudo}/avis/{v['jeton']}"
            emails.envoie(v["email"], f"Ton avis sur « {p.get('titre')} » ?", bq._gabarit(
                page, "Ça t'a plu ?", f"<p>Tu as reçu <b>{E(p.get('titre') or '')}</b> il y a quelques jours. Ton avis aide énormément "
                                      "les prochaines personnes à se décider (et moi à m'améliorer). Ça prend 30 secondes.</p>",
                ("Donner mon avis", lien)), attendre=True)
            envoyes += 1
    return envoyes


def desinscrit(uid: int, jeton: str) -> bool:
    f = dossier(uid) / "inscrits.json"
    with bq.verrou(uid):
        l = bq._lit(f, [])
        x = next((y for y in l if y.get("jeton") and secrets.compare_digest(y["jeton"], jeton)), None)
        if x:
            x["desinscrit"] = True
            bq._ecrit(f, l)
    return bool(x)


# ------------------------------------------------------------
#  Rendu : fiche produit, page de remerciement, avis
# ------------------------------------------------------------
SCRIPT_PRODUIT = """
<script>
document.querySelectorAll("[data-fin]").forEach(el => {
  const fin = new Date(el.dataset.fin).getTime();
  const tic = () => { let s = Math.max(0, Math.floor((fin - Date.now()) / 1000)); if (!s) { el.textContent = "Offre terminée"; return; }
    const j = Math.floor(s / 86400); s %= 86400; const h = Math.floor(s / 3600); s %= 3600; const m = Math.floor(s / 60); s %= 60;
    el.innerHTML = "Fin de l’offre dans " + (j ? "<b>" + j + "</b> j " : "") + "<b>" + String(h).padStart(2, "0") + "</b> h <b>" + String(m).padStart(2, "0") + "</b> min <b>" + String(s).padStart(2, "0") + "</b> s"; };
  tic(); setInterval(tic, 1000);
});
const cr = document.getElementById("creneaux");
if (cr) {
  const J = JSON.parse(cr.dataset.jours), jours = cr.querySelector(".jours"), heures = cr.querySelector(".heures"), champ = document.querySelector("[name=creneau]");
  const choisitJour = i => { jours.querySelectorAll("button").forEach((b, k) => b.setAttribute("aria-pressed", k === i));
    heures.innerHTML = J[i].heures.map(h => `<button type="button" data-iso="${h.iso}">${h.h}</button>`).join(""); champ.value = "";
    heures.querySelectorAll("button").forEach(b => b.onclick = () => { heures.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); champ.value = b.dataset.iso; }); };
  jours.innerHTML = J.map((j, i) => `<button type="button">${j.libelle}</button>`).join("");
  jours.querySelectorAll("button").forEach((b, i) => b.onclick = () => choisitJour(i));
  if (J.length) choisitJour(0);
  cr.closest("form").addEventListener("submit", e => { if (!champ.value) { e.preventDefault(); e.stopImmediatePropagation(); alert("Choisis un créneau"); } }, true);
}
</script>"""

CSS_FICHE = """<style>
.compte{margin:-6px 0 14px;font-size:14px;background:var(--a);color:var(--ac);border-radius:var(--rk);padding:9px 12px;text-align:center}
.compte b{font-size:16px}
.note-avis{display:inline-flex;gap:6px;align-items:center;font-size:14px;margin:4px 0 0;text-decoration:none;opacity:.9}
.note-avis .et,.avis .et{color:var(--a);letter-spacing:1px}
.code-promo{margin:10px 0 0}.code-promo summary{cursor:pointer;font-size:14px;opacity:.8;text-align:center;list-style:none}
.code-promo .champ{margin-top:8px}.code-promo input{color:var(--t);border-color:color-mix(in srgb,var(--t) 30%,transparent)}
.champs-fiche{display:flex;flex-direction:column;gap:8px}.champs-fiche input{width:100%;color:var(--t);border:1.5px solid color-mix(in srgb,var(--t) 30%,transparent);background:transparent;border-radius:var(--r);padding:12px 14px;font:inherit}
.pack{margin:16px 0}.pack div{display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid color-mix(in srgb,var(--kt) 15%,transparent)}.pack div:last-child{border:0}
.pack img,.pack i{width:44px;height:44px;border-radius:8px;object-fit:cover;background:var(--a);flex-shrink:0}
#creneaux .jours,#creneaux .heures{display:flex;gap:6px;overflow-x:auto;padding:4px 0 8px;scrollbar-width:none}
#creneaux .heures{flex-wrap:wrap;overflow:visible}
#creneaux button{flex-shrink:0;border:1.5px solid color-mix(in srgb,var(--t) 25%,transparent);background:transparent;color:var(--t);border-radius:12px;padding:8px 12px;font:600 13.5px var(--tx);cursor:pointer}
#creneaux button[aria-pressed=true]{background:var(--a);border-color:var(--a);color:var(--ac)}
.avis{margin-top:26px}.avis article{padding:12px 0;border-bottom:1px solid color-mix(in srgb,var(--t) 14%,transparent)}.avis article:last-child{border:0}
.avis p{margin:4px 0 0;white-space:pre-line}.avis small{opacity:.65}
.upsell{margin-top:16px;text-align:left;display:flex;gap:12px;align-items:center}.upsell img{width:70px;height:70px;border-radius:10px;object-fit:cover}
.etoiles-choix{display:flex;flex-direction:row-reverse;justify-content:center;gap:4px;font-size:34px}
.etoiles-choix input{display:none}.etoiles-choix label{cursor:pointer;color:color-mix(in srgb,var(--t) 25%,transparent)}
.etoiles-choix input:checked~label,.etoiles-choix label:hover,.etoiles-choix label:hover~label{color:var(--a)}
</style>"""


def livrable(page: dict, p: dict) -> bool:
    """Le produit a bien quelque chose à livrer (fichier, lien, créneaux ou produits du pack)."""
    if p.get("type") == "rdv":
        return True
    if p.get("type") == "pack":
        prods = {x["id"]: x for x in page.get("produits", [])}
        return any(livrable(page, prods[i]) for i in p.get("inclus") or [] if i in prods and prods[i].get("type") != "pack")
    return bool(p.get("fichier") or p.get("lien"))


def rendu_produit(page: dict, pseudo: str, p: dict, uid: int, message: str = "", vente_possible: bool = True, code: str = "", src: str = "") -> str:
    pe = prix_effectif(p)
    prix, devise = pe["prix"], p.get("devise", "eur")
    code_msg = ""
    if code and prix:
        nouveau, err = code_valide(page, p, code, prix)
        if err:
            code_msg, code = err, ""
        elif nouveau < prix:
            pe["barre"], prix = max(pe["barre"], prix), nouveau
            code_msg = f"Code « {code.upper()} » appliqué ✓"
    img = f'<img class="couv-p" src="{_img(pseudo, p["image"])}" alt="">' if p.get("image") else ""
    barre = f'<s>{E(prix_txt(pe["barre"], devise))}</s>' if pe["barre"] else ""
    compte = f'<p class="compte" data-fin="{pe["fin"].isoformat()}">Offre limitée</p>' if pe["fin"] else ""
    note = resume_avis(uid).get(p["id"])
    note_html = f'<a class="note-avis" href="#avis"><span class="et">{etoiles(note[0])}</span> {str(note[0]).replace(".", ",")} · {note[1]} avis</a>' if note else ""
    src_input = f'<input type="hidden" name="src" value="{E(src)}">' if src else ""
    gratuit = not prix
    est_rdv = p.get("type") == "rdv"
    champs_contact = ('<div class="champs-fiche"><input type="text" name="prenom" placeholder="Ton prénom" aria-label="Ton prénom"'
                      f'{" required" if est_rdv else ""}><input type="email" name="email" required placeholder="Ton e-mail" aria-label="Ton e-mail"></div>')
    creneaux_html = ""
    if est_rdv:
        jours = creneaux(uid, p)
        if not jours:
            creneaux_html = '<p class="note" style="font-size:15px">Aucun créneau disponible pour le moment.</p>'
        else:
            creneaux_html = (f'<div id="creneaux" data-jours="{E(json.dumps(jours))}"><p style="margin:0 0 4px;font-weight:600">Choisis ton créneau '
                             f'<small style="font-weight:400;opacity:.7">({(p.get("rdv") or {}).get("duree", 30)} min, heure de Paris)</small></p>'
                             '<div class="jours"></div><div class="heures"></div></div><input type="hidden" name="creneau">')
    if not livrable(page, p):
        action = '<p class="note" style="font-size:15px">Ce produit sera disponible très bientôt.</p>'
    elif p.get("lien") and not p.get("fichier") and gratuit and p.get("type") not in ("rdv", "pack"):
        action = f'<a class="bouton" style="display:block;text-align:center;text-decoration:none" href="/@{pseudo}/p/{p["id"]}/ouvrir" target="_blank" rel="noopener">{E(p.get("bouton") or "J’y vais")}</a>'
    elif est_rdv and not creneaux(uid, p):
        action = creneaux_html
    elif gratuit:
        action = (f'<form method="post" action="/@{pseudo}/p/{p["id"]}/obtenir" data-capture>{creneaux_html}{champs_contact}{src_input}'
                  f'<input type="hidden" name="code" value="{E(code)}"><button class="bouton" style="width:100%;margin-top:10px">'
                  f'{E(p.get("bouton") or ("Je réserve" if est_rdv else "Je le reçois gratuitement"))}</button></form>'
                  f'<p class="note">{"Confirmation immédiate par e-mail." if est_rdv else "Tu le reçois tout de suite, et aussi par e-mail."}</p>')
    elif vente_possible:
        promo_champ = ("" if code else '<details class="code-promo"><summary>J’ai un code promo</summary><div class="champ">'
                       '<input name="code" placeholder="CODE" autocapitalize="characters" aria-label="Code promo"><button class="bouton" formaction="?" formmethod="get" '
                       'type="submit" name="appliquer" value="1">Appliquer</button></div></details>')
        action = (f'<form method="post" action="/@{pseudo}/p/{p["id"]}/acheter">{creneaux_html}{champs_contact if est_rdv else ""}{src_input}'
                  f'<input type="hidden" name="code" value="{E(code)}"><button class="bouton" style="width:100%;margin-top:10px">'
                  f'{E(p.get("bouton") or ("Je réserve" if est_rdv else "Je le veux"))} · {E(prix_txt(prix, devise))}</button>{promo_champ}</form>'
                  '<p class="note">Paiement sécurisé par Stripe</p>')
    else:
        action = '<p class="note" style="font-size:15px">Ce produit sera bientôt disponible à l’achat.</p>'
    msg = "".join(f'<div class="carte" style="margin-bottom:14px">{E(m)}</div>' for m in (message, code_msg) if m)
    st = f'<p style="opacity:.8;margin:0">{E(p["sous_titre"])}</p>' if p.get("sous_titre") else ""
    pack = ""
    if p.get("type") == "pack" and p.get("inclus"):
        prods = {x["id"]: x for x in page.get("produits", [])}
        def ligne(x):
            vis = f'<img src="{_img(pseudo, x["image"])}" alt="">' if x.get("image") else "<i></i>"
            return f'<div>{vis}<b>{E(x.get("titre") or "")}</b></div>'
        lignes = "".join(ligne(prods[i]) for i in p["inclus"] if i in prods)
        pack = f'<div class="pack carte"><p style="margin:0 0 4px;font-weight:700">Ce pack contient</p>{lignes}</div>' if lignes else ""
    avis = [a for a in lit_avis(uid) if a["produit"] == p["id"] and a.get("visible", True)]
    avis_html = ""
    def un_avis(a):
        t = f'<p>{E(a["texte"])}</p>' if a.get("texte") else ""
        return f'<article><span class="et">{etoiles(a["note"])}</span> <b>{E(a["prenom"])}</b> <small>· achat vérifié</small>{t}</article>'
    if avis:
        avis_html = '<section class="avis" id="avis"><h2 class="t2" style="margin-top:0">Ce qu’elles en pensent</h2>' + "".join(un_avis(a) for a in sorted(avis, key=lambda a: a["date"], reverse=True)[:30]) + "</section>"
    corps = (f'{CSS_FICHE}<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a>{msg}<article class="fiche">{img}<h1>{E(p.get("titre") or "")}</h1>'
             f'{st}{note_html}<p class="px">{E(prix_txt(prix, devise))}{barre}</p>{compte}{action}{pack}'
             f'<div class="desc">{E(p.get("description") or "")}</div>{avis_html}</article>{badge(page)}{SCRIPT_PRODUIT}')
    return document(page, pseudo, corps, f'{p.get("titre")} · {page.get("nom")}', (p.get("sous_titre") or p.get("description") or "")[:160],
                    image_og=_img(pseudo, p["image"]) if p.get("image") else "")


def rendu_merci(page: dict, pseudo: str, uid: int, vente: dict, demo: bool = False) -> str:
    prods = {x["id"]: x for x in page.get("produits", [])}
    p = prods.get(vente["produit"]) or {"titre": "ton produit"}
    gratuit = not vente.get("montant")
    lien = f"/@{pseudo}/telecharger/{vente['jeton']}"
    contenu = ""
    if p.get("type") == "rdv":
        r = next((x for x in lit_rdv(uid) if x["id"] == vente.get("rdv")), None)
        if r:
            contenu = (f'<p style="font-size:18px;margin:10px 0 4px"><b>{E(date_fr(_date(r["debut"])))}</b></p>'
                       f'<p style="margin:0 0 6px;opacity:.85">{E((p.get("rdv") or {}).get("lieu") or "")}</p>'
                       f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:14px" href="/@{pseudo}/rdv/{r["id"]}.ics?j={r["jeton"]}">Ajouter à mon agenda</a>')
    elif p.get("type") == "pack":
        contenu = '<div style="text-align:left;margin-top:14px">' + "".join(
            f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:8px" href="{lien}?p={i}">{E(prods[i].get("titre") or "Télécharger")}</a>'
            for i in p.get("inclus") or [] if i in prods) + "</div>"
    else:
        contenu = (f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:16px" href="{lien}">'
                   f'{"Télécharger" if p.get("fichier") else "Accéder"}</a>')
    up = ""
    u = p.get("upsell") or {}
    pu = prods.get(u.get("produit"))
    if pu and pu.get("visible", True) and u.get("prix") is not None and pu["id"] != p.get("id"):
        pr = int(u["prix"])
        vis = f'<img src="{_img(pseudo, pu["image"])}" alt="">' if pu.get("image") else ""
        avant = f' <s style="opacity:.55">{E(prix_txt(pu["prix"], pu.get("devise", "eur")))}</s>' if pu.get("prix", 0) > pr else ""
        up = (f'<form class="carte upsell" method="post" action="/@{pseudo}/p/{pu["id"]}/acheter">'
              f'{vis}'
              f'<div style="flex:1"><small style="opacity:.75;text-transform:uppercase;letter-spacing:.06em;font-size:11px">Offre réservée à toi</small>'
              f'<b style="display:block">{E(pu.get("titre") or "")}</b><span style="color:var(--a);font-weight:700">{E(prix_txt(pr, pu.get("devise", "eur")))}</span>'
              f'{avant}'
              f'<input type="hidden" name="upsell" value="{E(vente["jeton"])}"><button class="bouton" style="width:100%;margin-top:8px">Je l’ajoute</button></div></form>')
    titre = "C'est à toi !" if gratuit else "Merci pour ton achat !"
    if p.get("type") == "rdv":
        titre = "C'est réservé !"
    texte = (f"« {p.get('titre')} » " + ("est confirmé." if p.get("type") == "rdv" else "est prêt.") +
             (" Tu reçois aussi la confirmation par e-mail." if vente.get("email") and "demo" not in vente["email"] else "") +
             (" (Achat simulé : mode démo.)" if demo else ""))
    corps = (f'<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a><div class="carte" style="text-align:center;padding:28px 20px">'
             f'<h1 style="font-size:calc(var(--tt) * .8)">{E(titre)}</h1><p style="margin:0">{E(texte)}</p>{contenu}</div>{up}{badge(page)}')
    return document(page, pseudo, CSS_FICHE + corps, titre)


def rendu_form_avis(page: dict, pseudo: str, p: dict, envoye: bool = False) -> str:
    if envoye:
        corps = (f'<div class="carte" style="text-align:center;padding:28px 20px"><h1 style="font-size:calc(var(--tt) * .8)">Merci 💛</h1>'
                 f'<p style="margin:0">Ton avis est publié sur la page du produit.</p>'
                 f'<a class="bouton" style="display:block;text-align:center;text-decoration:none;margin-top:16px" href="/@{pseudo}/p/{p["id"]}">Voir la page</a></div>')
    else:
        corps = (f'<form class="carte" method="post" style="text-align:center;padding:26px 20px"><h1 style="font-size:calc(var(--tt) * .7)">Ton avis sur « {E(p.get("titre") or "")} »</h1>'
                 '<div class="etoiles-choix">' + "".join(f'<input type="radio" name="note" id="n{i}" value="{i}"{" checked" if i == 5 else ""}><label for="n{i}" title="{i}/5">★</label>' for i in range(5, 0, -1)) +
                 '</div><div class="champs-fiche" style="margin-top:12px"><input name="prenom" placeholder="Ton prénom (affiché)" maxlength="40">'
                 '<textarea name="texte" rows="5" maxlength="800" placeholder="Ce que tu en as pensé, ce que ça t’a apporté…" '
                 'style="width:100%;color:var(--t);border:1.5px solid color-mix(in srgb,var(--t) 30%,transparent);background:transparent;border-radius:var(--rk);padding:12px 14px;font:inherit"></textarea></div>'
                 '<button class="bouton" style="width:100%;margin-top:12px">Publier mon avis</button></form>')
    return document(page, pseudo, CSS_FICHE + f'<a class="retour" href="/@{pseudo}">← {E(page.get("nom") or "")}</a>' + corps + badge(page), "Ton avis")
