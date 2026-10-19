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
from datetime import datetime, timedelta
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
        """)
        for table, col, typ in (("usage", "cout_usd", "REAL DEFAULT 0"), ("usage", "studio", "INTEGER DEFAULT 0"), ("utilisateurs", "derniere_connexion", "TEXT"),
                                ("utilisateurs", "cgv_acceptees", "TEXT")):
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass  # colonne déjà présente


# ------------------------------------------------------------
#  Utilisateurs
# ------------------------------------------------------------
def cree(email: str, mdp: str, prenom: str = "", cgv: bool = False) -> dict:
    email = email.strip().lower()
    if "@" not in email or len(mdp) < 8:
        raise ValueError("Adresse e-mail invalide ou mot de passe trop court (8 caractères minimum).")
    duree = plans()["essai"].get("duree_jours", 7)
    with _verrou, _db() as c:
        try:
            c.execute("INSERT INTO utilisateurs(email, mdp, prenom, fin_essai, cree, cgv_acceptees) VALUES (?,?,?,?,?,?)",
                      (email, generate_password_hash(mdp), prenom.strip(),
                       (datetime.now() + timedelta(days=duree)).isoformat(timespec="minutes"), datetime.now().isoformat(timespec="minutes"),
                       datetime.now().isoformat(timespec="minutes") if cgv else None))
        except sqlite3.IntegrityError:
            raise ValueError("Un compte existe déjà avec cette adresse.") from None
    return verifie(email, mdp)


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
def _mois():
    return datetime.now().strftime("%Y-%m")


def usage(uid: int) -> dict:
    with _db() as c:
        r = c.execute("SELECT analyses, adaptations, studio FROM usage WHERE uid=? AND mois=?", (uid, _mois())).fetchone()
    return {"analyses": r["analyses"] if r else 0, "adaptations": r["adaptations"] if r else 0, "studio": (r["studio"] or 0) if r else 0}


def compte_usage(uid: int, analyses: int = 0, adaptations: int = 0, cout: float = 0.0, studio: int = 0):
    with _verrou, _db() as c:
        c.execute("INSERT INTO usage(uid, mois, analyses, adaptations, cout_usd, studio) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(uid, mois) DO UPDATE SET analyses=analyses+?, adaptations=adaptations+?, cout_usd=cout_usd+?, studio=studio+?",
                  (uid, _mois(), analyses, adaptations, cout, studio, analyses, adaptations, cout, studio))


def usage_tous() -> dict:
    """{uid: {"mois": {...}, "total_cout": x}} pour le tableau de bord administrateur."""
    res: dict = {}
    with _db() as c:
        for r in c.execute("SELECT uid, mois, analyses, adaptations, cout_usd FROM usage"):
            d = res.setdefault(r["uid"], {"mois": {"analyses": 0, "adaptations": 0, "cout_usd": 0.0}, "total_cout": 0.0})
            d["total_cout"] += r["cout_usd"] or 0
            if r["mois"] == _mois():
                d["mois"] = {"analyses": r["analyses"], "adaptations": r["adaptations"], "cout_usd": r["cout_usd"] or 0}
    return res


# Options des formules payantes (une formule peut en désactiver une dans plans.yaml, comme la formule gratuite)
OPTIONS_DEFAUT = {"ia": True, "montage_reel": True, "suivi_publications": True, "sequences_emails": True,
                  "filigrane": False, "mention_boutique": False}


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
        "usage": us,
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
        return f"Tu as utilisé tes {d['quotas']['analyses_par_mois']} analyses du mois. Passe à la formule supérieure ou attends le mois prochain."
    if adaptations and d["quotas"]["adaptations_par_mois"] == 0:
        return MSG_ABONNEES
    if adaptations and d["reste"]["adaptations"] < adaptations:
        return f"Il te reste {max(d['reste']['adaptations'], 0)} adaptations ce mois-ci, il en faut {adaptations}."
    if studio and d["reste"]["studio"] < studio:
        return f"Tu as utilisé tes {d['quotas']['studio_par_mois']} créations du mois au studio. Passe à la formule supérieure ou attends le mois prochain."
    return None


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
        maj(uid, plan=obj["metadata"].get("plan", "createur"), statut="actif",
            stripe_client=obj.get("customer"), stripe_abonnement=obj.get("subscription"))
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
            maj(uid, **champs)
    return typ
