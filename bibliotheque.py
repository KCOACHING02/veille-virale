"""
Bibliothèque virale partagée, par niche.

Virallink surveille lui-même une liste de comptes Instagram par grande niche (bibliotheque.yaml, modifiable
depuis l'admin). Une fois par jour : une seule collecte pour toutes les clientes, puis chaque publication
virale de moins de 3 mois est préparée une seule fois (slides téléchargées, vidéo lue et transcrite sur le
serveur). Les clientes y puisent ensuite selon leur niche : seule l'adaptation à leur marque est faite pour
chacune (par Claude, quand elle choisit un contenu ou pour les 7 meilleurs de sa veille du lundi).

Règle « viral » (REGLES) : publiée depuis 48 h à 3 mois, au moins MULTIPLE × l'habitude de son compte pour ce
format (médiane de ses publications des 3 derniers mois), et un minimum absolu par format :
  Reel      : 30 000 vues et 3 % d'engagement ((j'aime + commentaires) / vues)
  Carrousel : 5 000 j'aime
  Photo     : 10 000 j'aime
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from espace import DATA
from modele import Post, date_utc, entier, log

CODE = Path(__file__).parent
RACINE = DATA / "bibliotheque"
MEDIA = RACINE / "media"
SEED = CODE / "bibliotheque.yaml"

FORMATS = ["Carrousel", "Reel", "Photo"]           # les 3 catégories affichées
NOMS_FORMATS = {"Carrousel": "Carrousels", "Reel": "Reels", "Photo": "Publications"}
REGLES = {"Reel": {"vues_min": 30_000, "engagement_min": 0.03},
          "Carrousel": {"jaime_min": 5_000},
          "Photo": {"jaime_min": 10_000}}
MULTIPLE = 3          # au moins 3 × l'habitude du compte
TRES_VIRAL = 10       # badge « Très viral »
JOURS_MAX = 90        # moins de 3 mois
DELAI_H = 48          # chiffres stables
PAR_COMPTE = 12       # publications lues par compte et par format chaque jour
PAR_COMPTE_LUNDI = 40  # le lundi : lecture plus profonde (publications devenues virales sur la durée)
LOT = 40              # comptes par lancement du collecteur
MAX_PREPARATIONS = 120  # nouvelles publications virales préparées par jour (lecture vidéo sur le serveur)

_VERROU = threading.RLock()


# ------------------------------------------------------------
#  Fichiers
# ------------------------------------------------------------
def _lit(nom: str, defaut):
    f = RACINE / nom
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def _ecrit(nom: str, data):
    RACINE.mkdir(parents=True, exist_ok=True)
    f = RACINE / nom
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def _propre(c: str) -> str:
    c = str(c or "").strip().lower()
    for p in ("https://", "http://", "www.", "instagram.com/"):
        c = c.replace(p, "")
    return c.strip("/@ ").split("/")[0].split("?")[0]


def niches() -> dict:
    """{id: {nom, mots, comptes}} : la version modifiée dans l'admin, sinon la liste de départ."""
    d = _lit("niches.json", None)
    if not d:
        d = yaml.safe_load(SEED.read_text(encoding="utf-8")) or {}
    return {k: {"nom": v.get("nom") or k, "mots": list(v.get("mots") or []),
                "comptes": list(dict.fromkeys(_propre(c) for c in v.get("comptes") or [] if _propre(c)))}
            for k, v in d.items()}


def sauve_niches(d: dict) -> dict:
    with _VERROU:
        propre = {}
        for k, v in (d or {}).items():
            k = "".join(ch for ch in str(k).lower() if ch.isalnum() or ch == "_")[:30]
            if not k or not isinstance(v, dict):
                continue
            propre[k] = {"nom": str(v.get("nom") or k)[:60], "mots": [str(m)[:40] for m in (v.get("mots") or [])][:40],
                         "comptes": list(dict.fromkeys(_propre(c) for c in (v.get("comptes") or []) if _propre(c)))[:80]}
        _ecrit("niches.json", propre)
        return propre


