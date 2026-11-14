"""
Messages privés automatiques sur Instagram (type « commente GUIDE et je t'envoie le lien »).

Fonctionnement (API Instagram avec connexion unifiée, « Unified Login », imposée par Meta aux nouvelles
applications depuis octobre 2026 ; pas besoin de page Facebook) :
  - la cliente relie son compte Instagram professionnel : elle se connecte avec Instagram ou Facebook,
    choisit son portefeuille business et le compte à partager (Facebook Login for Business + config_id) ;
  - Virallink reçoit un jeton d'« utilisateur système d'intégration » qui appartient à son portefeuille
    (durée choisie dans la configuration Meta : « jamais » conseillé) ; tous les appels passent par graph.facebook.com ;
  - Meta nous prévient à chaque commentaire (webhook « comments ») ;
  - si le commentaire contient un mot-clé d'une de ses règles, on envoie UNE réponse privée à la personne
    (POST /<ig_id>/messages avec recipient.comment_id, dans les 7 jours) et, si elle le veut,
    une réponse publique sous le commentaire (« Je t'ai envoyé le lien en privé 💌 »).

Variables d'environnement : INSTAGRAM_APP_ID et INSTAGRAM_APP_SECRET (identifiant et clé secrète de l'application
Meta, Paramètres de l'app → Général), INSTAGRAM_CONFIG_ID (identifiant de la configuration de connexion),
INSTAGRAM_WEBHOOK_TOKEN (facultatif : jeton de vérification du webhook, dérivé de SECRET_KEY sinon).

Données : table `instagram` (compte relié par cliente) dans data/app.db ;
règles et journal dans data/espaces/<uid>/messages_auto.json.
Aucun coût d'API payante (ni Claude ni Apify) : seules les limites de Meta s'appliquent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import requests

import abonnements as ab
from espace import DATA

VERSION = "v27.0"
GRAPH = "https://graph.facebook.com"
CHAMPS_WEBHOOK = "comments,messages"
MAX_PAR_HEURE = 150          # en dessous de la limite de Meta, pour ne jamais faire bloquer un compte
JOURS_JOURNAL = 60
_verrou = threading.Lock()


def configure() -> bool:
    return bool(os.getenv("INSTAGRAM_APP_ID") and os.getenv("INSTAGRAM_APP_SECRET") and os.getenv("INSTAGRAM_CONFIG_ID"))


def jeton_webhook(secret: str) -> str:
    return os.getenv("INSTAGRAM_WEBHOOK_TOKEN") or hmac.new(secret.encode(), b"webhook-instagram", hashlib.sha256).hexdigest()[:32]


# ------------------------------------------------------------
#  Comptes reliés
# ------------------------------------------------------------
def _table():
    with ab._db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS instagram(uid INTEGER PRIMARY KEY, ig_id TEXT UNIQUE, pseudo TEXT,
                     jeton TEXT, expire TEXT, relie TEXT, photo TEXT)""")
        if "entreprise" not in {r[1] for r in c.execute("PRAGMA table_info(instagram)")}:
            c.execute("ALTER TABLE instagram ADD COLUMN entreprise TEXT")


def compte(uid: int) -> dict | None:
    _table()
    with ab._db() as c:
        r = c.execute("SELECT * FROM instagram WHERE uid=?", (uid,)).fetchone()
    return dict(r) if r else None


def compte_par_ig(ig_id: str) -> dict | None:
    _table()
    with ab._db() as c:
        r = c.execute("SELECT * FROM instagram WHERE ig_id=?", (str(ig_id),)).fetchone()
    return dict(r) if r else None


