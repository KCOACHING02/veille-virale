#!/usr/bin/env python3
"""
VEILLE VIRALE — application web (multi-clients, par abonnement)
---------------------------------------------------------------
    python app.py                         → http://localhost:8000
    python app.py --demo                  → données fictives (aucune clé API consommée)
    python app.py --hote 0.0.0.0          → sur un serveur (derrière un HTTPS : Caddy, Nginx…)

Variables d'environnement (.env) :
    APIFY_TOKEN, ANTHROPIC_API_KEY        clés de l'éditeur (toi), partagées par tous les clients
    SECRET_KEY                            clé de session (générée automatiquement si absente)
    ADMIN_EMAILS                          e-mails à accès illimité, séparés par des virgules
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET   paiement (optionnel ; prix dans plans.yaml)
"""

from __future__ import annotations

import argparse
import os
import secrets
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session

import abonnements as ab
import moteur
from espace import CODE, DATA, espace_client
from modele import LOG_HOOKS

app = Flask(__name__, static_folder=str(CODE / "static"), static_url_path="/static")
DEMO_FORCE = False


def cle_secrete() -> str:
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    f = DATA / "secret.key"
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


# Nettoie les clés collées avec des espaces, des retours à la ligne ou des guillemets
for _v in ("APIFY_TOKEN", "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"):
    if os.getenv(_v):
        os.environ[_v] = os.environ[_v].strip().strip('"').strip("'").removeprefix(_v + "=").strip()

app.secret_key = cle_secrete()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(days=30))
ab.init()


def en_demo() -> bool:
    return DEMO_FORCE or not (os.getenv("APIFY_TOKEN") and os.getenv("ANTHROPIC_API_KEY"))


def est_admin(u: dict) -> bool:
    return u["email"] in {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def droits(u: dict) -> dict:
    d = ab.droits(u)
    if est_admin(u):
        d.update(actif=True, nom_plan="Administrateur", veille_auto=bool(u.get("veille_auto")),
                 reste={"analyses": 9999, "adaptations": 9999})
    return d


def refus(u: dict, analyses=0, adaptations=0) -> str | None:
    return None if est_admin(u) else ab.peut(u, analyses, adaptations)


# ------------------------------------------------------------
#  Tâches en arrière-plan : une file, un travail à la fois (protège les quotas Apify/Claude)
# ------------------------------------------------------------
JOBS: dict[str, dict] = {}
FILE = threading.Lock()


def lance(uid: int, titre: str, fonction, *args, apres=None, **kwargs) -> str:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "uid": uid, "titre": titre, "statut": "en attente", "logs": [], "resultat": None, "erreur": None,
           "debut": datetime.now().isoformat(timespec="seconds")}
    JOBS[jid] = job

    def tourne():
        with FILE:
            job["statut"] = "en cours"
            hook = lambda m: job["logs"].append({"t": datetime.now().strftime("%H:%M:%S"), "m": m})  # noqa: E731
            LOG_HOOKS.append(hook)
            try:
                job["resultat"] = fonction(*args, **kwargs)
                if apres:
                    apres(job["resultat"])
                job["statut"] = "terminé"
            except Exception as e:  # noqa: BLE001
                job["statut"], job["erreur"] = "erreur", str(e)
                traceback.print_exc()
            finally:
                LOG_HOOKS.remove(hook)

    threading.Thread(target=tourne, daemon=True).start()
    return jid


def job_en_cours(uid: int):
    return next((j for j in JOBS.values() if j["uid"] == uid and j["statut"] in ("en attente", "en cours")), None)


# ------------------------------------------------------------
#  Authentification
# ------------------------------------------------------------
def connecte(f):
    @wraps(f)
    def w(*a, **kw):
        u = ab.get(session.get("uid", 0))
        if not u:
            return (jsonify({"erreur": "Session expirée, reconnecte-toi."}), 401) if request.path.startswith("/api/") else redirect("/connexion")
        g.u, g.esp = u, espace_client(u["id"])
        return f(*a, **kw)
    return w