def ajoute_comptes_depart(demo: bool = False) -> int:
    """Une fois : les comptes ajoutés à bibliotheque.yaml (liste doublée le 10 novembre 2026) rejoignent la liste
    modifiée dans l'admin, puis les nouveaux sont vérifiés et retirés s'ils sont introuvables ou privés."""
    if etat().get("comptes_depart_v2") or not _lit("niches.json", None):
        return 0  # déjà fait, ou pas de liste modifiée (la liste de départ s'applique telle quelle)
    depart = yaml.safe_load(SEED.read_text(encoding="utf-8")) or {}
    with _VERROU:
        d = niches()
        nouveaux = []
        for k, v in depart.items():
            if k not in d:
                continue
            for c in v.get("comptes") or []:
                c = _propre(c)
                if c and c not in d[k]["comptes"]:
                    d[k]["comptes"].append(c)
                    nouveaux.append(c)
        sauve_niches(d)
        _ecrit("etat.json", {**etat(), "comptes_depart_v2": datetime.now().isoformat(timespec="minutes")})
    nouveaux = list(dict.fromkeys(nouveaux))
    log(f"Bibliothèque : {len(nouveaux)} comptes ajoutés, vérification…")
    if nouveaux:
        verifie_comptes(nouveaux, demo=demo)
        verif = _lit("verif.json", {})  # seulement les comptes vraiment lus (une panne d'Apify ne retire rien)
        ko = {c for c in nouveaux if verif.get(c, {}).get("introuvable") or verif.get(c, {}).get("prive")}
        if ko:
            with _VERROU:
                d = niches()
                for v in d.values():
                    v["comptes"] = [c for c in v["comptes"] if c not in ko]
                sauve_niches(d)
            log(f"  {len(ko)} compte(s) introuvables ou privés retirés : {', '.join(sorted(ko))[:300]}")
    return len(nouveaux)


def tous_les_comptes() -> list[str]:
    return sorted({c for n in niches().values() for c in n["comptes"]})


def niches_du_compte(compte: str) -> list[str]:
    return [k for k, n in niches().items() if compte in n["comptes"]]


def tentatives(jour: str) -> int:
    return int((_lit("tentatives.json", {}) or {}).get(jour) or 0)


def note_tentative(jour: str):
    t = {k: v for k, v in (_lit("tentatives.json", {}) or {}).items() if k >= jour}
    t[jour] = int(t.get(jour) or 0) + 1
    _ecrit("tentatives.json", t)


def etat() -> dict:
    return _lit("etat.json", {})


def publications() -> dict:
    return _lit("publications.json", {})


def chemin_media(rel: str) -> Path | None:
    """Fichier de la bibliothèque à partir de son nom relatif (protégé contre les chemins sortants)."""
    f = (MEDIA / rel).resolve()
    return f if str(f).startswith(str(MEDIA.resolve())) and f.is_file() else None


# ------------------------------------------------------------
#  Règle virale
# ------------------------------------------------------------
def _age_j(date: str) -> float | None:
    d = date_utc(date)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400 if d else None


def _valeur(fmt: str, x: dict) -> float:
    """Ce qu'on compare à l'habitude du compte : vues pour un Reel, j'aime pour un carrousel ou une photo."""
    return float((x.get("v") or 0) if fmt == "Reel" else (x.get("l") or 0))


def juge(fmt: str, x: dict, historique: list[dict]) -> dict | None:
    """x = {l, c, v, d} ; historique = publications du même compte et du même format. None si pas viral."""
    age = _age_j(x.get("d"))
    if age is None or age > JOURS_MAX or age < DELAI_H / 24:
        return None
    valeurs = [_valeur(fmt, h) for h in historique if _valeur(fmt, h) > 0]
    val = _valeur(fmt, x)
    r = REGLES.get(fmt)
    if not r or not val:
        return None
    if fmt == "Reel":
        eng = ((x.get("l") or 0) + (x.get("c") or 0)) / val
        if val < r["vues_min"] or eng < r["engagement_min"]:
            return None
    elif val < r["jaime_min"]:
        return None
    if len(valeurs) >= 3:
        med = statistics.median(valeurs)
    else:  # compte sans habitude mesurable pour ce format : on exige le double du minimum
        med = None
        if val < 2 * (r.get("vues_min") or r.get("jaime_min")):
            return None
    multiple = round(val / med, 1) if med else float(MULTIPLE)
    if med and multiple < MULTIPLE:
        return None
    return {"multiple": multiple, "mediane": int(med) if med else None, "age_j": round(age, 1)}