def _enregistre(uid: int, ig_id: str, pseudo: str, jeton: str, duree_s: int, photo: str = "", entreprise: str = ""):
    """duree_s = 0 : jeton sans date d'expiration (réglage « jamais » de la configuration Meta)."""
    _table()
    expire = (datetime.now() + timedelta(seconds=duree_s)).isoformat(timespec="seconds") if duree_s else ""
    with ab._verrou, ab._db() as c:
        c.execute("DELETE FROM instagram WHERE uid=? OR ig_id=?", (uid, str(ig_id)))
        c.execute("INSERT INTO instagram(uid, ig_id, pseudo, jeton, expire, relie, photo, entreprise) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, str(ig_id), pseudo, jeton, expire, datetime.now().isoformat(timespec="seconds"), photo, entreprise))


def delie(uid: int):
    _table()
    with ab._verrou, ab._db() as c:
        c.execute("DELETE FROM instagram WHERE uid=?", (uid,))


def delie_par_ig(ig_id: str):
    _table()
    with ab._verrou, ab._db() as c:
        c.execute("DELETE FROM instagram WHERE ig_id=?", (str(ig_id),))


# ------------------------------------------------------------
#  Connexion (connexion unifiée : Facebook Login for Business + config_id)
# ------------------------------------------------------------
def url_connexion(redirection: str, etat: str) -> str:
    from urllib.parse import urlencode
    return "https://www.facebook.com/dialog/oauth?" + urlencode({
        "client_id": os.environ["INSTAGRAM_APP_ID"], "config_id": os.environ["INSTAGRAM_CONFIG_ID"],
        "override_default_response_type": "true", "redirect_uri": redirection, "response_type": "code",
        "state": etat, "prompt": "login"})


def _get(chemin: str, jeton: str, **params) -> dict:
    r = requests.get(f"{GRAPH}/{VERSION}/{chemin}", params=params, headers={"Authorization": f"Bearer {jeton}"}, timeout=30)
    try:
        return r.json()
    except ValueError:
        return {"error": {"message": f"réponse illisible ({r.status_code})"}}


def termine_connexion(uid: int, code: str, redirection: str) -> dict:
    """Code → jeton du portefeuille de la cliente → compte Instagram partagé, puis abonnement aux commentaires."""
    r = requests.get(f"{GRAPH}/{VERSION}/oauth/access_token", params={
        "client_id": os.environ["INSTAGRAM_APP_ID"], "client_secret": os.environ["INSTAGRAM_APP_SECRET"],
        "redirect_uri": redirection, "code": code.removesuffix("#_")}, timeout=30)
    d = r.json()
    if r.status_code != 200 or "access_token" not in d:
        raise RuntimeError(_erreur(d, "Instagram a refusé la connexion."))
    jeton = d["access_token"]
    entreprise = _get("me", jeton, fields="client_business_id").get("client_business_id", "")
    comptes = _get("me/assigned_instagram_accounts", jeton, fields="id,username,profile_picture_url")
    if not comptes.get("data"):
        raise RuntimeError(_erreur(comptes, "Aucun compte Instagram partagé. Recommence et coche ton compte Instagram professionnel."))
    moi = comptes["data"][0]
    _enregistre(uid, moi["id"], moi.get("username", ""), jeton, int(d.get("expires_in") or 0), moi.get("profile_picture_url", ""), entreprise)
    abonne_webhook(moi["id"], jeton)
    abonne_page(moi["id"], jeton, entreprise)
    return compte(uid)


def abonne_webhook(ig_id: str, jeton: str):
    r = requests.post(f"{GRAPH}/{VERSION}/{ig_id}/subscribed_apps", data={"subscribed_fields": CHAMPS_WEBHOOK},
                      headers={"Authorization": f"Bearer {jeton}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(_erreur(r.json(), "Instagram n'a pas activé les notifications de commentaires."))


def _page_du_compte(ig_id: str, jeton: str, entreprise: str = "") -> dict | None:
    """Page Facebook reliée au compte Instagram (avec son jeton de page si Meta le donne)."""
    sources = ["me/accounts"]
    if entreprise:
        sources += [f"{entreprise}/owned_pages", f"{entreprise}/client_pages"]
    for src in sources:
        d = _get(src, jeton, fields="id,name,access_token,instagram_business_account", limit=100)
        for p in d.get("data", []) or []:
            if str((p.get("instagram_business_account") or {}).get("id") or "") == str(ig_id):
                if not p.get("access_token"):
                    p["access_token"] = _get(p["id"], jeton, fields="access_token").get("access_token", "")
                return p
    return None


def abonne_page(ig_id: str, jeton: str, entreprise: str = "") -> bool:
    """Avec la connexion Facebook, Meta n'envoie les commentaires Instagram que si la page Facebook reliée
    est abonnée à l'application (n'importe quel champ de page). Jamais bloquant : on journalise seulement."""
    try:
        p = _page_du_compte(ig_id, jeton, entreprise)
        if not p:
            print(f"[messages auto] page Facebook du compte {ig_id} introuvable : abonnement de page non fait")
            return False
        r = requests.post(f"{GRAPH}/{VERSION}/{p['id']}/subscribed_apps", data={"subscribed_fields": "feed"},
                          headers={"Authorization": f"Bearer {p.get('access_token') or jeton}"}, timeout=30)
        print(f"[messages auto] abonnement de la page {p.get('name')} ({p['id']}) : {r.status_code} {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        print(f"[messages auto] abonnement de page impossible : {e}")
        return False


def reabonne_tous():
    """Au démarrage : refait les abonnements (compte + page) des comptes déjà reliés, sans reconnexion."""
    if not configure():
        return
    _table()
    with ab._db() as c:
        lignes = [dict(r) for r in c.execute("SELECT * FROM instagram").fetchall()]
    for x in lignes:
        try:
            abonne_webhook(x["ig_id"], x["jeton"])
        except Exception as e:  # noqa: BLE001
            print(f"[messages auto] réabonnement de {x.get('pseudo')} : {e}")
        abonne_page(x["ig_id"], x["jeton"], x.get("entreprise") or "")


def renouvelle_jetons():
    """Une fois par jour : signale les jetons qui expirent bientôt (configuration Meta avec une durée).
    Avec le réglage conseillé « jamais », il n'y a rien à faire. Un jeton expiré oblige la cliente à se reconnecter."""
    if not configure():
        return
    _table()
    with ab._db() as c:
        lignes = [dict(r) for r in c.execute("SELECT * FROM instagram WHERE expire != ''").fetchall()]
    for x in lignes:
        try:
            if datetime.fromisoformat(x["expire"]) - datetime.now() < timedelta(days=7):
                print(f"[messages auto] le jeton de {x.get('pseudo')} expire le {x['expire'][:10]} : reconnexion nécessaire")
        except ValueError:
            pass


def publications(uid: int, demo: bool = False) -> list[dict]:
    """Dernières publications du compte relié, pour viser une publication précise."""
    if demo:
        return [{"id": f"demo{i}", "legende": t, "image": "", "lien": "", "date": ""} for i, t in enumerate(
            ["Les 3 erreurs qui te fatiguent le matin…", "Mon guide offert : commente GUIDE", "Avant / après de Julie"])]
    c = compte(uid)
    if not c:
        return []
    d = _get(f"{c['ig_id']}/media", c["jeton"], fields="id,caption,media_type,thumbnail_url,media_url,permalink,timestamp", limit=24)
    return [{"id": m["id"], "legende": (m.get("caption") or "")[:120], "image": m.get("thumbnail_url") or m.get("media_url") or "",
             "lien": m.get("permalink", ""), "date": (m.get("timestamp") or "")[:10]} for m in d.get("data", [])]


def _erreur(d: dict, defaut: str) -> str:
    e = (d or {}).get("error") or {}
    return f"{defaut} ({e.get('message')})" if isinstance(e, dict) and e.get("message") else (d.get("error_message") or defaut)


# ------------------------------------------------------------
#  Règles (mots-clés) et journal
# ------------------------------------------------------------
def _fichier(uid: int) -> Path:
    d = DATA / "espaces" / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d / "messages_auto.json"


def lit(uid: int) -> dict:
    try:
        return json.loads(_fichier(uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"regles": [], "journal": [], "repondus": {}}


def _ecrit(uid: int, d: dict):
    f = _fichier(uid)
    t = f.with_suffix(".tmp")
    t.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    t.replace(f)


def _s(x, n: int) -> str:
    return str(x or "").strip()[:n]


def regle_propre(r: dict) -> dict | None:
    if not isinstance(r, dict):
        return None
    mots = [m for m in (_s(x, 30) for x in (r.get("mots") or [])[:8]) if m]
    if not mots:
        return None
    pubs = [_s(x, 40) for x in (r.get("publications") or [])[:30] if _s(x, 40)]
    publiques = [p for p in (_s(x, 200) for x in (r.get("reponses_publiques") or [])[:6]) if p]
    return {"id": re.sub(r"\W", "", _s(r.get("id"), 12)) or secrets.token_hex(4), "nom": _s(r.get("nom"), 60) or mots[0].upper(),
            "mots": mots, "toutes": r.get("toutes", True) is not False or not pubs, "publications": pubs,
            "message": _s(r.get("message"), 900), "lien": _s(r.get("lien"), 400), "bouton": _s(r.get("bouton"), 40),
            "reponses_publiques": publiques, "actif": r.get("actif", True) is not False,
            "cree": _s(r.get("cree"), 25) or datetime.now().isoformat(timespec="seconds")}


def enregistre_regles(uid: int, regles: list) -> list:
    with _verrou:
        d = lit(uid)
        d["regles"] = [x for x in (regle_propre(r) for r in (regles or [])[:30]) if x and x["message"]]
        _ecrit(uid, d)
    return d["regles"]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def correspond(regle: dict, texte: str, media_id: str) -> bool:
    if not regle.get("actif"):
        return False
    if not regle.get("toutes") and media_id not in regle.get("publications", []):
        return False
    mots_com = f" {_norm(texte)} "
    return any(f" {_norm(m)} " in mots_com for m in regle["mots"] if _norm(m))


def stats(uid: int) -> dict:
    d = lit(uid)
    res: dict = {}
    for j in d.get("journal", []):
        s = res.setdefault(j.get("regle", ""), {"envois": 0, "echecs": 0, "dernier": ""})
        s["envois" if j.get("ok") else "echecs"] += 1
        s["dernier"] = max(s["dernier"], j.get("date", ""))
    return res


# ------------------------------------------------------------
#  Réception d'un commentaire (webhook) et envoi
# ------------------------------------------------------------
def signature_valide(corps: bytes, signature: str) -> bool:
    secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if not secret or not signature.startswith("sha256="):
        return False
    attendu = hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, signature[7:])


def traite_webhook(charge: dict, peut_envoyer) -> int:
    """Parcourt les commentaires reçus ; renvoie le nombre de messages envoyés.
    peut_envoyer(uid) -> bool : la cliente a-t-elle encore droit à la fonction (formule payante active) ?"""
    n = 0
    print(f"[messages auto] webhook reçu : objet={charge.get('object')} "
          f"champs={[ch.get('field') for e in charge.get('entry', []) or [] for ch in e.get('changes', []) or []]}")
    for entree in charge.get("entry", []) or []:
        ig_id = str(entree.get("id") or "")
        for ch in entree.get("changes", []) or []:
            if ch.get("field") != "comments":
                continue
            v = ch.get("value") or {}
            try:
                n += traite_commentaire(ig_id, v, peut_envoyer)
            except Exception as e:  # noqa: BLE001
                print(f"[messages auto] commentaire non traité : {e}")
    return n


def traite_commentaire(ig_id: str, v: dict, peut_envoyer, demo: bool = False) -> int:
    c = compte_par_ig(ig_id) if not demo else None
    uid = c["uid"] if c else v.get("_uid")
    if not uid or not peut_envoyer(uid):
        if not demo:
            print(f"[messages auto] commentaire ignoré : compte {ig_id} {'non relié' if not uid else 'sans droit à la fonction'}")
        return 0
    auteur = (v.get("from") or {})
    if str(auteur.get("id") or "") == ig_id or (c and auteur.get("username") == c.get("pseudo")):
        return 0  # ses propres réponses ne déclenchent rien
    com_id, texte, media = str(v.get("id") or ""), v.get("text") or "", str((v.get("media") or {}).get("id") or "")
    with _verrou:
        d = lit(uid)
        if com_id in d.setdefault("repondus", {}):
            return 0
        regle = next((r for r in d.get("regles", []) if correspond(r, texte, media)), None)
        if not regle:
            return 0
        recents = [j for j in d.get("journal", []) if j.get("ok") and j.get("date", "") >= (datetime.now() - timedelta(hours=1)).isoformat()]
        if len(recents) >= MAX_PAR_HEURE:
            return 0
        d["repondus"][com_id] = datetime.now().isoformat(timespec="seconds")
        _ecrit(uid, d)
    message = regle["message"].replace("{prenom}", "").replace("{pseudo}", "@" + (auteur.get("username") or "")).strip()
    ok, erreur = True, ""
    if not demo:
        try:
            envoie_reponse_privee(c, com_id, message, regle.get("lien", ""), regle.get("bouton", ""))
            if regle.get("reponses_publiques"):
                try:
                    repond_publiquement(c, com_id, random.choice(regle["reponses_publiques"]))
                except Exception as e:  # noqa: BLE001
                    print(f"[messages auto] réponse publique non envoyée : {e}")
        except Exception as e:  # noqa: BLE001
            ok, erreur = False, str(e)[:200]
    with _verrou:
        d = lit(uid)
        d.setdefault("journal", []).insert(0, {"date": datetime.now().isoformat(timespec="seconds"), "regle": regle["id"], "mot": regle["mots"][0],
                                               "qui": auteur.get("username", ""), "commentaire": texte[:140], "ok": ok, "erreur": erreur})
        limite = (datetime.now() - timedelta(days=JOURS_JOURNAL)).isoformat()
        d["journal"] = [j for j in d["journal"] if j.get("date", "") >= limite][:2000]
        d["repondus"] = {k: t for k, t in d["repondus"].items() if t >= (datetime.now() - timedelta(days=8)).isoformat()}
        _ecrit(uid, d)
    if ok and not demo:
        try:
            import notifications as nt
            nt.notifie(uid, "💌 Message envoyé", f"@{auteur.get('username', '')} a commenté « {regle['mots'][0]} » : ton lien lui a été envoyé.", "/app#messages")
        except Exception:  # noqa: BLE001
            pass
    return 1 if ok else 0


def envoie_reponse_privee(c: dict, comment_id: str, texte: str, lien: str = "", bouton: str = ""):
    """Une seule réponse privée par commentaire, dans les 7 jours. Avec lien : bouton cliquable, sinon texte seul."""
    url = f"{GRAPH}/{VERSION}/{c['ig_id']}/messages"
    if lien:
        corps = {"recipient": {"comment_id": comment_id}, "message": {"attachment": {"type": "template", "payload": {
            "template_type": "button", "text": texte[:640], "buttons": [{"type": "web_url", "url": lien, "title": (bouton or "Ouvrir le lien")[:20]}]}}}}
        r = requests.post(url, json=corps, headers={"Authorization": f"Bearer {c['jeton']}"}, timeout=30)
        if r.status_code == 200:
            return
        # Certains comptes refusent les boutons : on renvoie en texte, lien compris
        texte = f"{texte}\n\n{lien}"
    r = requests.post(url, json={"recipient": {"comment_id": comment_id}, "message": {"text": texte[:1000]}},
                      headers={"Authorization": f"Bearer {c['jeton']}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(_erreur(r.json(), f"Instagram a refusé l'envoi (code {r.status_code})."))


def repond_publiquement(c: dict, comment_id: str, texte: str):
    r = requests.post(f"{GRAPH}/{VERSION}/{comment_id}/replies", data={"message": texte[:300]},
                      headers={"Authorization": f"Bearer {c['jeton']}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(_erreur(r.json(), "Réponse publique refusée."))


def simule(uid: int, texte: str, qui: str = "julie.test") -> dict:
    """Mode démo et bouton « Tester » : que se passerait-il si quelqu'un commentait ce texte ?"""
    d = lit(uid)
    regle = next((r for r in d.get("regles", []) if correspond(r, texte, "")), None)
    if not regle:
        return {"declenche": False}
    return {"declenche": True, "regle": regle["nom"], "message": regle["message"].replace("{pseudo}", "@" + qui),
            "lien": regle.get("lien", ""), "bouton": regle.get("bouton", ""),
            "publique": random.choice(regle["reponses_publiques"]) if regle.get("reponses_publiques") else ""}


def ajoute_demo(uid: int, regle: dict, qui: str = "julie.test"):
    """Démo : inscrit un faux envoi au journal pour voir le rendu."""
    traite_commentaire("", {"_uid": uid, "id": secrets.token_hex(6), "text": regle["mots"][0], "from": {"id": "x", "username": qui}},
                       lambda _u: True, demo=True)