@app.get("/connexion")
def page_connexion():
    return send_from_directory(CODE / "static", "connexion.html")


@app.post("/api/inscription")
def inscription():
    c = request.get_json(force=True)
    try:
        u = ab.cree(c.get("email", ""), c.get("mdp", ""), c.get("prenom", ""))
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    session.permanent, session["uid"] = True, u["id"]
    return jsonify({"ok": True})


@app.post("/api/connexion")
def connexion():
    c = request.get_json(force=True)
    time.sleep(0.3)  # freine les essais de mots de passe en rafale
    u = ab.verifie(c.get("email", ""), c.get("mdp", ""))
    if not u:
        return jsonify({"erreur": "E-mail ou mot de passe incorrect."}), 401
    session.permanent, session["uid"] = True, u["id"]
    return jsonify({"ok": True})


@app.post("/api/deconnexion")
def deconnexion():
    session.clear()
    return jsonify({"ok": True})


# ------------------------------------------------------------
#  Pages et fichiers
# ------------------------------------------------------------
@app.get("/")
@connecte
def accueil():
    return send_from_directory(CODE / "static", "index.html")


@app.get("/media/<path:nom>")
@connecte
def media(nom):
    return send_from_directory(g.esp.media, nom, max_age=86400)


@app.get("/rapports/<path:nom>")
@connecte
def fichier_rapport(nom):
    return send_from_directory(g.esp.rapports, nom, as_attachment=nom.endswith(".xlsx"))


# ------------------------------------------------------------
#  État, analyses, Reels
# ------------------------------------------------------------
@app.get("/api/etat")
@connecte
def etat():
    cfg = g.esp.lit_config()
    return jsonify({
        "utilisateur": {"prenom": g.u["prenom"], "email": g.u["email"], "onboarding": bool(g.u["onboarding"]),
                        "veille_auto": bool(g.u["veille_auto"])},
        "abonnement": droits(g.u), "demo": en_demo(),
        "niche": cfg["niche"]["nom"], "criteres": cfg["analyse"], "objectifs": cfg["objectifs"],
        "comptes": cfg["comptes"], "mon_compte": cfg.get("mon_compte") or {}, "job": job_en_cours(g.u["id"]),
    })


@app.get("/api/analyses")
@connecte
def analyses():
    return jsonify(moteur.liste_analyses(g.esp))


@app.get("/api/analyses/<aid>")
@connecte
def analyse(aid):
    try:
        return jsonify(moteur.charge(g.esp, aid))
    except FileNotFoundError:
        abort(404)


@app.delete("/api/analyses/<aid>")
@connecte
def supprime(aid):
    (g.esp.analyses / f"{Path(aid).name}.json").unlink(missing_ok=True)
    return jsonify({"ok": True})


def _apres_analyse(uid):
    return lambda a: ab.compte_usage(uid, analyses=1, adaptations=(a.get("stats") or {}).get("adaptes", 0))