def rang(e: dict) -> float:
    """Classement : force de la surperformance, avec un bonus aux publications récentes (jusqu'à × 2 sous 30 jours)."""
    age = _age_j(e.get("date")) or JOURS_MAX
    return (e.get("multiple") or 0) * (1 + max(0.0, 30 - age) / 30)


def badge(e: dict) -> str:
    return "tres_viral" if (e.get("multiple") or 0) >= TRES_VIRAL else "viral"


# ------------------------------------------------------------
#  Actualisation quotidienne
# ------------------------------------------------------------
def a_faire() -> bool:
    return (etat().get("jour") or "") < datetime.now().strftime("%Y-%m-%d")


def _cfg_base() -> dict:
    return yaml.safe_load((CODE / "config.exemple.yaml").read_text(encoding="utf-8"))


def actualise(demo: bool = False, profond: bool | None = None) -> dict:
    """Une collecte pour tous les comptes de toutes les niches, puis préparation des nouvelles publications virales."""
    with _VERROU:
        import collecte
        debut = datetime.now()
        cout_avant = collecte.cout_apify_total()
        comptes = tous_les_comptes()
        profond = (debut.weekday() == 0) if profond is None else profond
        maxi = PAR_COMPTE_LUNDI if profond else PAR_COMPTE
        log(f"Bibliothèque : lecture de {len(comptes)} comptes Instagram ({maxi} publications par format)…")
        if demo:
            import demo as d
            posts = d.posts_bibliotheque(comptes)
        else:
            token = os.getenv("APIFY_TOKEN")
            if not token:
                raise RuntimeError("Clé APIFY_TOKEN manquante.")
            cfg = _cfg_base()
            posts = []
            for i in range(0, len(comptes), LOT):
                lot = comptes[i:i + LOT]
                try:
                    posts += collecte.collecte_instagram(lot, JOURS_MAX, maxi, cfg, token)
                except Exception as e:  # noqa: BLE001
                    log(f"  ⚠️  Lot {i // LOT + 1} illisible : {str(e)[:120]}")
                log(f"  {min(i + LOT, len(comptes))}/{len(comptes)} comptes lus")

        # Historique par compte (3 mois) : sert à mesurer l'habitude de chaque compte, format par format
        hist = _lit("comptes.json", {})
        limite = (datetime.now(timezone.utc) - timedelta(days=JOURS_MAX + 7)).isoformat()
        vus_par_compte: dict[str, int] = {}
        for p in posts:
            if p.plateforme != "Instagram" or p.format not in FORMATS:
                continue
            c = _propre(p.compte)
            h = hist.setdefault(c, {"posts": {}})
            h["posts"][p.id] = {"f": p.format, "l": p.likes or 0, "c": p.commentaires or 0, "v": p.vues or 0, "d": p.date}
            vus_par_compte[c] = vus_par_compte.get(c, 0) + 1
        for c, h in hist.items():
            h["posts"] = {k: x for k, x in h["posts"].items() if (x.get("d") or "") >= limite}
            if c in vus_par_compte:
                h["lu_le"] = debut.isoformat(timespec="minutes")
                h["derniere_lecture"] = vus_par_compte[c]
            elif c in comptes:
                h["derniere_lecture"] = 0
        _ecrit("comptes.json", hist)

        # Publications virales
        pubs = publications()
        nouvelles = []
        for p in posts:
            if p.format not in FORMATS:
                continue
            c = _propre(p.compte)
            x = {"l": p.likes or 0, "c": p.commentaires or 0, "v": p.vues or 0, "d": p.date}
            histo = [y for k, y in hist.get(c, {}).get("posts", {}).items() if y["f"] == p.format and k != p.id]
            j = juge(p.format, x, histo)
            if not j:
                continue
            e = pubs.get(p.id)
            if e:  # déjà connue : chiffres mis à jour, médias gardés
                e.update({"likes": p.likes, "commentaires": p.commentaires, "vues": p.vues, "multiple": j["multiple"],
                          "mediane": j["mediane"], "maj_le": debut.isoformat(timespec="minutes"), "niches": niches_du_compte(c)})
                continue
            e = {"id": p.id, "compte": c, "url": p.url, "format": p.format, "date": p.date, "legende": (p.legende or "")[:2500],
                 "likes": p.likes, "commentaires": p.commentaires, "vues": p.vues, "duree_s": p.duree_s, "son": p.son or {},
                 "multiple": j["multiple"], "mediane": j["mediane"], "niches": niches_du_compte(c),
                 "video_url": p.video_url, "cover_url": p.cover_url,
                 "medias": p.medias or ([p.cover_url] if p.format == "Photo" and p.cover_url else []),
                 "vu_le": debut.isoformat(timespec="minutes"), "maj_le": debut.isoformat(timespec="minutes"), "prepare": False}
            pubs[p.id] = e
            nouvelles.append(e)
        log(f"  {len(nouvelles)} nouvelle(s) publication(s) virale(s)")

        # Publications de plus de 3 mois ou de comptes retirés : sorties de la bibliothèque
        suivis = set(comptes)
        for k in [k for k, e in pubs.items() if (_age_j(e.get("date")) or 999) > JOURS_MAX or e.get("compte") not in suivis]:
            shutil.rmtree(MEDIA / k, ignore_errors=True)
            pubs.pop(k)
        _ecrit("publications.json", pubs)

        # La collecte est faite : on l'enregistre tout de suite, pour qu'un redémarrage du serveur ne la refasse pas
        cout = round(collecte.cout_apify_total() - cout_avant, 3)
        et = etat()
        journal = ([{"jour": debut.strftime("%Y-%m-%d"), "cout_usd": cout, "comptes": len(comptes), "lus": len(posts),
                     "nouvelles": len(nouvelles), "total": len(pubs)}] + (et.get("journal") or []))[:60]
        _ecrit("etat.json", {**et, "jour": debut.strftime("%Y-%m-%d"), "fin": datetime.now().isoformat(timespec="minutes"),
                             "cout_usd": cout, "total": len(pubs), "par_format": _par_format(pubs), "journal": journal})
        log(f"✅ Collecte terminée : {len(pubs)} publications virales ({cout:.2f} $). Préparation…")
    prepare_restants(demo=demo)
    try:
        marque_faceless()
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️  Détection des visages impossible : {str(e)[:120]}")
    return {"total": len(pubs), "nouvelles": len(nouvelles), "cout_usd": cout}


