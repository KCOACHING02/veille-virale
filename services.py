"""
État des services payants dont Virallink dépend : clés valides et crédit suffisant, pour éviter une interruption.

Chaque contrôle est gratuit ou presque (lecture de compte, ou un mini-appel à ~0,0001 $ pour Claude, qui n'a pas
d'API de solde). Résultat : {id, nom, role, etat (ok | alerte | ko | absent), detail, conseil, lien}.
Vérifié à la demande depuis l'admin et chaque matin par `planificateur` (e-mail aux admins s'il y a un problème).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

from espace import DATA

FICHIER = DATA / "services.json"
SEUIL_APIFY_USD = 5  # reste à dépenser sur le cycle en dessous duquel on alerte


def _r(id_, nom, role, etat, detail, conseil="", lien=""):
    return {"id": id_, "nom": nom, "role": role, "etat": etat, "detail": detail, "conseil": conseil, "lien": lien}


def _apify():
    nom, role, lien = "Apify", "Lecture des publications Instagram (bibliothèque, veilles)", "https://console.apify.com/billing"
    t = os.getenv("APIFY_TOKEN")
    if not t:
        return _r("apify", nom, role, "absent", "Clé APIFY_TOKEN absente.", "Ajoute-la dans Railway.", lien)
    try:
        r = requests.get("https://api.apify.com/v2/users/me/limits", params={"token": t}, timeout=20)
        if r.status_code == 401:
            return _r("apify", nom, role, "ko", "Clé refusée par Apify.", "Recrée une clé dans Apify → Settings → Integrations, puis remplace-la dans Railway.", lien)
        r.raise_for_status()
        d = r.json()["data"]
        maxi = float(d["limits"].get("maxMonthlyUsageUsd") or 0)
        conso = float(d["current"].get("monthlyUsageUsd") or 0)
        cyc = d.get("monthlyUsageCycle") or {}
        debut = datetime.fromisoformat(cyc["startAt"].replace("Z", "+00:00")) if cyc.get("startAt") else None
        fin = datetime.fromisoformat(cyc["endAt"].replace("Z", "+00:00")) if cyc.get("endAt") else None
        now = datetime.now(timezone.utc)
        reste = maxi - conso
        prevu = conso
        if debut and fin and now > debut:
            prevu = conso / max((now - debut).total_seconds(), 3600) * (fin - debut).total_seconds()
        fin_txt = fin.strftime("%d/%m") if fin else "?"
        eur = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
        detail = f"{eur(conso)} $ utilisés sur {eur(maxi)} $ autorisés ce mois-ci (cycle jusqu'au {fin_txt}). À ce rythme : ~{eur(prevu)} $ sur le mois."
        if maxi and reste <= 0:
            return _r("apify", nom, role, "ko", detail, "Plafond atteint : les collectes sont bloquées. Augmente la limite ou change de formule Apify.", lien)
        if maxi and (reste < SEUIL_APIFY_USD or prevu > maxi):
            return _r("apify", nom, role, "alerte", detail, "Le plafond risque d'être atteint avant la fin du cycle : augmente la limite mensuelle (Billing → Limits) ou la formule.", lien)
        return _r("apify", nom, role, "ok", detail, "", lien)
    except Exception as e:  # noqa: BLE001
        return _r("apify", nom, role, "alerte", f"Vérification impossible : {str(e)[:120]}", "Réessaie plus tard.", lien)


def _claude():
    nom, role, lien = "Claude (Anthropic)", "Virall.ai : adaptations, Studio, plans, boutique", "https://console.anthropic.com/settings/billing"
    if not os.getenv("ANTHROPIC_API_KEY"):
        return _r("claude", nom, role, "absent", "Clé ANTHROPIC_API_KEY absente.", "Ajoute-la dans Railway.", lien)
    try:
        import anthropic
        import yaml
        from espace import CODE
        modele = (yaml.safe_load((CODE / "config.exemple.yaml").read_text(encoding="utf-8")).get("claude") or {}).get("modele") or "claude-sonnet-5-5"
        anthropic.Anthropic().messages.create(model=modele, max_tokens=1, messages=[{"role": "user", "content": "ok"}])
        return _r("claude", nom, role, "ok", f"Clé valide, crédit disponible (modèle {modele}). Anthropic n'indique pas le solde restant.",
                  "Active la recharge automatique (Billing → Auto-reload) pour ne jamais tomber à zéro.", lien)
    except Exception as e:  # noqa: BLE001
        t = str(e).lower()
        if "credit balance" in t or "billing" in t or "insufficient" in t:
            return _r("claude", nom, role, "ko", "Crédit épuisé : Virall.ai ne peut plus écrire.", "Recharge le crédit et active la recharge automatique.", lien)
        if "authentication" in t or "invalid x-api-key" in t or "401" in t:
            return _r("claude", nom, role, "ko", "Clé refusée par Anthropic.", "Recrée une clé dans la console Anthropic et remplace-la dans Railway.", lien)
        if "rate_limit" in t or "429" in t or "overloaded" in t or "529" in t:
            return _r("claude", nom, role, "ok", "Clé valide (service momentanément chargé).", "", lien)
        return _r("claude", nom, role, "alerte", f"Vérification impossible : {str(e)[:140]}", "", lien)


def _resend():
    nom, role, lien = "Resend", "E-mails (confirmation, relances, veille prête)", "https://resend.com/domains"
    k = os.getenv("RESEND_API_KEY")
    if not k:
        return _r("resend", nom, role, "absent", "Clé RESEND_API_KEY absente : aucun e-mail n'est envoyé.", "Ajoute-la dans Railway.", lien)
    try:
        r = requests.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {k.strip()}"}, timeout=20)
        if r.status_code in (401, 403) and "restricted" in r.text.lower():
            return _r("resend", nom, role, "ok", "Clé valide (limitée à l'envoi). Le quota d'envoi n'est pas lisible par l'API.",
                      "Vérifie de temps en temps le volume envoyé dans Resend (offre gratuite : 3 000 e-mails par mois).", "https://resend.com/overview")
        if r.status_code in (401, 403):
            return _r("resend", nom, role, "ko", "Clé refusée par Resend.", "Recrée une clé et remplace-la dans Railway.", lien)
        r.raise_for_status()
        doms = r.json().get("data") or []
        ko = [d["name"] for d in doms if d.get("status") != "verified"]
        if not doms or ko:
            return _r("resend", nom, role, "alerte", f"Domaine non vérifié : {', '.join(ko) or 'aucun domaine'}.", "Termine la vérification DNS du domaine dans Resend.", lien)
        return _r("resend", nom, role, "ok", f"Domaine vérifié : {', '.join(d['name'] for d in doms)}. Le quota d'envoi n'est pas lisible par l'API.",
                  "Offre gratuite : 3 000 e-mails par mois. Passe à l'offre payante quand les inscriptions augmentent.", "https://resend.com/overview")
    except Exception as e:  # noqa: BLE001
        return _r("resend", nom, role, "alerte", f"Vérification impossible : {str(e)[:120]}", "", lien)


def _stripe():
    nom, role, lien = "Stripe", "Abonnements Virallink et paiements des boutiques", "https://dashboard.stripe.com/settings/account"
    k = os.getenv("STRIPE_SECRET_KEY")
    if not k:
        return _r("stripe", nom, role, "absent", "Clé STRIPE_SECRET_KEY absente : pas de paiement possible.", "Ajoute-la dans Railway.", lien)
    try:
        r = requests.get("https://api.stripe.com/v1/account", auth=(k, ""), timeout=20)
        if r.status_code == 401:
            return _r("stripe", nom, role, "ko", "Clé refusée par Stripe.", "Remplace la clé secrète dans Railway.", lien)
        r.raise_for_status()
        a = r.json()
        mode = "test" if k.startswith(("sk_test", "rk_test")) else "réel"
        if not a.get("charges_enabled") or not a.get("payouts_enabled"):
            manque = [x for x, ok in (("encaissements", a.get("charges_enabled")), ("virements", a.get("payouts_enabled"))) if not ok]
            return _r("stripe", nom, role, "alerte", f"Compte en mode {mode} : {' et '.join(manque)} bloqués.",
                      "Complète les informations demandées par Stripe (identité, IBAN).", lien)
        return _r("stripe", nom, role, "ok", f"Compte en mode {mode}, encaissements et virements actifs.", "", lien)
    except Exception as e:  # noqa: BLE001
        return _r("stripe", nom, role, "alerte", f"Vérification impossible : {str(e)[:120]}", "", lien)


def _banque():
    nom, role = "Banque d'images", "Photos et vidéos libres de droits du Studio"
    try:
        if os.getenv("PIXABAY_API_KEY"):
            r = requests.get("https://pixabay.com/api/", params={"key": os.environ["PIXABAY_API_KEY"].strip(), "q": "coffee", "per_page": 3}, timeout=20)
            if r.status_code in (400, 401, 403):
                return _r("banque", nom + " (Pixabay)", role, "ko", "Clé refusée par Pixabay.", "Remplace PIXABAY_API_KEY dans Railway.", "https://pixabay.com/api/docs/")
            reste = r.headers.get("X-RateLimit-Remaining")
            return _r("banque", nom + " (Pixabay)", role, "ok", f"Gratuit. Clé valide{f', {reste} recherches restantes dans la minute' if reste else ''}.", "", "https://pixabay.com/api/docs/")
        if os.getenv("PEXELS_API_KEY"):
            r = requests.get("https://api.pexels.com/v1/search", params={"query": "coffee", "per_page": 1},
                             headers={"Authorization": os.environ["PEXELS_API_KEY"].strip()}, timeout=20)
            if r.status_code in (401, 403):
                return _r("banque", nom + " (Pexels)", role, "ko", "Clé refusée par Pexels.", "Remplace PEXELS_API_KEY dans Railway.", "https://www.pexels.com/api/")
            reste, total = r.headers.get("X-Ratelimit-Remaining"), r.headers.get("X-Ratelimit-Limit")
            etat = "alerte" if reste and total and int(reste) < int(total) * 0.1 else "ok"
            return _r("banque", nom + " (Pexels)", role, etat, f"Gratuit. {reste or '?'} recherches restantes sur {total or '?'} ce mois-ci.", "", "https://www.pexels.com/api/")
        return _r("banque", nom, role, "absent", "Aucune clé (PIXABAY_API_KEY ou PEXELS_API_KEY).", "Le Studio propose alors seulement tes propres photos.", "https://pixabay.com/api/docs/")
    except Exception as e:  # noqa: BLE001
        return _r("banque", nom, role, "alerte", f"Vérification impossible : {str(e)[:120]}", "", "")


def _meta():
    nom, role, lien = "Meta (Instagram)", "Messages privés automatiques", "https://developers.facebook.com/apps/"
    app_id, secret = os.getenv("INSTAGRAM_APP_ID"), os.getenv("INSTAGRAM_APP_SECRET")
    if not (app_id and secret):
        return _r("meta", nom, role, "absent", "Application Meta non configurée.", "", lien)
    try:
        r = requests.get(f"https://graph.facebook.com/v27.0/{app_id}", params={"access_token": f"{app_id}|{secret}", "fields": "name"}, timeout=20)
        if r.status_code != 200:
            return _r("meta", nom, role, "ko", "Identifiants de l'application refusés par Meta.", "Vérifie INSTAGRAM_APP_ID et INSTAGRAM_APP_SECRET dans Railway.", lien)
        return _r("meta", nom, role, "ok", f"Application « {r.json().get('name', '?')} » reconnue. Gratuit.", "", lien)
    except Exception as e:  # noqa: BLE001
        return _r("meta", nom, role, "alerte", f"Vérification impossible : {str(e)[:120]}", "", lien)


def verifie_tout() -> dict:
    res = [_apify(), _claude(), _stripe(), _resend(), _banque(), _meta(),
           _r("railway", "Railway", "Hébergement du site et des données", "info",
              "Pas d'API de solde : vérifie que ta carte est à jour et que l'usage reste dans ton budget.",
              "Railway → Usage : regarde l'estimation du mois.", "https://railway.com/account/usage")]
    data = {"le": datetime.now().isoformat(timespec="minutes"), "services": res}
    try:
        FICHIER.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return data


def dernier() -> dict:
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def problemes(data: dict) -> list[dict]:
    return [s for s in data.get("services", []) if s["etat"] in ("ko", "alerte")]
