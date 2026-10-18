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
    RESEND_API_KEY, EMAIL_EXPEDITEUR      e-mails (mot de passe oublié, bienvenue, veille prête)
    URL_PUBLIQUE                          adresse du site (ex. https://veille.mondomaine.fr), pour les liens des e-mails
"""

from __future__ import annotations

import argparse
import json
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
import emails
import moteur
import publications as pubs
from espace import CODE, DATA, espace_client
from modele import FIL, LOG_HOOKS

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
for _v in ("APIFY_TOKEN", "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY"):
    if os.getenv(_v):
        os.environ[_v] = os.environ[_v].strip().strip('"').strip("'").removeprefix(_v + "=").strip()

app.secret_key = cle_secrete()
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 7 * 86400  # polices, images : gardées en cache par le navigateur


# ------------------------------------------------------------
#  Performance : compression des réponses et pages HTML jamais mises en cache
# ------------------------------------------------------------
import gzip as _gzip  # noqa: E402

TYPES_COMPRESSES = ("application/json", "text/html", "text/css", "application/javascript", "text/javascript", "image/svg+xml")


@app.after_request
def compresse(rep):
    if rep.mimetype == "text/html":
        rep.headers["Cache-Control"] = "no-cache"  # toujours la dernière version de l'application après une mise à jour
    if (rep.direct_passthrough or rep.status_code < 200 or rep.status_code >= 300 or "Content-Encoding" in rep.headers
            or rep.mimetype not in TYPES_COMPRESSES or "gzip" not in request.headers.get("Accept-Encoding", "")):
        return rep
    donnees = rep.get_data()
    if len(donnees) < 1500:
        return rep
    rep.set_data(_gzip.compress(donnees, compresslevel=5))
    rep.headers["Content-Encoding"] = "gzip"
    rep.headers["Vary"] = "Accept-Encoding"
    rep.headers["Content-Length"] = str(len(rep.get_data()))
    return rep
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(days=30),
                  MAX_CONTENT_LENGTH=300 * 1024 * 1024)  # vidéos du studio : 300 Mo maximum
ab.init()


def en_demo() -> bool:
    return DEMO_FORCE or not (os.getenv("APIFY_TOKEN") and os.getenv("ANTHROPIC_API_KEY"))


def est_admin(u: dict) -> bool:
    return u["email"] in {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def droits(u: dict) -> dict:
    d = ab.droits(u)
    if est_admin(u):
        d.update(actif=True, nom_plan="Administrateur", veille_auto=bool(u.get("veille_auto")),
                 reste={"analyses": 9999, "adaptations": 9999, "studio": 9999})
    return d


def refus(u: dict, analyses=0, adaptations=0, studio=0) -> str | None:
    return None if est_admin(u) else ab.peut(u, analyses, adaptations, studio)


# ------------------------------------------------------------
#  Tâches en arrière-plan : une file, un travail à la fois (protège les quotas Apify/Claude)
# ------------------------------------------------------------
JOBS: dict[str, dict] = {}
FILE = threading.Lock()
FILE_STUDIO = threading.Lock()  # montages du studio : file séparée, pour ne pas attendre la fin d'une veille


JOBS_DIR = DATA / "jobs"


def lance(uid: int, titre: str, fonction, *args, apres=None, persiste: dict | None = None, file_=None, **kwargs) -> str:
    """Lance une tâche. `persiste` (paramètres JSON d'une analyse) permet de la reprendre si le serveur redémarre."""
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "uid": uid, "titre": titre, "statut": "en attente", "logs": [], "resultat": None, "erreur": None,
           "debut": datetime.now().isoformat(timespec="seconds"), "analyse_id": kwargs.get("aid"),
           "studio": file_ is FILE_STUDIO}
    JOBS[jid] = job
    fichier = None
    if persiste is not None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        fichier = JOBS_DIR / f"{jid}.json"
        fichier.write_text(json.dumps({"uid": uid, "titre": titre, "params": persiste}, ensure_ascii=False), encoding="utf-8")

    def tourne():
        try:  # les tâches lourdes (Whisper, ffmpeg) passent après les pages : le site reste fluide pendant une veille
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        with (file_ or FILE):
            job["statut"] = "en cours"
            def hook(m):
                job["logs"].append({"t": datetime.now().strftime("%H:%M:%S"), "m": m})
            hook.studio = FIL.studio = job["studio"]
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
                if fichier:
                    fichier.unlink(missing_ok=True)

    threading.Thread(target=tourne, daemon=True).start()
    return jid


def lance_analyse(uid: int, titre: str, params: dict) -> str:
    """Analyse complète, persistée : relancée automatiquement après un redémarrage du serveur."""
    params = {**params, "aid": params.get("aid") or f"{datetime.now():%Y%m%d-%H%M%S}-{params.get('mode', 'veille')}"}
    return lance(uid, titre, moteur.executer, espace_client(uid), apres=_apres_analyse(uid), persiste=params, **params)


def reprend_analyses():
    """Au démarrage : relance les analyses interrompues (les collectes et adaptations déjà faites sont réutilisées)."""
    if not JOBS_DIR.exists():
        return
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            f.unlink()
            if j.get("reprises", 0) >= 2:
                continue  # évite une boucle si l'analyse fait elle-même planter le serveur
            print(f"Reprise de l'analyse interrompue « {j['titre']} » (client {j['uid']})")
            jid = lance_analyse(j["uid"], j["titre"], j["params"])
            nf = JOBS_DIR / f"{jid}.json"
            if nf.exists():
                d = json.loads(nf.read_text(encoding="utf-8"))
                d["reprises"] = j.get("reprises", 0) + 1
                nf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            JOBS[jid]["logs"].append({"t": datetime.now().strftime("%H:%M:%S"),
                                      "m": "Reprise automatique après redémarrage du serveur : les étapes déjà faites sont réutilisées."})
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def job_en_cours(uid: int, studio_: bool = False):
    return next((j for j in JOBS.values() if j["uid"] == uid and j["statut"] in ("en attente", "en cours")
                 and j.get("studio", False) == studio_), None)


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
    return _page("connexion.html")


def _page(nom: str):
    """Page HTML lue en mémoire (compressible), jamais mise en cache par le navigateur."""
    rep = send_from_directory(CODE / "static", nom, max_age=0)
    rep.direct_passthrough = False
    return rep


def url_site() -> str:
    """Adresse publique du site (liens des e-mails). Sur Railway, déduite du domaine si URL_PUBLIQUE est absente."""
    if os.getenv("URL_PUBLIQUE"):
        return os.environ["URL_PUBLIQUE"].rstrip("/")
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        return "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:  # hors requête (planificateur)
        return "http://localhost:8000"


@app.post("/api/inscription")
def inscription():
    c = request.get_json(force=True)
    if not c.get("cgv"):
        return jsonify({"erreur": "Accepte les conditions générales pour créer ton compte."}), 400
    try:
        u = ab.cree(c.get("email", ""), c.get("mdp", ""), c.get("prenom", ""), cgv=True)
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    session.permanent, session["uid"] = True, u["id"]
    ab.maj(u["id"], derniere_connexion=datetime.now().isoformat(timespec="minutes"))
    emails.bienvenue(u["email"], u.get("prenom") or "", url_site() + "/app")
    return jsonify({"ok": True})


@app.post("/api/mot-de-passe-oublie")
def mot_de_passe_oublie():
    time.sleep(0.4)
    u = ab.par_email((request.get_json(force=True) or {}).get("email", ""))
    res = {"ok": True}  # même réponse que le compte existe ou non (on ne révèle pas les adresses inscrites)
    if u:
        lien = f"{url_site()}/connexion?t={ab.jeton_reinit(u['id'])}"
        emails.reinitialisation(u["email"], lien)
        if en_demo() and not emails.actif():
            res["lien_demo"] = lien
    return jsonify(res)


@app.post("/api/reinitialiser")
def reinitialiser():
    c = request.get_json(force=True)
    try:
        u = ab.reinitialise(c.get("jeton", ""), c.get("mdp", ""))
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
    ab.maj(u["id"], derniere_connexion=datetime.now().isoformat(timespec="minutes"))
    return jsonify({"ok": True})


@app.post("/api/deconnexion")
def deconnexion():
    session.clear()
    return jsonify({"ok": True})


# ------------------------------------------------------------
#  Pages et fichiers
# ------------------------------------------------------------
@app.get("/")
def accueil():
    """Visiteur : page de présentation. Client connecté : son application."""
    if ab.get(session.get("uid", 0)):
        return _page("index.html")
    return _page("accueil.html")


@app.get("/app")
@connecte
def application():
    return _page("index.html")


@app.get("/api/formules")
def formules_publiques():
    p = ab.plans()
    return jsonify({"essai_jours": p["essai"].get("duree_jours", 7),
                    "plans": [{"id": k, **{x: v.get(x) for x in ("nom", "prix_mensuel", "analyses_par_mois", "adaptations_par_mois",
                                                                 "comptes_surveilles", "veille_auto", "studio_par_mois")}}
                              for k, v in p.items() if k != "essai"]})


@app.get("/<any(cgv, confidentialite, 'mentions-legales'):page>")
def page_legale(page):
    import legal
    return legal.page(page)


@app.get("/media/<path:nom>")
@connecte
def media(nom):
    allege(g.esp.media / Path(nom).name)
    return send_from_directory(g.esp.media, nom, max_age=7 * 86400)


def allege(f: Path, largeur: int = 480, seuil: int = 90_000):
    """Les couvertures Instagram font souvent 1080 px : on les réduit une fois pour toutes (galerie bien plus rapide)."""
    try:
        if f.suffix.lower() in (".jpg", ".jpeg") and f.exists() and f.stat().st_size > seuil:
            from PIL import Image
            im = Image.open(f)
            if im.width > largeur:
                im = im.convert("RGB")
                im.thumbnail((largeur, largeur * 2))
                tmp = f.with_suffix(".tmp.jpg")
                im.save(tmp, "JPEG", quality=78, optimize=True)
                tmp.replace(f)
    except Exception:  # noqa: BLE001
        pass


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
        "abonnement": droits(g.u), "demo": en_demo(), "admin": est_admin(g.u),
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
    def fin(a):
        st = a.get("stats") or {}
        ab.compte_usage(uid, analyses=1, adaptations=st.get("adaptes", 0),
                        cout=0 if a.get("demo") else (st.get("cout_apify_usd") or 0) + (st.get("cout_claude_usd") or 0))
        u = ab.get(uid)
        if u and a.get("mode") == "veille" and st.get("adaptes"):
            emails.veille_prete(u["email"], u.get("prenom") or "", st["adaptes"], url_site() + "/app")
    return fin


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
    for k_in, k_cfg, conv in (("vues_min", "vues_min", int), ("taux_engagement_min", "taux_engagement_min", lambda x: float(x) / 100), ("mois", "mois", int),
                             ("seuil_mode", "seuil_mode", str), ("seuil_multiple", "seuil_multiple", float)):
        if c.get(k_in):
            cfg["analyse"][k_cfg] = conv(c[k_in])
    titre = "Veille de la semaine" if mode == "veille" else "Analyse de comptes"
    jid = lance_analyse(u["id"], titre, {"cfg": cfg, "mode": mode, "saisie": saisie, "nb_adapter": nb if mode == "copie" else None,
                                         "demo": en_demo(), "max_adaptations": d["reste"]["adaptations"]})
    return jsonify({"job": jid, "saisie": saisie})


@app.post("/api/estimation")
@connecte
def estimation():
    c = request.get_json(force=True)
    mode = c.get("mode", "copie")
    saisie = moteur.parse_saisie(c.get("texte", ""), c.get("plateforme", "Instagram")) if mode == "copie" else None
    cfg = g.esp.lit_config()
    if c.get("mois"):
        cfg["analyse"]["mois"] = int(c["mois"])
    return jsonify(moteur.estime(g.esp, cfg, mode, saisie, int(c.get("nb") or 10)))


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
    if len(res["logs"]) > 160:  # le début (phases) et la fin suffisent au suivi
        res["logs"] = res["logs"][:40] + res["logs"][-120:]
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
        for k, conv in (("vues_min", int), ("taux_engagement_min", float), ("mois", int), ("seuil_mode", str),
                        ("seuil_multiple", float), ("seuil_plancher", int)):
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
#  Mes publications (bouton « J'ai publié »)
# ------------------------------------------------------------
@app.get("/api/publications")
@connecte
def publications_liste():
    cfg = g.esp.lit_config()
    return jsonify({"publications": pubs.charge(g.esp), "bilan": pubs.bilan_semaine(g.esp, cfg)})


@app.post("/api/publications")
@connecte
def publication_ajoute():
    c = request.get_json(force=True)
    inspiration = None
    if c.get("analyse_id") and c.get("cle"):
        try:
            inspiration = next((p for p in moteur.charge(g.esp, c["analyse_id"])["posts"] if p["cle"] == c["cle"]), None)
        except FileNotFoundError:
            pass
    try:
        pub = pubs.ajoute(g.esp, c.get("url", ""), inspiration)
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    _lance_releve(g.u["id"])
    return jsonify(pub)


@app.patch("/api/publications/<pid>")
@connecte
def publication_modifie(pid):
    try:
        return jsonify(pubs.modifie(g.esp, pid, **request.get_json(force=True)))
    except KeyError:
        abort(404)
    except ValueError:
        return jsonify({"erreur": "Nombre invalide."}), 400


@app.delete("/api/publications/<pid>")
@connecte
def publication_supprime(pid):
    pubs.supprime(g.esp, pid)
    return jsonify({"ok": True})


@app.post("/api/publications/maj")
@connecte
def publications_maj():
    if job_en_cours(g.u["id"]):
        return jsonify({"erreur": "Une tâche est déjà en cours."}), 409
    return jsonify({"job": _lance_releve(g.u["id"], forcer=True)})


def _lance_releve(uid: int, forcer: bool = False):
    if job_en_cours(uid):
        return None
    esp = espace_client(uid)
    return lance(uid, "Mise à jour de tes publications", pubs.releve, esp, esp.lit_config(), os.getenv("APIFY_TOKEN"),
                 forcer=forcer, demo=en_demo())


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
#  Studio : carrousels et Reels montés à partir des fichiers de l'utilisateur
# ------------------------------------------------------------
import studio  # noqa: E402


def _projet(sid):
    try:
        return studio.charge(g.esp, sid)
    except FileNotFoundError:
        abort(404)


@app.get("/api/studio")
@connecte
def studio_liste():
    return jsonify({"projets": studio.liste(g.esp), "reste": droits(g.u)["reste"]["studio"], "quota": droits(g.u)["quotas"]["studio_par_mois"],
                    **_options_studio()})


def _options_studio():
    return {"styles": [{"id": k, "nom": v[0], "aide": v[1]} for k, v in studio.STYLES.items()],
            "typos": [{"id": k, "nom": studio.NOMS_TYPOS[k], "police": v[5]} for k, v in studio.TYPOS.items()],
            "voix_connue": studio.voix_connue(g.esp)}


@app.post("/api/studio")
@connecte
def studio_cree():
    c = request.get_json(force=True)
    msg = refus(g.u)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre création : réessaie dans un instant."}), 409
    try:
        post = next(p for p in moteur.charge(g.esp, c["analyse_id"])["posts"] if p["cle"] == c["cle"])
    except (FileNotFoundError, StopIteration, KeyError):
        return jsonify({"erreur": "Reel introuvable."}), 404
    if not (post.get("adaptation") and not post["adaptation"].get("erreur")):
        return jsonify({"erreur": "Adapte d'abord ce Reel."}), 400
    cfg = g.esp.lit_config()
    p = studio.cree(g.esp, cfg, post, c.get("type", "carrousel"), c["analyse_id"], c.get("style") or "ma_voix")
    # Carrousel copié d'un carrousel modèle : les slides sont déjà adaptées une par une pendant la veille, rien à réécrire
    jid = None if (p.get("copie_du_modele") and p["type"] == "carrousel") else lance(
        g.u["id"], "Écriture des slides", studio.ecrit_textes, g.esp, cfg, p["id"], demo=en_demo(), file_=FILE_STUDIO)
    p.pop("adaptation", None)
    return jsonify({"projet": p, "job": jid})


@app.get("/api/studio/<sid>")
@connecte
def studio_projet(sid):
    p = _projet(sid)
    p.pop("adaptation", None)
    return jsonify({**p, "options": _options_studio()})


@app.put("/api/studio/<sid>")
@connecte
def studio_modifie(sid):
    _projet(sid)
    p = studio.modifie(g.esp, sid, request.get_json(force=True) or {})
    p.pop("adaptation", None)
    return jsonify(p)


@app.delete("/api/studio/<sid>")
@connecte
def studio_supprime(sid):
    _projet(sid)
    studio.supprime(g.esp, sid)
    return jsonify({"ok": True})


@app.post("/api/studio/<sid>/fichiers")
@connecte
def studio_import(sid):
    _projet(sid)
    erreurs, p = [], None
    for f in request.files.getlist("fichiers"):
        try:
            p = studio.ajoute_fichier(g.esp, sid, f.filename, f)
        except ValueError as e:
            erreurs.append(str(e))
    p = p or studio.charge(g.esp, sid)
    p.pop("adaptation", None)
    return jsonify({"projet": p, "erreurs": erreurs}), (400 if erreurs and not request.files else 200)


@app.delete("/api/studio/<sid>/fichiers/<nom>")
@connecte
def studio_retire(sid, nom):
    _projet(sid)
    p = studio.retire_fichier(g.esp, sid, nom)
    p.pop("adaptation", None)
    return jsonify(p)


@app.post("/api/studio/<sid>/ecrire")
@connecte
def studio_ecrire(sid):
    _projet(sid)
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre création : réessaie dans un instant."}), 409
    msg = refus(g.u)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    return jsonify({"job": lance(g.u["id"], "Écriture des slides", studio.ecrit_textes, g.esp, g.esp.lit_config(), sid,
                                 demo=en_demo(), file_=FILE_STUDIO)})


@app.post("/api/studio/<sid>/generer")
@connecte
def studio_generer(sid):
    p = _projet(sid)
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre création : réessaie dans un instant."}), 409
    deja = bool(p.get("genere_le"))  # régénérer après une retouche ne consomme pas de nouvelle création
    msg = None if deja else refus(g.u, studio=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    titre = "Création du carrousel" if p["type"] == "carrousel" else "Montage du Reel"
    jid = lance(uid, titre, studio.genere, g.esp, sid, demo=en_demo(), file_=FILE_STUDIO,
                apres=None if deja else (lambda _: ab.compte_usage(uid, studio=1)))
    return jsonify({"job": jid})


@app.get("/studio/<sid>/<dossier_>/<nom>")
@connecte
def studio_fichier(sid, dossier_, nom):
    if dossier_ not in ("sources", "sortie"):
        abort(404)
    try:
        d = studio.dossier(g.esp, sid) / dossier_
    except FileNotFoundError:
        abort(404)
    return send_from_directory(d, nom, as_attachment=request.args.get("telecharger") == "1")


# ------------------------------------------------------------
#  Administration (réservée aux adresses ADMIN_EMAILS)
# ------------------------------------------------------------
def admin_requis(f):
    @wraps(f)
    @connecte
    def w(*a, **kw):
        if not est_admin(g.u):
            abort(404)
        return f(*a, **kw)
    return w


@app.get("/admin")
@admin_requis
def page_admin():
    return _page("admin.html")


@app.get("/api/admin")
@admin_requis
def admin_donnees():
    p = ab.plans()
    us = ab.usage_tous()
    clients, mrr, cout_mois = [], 0, 0.0
    for u in ab.tous():
        d = ab.droits(u)
        m = (us.get(u["id"]) or {}).get("mois") or {}
        prix = (p.get(u["plan"]) or {}).get("prix_mensuel", 0) if u["statut"] == "actif" else 0
        mrr += prix
        cout_mois += m.get("cout_usd", 0)
        clients.append({
            "id": u["id"], "email": u["email"], "prenom": u["prenom"], "plan": u["plan"], "nom_plan": d["nom_plan"],
            "statut": u["statut"], "actif": d["actif"], "admin": est_admin(u), "cree": u["cree"], "fin_essai": u["fin_essai"],
            "derniere_connexion": u.get("derniere_connexion"), "onboarding": bool(u["onboarding"]), "stripe": bool(u.get("stripe_client")),
            "analyses_mois": m.get("analyses", 0), "adaptations_mois": m.get("adaptations", 0),
            "cout_mois": round(m.get("cout_usd", 0), 2), "cout_total": round((us.get(u["id"]) or {}).get("total_cout", 0), 2),
            "prix": prix, "job": (job_en_cours(u["id"]) or {}).get("titre"),
        })
    clients.sort(key=lambda c: c["cree"] or "", reverse=True)
    return jsonify({
        "clients": clients, "plans": {k: v["nom"] for k, v in p.items()},
        "kpi": {"clients": len(clients), "payants": sum(1 for c in clients if c["prix"]),
                "essais": sum(1 for c in clients if c["statut"] == "essai" and c["actif"]),
                "mrr": mrr, "cout_mois_usd": round(cout_mois, 2)},
        "config": {"apify": bool(os.getenv("APIFY_TOKEN")), "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
                   "stripe": ab.stripe_actif(), "emails": emails.actif(), "demo": en_demo(), "url": url_site()},
    })


@app.patch("/api/admin/clients/<int:uid>")
@admin_requis
def admin_modifie(uid):
    c = request.get_json(force=True)
    u = ab.get(uid)
    if not u:
        abort(404)
    champs = {}
    if c.get("plan") in ab.plans():
        champs["plan"] = c["plan"]
    if c.get("statut") in ("essai", "actif", "impaye", "resilie", "suspendu"):
        champs["statut"] = c["statut"]
    if c.get("prolonger_jours"):
        base = max(datetime.now(), datetime.fromisoformat(u["fin_essai"]) if u.get("fin_essai") else datetime.now())
        champs.update(fin_essai=(base + timedelta(days=int(c["prolonger_jours"]))).isoformat(timespec="minutes"), statut="essai")
    ab.maj(uid, **champs)
    res = {"ok": True}
    if c.get("lien_mdp"):
        res["lien"] = f"{url_site()}/connexion?t={ab.jeton_reinit(uid, heures=48)}"
    return jsonify(res)


# ------------------------------------------------------------
#  Veille automatique : chaque lundi matin pour les formules qui l'incluent
# ------------------------------------------------------------
def planificateur():
    while True:
        try:
            now = datetime.now()
            lundi = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            for u in ab.tous():  # relevés des Reels publiés (J+2, J+7)
                try:
                    if droits(u)["actif"] and pubs.a_relever_esp(espace_client(u["id"])):
                        _lance_releve(u["id"])
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
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
                    lance_analyse(u["id"], "Veille automatique du lundi", {"cfg": cfg, "mode": "veille", "demo": en_demo(),
                                                                           "max_adaptations": d["reste"]["adaptations"]})
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
    reprend_analyses()
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