def _par_format(pubs: dict) -> dict:
    return {f: sum(1 for e in pubs.values() if e["format"] == f) for f in FORMATS}


def restants() -> list[dict]:
    """Publications virales pas encore préparées (3 essais au plus), les plus fortes d'abord."""
    return sorted([e for e in publications().values() if not e.get("prepare") and (e.get("essais") or 0) < 3], key=rang, reverse=True)


def marque_faceless(maxi: int = 400) -> int:
    """Publications préparées avant la détection des visages : on juge leurs images une fois (local, gratuit)."""
    import visages
    a_juger = [e for e in publications().values() if e.get("prepare") and "faceless" not in e][:maxi]
    if not a_juger:
        return 0
    res = {e["id"]: visages.faceless([MEDIA / r for r in e.get("images") or []], e["format"]) for e in a_juger}
    with _VERROU:
        pubs = publications()
        for k, v in res.items():
            if k in pubs:
                pubs[k]["faceless"] = v
        _ecrit("publications.json", pubs)
        _ecrit("etat.json", {**etat(), "visages": datetime.now().isoformat(timespec="seconds")})  # les tendances des clientes se refont
    log(f"Bibliothèque : {sum(1 for v in res.values() if v)} publications sans visage sur {len(res)} jugées")
    return len(res)


