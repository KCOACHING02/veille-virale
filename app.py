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
    PIXABAY_API_KEY (ou PEXELS_API_KEY)   banque d'images et de vidéos libres de droits du studio (gratuite)
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
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session

import abonnements as ab
import emails
import notifications as nt
import moteur
import publications as pubs
from espace import CODE, DATA, espace_client
from modele import FIL, LOG_HOOKS

app = Flask(__name__, static_folder=str(CODE / "static"), static_url_path="/static")
app.json.sort_keys = False  # garde l'ordre voulu des options (thèmes, formes…)
DEMO_FORCE = False


def trop_lourd(_e):
    return jsonify({"erreur": "Fichier trop lourd (300 Mo maximum). Sur iPhone, filme en 1080p (Réglages → Appareil photo → Enregistrement vidéo) "
                              "ou raccourcis la vidéo avant de l'envoyer."}), 413


app.register_error_handler(413, trop_lourd)


@app.before_request
def vers_domaine_principal():
    """Ancienne adresse *.up.railway.app → nom de domaine (URL_PUBLIQUE), pour les pages consultées (GET).
    Les appels entrants (webhooks Stripe, formulaires) ne sont pas redirigés : ils continuent de fonctionner."""
    cible = (os.getenv("URL_PUBLIQUE") or "").rstrip("/")
    hote = (request.host or "").split(":")[0].lower()
    if cible and request.method in ("GET", "HEAD") and hote.endswith(".up.railway.app") and hote not in cible:
        return redirect(cible + request.full_path.rstrip("?"), 301)


def cle_secrete() -> str:
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    f = DATA / "secret.key"
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


# Nettoie les clés collées avec des espaces, des retours à la ligne ou des guillemets
for _v in ("APIFY_TOKEN", "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY"):
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
        d.update(actif=True, nom_plan="Administrateur", veille_auto=bool(u.get("veille_auto")), gratuit=False,
                 options={**ab.OPTIONS_DEFAUT, "filigrane": False, "mention_boutique": False},
                 reste={"analyses": 9999, "adaptations": 9999, "studio": 9999})
    return d


def refus(u: dict, analyses=0, adaptations=0, studio=0) -> str | None:
    return None if est_admin(u) else ab.peut(u, analyses, adaptations, studio)


def reserve(u: dict, option: str) -> str | None:
    """Fonction incluse dans la formule ? (formule gratuite : pas d'IA, pas de montage de Reel, pas de suivi…)"""
    return None if est_admin(u) else ab.reserve(u, option)


def bloque(msg: str):
    return jsonify({"erreur": msg, "quota": True}), 402


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
            import ia as _ia
            cout_avant = _ia.cout_total()
            def hook(m):
                job["logs"].append({"t": datetime.now().strftime("%H:%M:%S"), "m": m})
            hook.studio = FIL.studio = job["studio"]
            FIL.verrou = file_ or FILE  # une longue attente (traitement différé) peut libérer la file pendant ce temps
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
                # coût IA des petites tâches (adaptation, assistant, boutique) : les analyses l'enregistrent elles-mêmes
                cout = _ia.cout_total() - cout_avant
                if persiste is None and cout > 0 and not en_demo():
                    try:
                        ab.compte_usage(uid, cout=cout)
                    except Exception:  # noqa: BLE001
                        pass

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
            if request.path.startswith("/api/"):
                return jsonify({"erreur": "Session expirée, reconnecte-toi."}), 401
            # Après connexion, on revient à la page demandée (ex. lien d'un e-mail ouvert sur le téléphone)
            suite = request.full_path.rstrip("?")
            return redirect(f"/connexion?suite={quote(suite)}#connexion" if suite not in ("/", "/app") else "/connexion#connexion")
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
    code = (c.get("parrain") or request.cookies.get("vv_parrain") or "").strip().lower()
    if code and ab.rattache_parrain(u["id"], code):
        p = ab.par_code(code)
        if p:
            nt.notifie(p["id"], "Ta filleule s'est inscrite 💌", f"{u.get('prenom') or 'Une amie'} a rejoint Virallink grâce à toi.", "/app")
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
    rep = _page("accueil.html")
    code = (request.args.get("parrain") or "").strip().lower()
    if code and _re.fullmatch(r"[a-z0-9]{3,20}", code):
        rep.set_cookie("vv_parrain", code, max_age=60 * 86400, samesite="Lax", secure=request.is_secure)
    return rep


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
        "boutique": bq.pseudo_de(g.u["id"]),
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
            nt.notifie(uid, "Ta veille est prête 🔥", f"{st['adaptes']} Reels viraux adaptés à ta niche t'attendent.", "/app")
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
    classement = not d["options"]["ia"]  # formule gratuite : classement des Reels viraux, sans adaptation
    if classement and mode == "veille":
        return bloque("La veille de la semaine (Reels trouvés et adaptés pour toi) est réservée aux abonnées. "
                      "En gratuit, lance un classement de comptes : tu verras leurs Reels viraux et les sons tendance.")
    if mode == "copie":
        nb = max(1, min(nb, d["reste"]["adaptations"]))
    msg = refus(u, analyses=1) if classement else refus(u, analyses=1, adaptations=nb if mode == "copie" else min(o["reels_par_jour"] * o["jours_planifies"], moteur.adaptations_auto(cfg)))
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    saisie = None
    if mode == "copie":
        saisie = moteur.parse_saisie(c.get("texte", ""), c.get("plateforme", "Instagram"))
        if not (saisie["comptes"] or saisie["posts"]):
            return jsonify({"erreur": "Aucun compte ni lien reconnu.", "ignores": saisie["ignores"]}), 400
        lim = d["quotas"]["comptes_surveilles"]
        if classement and len(saisie["comptes"]) + len(saisie["posts"]) > lim:
            return bloque(f"En gratuit, un classement porte sur {lim} comptes au maximum. Garde les {lim} qui t'intéressent le plus.")
        if c.get("ajouter_a_veille") and saisie["comptes"] and not classement:
            moteur.ajoute_a_la_veille(esp, saisie["comptes"][: max(0, d["quotas"]["comptes_surveilles"] - _nb_comptes(cfg))])
    else:
        if not _nb_comptes(cfg):
            return jsonify({"erreur": "Ajoute d'abord des comptes à surveiller (menu Comptes)."}), 400
    for k_in, k_cfg, conv in (("vues_min", "vues_min", int), ("taux_engagement_min", "taux_engagement_min", lambda x: float(x) / 100), ("mois", "mois", int),
                             ("seuil_mode", "seuil_mode", str), ("seuil_multiple", "seuil_multiple", float)):
        if c.get(k_in):
            cfg["analyse"][k_cfg] = conv(c[k_in])
    titre = "Veille de la semaine" if mode == "veille" else "Analyse de comptes"
    if classement:
        titre = "Classement de comptes"
    jid = lance_analyse(u["id"], titre, {"cfg": cfg, "mode": mode, "saisie": saisie, "nb_adapter": nb if mode == "copie" else None,
                                         "demo": en_demo(), "max_adaptations": d["reste"]["adaptations"], "classement_seul": classement})
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
    msg = reserve(g.u, "ia") or refus(g.u, adaptations=1)
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
                    "voix": voix, "profil_compte": prof, "limite_comptes": droits(g.u)["quotas"]["comptes_surveilles"],
                    "marque": cfg.get("marque") or {}, "typos": _options_studio()["typos"],
                    "synthese": bool(g.u.get("synthese", 1))})


MISES_EN_FORME = ("phrases courtes", "sauts de ligne entre les idées", "listes à puces ou numérotées", "majuscules pour insister",
                  "une question au lecteur", "texte en paragraphes")


def _marque_propre(m: dict) -> dict:
    """Réglages de marque reçus de l'interface, nettoyés (valeurs connues, longueurs limitées)."""
    t = lambda k, n: str(m.get(k) or "").strip()[:n]  # noqa: E731
    c = m.get("couleurs") if isinstance(m.get("couleurs"), dict) else {}
    couleurs = {k: c[k] for k in ("fond", "texte", "accent") if studio.HEX.match(str(c.get(k) or ""))}
    return {
        "adresse": m.get("adresse") if m.get("adresse") in ("tu", "vous") else "",
        "emojis": m.get("emojis") if m.get("emojis") in ("aucun", "peu", "beaucoup") else "",
        "longueur": m.get("longueur") if m.get("longueur") in ("courte", "moyenne", "longue") else "",
        "mise_en_forme": [x for x in (m.get("mise_en_forme") or []) if x in MISES_EN_FORME],
        "signature": t("signature", 200), "expressions": t("expressions", 500), "mots_interdits": t("mots_interdits", 500),
        "hashtags": t("hashtags", 300), "consignes": t("consignes", 1000),
        "couleurs": couleurs if len(couleurs) == 3 else {},
        "typo": m.get("typo") if m.get("typo") in studio.TYPOS else "",
    }


@app.post("/api/marque/palette")
@connecte
def marque_palette():
    """Couleurs dominantes d'une image de ses publications (calcul local, aucune API)."""
    f = request.files.get("fichier")
    if not f:
        return jsonify({"erreur": "Aucune image reçue."}), 400
    try:
        from PIL import Image
        im = Image.open(f.stream).convert("RGB")
        im.thumbnail((200, 200))
        q = im.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[:24]
        comptes = sorted(q.getcolors(), reverse=True)
        couleurs = []
        for n, i in comptes:
            r, gr, b = pal[3 * i:3 * i + 3]
            if all(abs(r - x[0]) + abs(gr - x[1]) + abs(b - x[2]) > 60 for x in couleurs):
                couleurs.append((r, gr, b))
    except Exception:  # noqa: BLE001
        return jsonify({"erreur": "Ce fichier n'est pas une image lisible (JPG, PNG ou WebP)."}), 400
    return jsonify({"couleurs": ["#%02x%02x%02x" % c for c in couleurs[:6]]})


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
    if isinstance(c.get("marque"), dict):
        cfg["marque"] = _marque_propre(c["marque"])
    g.esp.ecrit_config(cfg)
    if c.get("onboarding_termine"):
        ab.maj(g.u["id"], onboarding=1)
    if "veille_auto" in c:
        ab.maj(g.u["id"], veille_auto=1 if c["veille_auto"] else 0)
    if "synthese" in c:
        ab.maj(g.u["id"], synthese=1 if c["synthese"] else 0)
    return jsonify({"ok": True})