@app.post("/api/analyses")
@connecte
def nouvelle():
    u, esp = g.u, g.esp
    if job_en_cours(u["id"]):
        return jsonify({"erreur": "Une analyse est déjà en cours."}), 409
    c = request.get_json(force=True)
    mode = c.get("mode", "copie")
    cfg = esp.lit_config()
    o = cfg["objectifs"]
    nb = int(c.get("nb") or 10) if mode == "copie" else int(o["reels_par_jour"] * o["jours_planifies"] * cfg["diversite"]["marge_candidats"] + .999)
    d = droits(u)
    if mode == "copie":
        nb = max(1, min(nb, d["reste"]["adaptations"]))
    msg = refus(u, analyses=1, adaptations=nb if mode == "copie" else o["reels_par_jour"] * o["jours_planifies"])
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    saisie = None
    if mode == "copie":
        saisie = moteur.parse_saisie(c.get("texte", ""), c.get("plateforme", "Instagram"))
        if not (saisie["comptes"] or saisie["posts"]):
            return jsonify({"erreur": "Aucun compte ni lien reconnu.", "ignores": saisie["ignores"]}), 400
        if c.get("ajouter_a_veille") and saisie["comptes"]:
            moteur.ajoute_a_la_veille(esp, saisie["comptes"][: max(0, d["quotas"]["comptes_surveilles"] - _nb_comptes(cfg))])
    else:
        if not _nb_comptes(cfg):
            return jsonify({"erreur": "Ajoute d'abord des comptes à surveiller (menu Comptes)."}), 400
    for k_in, k_cfg, conv in (("vues_min", "vues_min", int), ("taux_engagement_min", "taux_engagement_min", lambda x: float(x) / 100), ("mois", "mois", int)):
        if c.get(k_in):
            cfg["analyse"][k_cfg] = conv(c[k_in])
    titre = "Veille de la semaine" if mode == "veille" else "Analyse de comptes"
    jid = lance(u["id"], titre, moteur.executer, esp, cfg, mode=mode, saisie=saisie, nb_adapter=nb if mode == "copie" else None,
                demo=en_demo(), max_adaptations=d["reste"]["adaptations"], apres=_apres_analyse(u["id"]))
    return jsonify({"job": jid, "saisie": saisie})