def prepare_restants(demo: bool = False, maxi: int = MAX_PREPARATIONS, lot: int = 4) -> int:
    """Prépare les publications en attente par petits lots, enregistrés au fur et à mesure (rien n'est perdu si le serveur redémarre)."""
    a_faire = restants()[:maxi]
    faites = 0
    for i in range(0, len(a_faire), lot):
        paquet = a_faire[i:i + lot]
        prepare(paquet, demo=demo)
        with _VERROU:
            pubs = publications()
            for e in paquet:
                if e["id"] in pubs:
                    pubs[e["id"]] = e
            _ecrit("publications.json", pubs)
        faites += len(paquet)
        log(f"  {faites}/{len(a_faire)} publications préparées")
    if a_faire:
        log(f"✅ Bibliothèque : {sum(1 for e in publications().values() if e.get('prepare'))} publications prêtes pour les clientes")
    return faites


def prepare(entrees: list[dict], demo: bool = False):
    """Télécharge les slides (carrousel, photo) ou lit la vidéo (images clés + transcription) de chaque publication."""
    from video import reduit, slides_carrousels, traite_videos
    travail = Path(tempfile.mkdtemp(prefix="veille_biblio_"))
    MEDIA.mkdir(parents=True, exist_ok=True)
    try:
        posts = []
        for e in entrees:
            p = Post(plateforme="Instagram", compte=e["compte"], id=e["id"], url=e["url"], date=e["date"],
                     format=e["format"], legende=e.get("legende") or "", video_url=e.get("video_url"),
                     cover_url=e.get("cover_url"), duree_s=e.get("duree_s"), medias=list(e.get("medias") or []))
            posts.append((e, p))
        log(f"Préparation de {len(posts)} publication(s) virale(s)…")
        if demo:
            import demo as d
            for e, p in posts:
                d.prepare_bibliotheque(p, travail)
        else:
            images = [p for e, p in posts if e["format"] != "Reel"]
            if images:
                slides_carrousels(images, travail, None)
            videos = [p for e, p in posts if e["format"] == "Reel"]
            if videos:
                cfg = _cfg_base()
                cfg["video"]["actif"] = True
                traite_videos(videos, cfg, None, travail, None)
        for e, p in posts:
            d = MEDIA / e["id"]
            d.mkdir(parents=True, exist_ok=True)
            rels = []
            for i, src in enumerate(p.images or []):
                if Path(src).is_file():
                    nom = f"{i + 1:02d}.jpg"
                    shutil.copy(src, d / nom)
                    rels.append(f"{e['id']}/{nom}")
            e["essais"] = (e.get("essais") or 0) + 1
            if not rels:
                log(f"  ⚠️  @{e['compte']} : médias illisibles (essai {e['essais']}/3)")
                continue
            # Vignette : 2e image clé d'une vidéo (la 1re est souvent noire), 1re slide sinon
            vign = rels[1] if e["format"] == "Reel" and len(rels) > 1 else rels[0]
            shutil.copy(MEDIA / vign, d / "vignette.jpg")
            try:
                reduit(d / "vignette.jpg")
            except Exception:  # noqa: BLE001
                pass
            try:
                import visages
                e["faceless"] = visages.faceless([MEDIA / r for r in rels], e["format"])
            except Exception:  # noqa: BLE001
                pass
            e.update({"images": rels, "vignette": f"{e['id']}/vignette.jpg", "transcription": p.transcription or "",
                      "duree_s": p.duree_s or e.get("duree_s"), "prepare": True, "prepare_le": datetime.now().isoformat(timespec="minutes")})
            e.pop("video_url", None)  # lien Instagram temporaire : inutile une fois la vidéo lue
    finally:
        shutil.rmtree(travail, ignore_errors=True)
        try:
            from ressources import libere_memoire
            libere_memoire()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------