@app.post("/api/assistant/mon-compte")
@connecte
def assistant_compte():
    msg = reserve(g.u, "ia")
    if msg:
        return bloque(msg)
    if job_en_cours(g.u["id"]):
        return jsonify({"erreur": "Une tâche est déjà en cours."}), 409
    c = request.get_json(force=True)
    cfg = g.esp.lit_config()
    cfg["mon_compte"] = {"instagram": (c.get("instagram") or "").strip().lstrip("@"), "tiktok": (c.get("tiktok") or "").strip().lstrip("@")}
    g.esp.ecrit_config(cfg)
    jid = lance(g.u["id"], "Analyse de ton compte", moteur.analyse_mon_compte, g.esp, cfg,
                cfg["mon_compte"]["instagram"], cfg["mon_compte"]["tiktok"], demo=en_demo())
    return jsonify({"job": jid})


@app.post("/api/assistant/comptes-suggeres")
@connecte
def assistant_comptes():
    """Suggestions de comptes à copier, vérifiées par une vraie collecte (quelques centimes) : file de tâches + abonnement actif."""
    msg = reserve(g.u, "ia")
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    if job_en_cours(g.u["id"]):
        return jsonify({"erreur": "Une veille est en cours : réessaie quand elle sera terminée."}), 409
    import suggestions
    cfg = g.esp.lit_config()
    c = request.get_json(silent=True) or {}
    cfg["niche"].update({k: v for k, v in (c.get("niche") or {}).items() if v})
    return jsonify({"job": lance(g.u["id"], "Comptes suggérés", suggestions.suggere, cfg, os.getenv("APIFY_TOKEN"), demo=en_demo())})


@app.post("/api/assistant/hashtags")
@connecte
def assistant_hashtags():
    msg = reserve(g.u, "ia")
    if msg:
        return bloque(msg)
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
    if not reserve(g.u, "suivi_publications"):  # gratuit : le Reel est noté, mais sans relevé automatique (Apify)
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
    msg = reserve(g.u, "suivi_publications")
    if msg:
        return bloque(msg)
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
                              for k, v in p.items() if k not in ("essai", "gratuit")],
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
        ab.maj(g.u["id"], plan=plan, statut="actif", a_paye=1)
        ab.recompense_parrain(g.u["id"])
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


def _banque_dispo() -> bool:
    return banque.active() or en_demo()


def _options_studio_couv():
    return [{"id": k, "nom": v} for k, v in studio.STYLES_COUV.items()]


def _options_studio():
    return {"styles": [{"id": k, "nom": v[0], "aide": v[1]} for k, v in studio.STYLES.items()],
            "typos": [{"id": k, "nom": studio.NOMS_TYPOS[k], "police": v[5], "fichier": v[0], "style": studio.STYLE_DE_TYPO.get(k, "moderne"),
                       "maj": v[3]} for s_, _, ids in studio.STYLES_TYPO for k in ids for v in [studio.TYPOS[k]]],
            "styles_typo": [{"id": s_, "nom": n} for s_, n, _ in studio.STYLES_TYPO],
            "familles_modeles": [{"id": f, "nom": n, "pastille": c} for f, n, c in studio.SS.FAMILLES],
            "modeles": [{"id": k, "nom": m["nom"], "note": bool(m.get("note")), "couleur": m.get("couleur", "blanc"), "titre": "#%02x%02x%02x" % m["titre"], "texte": "#%02x%02x%02x" % m["texte"]}
                        for k, m in studio.SS.MODELES.items()],
            "voix_connue": studio.voix_connue(g.esp), "banque": _banque_dispo(),
            "marque": studio.couleurs_marque(g.esp.lit_config()), "couvertures": _options_studio_couv()}


@app.post("/api/studio")
@connecte
def studio_cree():
    c = request.get_json(force=True)
    msg = refus(g.u)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre création : réessaie dans un instant."}), 409
    if c.get("vierge"):  # carrousel écrit par l'utilisatrice elle-même : aucun appel à Claude (formule gratuite comprise)
        p = studio.cree_vierge(g.esp, g.esp.lit_config())
        return jsonify({"projet": p, "job": None})
    try:
        post = next(p for p in moteur.charge(g.esp, c["analyse_id"])["posts"] if p["cle"] == c["cle"])
    except (FileNotFoundError, StopIteration, KeyError):
        return jsonify({"erreur": "Reel introuvable."}), 404
    if not (post.get("adaptation") and not post["adaptation"].get("erreur")):
        return jsonify({"erreur": "Adapte d'abord ce Reel."}), 400
    # Sans IA (formule gratuite), seul un carrousel copié slide par slide d'un carrousel modèle se crée sans Claude
    copie_sans_ia = c.get("type", "carrousel") == "carrousel" and bool(studio.slides_du_modele(post["adaptation"]))
    msg = None if copie_sans_ia else reserve(g.u, "ia")
    if msg:
        return bloque(msg)
    cfg = g.esp.lit_config()
    p = studio.cree(g.esp, cfg, post, c.get("type", "carrousel"), c["analyse_id"], c.get("style") or "ma_voix")
    # Carrousel copié d'un carrousel modèle : les slides sont déjà adaptées une par une pendant la veille, rien à réécrire ;
    # on propose seulement des images de la banque pour les slides qui demandent une photo
    if p.get("copie_du_modele") and p["type"] == "carrousel":
        jid = lance(g.u["id"], "Choix des images", studio.remplit_banque, g.esp, p["id"], demo=en_demo(), file_=FILE_STUDIO)
    else:
        jid = lance(g.u["id"], "Écriture des slides", studio.ecrit_textes, g.esp, cfg, p["id"], demo=en_demo(), file_=FILE_STUDIO)
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
    slide_i = request.args.get("slide", type=int)
    video = False
    for f in request.files.getlist("fichiers"):
        try:
            p = studio.ajoute_fichier(g.esp, sid, f.filename, f, slide_i)
            video = video or Path(f.filename or "").suffix.lower() in studio.EXT_VIDEOS
        except ValueError as e:
            erreurs.append(str(e))
    p = p or studio.charge(g.esp, sid)
    p.pop("adaptation", None)
    job = None
    if video and p.get("video") and studio.video_a_optimiser(studio.dossier(g.esp, sid) / "sources" / p["video"]):
        job = lance(g.u["id"], "Préparation de ta vidéo", studio.optimise_video, g.esp, sid, file_=FILE_STUDIO)
    return jsonify({"projet": p, "erreurs": erreurs, "job": job}), (400 if erreurs and not request.files else 200)


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
    msg = reserve(g.u, "ia")
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    return jsonify({"job": lance(g.u["id"], "Écriture des slides", studio.ecrit_textes, g.esp, g.esp.lit_config(), sid,
                                 demo=en_demo(), file_=FILE_STUDIO)})


def _apres_studio(uid: int, sid: str):
    """Première création d'un projet : compte le quota et prévient par e-mail (le montage peut prendre quelques minutes)."""
    def fin(_):
        ab.compte_usage(uid, studio=1)
        u = ab.get(uid)
        try:
            p = studio.charge(espace_client(uid), sid)
        except Exception:  # noqa: BLE001
            return
        if u and p.get("statut") == "pret":
            emails.contenu_pret(u["email"], u.get("prenom") or "", p.get("type") or "", p.get("titre") or "",
                                f"{url_site()}/app?projet={quote(sid)}")
    return fin


@app.post("/api/studio/<sid>/generer")
@connecte
def studio_generer(sid):
    p = _projet(sid)
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre création : réessaie dans un instant."}), 409
    if p["type"] == "reel":
        msg = reserve(g.u, "montage_reel")
        if msg:
            return bloque(msg)
    deja = bool(p.get("genere_le"))  # régénérer après une retouche ne consomme pas de nouvelle création
    msg = None if deja else refus(g.u, studio=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    titre = "Création du carrousel" if p["type"] == "carrousel" else "Montage du Reel"
    jid = lance(uid, titre, studio.genere, g.esp, sid, demo=en_demo(), filigrane=droits(g.u)["options"]["filigrane"], file_=FILE_STUDIO,
                apres=None if deja else _apres_studio(uid, sid))
    return jsonify({"job": jid})


# ------------------------------------------------------------
#  Banque d'images (Pexels) : recherche gratuite, aucun quota consommé
# ------------------------------------------------------------
import banque  # noqa: E402


@app.get("/api/banque")
@connecte
def banque_recherche():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"resultats": [], "active": banque.active() or en_demo(), "source": banque.nom_source()})
    if not (banque.active() or en_demo()):
        return jsonify({"resultats": [], "active": False})
    try:
        res = banque.videos(q) if request.args.get("type") == "video" else banque.photos(q, n=18)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erreur": str(e)}), 502
    return jsonify({"resultats": banque.via_serveur(res), "active": True, "source": banque.nom_source()})


@app.get("/api/banque/vignette")
@connecte
def banque_vignette():
    try:
        f = banque.vignette(request.args.get("u", ""))
    except ValueError:
        abort(400)
    except Exception:  # noqa: BLE001
        abort(404)
    return send_from_directory(f.parent, f.name, max_age=86400)


@app.get("/banque-demo/<nom>")
@connecte
def banque_demo(nom):
    return send_from_directory(banque.chemin_demo(nom).parent, Path(nom).name, max_age=86400)


