"""Comptes clients, formules, quotas et paiement Stripe (optionnel)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml
from werkzeug.security import check_password_hash, generate_password_hash

from espace import DATA

CODE = Path(__file__).resolve().parent
BASE = DATA / "app.db"
_verrou = threading.Lock()


def plans() -> dict:
    return yaml.safe_load((CODE / "plans.yaml").read_text(encoding="utf-8"))


def _db():
    BASE.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(BASE, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _verrou, _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS utilisateurs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, mdp TEXT NOT NULL, prenom TEXT,
            plan TEXT DEFAULT 'essai', statut TEXT DEFAULT 'essai', fin_essai TEXT, cree TEXT,
            onboarding INTEGER DEFAULT 0, veille_auto INTEGER DEFAULT 1, derniere_veille_auto TEXT,
            stripe_client TEXT, stripe_abonnement TEXT);
        CREATE TABLE IF NOT EXISTS usage(
            uid INTEGER, mois TEXT, analyses INTEGER DEFAULT 0, adaptations INTEGER DEFAULT 0, PRIMARY KEY(uid, mois));
        CREATE TABLE IF NOT EXISTS reinit(jeton TEXT PRIMARY KEY, uid INTEGER, expire TEXT);
        CREATE TABLE IF NOT EXISTS push(endpoint TEXT PRIMARY KEY, uid INTEGER NOT NULL, p256dh TEXT, auth TEXT, cree TEXT);
        """)
        for table, col, typ in (("usage", "cout_usd", "REAL DEFAULT 0"), ("usage", "studio", "INTEGER DEFAULT 0"), ("utilisateurs", "derniere_connexion", "TEXT"),
                                ("utilisateurs", "cgv_acceptees", "TEXT"), ("utilisateurs", "code_parrain", "TEXT"),
                                ("utilisateurs", "parrain", "INTEGER"), ("utilisateurs", "mois_offerts", "INTEGER DEFAULT 0"),
                                ("utilisateurs", "parrainage_recompense", "INTEGER DEFAULT 0"), ("utilisateurs", "synthese", "INTEGER DEFAULT 1"),
                                ("utilisateurs", "derniere_synthese", "TEXT"), ("utilisateurs", "a_paye", "INTEGER DEFAULT 0"),
                                ("utilisateurs", "debut_cycle", "TEXT"), ("utilisateurs", "origine", "TEXT"),
                                ("utilisateurs", "relances_boutique", "INTEGER DEFAULT 0"), ("utilisateurs", "essai_utilise", "INTEGER DEFAULT 0")):
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                if col == "essai_utilise":  # comptes existants : ils ont tous eu leur essai à l'inscription
                    c.execute("UPDATE utilisateurs SET essai_utilise=1")
            except sqlite3.OperationalError:
                pass  # colonne déjà présente


# ------------------------------------------------------------
#  Utilisateurs
# ------------------------------------------------------------
def cree(email: str, mdp: str, prenom: str = "", cgv: bool = False, offre: str = "") -> dict:
    """offre="boutique" : boutique gratuite (aimant à prospects) ; l'essai de la veille reste disponible pour plus tard."""
    email = email.strip().lower()
    if "@" not in email or len(mdp) < 8:
        raise ValueError("Adresse e-mail invalide ou mot de passe trop court (8 caractères minimum).")
    duree = plans()["essai"].get("duree_jours", 7)
    with _verrou, _db() as c:
        try:
            boutique = offre == "boutique" and "gratuit" in plans()
            c.execute("INSERT INTO utilisateurs(email, mdp, prenom, fin_essai, cree, cgv_acceptees, plan, statut, origine, essai_utilise) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (email, generate_password_hash(mdp), prenom.strip(),
                       None if boutique else (datetime.now() + timedelta(days=duree)).isoformat(timespec="minutes"),
                       datetime.now().isoformat(timespec="minutes"), datetime.now().isoformat(timespec="minutes") if cgv else None,
                       "gratuit" if boutique else "essai", "gratuit" if boutique else "essai", "boutique" if boutique else None,
                       0 if boutique else 1))
        except sqlite3.IntegrityError:
            raise ValueError("Un compte existe déjà avec cette adresse.") from None
    return verifie(email, mdp)