#  Vérification des comptes (admin)
# ------------------------------------------------------------
def verifie_comptes(comptes: list[str] | None = None, demo: bool = False) -> dict:
    """Profil public de chaque compte (existe, public, abonnés) : une lecture par compte, à la demande de l'admin."""
    comptes = [_propre(c) for c in (comptes or tous_les_comptes()) if _propre(c)]
    verif = _lit("verif.json", {})
    if demo:
        for i, c in enumerate(comptes):
            verif[c] = {"ok": i % 9 != 4, "abonnes": 120_000 + i * 37_000, "prive": False, "nom": c.title(),
                        "le": datetime.now().isoformat(timespec="minutes")}
    else:
        import collecte
        token = os.getenv("APIFY_TOKEN")
        if not token:
            raise RuntimeError("Clé APIFY_TOKEN manquante.")
        cfg = _cfg_base()
        for i in range(0, len(comptes), LOT):
            lot = comptes[i:i + LOT]
            try:
                items = collecte.apify_run(cfg["apify"]["actor_instagram"], {
                    "directUrls": [f"https://www.instagram.com/{c}/" for c in lot], "resultsType": "details", "resultsLimit": 1}, token)
            except Exception as e:  # noqa: BLE001
                log(f"  ⚠️  Vérification impossible : {str(e)[:120]}")
                continue
            trouves = {}
            for it in items:
                u = _propre(it.get("username") or "")
                if u:
                    trouves[u] = it
            for c in lot:
                it = trouves.get(c)
                verif[c] = ({"ok": not it.get("private"), "abonnes": entier(it.get("followersCount")),
                             "prive": bool(it.get("private")), "nom": it.get("fullName") or "",
                             "le": datetime.now().isoformat(timespec="minutes")} if it
                            else {"ok": False, "introuvable": True, "le": datetime.now().isoformat(timespec="minutes")})
            log(f"  {min(i + LOT, len(comptes))}/{len(comptes)} comptes vérifiés")
    _ecrit("verif.json", verif)
    ko = [c for c in comptes if not verif.get(c, {}).get("ok")]
    log(f"✅ {len(comptes) - len(ko)} compte(s) valides, {len(ko)} à remplacer")
    return {"ok": len(comptes) - len(ko), "ko": ko}


def resume_admin() -> dict:
    n, pubs, verif, hist = niches(), publications(), _lit("verif.json", {}), _lit("comptes.json", {})
    out = {}
    for k, v in n.items():
        mes = [e for e in pubs.values() if k in (e.get("niches") or [])]
        out[k] = {"nom": v["nom"], "mots": v["mots"],
                  "comptes": [{"compte": c, **verif.get(c, {}), "lus": hist.get(c, {}).get("derniere_lecture"),
                               "viraux": sum(1 for e in mes if e["compte"] == c)} for c in v["comptes"]],
                  "par_format": {f: sum(1 for e in mes if e["format"] == f) for f in FORMATS}}
    return {"niches": out, "etat": {**etat(), "total": len(pubs), "prets": sum(1 for e in pubs.values() if e.get("prepare")),
                                    "par_format": _par_format(pubs)}, "regles": REGLES, "multiple": MULTIPLE}


# ------------------------------------------------------------
#  Côté clientes
# ------------------------------------------------------------
def _norm(t: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(ch) != "Mn")


def _scores_niches(cfg: dict, plus: str = "") -> list[tuple[int, str]]:
    n = cfg.get("niche") or {}
    texte = _norm(" ".join(str(x) for x in [n.get("nom"), n.get("description"), n.get("cible"), n.get("offre"),
                                              " ".join(n.get("douleurs") or []), plus] if x))
    return sorted(((sum(texte.count(_norm(m)) for m in v["mots"]), k) for k, v in niches().items()), reverse=True)