@app.post("/api/studio/<sid>/banque")
@connecte
def studio_banque(sid):
    _projet(sid)
    c = request.get_json(force=True)
    el = c.get("element") or {}
    if not str(el.get("grande", "")).startswith(("https://images.pexels.com/", "https://videos.pexels.com/", "https://player.vimeo.com/",
                                                   "https://www.pexels.com/", "https://pixabay.com/", "https://cdn.pixabay.com/",
                                                   "/banque-demo/")):
        return jsonify({"erreur": "Image non autorisée."}), 400
    try:
        p = studio.choisit_banque(g.esp, sid, c.get("slide"), el)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erreur": f"Téléchargement impossible : {str(e)[:120]}"}), 502
    p.pop("adaptation", None)
    return jsonify(p)


@app.get("/api/studio/<sid>/propositions/<int:i>")
@connecte
def studio_propositions(sid, i):
    _projet(sid)
    if not _banque_dispo():
        return jsonify({"requete": "", "resultats": []})
    try:
        r = studio.propositions(g.esp, sid, i)
        banque.via_serveur(r["resultats"])
        return jsonify(r)
    except Exception as e:  # noqa: BLE001
        return jsonify({"erreur": str(e)[:150], "resultats": []}), 502


@app.post("/api/studio/<sid>/banque/auto")
@connecte
def studio_banque_auto(sid):
    _projet(sid)
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre tâche : réessaie dans un instant."}), 409
    return jsonify({"job": lance(g.u["id"], "Choix des images", studio.remplit_banque, g.esp, sid, demo=en_demo(),
                                 toutes=bool((request.get_json(silent=True) or {}).get("toutes")), file_=FILE_STUDIO)})


@app.get("/api/studio/modeles/<mid>.jpg")
@connecte
def studio_vignette_modele(mid):
    from flask import Response
    if mid not in studio.SS.MODELES:
        abort(404)
    return Response(studio.vignette_modele(mid), mimetype="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/studio/<sid>/apercu/<int:i>")