@app.post("/api/analyses/<aid>/adapter")
@connecte
def adapter(aid):
    if job_en_cours(g.u["id"]):
        return jsonify({"erreur": "Une tâche est déjà en cours."}), 409
    msg = refus(g.u, adaptations=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    jid = lance(uid, "Adaptation d'un Reel", moteur.adapter_un, g.esp, g.esp.lit_config(), aid, request.get_json(force=True).get("cle"),
                demo=en_demo(), apres=lambda _: ab.compte_usage(uid, adaptations=1))
    return jsonify({"job": jid})


@app.get("/api/jobs/<jid>")
@connecte
def job(jid):
    j = JOBS.get(jid)
    if not j or j["uid"] != g.u["id"]:
        abort(404)
    res = {k: v for k, v in j.items() if k != "resultat"}
    r = j.get("resultat")
    res["resultat"] = {"id": r["id"]} if isinstance(r, dict) and "posts" in r else r
    return jsonify(res)


# ------------------------------------------------------------
#  Comptes surveillés
# ------------------------------------------------------------
def _nb_comptes(cfg):
    return len(cfg["comptes"].get("instagram") or []) + len(cfg["comptes"].get("tiktok") or [])


@app.get("/api/comptes")
@connecte
def comptes():
    return jsonify(g.esp.lit_config()["comptes"])


@app.post("/api/comptes")
@connecte
def ajoute_comptes():
    c = request.get_json(force=True)
    s = moteur.parse_saisie(c.get("texte", ""), c.get("plateforme", "Instagram"))
    place = droits(g.u)["quotas"]["comptes_surveilles"] - _nb_comptes(g.esp.lit_config())
    if not est_admin(g.u) and len(s["comptes"]) > place:
        return jsonify({"erreur": f"Ta formule permet {droits(g.u)['quotas']['comptes_surveilles']} comptes surveillés.", "quota": True}), 402
    ajoutes = moteur.ajoute_a_la_veille(g.esp, s["comptes"])
    return jsonify({"ajoutes": ajoutes, "ignores": s["ignores"] + [x for _, x in s["posts"]], "comptes": g.esp.lit_config()["comptes"]})


@app.delete("/api/comptes")
@connecte
def retire_compte():
    c = request.get_json(force=True)
    moteur.retire_de_la_veille(g.esp, c["plateforme"], c["compte"])
    return jsonify(g.esp.lit_config()["comptes"])


# ------------------------------------------------------------
#  Profil et assistant de configuration
# ------------------------------------------------------------
@app.get("/api/profil")
@connecte
def profil():
    cfg = g.esp.lit_config()
    voix = g.esp.voix.read_text(encoding="utf-8") if g.esp.voix.exists() else ""
    voix = "\n".join(l for l in voix.splitlines() if not l.startswith("<!--") and "COLLE ICI" not in l).strip()
    import json
    prof = json.loads(g.esp.profil_compte.read_text(encoding="utf-8")) if g.esp.profil_compte.exists() else None
    return jsonify({"niche": cfg["niche"], "objectifs": cfg["objectifs"], "analyse": cfg["analyse"], "comptes": cfg["comptes"],
                    "mon_compte": cfg.get("mon_compte") or {}, "hashtags": {"instagram": cfg["decouverte"].get("hashtags_instagram") or [],
                                                                             "tiktok": cfg["decouverte"].get("hashtags_tiktok") or []},
                    "voix": voix, "profil_compte": prof, "limite_comptes": droits(g.u)["quotas"]["comptes_surveilles"]})


@app.put("/api/profil")
@connecte
def maj_profil():
    c = request.get_json(force=True)
    cfg = g.esp.lit_config()
    for bloc in ("niche", "objectifs", "mon_compte"):
        if isinstance(c.get(bloc), dict):
            cfg.setdefault(bloc, {}).update({k: v for k, v in c[bloc].items() if v is not None})
    if isinstance(c.get("analyse"), dict):
        a = c["analyse"]
        for k, conv in (("vues_min", int), ("taux_engagement_min", float), ("mois", int)):
            if a.get(k) is not None:
                cfg["analyse"][k] = conv(a[k])
    if isinstance(c.get("comptes"), dict):
        lim = droits(g.u)["quotas"]["comptes_surveilles"]
        ig, tt = list(dict.fromkeys(c["comptes"].get("instagram") or [])), list(dict.fromkeys(c["comptes"].get("tiktok") or []))
        if not est_admin(g.u) and len(ig) + len(tt) > lim:
            return jsonify({"erreur": f"Ta formule permet {lim} comptes surveillés.", "quota": True}), 402
        cfg["comptes"] = {"instagram": ig, "tiktok": tt}
    if isinstance(c.get("hashtags"), dict):
        cfg["decouverte"]["hashtags_instagram"] = [h.strip("# ") for h in c["hashtags"].get("instagram") or [] if h.strip("# ")]
        cfg["decouverte"]["hashtags_tiktok"] = [h.strip("# ") for h in c["hashtags"].get("tiktok") or [] if h.strip("# ")]
    if "voix" in c:
        g.esp.voix.write_text(c["voix"] or "", encoding="utf-8")
    g.esp.ecrit_config(cfg)
    if c.get("onboarding_termine"):
        ab.maj(g.u["id"], onboarding=1)
    if "veille_auto" in c:
        ab.maj(g.u["id"], veille_auto=1 if c["veille_auto"] else 0)
    return jsonify({"ok": True})


@app.post("/api/assistant/mon-compte")
@connecte
def assistant_compte():
    if job_en_cours(g.u["id"]):
        return jsonify({"erreur": "Une tâche est déjà en cours."}), 409
    c = request.get_json(force=True)
    cfg = g.esp.lit_config()
    cfg["mon_compte"] = {"instagram": (c.get("instagram") or "").strip().lstrip("@"), "tiktok": (c.get("tiktok") or "").strip().lstrip("@")}
    g.esp.ecrit_config(cfg)
    jid = lance(g.u["id"], "Analyse de ton compte", moteur.analyse_mon_compte, g.esp, cfg,
                cfg["mon_compte"]["instagram"], cfg["mon_compte"]["tiktok"], demo=en_demo())
    return jsonify({"job": jid})


@app.post("/api/assistant/hashtags")
@connecte
def assistant_hashtags():
    cfg = g.esp.lit_config()
    c = request.get_json(force=True) or {}
    cfg["niche"].update({k: v for k, v in (c.get("niche") or {}).items() if v})
    try:
        return jsonify(moteur.suggere_hashtags(cfg, demo=en_demo()))
    except Exception as e:  # noqa: BLE001
        return jsonify({"erreur": str(e)}), 500


# ------------------------------------------------------------
#  Abonnement
# ------------------------------------------------------------
@app.get("/api/abonnement")
@connecte
def abonnement():
    p = ab.plans()
    return jsonify({"droits": droits(g.u), "stripe": ab.stripe_actif(), "demo": en_demo(),
                    "plans": [{"id": k, **{x: v[x] for x in ("nom", "prix_mensuel", "analyses_par_mois", "adaptations_par_mois", "comptes_surveilles", "veille_auto")}}
                              for k, v in p.items() if k != "essai"],
                    "portail": bool(g.u.get("stripe_client"))})


@app.post("/api/abonnement/choisir")
@connecte
def choisir_plan():
    plan = request.get_json(force=True).get("plan")
    if plan not in ab.plans() or plan == "essai":
        return jsonify({"erreur": "Formule inconnue."}), 400
    retour = request.host_url.rstrip("/") + "/"
    if ab.stripe_actif():
        try:
            return jsonify({"url": ab.checkout(g.u, plan, retour)})
        except ValueError as e:
            return jsonify({"erreur": str(e)}), 400
    if en_demo():  # sans Stripe, en démo : changement direct pour tester
        ab.maj(g.u["id"], plan=plan, statut="actif")
        return jsonify({"ok": True, "simule": True})
    return jsonify({"erreur": "Le paiement n'est pas encore configuré (STRIPE_SECRET_KEY)."}), 400


@app.post("/api/abonnement/portail")
@connecte
def portail():
    try:
        return jsonify({"url": ab.portail(g.u, request.host_url)})
    except (ValueError, KeyError) as e:
        return jsonify({"erreur": str(e)}), 400


@app.post("/api/stripe/webhook")
def stripe_webhook():
    try:
        typ = ab.webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    except PermissionError:
        abort(400)
    return jsonify({"recu": typ})


# ------------------------------------------------------------
#  Veille automatique : chaque lundi matin pour les formules qui l'incluent
# ------------------------------------------------------------
def planificateur():
    while True:
        try:
            now = datetime.now()
            lundi = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            if now.hour >= 6:
                for u in ab.tous():
                    d = droits(u)
                    if not (u["onboarding"] and d["veille_auto"] and d["actif"]) or (u.get("derniere_veille_auto") or "") >= lundi:
                        continue
                    esp = espace_client(u["id"])
                    cfg = esp.lit_config()
                    if not _nb_comptes(cfg) or refus(u, analyses=1, adaptations=cfg["objectifs"]["reels_par_jour"] * cfg["objectifs"]["jours_planifies"]):
                        continue
                    ab.maj(u["id"], derniere_veille_auto=lundi)
                    lance(u["id"], "Veille automatique du lundi", moteur.executer, esp, cfg, mode="veille", demo=en_demo(),
                          max_adaptations=d["reste"]["adaptations"], apres=_apres_analyse(u["id"]))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(900)


def main():
    global DEMO_FORCE
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--hote", default=os.getenv("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))  # PORT est fourni par Railway, Render…
    ap.add_argument("--sans-planificateur", action="store_true")
    args = ap.parse_args()
    DEMO_FORCE = args.demo
    if not args.sans_planificateur:
        threading.Thread(target=planificateur, daemon=True).start()
    print(f"Données : {DATA}")
    if os.getenv("RAILWAY_ENVIRONMENT") and not os.getenv("RAILWAY_VOLUME_MOUNT_PATH") and not os.getenv("DATA_DIR"):
        print("⚠️  Aucun volume Railway détecté : les comptes seront effacés à chaque mise à jour.")
    print(f"→ Ouvre http://{'localhost' if args.hote == '127.0.0.1' else args.hote}:{args.port}"
          + ("   (mode démo : données fictives)" if en_demo() else ""))
    try:
        from waitress import serve
        serve(app, host=args.hote, port=args.port, threads=8)
    except ImportError:
        app.run(host=args.hote, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