# ------------------------------------------------------------
#  Parrainage : un mois offert à la filleule (essai prolongé) et à la marraine (quand la filleule s'abonne)
# ------------------------------------------------------------
JOURS_FILLEULE = 30


def code_parrain(uid: int) -> str:
    u = get(uid)
    if u and u.get("code_parrain"):
        return u["code_parrain"]
    import re as _re
    base = _re.sub(r"[^a-z0-9]", "", ((u or {}).get("prenom") or "").lower())[:10] or "amie"
    for _ in range(20):
        code = f"{base}{secrets.randbelow(9000) + 1000}"
        with _verrou, _db() as c:
            if not c.execute("SELECT 1 FROM utilisateurs WHERE code_parrain=?", (code,)).fetchone():
                c.execute("UPDATE utilisateurs SET code_parrain=? WHERE id=?", (code, uid))
                return code
    return str(uid)


def par_code(code: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM utilisateurs WHERE code_parrain=?", ((code or "").strip().lower(),)).fetchone()
    return dict(r) if r else None


def rattache_parrain(uid: int, code: str) -> bool:
    """À l'inscription : la filleule gagne un mois d'essai en plus."""
    p = par_code(code)
    u = get(uid)
    if not p or not u or p["id"] == uid or u.get("parrain"):
        return False
    fin = max(datetime.fromisoformat(u["fin_essai"]), datetime.now()) + timedelta(days=JOURS_FILLEULE) if u.get("fin_essai") else None
    maj(uid, parrain=p["id"], **({"fin_essai": fin.isoformat(timespec="minutes")} if fin else {}))
    return True


def filleules(uid: int) -> dict:
    with _db() as c:
        l = [dict(r) for r in c.execute("SELECT id, prenom, statut, a_paye, cree FROM utilisateurs WHERE parrain=?", (uid,))]
    return {"inscrites": len(l), "abonnees": sum(1 for x in l if x["a_paye"]), "liste": l}


def recompense_parrain(uid_filleule: int) -> dict | None:
    """Première souscription payante de la filleule : un mois offert à la marraine (crédit Stripe ou essai prolongé). Une seule fois."""
    f = get(uid_filleule)
    if not f or not f.get("parrain") or f.get("parrainage_recompense"):
        return None
    maj(uid_filleule, parrainage_recompense=1)
    p = get(f["parrain"])
    if not p:
        return None
    if p.get("stripe_client") and stripe_actif():
        prix = (plans().get(p["plan"]) or {}).get("prix_mensuel") or 0
        if prix:
            try:
                requests.post(f"https://api.stripe.com/v1/customers/{p['stripe_client']}/balance_transactions",
                              data={"amount": -round(float(prix) * 100), "currency": "eur", "description": "Parrainage : un mois offert"},
                              auth=(os.environ["STRIPE_SECRET_KEY"], ""), timeout=30)
            except Exception:  # noqa: BLE001
                pass
    elif p.get("statut") == "essai":
        base = max(datetime.fromisoformat(p["fin_essai"]), datetime.now()) if p.get("fin_essai") else datetime.now()
        maj(p["id"], fin_essai=(base + timedelta(days=30)).isoformat(timespec="minutes"))
    maj(p["id"], mois_offerts=(p.get("mois_offerts") or 0) + 1)
    return p


# ------------------------------------------------------------
#  Notifications push (abonnements des appareils)
# ------------------------------------------------------------
def ajoute_push(uid: int, endpoint: str, p256dh: str, auth: str):
    with _verrou, _db() as c:
        c.execute("INSERT OR REPLACE INTO push(endpoint, uid, p256dh, auth, cree) VALUES (?,?,?,?,?)",
                  (endpoint, uid, p256dh, auth, datetime.now().isoformat(timespec="minutes")))


def retire_push(endpoint: str):
    with _verrou, _db() as c:
        c.execute("DELETE FROM push WHERE endpoint=?", (endpoint,))


def push_de(uid: int) -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM push WHERE uid=?", (uid,))]


def verifie(email: str, mdp: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM utilisateurs WHERE email=?", (email.strip().lower(),)).fetchone()
    return dict(r) if r and check_password_hash(r["mdp"], mdp) else None


def par_email(email: str) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM utilisateurs WHERE email=?", (email.strip().lower(),)).fetchone()
    return dict(r) if r else None


def _h(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def jeton_reinit(uid: int, heures: int = 1) -> str:
    """Jeton de réinitialisation à usage unique (seule son empreinte est stockée)."""
    jeton = secrets.token_urlsafe(32)
    with _verrou, _db() as c:
        c.execute("DELETE FROM reinit WHERE uid=? OR expire < ?", (uid, datetime.now().isoformat()))
        c.execute("INSERT INTO reinit VALUES (?,?,?)", (_h(jeton), uid, (datetime.now() + timedelta(hours=heures)).isoformat()))
    return jeton


def reinitialise(jeton: str, mdp: str) -> dict:
    if len(mdp) < 8:
        raise ValueError("Le mot de passe doit faire au moins 8 caractères.")
    with _verrou, _db() as c:
        r = c.execute("SELECT uid, expire FROM reinit WHERE jeton=?", (_h(jeton or ""),)).fetchone()
        if not r or r["expire"] < datetime.now().isoformat():
            raise ValueError("Ce lien a expiré ou a déjà servi. Refais une demande.")
        c.execute("DELETE FROM reinit WHERE uid=?", (r["uid"],))
        c.execute("UPDATE utilisateurs SET mdp=? WHERE id=?", (generate_password_hash(mdp), r["uid"]))
    return get(r["uid"])


def get(uid: int) -> dict | None:
    with _db() as c:
        r = c.execute("SELECT * FROM utilisateurs WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def maj(uid: int, **champs):
    if not champs:
        return
    with _verrou, _db() as c:
        c.execute(f"UPDATE utilisateurs SET {', '.join(k + '=?' for k in champs)} WHERE id=?", (*champs.values(), uid))


def tous() -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM utilisateurs")]


# ------------------------------------------------------------
#  Droits et quotas
# ------------------------------------------------------------
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _jour_du_mois(annee: int, mois: int, jour: int) -> date:
    """Le même jour le mois donné ; ramené au dernier jour si le mois est plus court (31 → 30 ou 28)."""
    import calendar
    while mois < 1:
        annee, mois = annee - 1, mois + 12
    while mois > 12:
        annee, mois = annee + 1, mois - 12
    return date(annee, mois, min(jour, calendar.monthrange(annee, mois)[1]))


def periode(u: dict | None, jour_j: date | None = None) -> tuple[date, date]:
    """
    Période de décompte en cours : d'une date anniversaire à la suivante (abonnement souscrit le 10 → du 10 au 10).
    Ancre : date de souscription (ou de renouvellement Stripe), sinon date d'inscription.
    """
    jour_j = jour_j or date.today()
    ancre = (u or {}).get("debut_cycle") or (u or {}).get("cree") or jour_j.isoformat()
    try:
        j = date.fromisoformat(str(ancre)[:10]).day
    except ValueError:
        j = 1
    debut = _jour_du_mois(jour_j.year, jour_j.month, j)
    if debut > jour_j:
        debut = _jour_du_mois(jour_j.year, jour_j.month - 1, j)
    return debut, _jour_du_mois(debut.year, debut.month + 1, j)


def date_fr(d: date) -> str:
    return f"{d.day}{'er' if d.day == 1 else ''} {MOIS_FR[d.month - 1]}"


def _cle_periode(uid: int) -> str:
    return periode(get(uid))[0].isoformat()


def usage(uid: int) -> dict:
    with _db() as c:
        r = c.execute("SELECT analyses, adaptations, studio, cout_usd FROM usage WHERE uid=? AND mois=?", (uid, _cle_periode(uid))).fetchone()
    return {"analyses": r["analyses"] if r else 0, "adaptations": r["adaptations"] if r else 0, "studio": (r["studio"] or 0) if r else 0,
            "cout_usd": (r["cout_usd"] or 0) if r else 0.0}


def compte_usage(uid: int, analyses: int = 0, adaptations: int = 0, cout: float = 0.0, studio: int = 0):
    with _verrou, _db() as c:
        c.execute("INSERT INTO usage(uid, mois, analyses, adaptations, cout_usd, studio) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(uid, mois) DO UPDATE SET analyses=analyses+?, adaptations=adaptations+?, cout_usd=cout_usd+?, studio=studio+?",
                  (uid, _cle_periode(uid), analyses, adaptations, cout, studio, analyses, adaptations, cout, studio))


def usage_tous() -> dict:
    """{uid: {"mois": {...}, "total_cout": x}} pour le tableau de bord administrateur."""
    res: dict = {}
    cles = {u["id"]: periode(u)[0].isoformat() for u in tous()}
    with _db() as c:
        for r in c.execute("SELECT uid, mois, analyses, adaptations, cout_usd FROM usage"):
            d = res.setdefault(r["uid"], {"mois": {"analyses": 0, "adaptations": 0, "cout_usd": 0.0}, "total_cout": 0.0})
            d["total_cout"] += r["cout_usd"] or 0
            if r["mois"] == cles.get(r["uid"]):
                d["mois"] = {"analyses": r["analyses"], "adaptations": r["adaptations"], "cout_usd": r["cout_usd"] or 0}
    return res


# Options des formules payantes (une formule peut en désactiver une dans plans.yaml, comme la formule gratuite)
OPTIONS_DEFAUT = {"ia": True, "montage_reel": True, "suivi_publications": True, "sequences_emails": True,
                  "filigrane": False, "mention_boutique": False}


def essai_dispo(u: dict) -> bool:
    """L'essai de la veille n'a pas encore servi (inscription par la boutique gratuite) et la cliente n'est pas abonnée."""
    return not u.get("essai_utilise") and plan_effectif(u) == "gratuit"


def demarre_essai(uid: int) -> bool:
    u = get(uid)
    if not u or not essai_dispo(u):
        return False
    duree = plans()["essai"].get("duree_jours", 7) + (JOURS_FILLEULE if u.get("parrain") else 0)  # invitée par une amie : le mois promis
    maj(uid, plan="essai", statut="essai", essai_utilise=1, debut_cycle=date.today().isoformat(),
        fin_essai=(datetime.now() + timedelta(days=duree)).isoformat(timespec="minutes"))
    return True


def plan_effectif(u: dict) -> str:
    """Formule réellement appliquée : fin d'essai, résiliation ou impayé → formule gratuite (si elle existe)."""
    p = plans()
    expire = u["statut"] == "essai" and u.get("fin_essai") and u["fin_essai"] < datetime.now().isoformat()
    if (expire or u["statut"] in ("resilie", "impaye")) and "gratuit" in p:  # « suspendu » (par l'admin) reste bloqué
        return "gratuit"
    return u["plan"] if u["plan"] in p else "essai"


def droits(u: dict) -> dict:
    p = plans()
    cle = plan_effectif(u)
    plan = p[cle]
    actif = cle == "gratuit" or u["statut"] in ("actif", "essai")
    if cle != "gratuit" and u["statut"] == "essai" and u.get("fin_essai") and u["fin_essai"] < datetime.now().isoformat():
        actif = False
    us = usage(u["id"])
    return {
        "plan": cle, "nom_plan": plan["nom"], "statut": u["statut"], "actif": actif, "fin_essai": u.get("fin_essai"),
        "gratuit": bool(plan.get("gratuit")),
        "options": {k: bool(plan.get(k, v)) for k, v in OPTIONS_DEFAUT.items()},
        "commission_boutique": plan.get("commission_boutique"),
        "quotas": {**{k: plan[k] for k in ("analyses_par_mois", "adaptations_par_mois", "comptes_surveilles")},
                   "studio_par_mois": plan.get("studio_par_mois", 10)},
        "veille_auto": bool(plan.get("veille_auto")) and bool(u.get("veille_auto")),
        "usage": {k: us[k] for k in ("analyses", "adaptations", "studio")},  # le coût réel reste côté administrateur
        "renouvellement": periode(u)[1].isoformat(), "renouvellement_fr": date_fr(periode(u)[1]),
        "essai_dispo": essai_dispo(u), "essai_jours": p["essai"].get("duree_jours", 7),
        "reste": {"analyses": plan["analyses_par_mois"] - us["analyses"], "adaptations": plan["adaptations_par_mois"] - us["adaptations"],
                  "studio": plan.get("studio_par_mois", 10) - us["studio"]},
    }


MSG_ABONNEES = "Cette fonction est réservée aux abonnées : choisis une formule pour l'utiliser."
MSG_OPTIONS = {
    "ia": "L'adaptation à ta niche et l'écriture par l'IA sont réservées aux abonnées. Choisis une formule pour les débloquer.",
    "montage_reel": "Le montage des Reels est réservé aux abonnées. En gratuit, tu peux créer des carrousels.",
    "suivi_publications": "Le suivi automatique de tes Reels publiés est réservé aux abonnées.",
    "sequences_emails": "Les séquences d'e-mails automatiques sont réservées aux abonnées.",
}


def reserve(u: dict, option: str) -> str | None:
    """None si la formule de l'utilisateur inclut l'option, sinon le message à afficher."""
    d = droits(u)
    if not d["actif"]:
        return "Ton abonnement n'est pas actif. Choisis une formule pour continuer."
    return None if d["options"].get(option, True) else MSG_OPTIONS.get(option, MSG_ABONNEES)


def peut(u: dict, analyses: int = 0, adaptations: int = 0, studio: int = 0) -> str | None:
    """Renvoie None si c'est autorisé, sinon le message à afficher."""
    d = droits(u)
    if not d["actif"]:
        return "Ton essai est terminé ou ton abonnement n'est pas actif. Choisis une formule pour continuer."
    if analyses and d["reste"]["analyses"] < analyses:
        return f"Tu as utilisé tes {d['quotas']['analyses_par_mois']} analyses de la période. {_suite(u, d)}"
    if adaptations and d["quotas"]["adaptations_par_mois"] == 0:
        return MSG_ABONNEES
    if adaptations and d["reste"]["adaptations"] < adaptations:
        return f"Il te reste {max(d['reste']['adaptations'], 0)} adaptation(s) jusqu'au {d['renouvellement_fr']}, il en faut {adaptations}. {_suite(u, d)}"
    if studio and d["reste"]["studio"] < studio:
        return f"Tu as utilisé tes {d['quotas']['studio_par_mois']} créations de la période au studio. {_suite(u, d)}"
    # Garde-fou : coût réel (collecte + IA) plafonné par formule et par mois (budget_usd dans plans.yaml)
    budget = float(plans().get(plan_effectif(u), {}).get("budget_usd") or 0)
    if (analyses or adaptations) and budget and usage(u["id"])["cout_usd"] >= budget:
        return f"Tu as atteint la limite d'usage de ta formule pour cette période. {_suite(u, d)}"
    return None


def _suite(u: dict, d: dict) -> str:
    """Proposer la formule supérieure (s'il y en a une), sinon la date de remise à zéro."""
    actuel = plans().get(plan_effectif(u), {})
    sup = sorted((p for p in plans().values() if not p.get("gratuit") and p.get("prix_mensuel")
                  and float(p["prix_mensuel"]) > float(actuel.get("prix_mensuel") or 0)), key=lambda p: float(p["prix_mensuel"]))
    if sup:
        return f"Passe à la formule {sup[0]['nom']} pour continuer tout de suite, ou attends le {d['renouvellement_fr']}."
    return f"Tes compteurs repartent à zéro le {d['renouvellement_fr']}."


# ------------------------------------------------------------
#  Stripe (sans SDK : appels HTTP directs)
# ------------------------------------------------------------
def stripe_actif() -> bool:
    return bool(os.getenv("STRIPE_SECRET_KEY"))


def checkout(u: dict, plan: str, url_retour: str) -> str:
    p = plans().get(plan)
    if not p or not p.get("stripe_price"):
        raise ValueError("Cette formule n'a pas de prix Stripe configuré (plans.yaml → stripe_price).")
    data = {
        "mode": "subscription", "line_items[0][price]": p["stripe_price"], "line_items[0][quantity]": 1,
        "success_url": url_retour + "?paiement=ok", "cancel_url": url_retour + "?paiement=annule",
        "client_reference_id": str(u["id"]), "metadata[uid]": str(u["id"]), "metadata[plan]": plan,
        "subscription_data[metadata][uid]": str(u["id"]), "subscription_data[metadata][plan]": plan,
        "allow_promotion_codes": "true", "locale": "fr",
    }
    if u.get("stripe_client"):
        data["customer"] = u["stripe_client"]
    else:
        data["customer_email"] = u["email"]
    r = requests.post("https://api.stripe.com/v1/checkout/sessions", data=data, auth=(os.environ["STRIPE_SECRET_KEY"], ""), timeout=30)
    if r.status_code >= 400:
        raise ValueError(r.json().get("error", {}).get("message", "Erreur Stripe"))
    return r.json()["url"]


def portail(u: dict, url_retour: str) -> str:
    if not u.get("stripe_client"):
        raise ValueError("Aucun abonnement Stripe pour ce compte.")
    r = requests.post("https://api.stripe.com/v1/billing_portal/sessions",
                      data={"customer": u["stripe_client"], "return_url": url_retour},
                      auth=(os.environ["STRIPE_SECRET_KEY"], ""), timeout=30)
    if r.status_code >= 400:
        raise ValueError(r.json().get("error", {}).get("message", "Erreur Stripe"))
    return r.json()["url"]


def webhook(charge_utile: bytes, signature: str) -> str:
    """Vérifie la signature Stripe et met à jour l'abonnement du client."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    morceaux = dict(x.split("=", 1) for x in signature.split(",") if "=" in x)
    attendu = hmac.new(secret.encode(), f"{morceaux.get('t', '')}.".encode() + charge_utile, hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(attendu, morceaux.get("v1", "")) or abs(time.time() - int(morceaux.get("t", 0))) > 600:
        raise PermissionError("Signature Stripe invalide")
    ev = json.loads(charge_utile)
    obj = ev["data"]["object"]
    typ = ev["type"]
    if typ == "checkout.session.completed":
        uid = int(obj.get("client_reference_id") or obj["metadata"]["uid"])
        maj(uid, plan=obj["metadata"].get("plan", "createur"), statut="actif", a_paye=1, debut_cycle=date.today().isoformat(),
            stripe_client=obj.get("customer"), stripe_abonnement=obj.get("subscription"))
        recompense_parrain(uid)
    elif typ in ("customer.subscription.updated", "customer.subscription.deleted"):
        uid = int((obj.get("metadata") or {}).get("uid", 0))
        if uid:
            statut = {"active": "actif", "trialing": "actif", "past_due": "impaye", "unpaid": "impaye"}.get(obj["status"], "resilie")
            champs = {"statut": "resilie" if typ.endswith("deleted") else statut}
            # La formule est déduite du prix (fonctionne aussi après un changement via le portail client)
            prix = ((obj.get("items") or {}).get("data") or [{}])[0].get("price", {}).get("id")
            plan = next((k for k, v in plans().items() if v.get("stripe_price") and v["stripe_price"] == prix), None)
            if plan:
                champs["plan"] = plan
            # Date de début de la période facturée : les compteurs suivent exactement la facturation
            debut = obj.get("current_period_start") or (((obj.get("items") or {}).get("data") or [{}])[0].get("current_period_start"))
            if debut:
                champs["debut_cycle"] = datetime.fromtimestamp(int(debut)).date().isoformat()
            maj(uid, **champs)
    return typ