@connecte
def studio_apercu(sid, i):
    _projet(sid)
    from flask import Response
    try:
        return Response(studio.apercu(g.esp, sid, i, filigrane=droits(g.u)["options"]["filigrane"]), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        abort(500)


@app.get("/api/studio/<sid>/couverture")
@connecte
def studio_couverture(sid):
    """Aperçu de la couverture du Reel (rendu local, aucune API consommée)."""
    from flask import Response
    _projet(sid)
    a = request.args
    try:
        t = float(a["t"]) if a.get("t") else None
    except ValueError:
        t = None
    data = studio.apercu_couverture(g.esp, sid, a.get("style"), t, a.get("image"), a.get("texte") or None, bool(a.get("grille")),
                                    360 if a.get("petit") else 540)
    return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


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
#  Boutique en lien dans la bio : page publique /@pseudo, produits, kit média
# ------------------------------------------------------------
import re as _re  # noqa: E402

import boutique as bq  # noqa: E402
import boutique_ventes as bv  # noqa: E402


def _droits_uid(uid: int) -> dict | None:
    u = ab.get(uid)
    return droits(u) if u else None


# La boutique dépend de la formule de sa propriétaire : mention « Créé avec » et commission sur les ventes
bq.AVEC_MARQUE = lambda uid: bool(((_droits_uid(uid) or {}).get("options") or {}).get("mention_boutique", True))
bq.TAUX_COMMISSION = lambda uid: (_droits_uid(uid) or {}).get("commission_boutique")

bq.init()
NOM_IMAGE = _re.compile(r"^[0-9a-f]{12}\.(jpg|png)$")


def _vitrine(pseudo: str):
    """(uid, page) d'une boutique publiée — ou visible par sa propriétaire connectée."""
    pseudo = (pseudo or "").lower()
    uid = bq.uid_de(pseudo)
    page = bq.lit_page(uid) if uid else None
    if not page:
        abort(404)
    if not page.get("publie") and session.get("uid") != uid:
        abort(404)
    page["_parrain"] = ab.code_parrain(uid)
    return uid, page


def _profil_compte(uid: int) -> dict | None:
    f = espace_client(uid).profil_compte
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _vente_possible(page: dict) -> bool:
    return bool(en_demo() or ((page.get("stripe") or {}).get("pret") and bq.stripe_actif()))


def _html(contenu: str, code: int = 200):
    from flask import Response
    return Response(contenu, code, mimetype="text/html")


def _src(pseudo: str) -> str:
    """Source de la visite : paramètre ?src= (lien suivi, QR code, e-mail…) ou cookie posé lors de la première visite."""
    return bv.source_propre(request.args.get("src") or request.form.get("src") or request.cookies.get("vvs_" + pseudo.lower()))


def _avec_cookie(rep, pseudo: str):
    s = bv.source_propre(request.args.get("src"))
    if s:
        rep.set_cookie("vvs_" + pseudo.lower(), s, max_age=30 * 86400, samesite="Lax", secure=request.is_secure)
    return rep


@app.get("/@<pseudo>")
def boutique_publique(pseudo):
    uid, page = _vitrine(pseudo)
    if session.get("uid") != uid:
        bq.compte(uid, "vue")
        if request.args.get("src"):
            bv.compte_source(uid, _src(pseudo), "vues")
    page["_avis"] = bv.resume_avis(uid)
    return _avec_cookie(_html(bq.rendu_page(page, pseudo.lower(), url=f"{url_site()}/@{pseudo.lower()}")), pseudo)


@app.get("/@<pseudo>/i/<nom>")
def boutique_image(pseudo, nom):
    uid = bq.uid_de(pseudo.lower())
    if not uid or not NOM_IMAGE.match(nom):
        abort(404)
    return send_from_directory(bq.dossier(uid) / "images", nom, max_age=30 * 86400)


@app.get("/@<pseudo>/l/<bid>")
def boutique_clic(pseudo, bid):
    uid, page = _vitrine(pseudo)
    b = next((x for x in page["blocs"] if x.get("id") == bid and x.get("type") == "lien"), None)
    u = bq.url_sure((b or {}).get("url"))
    if not u:
        abort(404)
    if session.get("uid") != uid:
        bq.compte(uid, "clics", bid)
    return redirect(u, 302)


@app.get("/@<pseudo>/m/<mot>")
def boutique_mot_cle(pseudo, mot):
    """Lien court d'un mot-clé (« commente GUIDE ») : mène au produit et compte la source."""
    uid, page = _vitrine(pseudo)
    p = bv.produit_par_mot(page, mot)
    if not p:
        return redirect(f"/@{pseudo.lower()}", 302)
    return redirect(f"/@{pseudo.lower()}/p/{p['id']}?src=mot-{bv.source_propre(mot.lower()) or 'x'}", 302)


def _produit(page, pid):
    p = next((x for x in page["produits"] if x.get("id") == pid and x.get("visible", True)), None)
    if not p:
        abort(404)
    return p


@app.get("/@<pseudo>/p/<pid>")
def boutique_produit(pseudo, pid):
    uid, page = _vitrine(pseudo)
    p = _produit(page, pid)
    if session.get("uid") != uid:
        bq.compte(uid, "produits", pid)
        if request.args.get("src"):
            bv.compte_source(uid, _src(pseudo), "vues")
    msg = "Paiement annulé : tu n'as pas été débitée." if request.args.get("annule") else ""
    if request.args.get("pris"):
        msg = "Ce créneau vient d'être réservé par quelqu'un d'autre : choisis-en un autre."
    rep = _html(bv.rendu_produit(page, pseudo.lower(), p, uid, msg, _vente_possible(page), request.args.get("code", ""), _src(pseudo)))
    return _avec_cookie(rep, pseudo)


@app.get("/@<pseudo>/p/<pid>/ouvrir")
def boutique_produit_lien(pseudo, pid):
    uid, page = _vitrine(pseudo)
    p = _produit(page, pid)
    u = bq.url_sure(p.get("lien"))
    if not u or p.get("prix"):
        abort(404)
    bq.compte(uid, "clics", "p-" + pid)
    return redirect(u, 302)


def _email_valide(e: str) -> bool:
    return bool(_re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[a-zA-Z]{2,}", e or ""))


def _livre(uid, page, pseudo, p, email, prenom="", montant=0, devise="eur", session_id="", src="", code="", rdv=None, nouvelle_cliente=True):
    """Enregistre la vente (ou le cadeau), envoie l'accès par e-mail et prévient la vendeuse. Renvoie la vente."""
    v = bq.enregistre_vente(uid, p, email, montant, devise, session_id or f"gratuit-{p['id']}-{email}-{(rdv or {}).get('id', '')}",
                            src=src, code=code, rdv=(rdv or {}).get("id"), prenom=prenom)
    if not v["nouvelle"]:
        return v
    lien = f"{url_site()}/@{pseudo}/merci?j={v['jeton']}"
    if email and "demo" not in email:
        if p.get("type") == "rdv" and rdv:
            bq.mail_rdv(page, p, email, lien, bv.date_fr(bv._date(rdv["debut"])))
        else:
            bq.mail_livraison(page, p, email, lien, not montant)
        if nouvelle_cliente:
            if bq.ajoute_inscrit(uid, email, prenom, ("achat : " if montant else "cadeau : ") + (p.get("titre") or "")):
                bv.compte_source(uid, src, "inscrits")
    if montant:
        bv.compte_source(uid, src, "ventes", montant)
        bv.utilise_code(uid, code)
    proprio = ab.get(uid)
    if proprio and (montant or p.get("type") == "rdv"):
        quand = f" pour le {bv.date_fr(bv._date(rdv['debut']))}" if rdv else ""
        bq.mail_vente(proprio["email"], page, p, montant, devise, (email or "une cliente") + quand)
        nt.notifie(uid, "Nouvelle réservation 📅" if rdv and not montant else f"Nouvelle vente : {bq.prix_txt(montant, devise)} 🎉",
                   f"{p.get('titre')}{quand}", "/app")
    return v


@app.post("/@<pseudo>/p/<pid>/obtenir")
def boutique_obtenir(pseudo, pid):
    uid, page = _vitrine(pseudo)
    p = _produit(page, pid)
    pseudo = pseudo.lower()
    email = (request.form.get("email") or "").strip().lower()
    prenom = (request.form.get("prenom") or "").strip()[:60]
    code = (request.form.get("code") or "").strip().upper()
    prix = bv.prix_effectif(p)["prix"]
    if prix and code:
        prix, err = bv.code_valide(page, p, code, prix)
        if err:
            return jsonify({"erreur": err}), 400
    if not bv.livrable(page, p):
        return jsonify({"erreur": "Ce produit n'est pas encore disponible."}), 409
    if prix or not _email_valide(email):
        return jsonify({"erreur": "Indique une adresse e-mail valide."}), 400
    rdv = None
    if p.get("type") == "rdv":
        rdv = bv.reserve_rdv(uid, p, request.form.get("creneau", ""), email, prenom, confirme=True)
        if not rdv:
            return jsonify({"erreur": "Ce créneau n'est plus disponible : recharge la page et choisis-en un autre."}), 409
    v = _livre(uid, page, pseudo, p, email, prenom, src=_src(pseudo), code=code, rdv=rdv)
    return jsonify({"url": f"{url_site()}/@{pseudo}/merci?j={v['jeton']}"})


@app.post("/@<pseudo>/inscription")
def boutique_inscription(pseudo):
    uid, page = _vitrine(pseudo)
    email = (request.form.get("email") or "").strip().lower()
    if not _email_valide(email):
        return jsonify({"erreur": "Indique une adresse e-mail valide."}), 400
    b = next((x for x in page["blocs"] if x.get("id") == request.form.get("bloc") and x.get("type") == "capture"), {})
    p = next((x for x in page["produits"] if x.get("id") == b.get("produit") and not x.get("prix")), None)
    src = _src(pseudo)
    if p and bv.livrable(page, p):
        v = _livre(uid, page, pseudo.lower(), p, email, src=src)
        return jsonify({"url": f"{url_site()}/@{pseudo.lower()}/merci?j={v['jeton']}"})
    if bq.ajoute_inscrit(uid, email, (request.form.get("prenom") or "").strip(), b.get("titre") or "formulaire"):
        bv.compte_source(uid, src, "inscrits")
    return jsonify({"message": b.get("merci") or "C'est noté, merci ! À très vite dans ta boîte mail."})


@app.post("/@<pseudo>/p/<pid>/acheter")
def boutique_acheter(pseudo, pid):
    uid, page = _vitrine(pseudo)
    p = _produit(page, pid)
    pseudo = pseudo.lower()
    f = request.form
    if not bv.livrable(page, p):
        return _html(bv.rendu_produit(page, pseudo, p, uid, "Ce produit n'est pas encore disponible."), 409)
    prix = bv.prix_effectif(p)["prix"]
    code = (f.get("code") or "").strip().upper()
    # Offre complémentaire après un achat : prix spécial, valable 2 h avec le jeton de la première commande
    jeton_up = f.get("upsell", "")
    if jeton_up:
        v0 = bq.vente_par_jeton(uid, jeton_up)
        source = next((x for x in page["produits"] if v0 and x["id"] == v0["produit"]), None)
        up = (source or {}).get("upsell") or {}
        frais = v0 and (datetime.now() - datetime.fromisoformat(v0["date"][:16])).total_seconds() < 7200
        if not (v0 and up.get("produit") == p["id"] and frais):
            return redirect(f"/@{pseudo}/p/{pid}")
        prix = int(up.get("prix") or 0)
    elif code and prix:
        prix, err = bv.code_valide(page, p, code, prix)
        if err:
            return _html(bv.rendu_produit(page, pseudo, p, uid, err, _vente_possible(page), "", _src(pseudo)), 400)
    email = (f.get("email") or "").strip().lower()
    prenom = (f.get("prenom") or "").strip()[:60]
    est_rdv = p.get("type") == "rdv"
    if est_rdv and not _email_valide(email):
        return _html(bv.rendu_produit(page, pseudo, p, uid, "Indique ton e-mail pour recevoir la confirmation.", _vente_possible(page)), 400)
    if not prix:  # gratuit grâce au code ou à l'offre : livraison directe, sans paiement
        if not _email_valide(email):
            email = (bq.vente_par_jeton(uid, jeton_up) or {}).get("email", "") if jeton_up else ""
        rdv = bv.reserve_rdv(uid, p, f.get("creneau", ""), email, prenom, confirme=True) if est_rdv else None
        if est_rdv and not rdv:
            return redirect(f"/@{pseudo}/p/{pid}?pris=1", 303)
        v = _livre(uid, page, pseudo, p, email, prenom, src=_src(pseudo), code=code, rdv=rdv)
        return redirect(f"/@{pseudo}/merci?j={v['jeton']}", 303)
    rdv = None
    if est_rdv:
        rdv = bv.reserve_rdv(uid, p, f.get("creneau", ""), email, prenom, confirme=False)
        if not rdv:
            return redirect(f"/@{pseudo}/p/{pid}?pris=1", 303)
    if not email and jeton_up:
        email = (bq.vente_par_jeton(uid, jeton_up) or {}).get("email", "")
    meta = {"src": _src(pseudo), "code": code, "rdv": (rdv or {}).get("id"), "prenom": prenom}
    compte = (page.get("stripe") or {}).get("compte")
    if compte and (page.get("stripe") or {}).get("pret") and bq.stripe_actif():
        try:
            return redirect(bq.session_achat(compte, p, url_site(), pseudo, prix, meta, email if _email_valide(email) else "", uid=uid), 303)
        except ValueError as e:
            return _html(bv.rendu_produit(page, pseudo, p, uid, f"Le paiement est momentanément indisponible ({e})."), 502)
    if en_demo():  # démo : achat simulé, sans paiement
        if rdv:
            bv.confirme_rdv(uid, rdv["id"])
        v = _livre(uid, page, pseudo, p, email or "acheteuse@demo.fr", prenom, prix, p.get("devise", "eur"), "demo-" + uuid.uuid4().hex,
                   src=meta["src"], code=code, rdv=rdv)
        return redirect(f"/@{pseudo}/merci?j={v['jeton']}&demo=1", 303)
    return _html(bv.rendu_produit(page, pseudo, p, uid, "Ce produit n'est pas encore disponible à l'achat."), 409)


@app.get("/@<pseudo>/merci")
def boutique_merci(pseudo):
    uid, page = _vitrine(pseudo)
    pseudo = pseudo.lower()
    v = None
    if request.args.get("s"):
        compte = (page.get("stripe") or {}).get("compte")
        try:
            r = bq.verifie_session(compte, request.args["s"]) if compte else None
        except ValueError:
            r = None
        p = next((x for x in page["produits"] if x.get("id") == (r or {}).get("produit")), None)
        if not r or not p:
            return _html(bq.rendu_message(page, pseudo, "Paiement en attente", "Ton paiement n'est pas encore confirmé. "
                                          "Si tu as été débitée, tu recevras ton accès par e-mail dans quelques minutes."), 202)
        meta = r.get("meta") or {}
        rdv = bv.confirme_rdv(uid, meta["rdv"]) if meta.get("rdv") else None
        v = _livre(uid, page, pseudo, p, r["email"], meta.get("prenom", ""), r["montant"], r["devise"], request.args["s"],
                   src=bv.source_propre(meta.get("src")), code=meta.get("code", ""), rdv=rdv)
    elif request.args.get("j"):
        v = bq.vente_par_jeton(uid, request.args["j"])
    if not v:
        return _html(bq.rendu_message(page, pseudo, "Lien expiré", "Ce lien n'est plus valable. Écris-nous et on te renvoie ton accès."), 404)
    return _html(bv.rendu_merci(page, pseudo, uid, v, bool(request.args.get("demo"))))


@app.get("/@<pseudo>/telecharger/<jeton>")
def boutique_telecharger(pseudo, jeton):
    pseudo = pseudo.lower()
    uid = bq.uid_de(pseudo)
    page = bq.lit_page(uid) if uid else None
    if not page:
        abort(404)
    v = bq.vente_par_jeton(uid, jeton, consomme=True)
    if not v:
        return _html(bq.rendu_message(page, pseudo, "Lien expiré", "Ce lien de téléchargement n'est plus valable (30 jours ou 20 téléchargements). "
                                      "Réponds à l'e-mail reçu et on te renvoie ton accès."), 404)
    p = next((x for x in page["produits"] if x.get("id") == v["produit"]), None)
    if p and p.get("type") == "pack":  # un produit précis du pack
        cible = request.args.get("p")
        p = next((x for x in page["produits"] if x["id"] == cible and cible in (p.get("inclus") or [])), None)
    if not p:
        return _html(bq.rendu_message(page, pseudo, "Produit introuvable", "Ce produit n'est plus proposé. Écris-nous et on t'aide."), 404)
    if p.get("fichier") and (bq.dossier(uid) / "fichiers" / p["fichier"]).exists():
        return send_from_directory(bq.dossier(uid) / "fichiers", p["fichier"], as_attachment=True,
                                   download_name=p.get("fichier_nom") or p["fichier"], max_age=0)
    u = bq.url_sure(p.get("lien"))
    if u:
        return redirect(u, 302)
    # rien d'attaché pour l'instant : le lien reste valable, il marchera dès que le fichier sera ajouté
    return _html(bq.rendu_message(page, pseudo, "Presque prêt", f"« {p.get('titre')} » est en cours de préparation. Ton lien reste valable : "
                                  "réessaie un peu plus tard, ou garde l'e-mail reçu."), 404)


@app.get("/@<pseudo>/rdv/<rid>.ics")
def boutique_rdv_ics(pseudo, rid):
    uid, page = _vitrine(pseudo)
    r = next((x for x in bv.lit_rdv(uid) if x["id"] == rid and x.get("jeton") == request.args.get("j")), None)
    p = next((x for x in page["produits"] if r and x["id"] == r["produit"]), None)
    if not r or not p:
        abort(404)
    from flask import Response
    return Response(bv.ics(page, r, p), mimetype="text/calendar", headers={"Content-Disposition": "attachment; filename=rendez-vous.ics"})


@app.route("/@<pseudo>/avis/<jeton>", methods=["GET", "POST"])
def boutique_avis(pseudo, jeton):
    uid, page = _vitrine(pseudo)
    v = bq.vente_par_jeton(uid, jeton)
    p = next((x for x in page["produits"] if v and x["id"] == v["produit"]), None)
    if not v or not p:
        return _html(bq.rendu_message(page, pseudo.lower(), "Lien expiré", "Ce lien pour donner ton avis n'est plus valable."), 404)
    if request.method == "POST":
        try:
            note = int(request.form.get("note", 5))
        except ValueError:
            note = 5
        bv.ajoute_avis(uid, v, note, request.form.get("prenom", ""), request.form.get("texte", ""))
        return _html(bv.rendu_form_avis(page, pseudo.lower(), p, envoye=True))
    if any(a.get("vente") == v["id"] for a in bv.lit_avis(uid)):
        return _html(bv.rendu_form_avis(page, pseudo.lower(), p, envoye=True))
    return _html(bv.rendu_form_avis(page, pseudo.lower(), p))


@app.get("/@<pseudo>/stop/<jeton>")
def boutique_stop(pseudo, jeton):
    uid, page = _vitrine(pseudo)
    bv.desinscrit(uid, jeton)
    return _html(bq.rendu_message(page, pseudo.lower(), "C'est fait", "Tu ne recevras plus d'e-mails de cette page."))


@app.get("/@<pseudo>/kit")
def boutique_kit(pseudo):
    uid, page = _vitrine(pseudo)
    if not (page.get("kit") or {}).get("actif", True):
        abort(404)
    return _html(bq.rendu_kit(page, pseudo.lower(), _profil_compte(uid)))


@app.get("/@<pseudo>/kit/m/<nom>")
def boutique_kit_media(pseudo, nom):
    uid = bq.uid_de(pseudo.lower())
    prof = _profil_compte(uid) if uid else None
    if not prof or nom not in {t.get("miniature") for t in prof.get("top") or []}:
        abort(404)
    f = espace_client(uid).media / nom
    if not f.exists():
        abort(404)
    allege(f)
    return send_from_directory(f.parent, f.name, max_age=7 * 86400)


# ---- API d'édition (application)
def _options_boutique() -> dict:
    return {"themes": [{"id": k, "nom": t["nom"], "ambiance": t["ambiance"], "design": t["design"]} for k, t in bq.THEMES.items()],
            "ambiances": bq.AMBIANCES, "polices": [{"nom": k, "categorie": v[2]} for k, v in bq.POLICES.items()],
            "polices_texte": bq.POLICES_TEXTE, "entetes": bq.ENTETES, "formes": bq.FORMES, "fonds": bq.FONDS, "motifs": bq.MOTIFS,
            "boutons": bq.BOUTONS, "animations": bq.ANIMATIONS, "vues_produits": bq.VUES_PRODUITS,
            "formes_bouton": bq.FORMES_BOUTON, "formes_decoupees": sorted(bq.FORMES_DECOUPEES), "survols": bq.SURVOLS,
            "tailles_bouton": bq.TAILLES_BOUTON, "alignements": bq.ALIGNEMENTS, "decors": bq.DECORS, "formes_image": bq.FORMES_IMAGE,
            "styles_prix": bq.STYLES_PRIX, "cadres_carte": bq.CADRES_CARTE,
            "reseaux": {k: v[0] for k, v in bq.RESEAUX.items()}, "defaut": bq.DESIGN_DEFAUT}


def _etat_boutique(uid: int, page: dict | None, rafraichir_stripe: bool = False) -> dict:
    pseudo = bq.pseudo_de(uid)
    st = (page or {}).get("stripe") or {}
    if page and st.get("compte") and bq.stripe_actif() and (rafraichir_stripe or not st.get("pret")):
        try:
            e = bq.etat_stripe(st["compte"])
            if e["pret"] != st.get("pret"):
                with bq.verrou(uid):
                    page2 = bq.lit_page(uid)
                    page2["stripe"] = {**st, **e}
                    bq.ecrit_page(uid, page2)
                    page = page2
            st = {**st, **e}
        except Exception:  # noqa: BLE001
            pass
    if page:
        page = {**page, "stripe": {"pret": bool(st.get("pret")), "relie": bool(st.get("compte"))}}
        page.setdefault("sequence", bv.sequence_defaut(page))
        page.setdefault("promos", [])
    prof = _profil_compte(uid)
    suggestion = None
    if not page:
        ini = bq.page_initiale(uid, prof, g.u.get("prenom") or "")
        base = bq.nettoie_pseudo((prof or {}).get("instagram") or (prof or {}).get("tiktok") or ini["nom"])
        libre = base if base and not bq.pseudo_libre(base, uid) else ""
        if base and not libre:
            libre = next((base[:26] + f"-{i}" for i in range(2, 50) if not bq.pseudo_libre(base[:26] + f"-{i}", uid)), "")
        suggestion = {"nom": ini["nom"], "bio": ini["bio"], "reseaux": ini["reseaux"], "pseudo": libre}
    return {"page": page, "pseudo": pseudo, "suggestion": suggestion, "url": f"{url_site()}/@{pseudo}" if pseudo else None,
            "paiement": {"plateforme": bq.stripe_actif(), "demo": en_demo(), "commission": bq.commission(g.u["id"])}, "emails": emails.actif(),
            "kit_chiffres": bq.chiffres_kit(prof) if prof else None, "options": _options_boutique()}


@app.get("/api/boutique")
@connecte
def boutique_etat():
    return jsonify(_etat_boutique(g.u["id"], bq.lit_page(g.u["id"]), bool(request.args.get("stripe"))))


@app.get("/api/boutique/pseudo")
@connecte
def boutique_pseudo_libre():
    p = bq.nettoie_pseudo(request.args.get("p", ""))
    return jsonify({"pseudo": p, "erreur": bq.pseudo_libre(p, g.u["id"])})


@app.post("/api/boutique")
@connecte
def boutique_cree():
    c = request.get_json(force=True)
    uid = g.u["id"]
    pseudo = bq.nettoie_pseudo(c.get("pseudo", ""))
    err = bq.reserve_pseudo(uid, pseudo)
    if err:
        return jsonify({"erreur": err}), 400
    with bq.verrou(uid):
        page = bq.lit_page(uid) or bq.page_initiale(uid, _profil_compte(uid), g.u.get("prenom") or "")
        for k in ("nom", "bio"):
            if isinstance(c.get(k), str):
                page[k] = c[k].strip()[:280 if k == "bio" else 60]
        if isinstance(c.get("photo"), str) and NOM_IMAGE.match(c["photo"]):
            page["photo"] = c["photo"]
        if c.get("theme") in bq.THEMES:
            page["design"] = bq.applique_theme(page["design"], c["theme"])
        page.setdefault("sequence", bv.sequence_defaut(page))
        bq.ecrit_page(uid, page)
    return jsonify(_etat_boutique(uid, page))


@app.put("/api/boutique/pseudo")
@connecte
def boutique_change_pseudo():
    pseudo = bq.nettoie_pseudo(request.get_json(force=True).get("pseudo", ""))
    err = bq.reserve_pseudo(g.u["id"], pseudo)
    return (jsonify({"erreur": err}), 400) if err else jsonify({"pseudo": pseudo, "url": f"{url_site()}/@{pseudo}"})


def _bloc_propre(b: dict) -> dict | None:
    t = b.get("type")
    if t not in ("lien", "titre", "texte", "video", "produit", "produits", "capture", "kit"):
        return None
    r = {"id": str(b.get("id") or bq.nouvel_id())[:12], "type": t, "visible": b.get("visible", True) is not False}
    for k, lim in (("titre", 120), ("url", 800), ("texte", 1200), ("emoji", 8), ("bouton", 60), ("produit", 12), ("merci", 200)):
        if isinstance(b.get(k), str):
            r[k] = b[k].strip()[:lim]
    if t == "lien":
        r["en_avant"] = bool(b.get("en_avant"))
    if isinstance(b.get("image"), str) and NOM_IMAGE.match(b["image"]):
        r["image"] = b["image"]
    if isinstance(b.get("ids"), list):
        r["ids"] = [str(i)[:12] for i in b["ids"]][:50]
    return r


def _produit_propre(p: dict, ancien: dict | None) -> dict:
    r = {"id": (ancien or {}).get("id") or str(p.get("id") or bq.nouvel_id())[:12], "visible": p.get("visible", True) is not False}
    for k, lim in (("titre", 120), ("sous_titre", 160), ("description", 4000), ("bouton", 50), ("lien", 800)):
        r[k] = (p.get(k) or "").strip()[:lim] if isinstance(p.get(k), str) else ""
    for k in ("prix", "prix_barre"):
        try:
            r[k] = max(0, min(10_000_00, int(p.get(k) or 0)))
        except (TypeError, ValueError):
            r[k] = 0
    if 0 < r["prix"] < 50:
        r["prix"] = 50  # minimum Stripe : 0,50 €
    r["devise"] = p.get("devise") if p.get("devise") in ("eur", "usd", "chf", "cad", "gbp") else "eur"
    r["image"] = p["image"] if isinstance(p.get("image"), str) and NOM_IMAGE.match(p["image"]) else ""
    r["type"] = p.get("type") if p.get("type") in ("telechargement", "rdv", "pack") else "telechargement"
    r["mot_cle"] = _re.sub(r"[^A-Z0-9]", "", str(p.get("mot_cle") or "").upper())[:20]
    r["inclus"] = [str(i)[:12] for i in (p.get("inclus") or []) if isinstance(i, str)][:20] if r["type"] == "pack" else []
    try:
        r["promo_prix"] = max(0, int(p.get("promo_prix") or 0))
    except (TypeError, ValueError):
        r["promo_prix"] = 0
    if 0 < r["promo_prix"] < 50:
        r["promo_prix"] = 50
    r["promo_fin"] = str(p.get("promo_fin") or "")[:25] if r["promo_prix"] else ""
    u = p.get("upsell") if isinstance(p.get("upsell"), dict) else {}
    try:
        r["upsell"] = {"produit": str(u.get("produit") or "")[:12], "prix": max(0, int(u.get("prix") or 0))} if u.get("produit") else {}
    except (TypeError, ValueError):
        r["upsell"] = {}
    if r["type"] == "rdv":
        c = p.get("rdv") if isinstance(p.get("rdv"), dict) else {}
        def entier(k, mini, maxi, defaut):
            try:
                return max(mini, min(maxi, int(c.get(k, defaut))))
            except (TypeError, ValueError):
                return defaut
        r["rdv"] = {"duree": entier("duree", 10, 240, 30), "delai_h": entier("delai_h", 0, 240, 12), "horizon_j": entier("horizon_j", 1, 90, 21),
                    "jours": sorted({int(j) for j in (c.get("jours") or []) if str(j).isdigit() and 0 <= int(j) <= 6}) or [0, 1, 2, 3, 4],
                    "plages": str(c.get("plages") or "09:00-12:00, 14:00-18:00")[:120], "lieu": str(c.get("lieu") or "")[:300]}
    # le fichier ne vient jamais du navigateur : il est attaché par l'envoi dédié
    r["fichier"], r["fichier_nom"] = (ancien or {}).get("fichier", ""), (ancien or {}).get("fichier_nom", "")
    if p.get("retirer_fichier"):
        r["fichier"] = r["fichier_nom"] = ""
    return r


@app.put("/api/boutique")
@connecte
def boutique_maj():
    c = request.get_json(force=True)
    uid = g.u["id"]
    with bq.verrou(uid):
        page = bq.lit_page(uid)
        if not page:
            return jsonify({"erreur": "Crée d'abord ta boutique."}), 404
        for k, lim in (("nom", 60), ("bio", 280)):
            if isinstance(c.get(k), str):
                page[k] = c[k].strip()[:lim]
        for k in ("photo", "couverture"):
            if k in c and (c[k] == "" or (isinstance(c[k], str) and NOM_IMAGE.match(c[k]))):
                page[k] = c[k]
        if isinstance(c.get("reseaux"), dict):
            page["reseaux"] = {k: str(v).strip()[:200] for k, v in c["reseaux"].items() if k in bq.RESEAUX and str(v or "").strip()}
        if isinstance(c.get("blocs"), list):
            page["blocs"] = [b for b in (_bloc_propre(x) for x in c["blocs"][:80] if isinstance(x, dict)) if b]
        if isinstance(c.get("produits"), list):
            anciens = {p["id"]: p for p in page["produits"]}
            page["produits"] = [_produit_propre(x, anciens.get(x.get("id"))) for x in c["produits"][:60] if isinstance(x, dict)]
        if isinstance(c.get("design"), dict):
            page["design"] = bq.design_propre({**page["design"], **c["design"]})
        if c.get("theme") in bq.THEMES:
            page["design"] = bq.applique_theme(page["design"], c["theme"])
        if isinstance(c.get("kit"), dict):
            k = c["kit"]
            page["kit"] = {"actif": k.get("actif", True) is not False, "a_propos": str(k.get("a_propos") or "")[:1500],
                           "marques": str(k.get("marques") or "")[:600], "contact": str(k.get("contact") or "")[:120],
                           "tarifs": [{"libelle": str(t.get("libelle") or "")[:80], "prix": str(t.get("prix") or "")[:30]}
                                      for t in (k.get("tarifs") or [])[:12] if isinstance(t, dict)],
                           "chiffres_perso": [{"libelle": str(t.get("libelle") or "")[:40], "valeur": str(t.get("valeur") or "")[:20]}
                                              for t in (k.get("chiffres_perso") or [])[:6] if isinstance(t, dict)]}
        if isinstance(c.get("promos"), list):
            anciens = {x.get("code"): x for x in page.get("promos") or []}
            promos = []
            for x in c["promos"][:30]:
                code = _re.sub(r"[^A-Z0-9_-]", "", str(x.get("code") or "").upper())[:24]
                if not code:
                    continue
                try:
                    valeur = max(0, int(x.get("valeur") or 0))
                    maxi = max(0, int(x.get("max") or 0))
                except (TypeError, ValueError):
                    continue
                typ = "montant" if x.get("type") == "montant" else "pourcent"
                promos.append({"code": code, "type": typ, "valeur": min(valeur, 100) if typ == "pourcent" else valeur, "max": maxi,
                               "fin": str(x.get("fin") or "")[:25], "produits": [str(i)[:12] for i in x.get("produits") or []][:60],
                               "utilisations": (anciens.get(code) or {}).get("utilisations", 0)})
            page["promos"] = promos
        if isinstance(c.get("sequence"), dict):
            q = c["sequence"]
            actif = bool(q.get("actif"))
            ancien = page.get("sequence") or {}
            page["sequence"] = {
                "actif": actif, "depuis": ancien.get("depuis") if ancien.get("actif") and actif else (datetime.now().astimezone().isoformat(timespec="minutes") if actif else ""),
                "emails": [{"delai_jours": max(0, min(90, int(e.get("delai_jours") or 0))) if str(e.get("delai_jours") or 0).isdigit() else 0,
                            "sujet": str(e.get("sujet") or "")[:150], "texte": str(e.get("texte") or "")[:5000], "produit": str(e.get("produit") or "")[:12]}
                           for e in (q.get("emails") or [])[:10] if isinstance(e, dict)]}
        if isinstance(c.get("sources_noms"), dict):
            page["sources_noms"] = {bv.source_propre(k): str(v)[:80] for k, v in list(c["sources_noms"].items())[:200] if bv.source_propre(k)}
        if "exemple" in c:
            page["exemple"] = bool(c["exemple"])
        if "publie" in c:
            page["publie"] = bool(c["publie"])
        bq.ecrit_page(uid, page)
    if c.get("nettoyer"):
        bq.nettoie_images(uid, page)
    return jsonify({"ok": True, "design": page["design"], "produits": page["produits"], "blocs": page["blocs"], "promos": page.get("promos") or [],
                    "sequence": page.get("sequence")})


@app.post("/api/boutique/apercu")
@connecte
def boutique_apercu():
    """Aperçu en direct : la page telle qu'elle est dans l'éditeur, sans l'enregistrer."""
    uid = g.u["id"]
    base = bq.lit_page(uid)
    if not base:
        abort(404)
    c = request.get_json(force=True)
    page = dict(base)
    vue = c.get("vue", "page")
    if isinstance(c.get("design"), dict):
        page["design"] = bq.design_propre({**base["design"], **c["design"]})
    if c.get("theme") in bq.THEMES:
        page["design"] = bq.applique_theme(page["design"], c["theme"])
    for k in ("nom", "bio", "photo", "couverture"):
        if isinstance(c.get(k), str):
            page[k] = c[k]
    if isinstance(c.get("reseaux"), dict):
        page["reseaux"] = c["reseaux"]
    if isinstance(c.get("blocs"), list):
        page["blocs"] = [b for b in (_bloc_propre(x) for x in c["blocs"] if isinstance(x, dict)) if b]
    if isinstance(c.get("produits"), list):
        anciens = {p["id"]: p for p in base["produits"]}
        page["produits"] = [_produit_propre(x, anciens.get(x.get("id"))) for x in c["produits"] if isinstance(x, dict)]
    if isinstance(c.get("kit"), dict):
        page["kit"] = c["kit"]
    pseudo = bq.pseudo_de(uid)
    if vue == "kit":
        h = bq.rendu_kit(page, pseudo, _profil_compte(uid))
    elif vue.startswith("p:"):
        p = next((x for x in page["produits"] if x["id"] == vue[2:]), None)
        h = bq.rendu_produit(page, pseudo, p, "", _vente_possible(base)) if p else bq.rendu_page(page, pseudo, True)
    else:
        h = bq.rendu_page(page, pseudo, True)
    if vue != "page":
        h = h.replace(bq.SCRIPT_PUBLIC, bq.SCRIPT_APERCU)
    return _html(h)


@app.post("/api/boutique/image")
@connecte
def boutique_image_envoi():
    f = request.files.get("fichier")
    if not f:
        return jsonify({"erreur": "Aucune image reçue."}), 400
    role = request.form.get("role", "")
    try:
        nom = bq.enregistre_image(g.u["id"], f.stream, 700 if role == "photo" else 1600)
    except Exception:  # noqa: BLE001
        return jsonify({"erreur": "Ce fichier n'est pas une image lisible (JPG, PNG ou WebP)."}), 400
    r = {"nom": nom}
    if role == "photo":
        try:
            r["palettes"] = bq.palettes_photo(bq.dossier(g.u["id"]) / "images" / nom)
        except Exception:  # noqa: BLE001
            pass
    return jsonify(r)


@app.get("/api/boutique/palettes")
@connecte
def boutique_palettes():
    page = bq.lit_page(g.u["id"])
    if not page or not page.get("photo"):
        return jsonify({"palettes": []})
    return jsonify({"palettes": bq.palettes_photo(bq.dossier(g.u["id"]) / "images" / page["photo"])})


EXT_PRODUITS = {".pdf", ".zip", ".epub", ".mp3", ".mp4", ".mov", ".m4a", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx", ".key", ".numbers", ".pages", ".txt", ".csv"}


@app.post("/api/boutique/produits/<pid>/fichier")
@connecte
def boutique_fichier_produit(pid):
    f = request.files.get("fichier")
    uid = g.u["id"]
    if not f or not f.filename:
        return jsonify({"erreur": "Aucun fichier reçu."}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in EXT_PRODUITS:
        return jsonify({"erreur": "Format non accepté. PDF, ZIP, EPUB, MP3, MP4, images ou documents Office."}), 400
    nom = uuid.uuid4().hex + ext
    f.save(bq.dossier(uid) / "fichiers" / nom)
    with bq.verrou(uid):
        page = bq.lit_page(uid)
        p = next((x for x in page["produits"] if x["id"] == pid), None)
        if not p:
            (bq.dossier(uid) / "fichiers" / nom).unlink(missing_ok=True)
            return jsonify({"erreur": "Enregistre d'abord le produit."}), 404
        ancien = p.get("fichier")
        p["fichier"], p["fichier_nom"] = nom, Path(f.filename).name[:120]
        bq.ecrit_page(uid, page)
    if ancien:
        (bq.dossier(uid) / "fichiers" / ancien).unlink(missing_ok=True)
    return jsonify({"fichier_nom": p["fichier_nom"]})


@app.get("/api/boutique/stats")
@connecte
def boutique_stats():
    uid = g.u["id"]
    page = bq.lit_page(uid)
    if not page:
        return jsonify({})
    s = bq.stats(uid, page)
    src = (bq._lit(bq.dossier(uid) / "stats.json", {}).get("sources") or {})
    s["sources"] = sorted(({"id": k, "nom": bv.nom_source(page, k), **v} for k, v in src.items()), key=lambda x: (-x.get("ca", 0), -x.get("vues", 0)))[:40]
    return jsonify(s)


@app.get("/api/boutique/rdv")
@connecte
def boutique_rdv_liste():
    uid = g.u["id"]
    page = bq.lit_page(uid) or {"produits": []}
    titres = {p["id"]: p.get("titre") for p in page["produits"]}
    maint = bv.maintenant() - timedelta(hours=2)
    l = [{**{k: r.get(k) for k in ("id", "debut", "duree", "email", "prenom", "statut")}, "produit": titres.get(r["produit"], "Rendez-vous"),
          "quand": bv.date_fr(bv._date(r["debut"]))} for r in bv.lit_rdv(uid) if r.get("statut") == "confirme" and bv._date(r["debut"]) > maint]
    return jsonify({"rdv": sorted(l, key=lambda r: r["debut"])})


@app.delete("/api/boutique/rdv/<rid>")
@connecte
def boutique_rdv_annule(rid):
    uid = g.u["id"]
    r = next((x for x in bv.lit_rdv(uid) if x["id"] == rid), None)
    if not r:
        abort(404)
    bv.annule_rdv(uid, rid)
    page = bq.lit_page(uid)
    if r.get("email") and "demo" not in r["email"]:
        import emails
        emails.envoie(r["email"], "Ton rendez-vous est annulé", bq._gabarit(page, "Rendez-vous annulé",
                      f"<p>Ton rendez-vous du {bv.date_fr(bv._date(r['debut']))} a dû être annulé. Choisis un autre créneau quand tu veux : "
                      f"{url_site()}/@{bq.pseudo_de(uid)}</p><p>Si tu avais payé, tu seras remboursée.</p>"))
    return jsonify({"ok": True})


@app.get("/api/boutique/avis")
@connecte
def boutique_avis_liste():
    uid = g.u["id"]
    page = bq.lit_page(uid) or {"produits": []}
    titres = {p["id"]: p.get("titre") for p in page["produits"]}
    return jsonify({"avis": [{**a, "produit_titre": titres.get(a["produit"], "Produit supprimé")} for a in reversed(bv.lit_avis(uid))]})


@app.patch("/api/boutique/avis/<aid>")
@connecte
def boutique_avis_modere(aid):
    c = request.get_json(force=True)
    bv.modere_avis(g.u["id"], aid, visible=bool(c.get("visible")), supprimer=bool(c.get("supprimer")))
    return jsonify({"ok": True})


@app.get("/api/boutique/qr.<ext>")
@connecte
def boutique_qr(ext):
    from flask import Response
    pseudo = bq.pseudo_de(g.u["id"])
    if not pseudo or ext not in ("png", "svg"):
        abort(404)
    url = f"{url_site()}/@{pseudo}?src=qr"
    c = request.args.get("c", "#000000")
    f = request.args.get("f", "#FFFFFF")
    c = c if bq.COULEUR.match(c) else "#000000"
    f = f if bq.COULEUR.match(f) else "#FFFFFF"
    data = bv.qr_png(url, c, f) if ext == "png" else bv.qr_svg(url, c, f)
    return Response(data, mimetype="image/png" if ext == "png" else "image/svg+xml",
                    headers={"Content-Disposition": f"inline; filename=qr-{pseudo}.{ext}"} if not request.args.get("dl") else
                    {"Content-Disposition": f"attachment; filename=qr-{pseudo}.{ext}"})


# ---- Claude au service de la boutique (file du studio, quotas de la formule)
@app.post("/api/boutique/idees")
@connecte
def boutique_idees():
    import boutique_ia
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre tâche : réessaie dans un instant."}), 409
    msg = reserve(g.u, "ia") or refus(g.u, adaptations=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    return jsonify({"job": lance(uid, "Idées de produits", boutique_ia.idees, g.esp, g.esp.lit_config(), demo=en_demo(), file_=FILE_STUDIO,
                                 apres=None if en_demo() else (lambda _: ab.compte_usage(uid, adaptations=1)))})


@app.post("/api/boutique/produits/<pid>/guide")
@connecte
def boutique_guide(pid):
    import boutique_ia
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre tâche : réessaie dans un instant."}), 409
    msg = reserve(g.u, "ia") or refus(g.u, studio=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    plan = [str(x)[:200] for x in (request.get_json(silent=True) or {}).get("plan") or []][:10]
    return jsonify({"job": lance(uid, "Écriture du guide", boutique_ia.guide, g.esp, g.esp.lit_config(), uid, pid, plan, demo=en_demo(),
                                 base=url_site(), file_=FILE_STUDIO, apres=lambda _: ab.compte_usage(uid, studio=1))})


@app.post("/api/boutique/sequence/ecrire")
@connecte
def boutique_sequence_ecrire():
    import boutique_ia
    if job_en_cours(g.u["id"], studio_=True):
        return jsonify({"erreur": "Le studio termine une autre tâche : réessaie dans un instant."}), 409
    msg = reserve(g.u, "ia") or refus(g.u, adaptations=1)
    if msg:
        return jsonify({"erreur": msg, "quota": True}), 402
    uid = g.u["id"]
    return jsonify({"job": lance(uid, "Séquence d'e-mails", boutique_ia.sequence, g.esp, g.esp.lit_config(), uid, demo=en_demo(), file_=FILE_STUDIO,
                                 apres=None if en_demo() else (lambda _: ab.compte_usage(uid, adaptations=1)))})


@app.post("/api/boutique/sequence/test")
@connecte
def boutique_sequence_test():
    import emails
    page = bq.lit_page(g.u["id"])
    c = request.get_json(force=True)
    i = int(c.get("i") or 0)
    e = ((page or {}).get("sequence") or {}).get("emails") or []
    if not page or i >= len(e):
        return jsonify({"erreur": "Enregistre d'abord l'e-mail."}), 400
    sujet, h = bv._mail_sequence(page, url_site(), bq.pseudo_de(g.u["id"]), {"prenom": g.u.get("prenom") or "", "jeton": "test"}, e[i])
    if not emails.envoie(g.u["email"], "[Test] " + sujet, h):
        return jsonify({"erreur": "Les e-mails ne sont pas encore configurés (clé Resend absente)."}), 400
    return jsonify({"ok": True, "email": g.u["email"]})


@app.get("/api/boutique/inscrits.csv")
@connecte
def boutique_inscrits_csv():
    from flask import Response
    return Response(bq.inscrits_csv(g.u["id"]), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=inscrits.csv"})


@app.post("/api/boutique/stripe")
@connecte
def boutique_stripe():
    uid = g.u["id"]
    page = bq.lit_page(uid)
    if not page:
        return jsonify({"erreur": "Crée d'abord ta boutique."}), 404
    if not bq.stripe_actif():
        return jsonify({"erreur": "Le paiement n'est pas encore activé sur Virallink. En attendant, propose des produits gratuits ou des liens externes."}), 400
    try:
        compte, lien = bq.connecte_stripe(uid, g.u["email"], (page.get("stripe") or {}).get("compte"), f"{url_site()}/app")
    except ValueError as e:
        return jsonify({"erreur": str(e)}), 400
    with bq.verrou(uid):
        page = bq.lit_page(uid)
        page["stripe"] = {**(page.get("stripe") or {}), "compte": compte}
        bq.ecrit_page(uid, page)
    return jsonify({"url": lien})


# ------------------------------------------------------------
#  Application installable (PWA), notifications push, parrainage, boutiques en exemple
# ------------------------------------------------------------
@app.get("/manifest.webmanifest")
def manifeste():
    from flask import Response
    m = {"name": "Virallink", "short_name": "Virallink", "description": "Les Reels viraux de ta niche, adaptés pour toi.",
         "start_url": "/app?source=app", "scope": "/", "display": "standalone", "orientation": "portrait",
         "background_color": "#F6F4F8", "theme_color": "#FF4F79", "lang": "fr",
         "icons": [{"src": "/static/icones/icone-192.png", "sizes": "192x192", "type": "image/png"},
                   {"src": "/static/icones/icone-512.png", "sizes": "512x512", "type": "image/png"},
                   {"src": "/static/icones/icone-masque-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    return Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    rep = send_from_directory(CODE / "static", "sw.js", max_age=0, mimetype="application/javascript")
    rep.headers["Service-Worker-Allowed"] = "/"
    rep.headers["Cache-Control"] = "no-cache"
    return rep


@app.get("/api/push/cle")
@connecte
def push_cle():
    return jsonify({"cle": nt.cle_publique(), "appareils": len(ab.push_de(g.u["id"]))})


@app.post("/api/push")
@connecte
def push_abonne():
    c = request.get_json(force=True)
    k = c.get("keys") or {}
    if not (str(c.get("endpoint", "")).startswith("https://") and k.get("p256dh") and k.get("auth")):
        return jsonify({"erreur": "Abonnement invalide."}), 400
    ab.ajoute_push(g.u["id"], c["endpoint"], k["p256dh"], k["auth"])
    nt.notifie(g.u["id"], "Notifications activées ✅", "Tu seras prévenue quand ta veille est prête et à chaque vente.", "/app")
    return jsonify({"ok": True})


@app.delete("/api/push")
@connecte
def push_desabonne():
    ab.retire_push(str((request.get_json(silent=True) or {}).get("endpoint", "")))
    return jsonify({"ok": True})


@app.get("/api/parrainage")
@connecte
def parrainage():
    code = ab.code_parrain(g.u["id"])
    f = ab.filleules(g.u["id"])
    u = ab.get(g.u["id"])
    return jsonify({"code": code, "lien": f"{url_site()}/?parrain={code}", "inscrites": f["inscrites"], "abonnees": f["abonnees"],
                    "mois_offerts": u.get("mois_offerts") or 0, "jours_filleule": ab.JOURS_FILLEULE})


@app.get("/api/vitrines")
def vitrines():
    """Boutiques publiées dont la propriétaire accepte de servir d'exemple (page d'accueil publique)."""
    res = []
    with ab._db() as c:
        lignes = c.execute("SELECT pseudo, uid FROM boutiques").fetchall()
    for r in lignes:
        page = bq.lit_page(r["uid"])
        if page and page.get("publie") and page.get("exemple") and page.get("photo"):
            res.append({"pseudo": r["pseudo"], "nom": page.get("nom") or r["pseudo"], "produits": len(page.get("produits") or []),
                        "maj": page.get("maj") or ""})
    res.sort(key=lambda x: (-x["produits"], x["maj"]), reverse=False)
    rep = jsonify({"vitrines": res[:8]})
    rep.headers["Cache-Control"] = "public, max-age=600"
    return rep


def synthese_de(u: dict) -> list[tuple[str, str]]:
    """Blocs du récapitulatif du lundi (vide s'il n'y a rien à raconter)."""
    import html as _h
    esp = espace_client(u["id"])
    blocs = []
    an = moteur.liste_analyses(esp)
    if an and an[0].get("date") and an[0]["date"] >= (datetime.now() - timedelta(days=8)).isoformat():
        a = moteur.charge(esp, an[0]["id"])
        adaptes = sorted([p for p in a.get("posts", []) if p.get("adaptation")], key=lambda p: -(p["adaptation"].get("pertinence") or 0))
        if adaptes:
            hooks = "".join(f"<li>{_h.escape((p['adaptation'].get('hook_viral') or '')[:120])}</li>" for p in adaptes[:3])
            blocs.append(("🔥 Ta veille", f"<p><b>{len(adaptes)} Reels viraux</b> adaptés à ta niche. À tourner en priorité :</p><ol>{hooks}</ol>"))
    try:
        b = pubs.bilan_semaine(esp, esp.lit_config())
        if b["publies"]:
            blocs.append(("📈 Tes publications", f"<p><b>{b['publies']}</b> Reels publiés ({b['vues']} vues, {b['conversations']} conversations, "
                                                f"{b['clients']} clientes).</p>"))
    except Exception:  # noqa: BLE001
        pass
    page = bq.lit_page(u["id"])
    if page and page.get("publie"):
        s = bq.stats(u["id"], page)
        if s["vues_7j"] or s["ventes_7j"] or s["inscrits_7j"]:
            blocs.append(("🛍️ Ta boutique", f"<p><b>{s['vues_7j']}</b> visites, <b>{s['inscrits_7j']}</b> nouvelles inscrites, "
                                            f"<b>{s['ventes_7j']}</b> ventes ({bq.prix_txt(s['chiffre_7j'], 'eur').replace('Gratuit', '0 €')}).</p>"))
    return blocs


def envoie_syntheses():
    maintenant = datetime.now()
    if maintenant.weekday() != 0 or maintenant.hour < 10:
        return
    semaine = maintenant.strftime("%G-%V")
    for u in ab.tous():
        try:
            if not u.get("synthese", 1) or (u.get("derniere_synthese") or "") == semaine or not droits(u)["actif"] or not u.get("onboarding"):
                continue
            ab.maj(u["id"], derniere_synthese=semaine)
            blocs = synthese_de(u)
            if blocs:
                emails.synthese(u["email"], u.get("prenom") or "", blocs, url_site() + "/app", url_site() + "/app#parametres")
                nt.notifie(u["id"], "Ta semaine est prête ☀️", "Ta veille, tes publications et ta boutique en un coup d'œil.", "/app")
        except Exception:  # noqa: BLE001
            traceback.print_exc()


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
    tous_ = {u["id"]: u for u in ab.tous()}
    limite = (datetime.now() - timedelta(days=14)).isoformat()
    for c in clients:
        u = tous_.get(c["id"]) or {}
        c["inactive"] = bool(c["actif"]) and (c["derniere_connexion"] or "") < limite
        c["parrain"] = (tous_.get(u.get("parrain")) or {}).get("email") if u.get("parrain") else None
        c["filleules"] = sum(1 for x in tous_.values() if x.get("parrain") == c["id"])
        c["a_paye"] = bool(u.get("a_paye"))
    anciens = [c for c in clients if (c["cree"] or "") < limite]
    mois = datetime.now().strftime("%Y-%m")
    ca_boutiques, boutiques_publiees, ventes_boutiques = 0, 0, 0
    with ab._db() as cx:
        for r in cx.execute("SELECT uid FROM boutiques").fetchall():
            page = bq.lit_page(r["uid"])
            if page and page.get("publie"):
                boutiques_publiees += 1
            for v in bq._lit(bq.dossier(r["uid"]) / "ventes.json", []):
                if v.get("montant") and "demo" not in (v.get("session") or ""):
                    ventes_boutiques += 1
                    ca_boutiques += v["montant"]
    croissance = {
        "conversion": round(100 * sum(1 for c in anciens if c["a_paye"]) / len(anciens)) if anciens else None,
        "resilies": sum(1 for c in clients if c["statut"] == "resilie"), "inactives": sum(1 for c in clients if c["inactive"]),
        "boutiques": boutiques_publiees, "ventes_boutiques": ventes_boutiques, "ca_boutiques": round(ca_boutiques / 100),
        "parrainages": sum(1 for u in tous_.values() if u.get("parrain")), "mois": mois,
    }
    return jsonify({"croissance": croissance,
        "clients": clients, "plans": {k: v["nom"] for k, v in p.items()},
        "kpi": {"clients": len(clients), "payants": sum(1 for c in clients if c["prix"]),
                "essais": sum(1 for c in clients if c["statut"] == "essai" and c["actif"]),
                "mrr": mrr, "cout_mois_usd": round(cout_mois, 2)},
        "config": {"apify": bool(os.getenv("APIFY_TOKEN")), "claude": bool(os.getenv("ANTHROPIC_API_KEY")), "banque": banque.active(),
                   "stripe": ab.stripe_actif(), "emails": emails.actif(), "demo": en_demo(), "url": url_site()},
        "serveur": {"memoire_mo": __import__("ressources").memoire_mo(), **__import__("ressources").disque(DATA)},
    })


@app.post("/api/admin/clients/<int:uid>/relance")
@admin_requis
def admin_relance(uid):
    u = ab.get(uid)
    if not u:
        abort(404)
    if not emails.actif():
        return jsonify({"erreur": "Les e-mails ne sont pas configurés (RESEND_API_KEY)."}), 400
    emails.relance(u["email"], u.get("prenom") or "", url_site() + "/app")
    nt.notifie(uid, "Ta veille t'attend 👀", "Les Reels qui ont explosé cette semaine sont prêts à être adaptés.", "/app")
    return jsonify({"ok": True})


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
def planificateur_emails():
    """Séquences d'e-mails des boutiques et demandes d'avis (toutes les 10 minutes)."""
    while True:
        time.sleep(600)
        try:
            with ab._db() as c:
                uids = [r["uid"] for r in c.execute("SELECT uid FROM boutiques").fetchall()]
            for uid in uids:
                try:
                    u = ab.get(uid)
                    if u and droits(u)["actif"] and droits(u)["options"]["sequences_emails"]:
                        bv.envoie_sequences(uid, url_site())
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def planificateur():
    while True:
        try:
            now = datetime.now()
            lundi = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            for u in ab.tous():  # relevés des Reels publiés (J+2, J+7)
                try:
                    if droits(u)["actif"] and droits(u)["options"]["suivi_publications"] and pubs.a_relever_esp(espace_client(u["id"])):
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
                    if not _nb_comptes(cfg) or refus(u, analyses=1, adaptations=min(cfg["objectifs"]["reels_par_jour"] * cfg["objectifs"]["jours_planifies"], moteur.adaptations_auto(cfg))):
                        continue
                    ab.maj(u["id"], derniere_veille_auto=lundi)
                    lance_analyse(u["id"], "Veille automatique du lundi", {"cfg": cfg, "mode": "veille", "demo": en_demo(), "differe": True,
                                                                           "max_adaptations": d["reste"]["adaptations"]})
            envoie_syntheses()
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
        threading.Thread(target=planificateur_emails, daemon=True).start()
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