def devine_niches(cfg: dict, plus: str = "", strict: bool = False) -> list[str]:
    """Niche(s) d'une cliente d'après son profil (mots-clés, sans IA). La 2e seulement si elle est presque aussi proche.
    `plus` : ce qu'elle a déjà dit ailleurs (création de sa boutique), pour ne pas lui reposer la question à vide.
    `strict` : rien si aucun mot ne correspond (au lieu de la niche par défaut)."""
    scores = _scores_niches(cfg, plus)
    if not scores or scores[0][0] == 0:
        if strict:
            return []
        return ["coaching"] if "coaching" in niches() else list(niches())[:1]
    res = [scores[0][1]]
    if len(scores) > 1 and scores[1][0] and scores[1][0] >= 0.7 * scores[0][0]:
        res.append(scores[1][1])
    return res


def niche_connue(cfg: dict) -> bool:
    """La niche a été choisie, ou son profil suffit à la deviner. Sinon on la lui demande avant de montrer des tendances."""
    if [k for k in ((cfg.get("bibliotheque") or {}).get("niches") or []) if k in niches()]:
        return True
    scores = _scores_niches(cfg)
    return bool(scores and scores[0][0])


def niches_de(cfg: dict) -> list[str]:
    choisies = [k for k in ((cfg.get("bibliotheque") or {}).get("niches") or []) if k in niches()]
    return choisies or devine_niches(cfg)


def liste(niches_ids: list[str], fmt: str | None = None, limite: int = 60, decalage: int = 0) -> list[dict]:
    """Publications préparées des niches données, les plus fortes d'abord."""
    res = [e for e in publications().values() if e.get("prepare") and set(e.get("niches") or []) & set(niches_ids)
           and (not fmt or e["format"] == fmt)]
    res.sort(key=rang, reverse=True)
    return res[decalage:decalage + limite]


def vue(e: dict) -> dict:
    """Ce que voit une cliente (sans chemins internes)."""
    return {"id": e["id"], "compte": e["compte"], "url": e["url"], "format": e["format"], "date": e["date"],
            "legende": (e.get("legende") or "")[:300], "likes": e.get("likes"), "commentaires": e.get("commentaires"),
            "vues": e.get("vues"), "multiple": e.get("multiple"), "badge": badge(e), "nb_slides": len(e.get("images") or []),
            "vignette": e.get("vignette"), "faceless": e.get("faceless")}


def en_post(e: dict, media_client: Path | None = None) -> Post:
    """Publication de la bibliothèque prête à être adaptée par le moteur (images locales, transcription, score)."""
    p = Post(plateforme="Instagram", compte=e["compte"], id=e["id"], url=e["url"], date=e["date"], format=e["format"],
             legende=e.get("legende") or "", likes=e.get("likes"), commentaires=e.get("commentaires"), vues=e.get("vues"),
             duree_s=e.get("duree_s"), son=e.get("son") or {}, transcription=e.get("transcription") or "")
    p.images = [str(MEDIA / r) for r in e.get("images") or [] if (MEDIA / r).is_file()]
    p.faceless = e.get("faceless")
    p.interactions = (p.likes or 0) + (p.commentaires or 0)
    if p.vues:
        p.taux_engagement = round(p.interactions / p.vues, 4)
        p.taux_commentaires = round((p.commentaires or 0) / p.vues, 5)
    p.score_viral = float(e.get("multiple") or MULTIPLE)
    p.criteres_ok = True
    r = REGLES[e["format"]]
    p.seuil_vues = r.get("vues_min") or r.get("jaime_min")
    if media_client is not None and e.get("vignette") and (MEDIA / e["vignette"]).is_file():
        media_client.mkdir(parents=True, exist_ok=True)
        nom = f"Instagram_{e['id']}.jpg"
        if not (media_client / nom).exists():
            shutil.copy(MEDIA / e["vignette"], media_client / nom)
        p.miniature = nom
    return p


def posts_pour(cfg: dict, media_client: Path | None = None, limite: int = 80) -> list[Post]:
    """Veille d'une cliente : les publications virales de sa niche, classées, toutes catégories confondues."""
    return [en_post(e, media_client) for e in liste(niches_de(cfg), limite=limite)]


def active() -> bool:
    return bool(publications()) or os.getenv("BIBLIOTHEQUE") == "1"
