"""
Plan 30 jours : un mois de carrousels qui forme un tunnel de vente, construit à partir de la veille.

La veille classe chaque publication virale par type de contenu (`Post.type_contenu`, classé par Claude d'après la légende).
Ces types sont regroupés en 4 catégories du tunnel : storytelling → éducatif → preuve sociale → vente.
Chaque case du plan reprend la STRUCTURE de la publication virale la mieux notée de sa catégorie (accroche, nombre de slides,
rythme), jamais son texte ni ses images, et le sujet vient du brief de la cliente.

Données : data/espaces/<id>/plan30/brief.json (infos de vente, une fois par boutique : brief_<bid>.json pour les boutiques
suivantes) et plan30/<pid>.json. Un carrousel fabriqué = un projet du studio (studio.py),
relié à sa case par p["plan30"] = {"plan": pid, "case": i} ; il compte 1 création au studio comme les autres.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import moteur
import studio
from espace import Espace
from modele import log

# Catégories du tunnel ← types de contenu de la veille (modele.TYPES_CONTENU). Le 1er type est prioritaire.
CATEGORIES = {
    "storytelling": {"nom": "Storytelling", "types": ["Storytelling", "Inspirant"], "style": "histoire",
                     "objectif": "Créer le lien",
                     "regles": "Première personne, un moment précis (lieu, moment, émotion), une difficulté, une leçon. Aucune vente directe."},
    "educatif": {"nom": "Éducatif", "types": ["Éducatif"], "style": "pedago",
                 "objectif": "Prouver l'expertise",
                 "regles": "Une promesse concrète dans l'accroche, des étapes ou des erreurs numérotées. Donner le « quoi », garder le « comment » complet pour l'offre."},
    "preuve": {"nom": "Preuve sociale", "types": ["Preuve sociale", "Coulisses"], "style": "ma_voix",
               "objectif": "Rassurer",
               "regles": "Uniquement les avis et résultats réels fournis dans le brief, cités tels quels. Structure avant / pendant / après."},
    "vente": {"nom": "Vente", "types": ["Commercial"], "style": "ma_voix",
              "objectif": "Convertir",
              "regles": "Pour qui (et pour qui ce n'est pas), ce que contient l'offre, le prix, la réponse à l'objection principale, la date limite si elle existe, un seul appel à l'action."},
}
TYPE_VERS_CAT = {t: c for c, v in CATEGORIES.items() for t in v["types"]}
SEMAINES = ["Attirer", "Éduquer", "Convaincre", "Vendre"]

# Le plan type : 8 carrousels, 2 par semaine (mardi et vendredi), la vente en dernière semaine.
# (semaine, catégorie, rôle dans le tunnel, appel à l'action de la dernière slide)
SEQUENCE = [
    (0, "storytelling", "Mon histoire : le déclic, pourquoi je fais ce métier", "Enregistre ce post et abonne-toi pour la suite"),
    (0, "educatif", "Les erreurs que fait ma cliente idéale (ses problèmes)", "Enregistre ce post pour le retrouver"),
    (1, "educatif", "Ma méthode en quelques étapes, sans tout donner", "Commente « OUI » si tu veux la suite"),
    (1, "preuve", "Le résultat d'une cliente (ou les coulisses de ma méthode)", "Pose ta question en commentaire"),
    (2, "storytelling", "Ma réponse à l'objection principale, par une histoire vécue", "Écris-moi en message privé"),
    (2, "preuve", "Plusieurs avis ou résultats réels", "Envoie le mot-clé en message privé"),
    (3, "educatif", "La dernière marche : ce qui manque pour passer à l'action", "Envoie le mot-clé en message privé pour recevoir l'offre"),
    (3, "vente", "L'offre : pour qui, ce qu'il y a dedans, le prix", "Lien en bio pour réserver ta place"),
]
JOURS_PUBLICATION = (1, 4)  # mardi, vendredi (0 = lundi)

CHAMPS_BRIEF = {
    "produit": 300, "prix": 120, "lien": 300, "date_cle": 10, "transformation": 300, "cible": 200, "histoire": 800,
    "ton": 20, "tutoiement": 5, "emojis": 12, "produit_id": 300,
}
TONS = ["Complice", "Experte", "Inspirante", "Directe"]


# ------------------------------------------------------------
#  Fichiers
# ------------------------------------------------------------
def _racine(esp: Espace) -> Path:
    d = esp.racine / "plan30"
    d.mkdir(exist_ok=True)
    return d


def _ecrit(f: Path, data: dict):
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _f_brief(esp: Espace, bid=None) -> Path:
    """Infos de vente renseignées une seule fois par boutique (la première boutique garde brief.json)."""
    b = str(bid or "")
    return _racine(esp) / (f"brief_{b}.json" if "-" in b else "brief.json")


def brief(esp: Espace, cfg: dict | None = None, bid=None) -> dict:
    """Brief enregistré, ou pré-rempli à partir du profil de la marque (niche, cible, problèmes, offre, ton)."""
    f = _f_brief(esp, bid)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    n = (cfg or {}).get("niche") or {}
    return {"produit": n.get("offre") or "", "prix": "", "lien": "", "date_cle": "", "transformation": "",
            "cible": n.get("cible") or "", "problemes": (n.get("douleurs") or [])[:3], "objections": [],
            "temoignages": [], "accord_temoignages": False, "resultats": [], "histoire": "",
            "ton": "Complice", "tutoiement": "tu", "emojis": "quelques", "neuf": True}


def sauve_brief(esp: Espace, champs: dict, bid=None) -> dict:
    b = brief(esp, None, bid)
    for k, n in CHAMPS_BRIEF.items():
        if k in champs:
            b[k] = str(champs[k] or "").strip()[:n]
    for k, maxi, n in (("problemes", 3, 200), ("objections", 3, 200), ("temoignages", 5, 600), ("resultats", 3, 200), ("produits", 12, 160)):
        if isinstance(champs.get(k), list):
            b[k] = [str(x).strip()[:n] for x in champs[k] if str(x or "").strip()][:maxi]
    if "accord_temoignages" in champs:
        b["accord_temoignages"] = bool(champs["accord_temoignages"])
    if b.get("ton") not in TONS:
        b["ton"] = "Complice"
    if b.get("tutoiement") not in ("tu", "vous"):
        b["tutoiement"] = "tu"
    if b.get("emojis") not in ("aucun", "quelques", "beaucoup"):
        b["emojis"] = "quelques"
    b.pop("neuf", None)
    b["modifie"] = datetime.now().isoformat(timespec="minutes")
    _ecrit(_f_brief(esp, bid), b)
    return b


def brief_complet(b: dict) -> str | None:
    """Message à afficher s'il manque un champ obligatoire, sinon None."""
    manque = [nom for k, nom in (("produit", "ton offre"), ("prix", "son prix"), ("lien", "le lien d'achat ou le mot-clé"),
                                 ("transformation", "la transformation promise"), ("cible", "ta cliente idéale"),
                                 ("histoire", "ton histoire")) if not (b.get(k) or "").strip()]
    if len(b.get("problemes") or []) < 2:
        manque.append("au moins 2 problèmes de ta cliente")
    if not b.get("objections"):
        manque.append("au moins 1 objection")
    return ("Il manque " + ", ".join(manque) + ".") if manque else None


def charge(esp: Espace, pid: str) -> dict:
    return json.loads((_racine(esp) / f"{Path(pid).name}.json").read_text(encoding="utf-8"))


def sauve(esp: Espace, plan: dict):
    _ecrit(_racine(esp) / f"{plan['id']}.json", plan)


def liste(esp: Espace) -> list[dict]:
    res = []
    for f in _racine(esp).glob("*.json"):
        if f.name.startswith("brief"):
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        res.append({k: p.get(k) for k in ("id", "cree", "debut", "fin", "titre")} |
                   {"prets": sum(1 for c in p.get("cases", []) if c.get("projet")), "total": len(p.get("cases", []))})
    return sorted(res, key=lambda p: p.get("cree") or "", reverse=True)


def nb_depuis(esp: Espace, debut: date) -> int:
    """Nombre de plans créés depuis le début de la période d'abonnement (quota plans_30j_par_mois)."""
    return sum(1 for p in liste(esp) if (p.get("cree") or "")[:10] >= debut.isoformat())


# ------------------------------------------------------------
#  La veille classée par catégorie du tunnel
# ------------------------------------------------------------
def _age_jours(p: dict) -> int:
    from modele import date_utc
    d = date_utc(p.get("date"))
    return (datetime.now(d.tzinfo) - d).days if d else 9999


def publications_classees(esp: Espace) -> dict[str, list[dict]]:
    """
    Publications virales de toutes les veilles de la cliente, rangées par catégorie du tunnel et triées :
    adaptées d'abord (leur structure est connue slide par slide), puis carrousels, puis score viral.
    """
    vus: dict[str, dict] = {}
    for a in moteur.liste_analyses(esp):
        if a.get("en_cours"):
            continue
        try:
            an = moteur.charge(esp, a["id"])
        except (OSError, ValueError):
            continue
        for p in an.get("posts") or []:
            cat = TYPE_VERS_CAT.get(p.get("type_contenu") or "")
            if not cat:
                continue
            ad = p.get("adaptation") or {}
            fiche = {"analyse_id": a["id"], "cle": p.get("cle"), "compte": p.get("compte"), "plateforme": p.get("plateforme"),
                     "format": p.get("format"), "url": p.get("url"), "miniature": p.get("miniature"), "type": p.get("type_contenu"),
                     "categorie": cat, "score": round(float(p.get("score_viral") or 0), 1), "viral": bool(p.get("criteres_ok")),
                     "adapte": bool(ad) and not ad.get("erreur"), "age": _age_jours(p),
                     "accroche": (ad.get("hook_viral") or (p.get("legende") or "").split("\n")[0])[:140]}
            ancien = vus.get(fiche["cle"])
            if not ancien or (fiche["adapte"], fiche["score"]) > (ancien["adapte"], ancien["score"]):
                vus[fiche["cle"]] = fiche
    res: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for f in vus.values():
        res[f["categorie"]].append(f)
    for c, l in res.items():
        # 90 derniers jours en priorité ; au-delà (jusqu'à 180 j) seulement si la catégorie en manque
        recents = [f for f in l if f["age"] <= 90]
        base = recents if len(recents) >= 3 else [f for f in l if f["age"] <= 180] or l
        prio_type = CATEGORIES[c]["types"][0]
        res[c] = sorted(base, key=lambda f: (f["adapte"], f["viral"], f["type"] == prio_type, f["format"] == "Carrousel", f["score"]),
                        reverse=True)
    return res


def resume_veille(classees: dict) -> dict:
    return {c: len(l) for c, l in classees.items()}


def _choisit(classees: dict, cat: str, deja: set) -> dict | None:
    """Meilleure publication de la catégorie pas encore utilisée dans le plan ; à défaut, une catégorie voisine."""
    for c in [cat] + [x for x in ("educatif", "storytelling", "preuve", "vente") if x != cat]:
        for f in classees.get(c) or []:
            if f["cle"] not in deja:
                return {**f, "niche_proche": c != cat}
    return None


# ------------------------------------------------------------
#  Création du plan
# ------------------------------------------------------------
def lundi(d: date) -> date:
    return d - timedelta(days=d.weekday())


def debut_par_defaut(b: dict) -> date:
    """Lundi prochain ; avec une date de lancement, le plan finit juste avant (la vente tombe la veille ou l'avant-veille)."""
    try:
        cle_ = date.fromisoformat(b.get("date_cle") or "")
        d = lundi(cle_ - timedelta(days=26))
        if d >= date.today():
            return d
    except ValueError:
        pass
    return lundi(date.today()) + timedelta(days=7)


def cree(esp: Espace, cfg: dict, debut: date | None = None, demo: bool = False, bid=None) -> dict:
    """Tâche de fond : choisit les publications virales de chaque case puis fait écrire titres et angles par Virall.ai."""
    b = brief(esp, cfg, bid)
    debut = lundi(debut or debut_par_defaut(b))
    log("Je classe les publications virales de ta veille par étape du tunnel…")
    classees = publications_classees(esp)
    if not any(classees.values()):
        raise RuntimeError("Ta veille ne contient encore aucune publication classée : lance d'abord une veille, puis reviens créer ton plan.")
    log("Nombre de modèles viraux : " + ", ".join(f"{CATEGORIES[c]['nom']} {n}" for c, n in resume_veille(classees).items()))
    cases, deja = [], set()
    for i, (sem, cat, role, cta) in enumerate(SEQUENCE):
        jour = debut + timedelta(days=sem * 7 + JOURS_PUBLICATION[i % 2])
        src = _choisit(classees, cat, deja)
        if src:
            deja.add(src["cle"])
        cases.append({"jour": jour.isoformat(), "semaine": sem, "categorie": cat, "role": role, "cta": cta,
                      "titre": role, "angle": "", "source": src, "projet": None, "publie": False})
    log("Virall.ai écrit le sujet de chacun de tes 8 carrousels…")
    sujets = _sujets_demo(b, cases) if demo else _sujets_ia(esp, cfg, b, cases)
    for c, s in zip(cases, sujets):
        if s.get("titre"):
            c["titre"] = str(s["titre"]).strip()[:110]
        c["angle"] = str(s.get("angle") or "").strip()[:300]
    pid = datetime.now().strftime("%Y%m%d-") + uuid.uuid4().hex[:5]
    plan = {"id": pid, "cree": datetime.now().isoformat(timespec="minutes"), "debut": debut.isoformat(),
            "fin": (debut + timedelta(days=27)).isoformat(), "titre": f"Plan du {debut.day} {MOIS[debut.month - 1]}",
            "offre": b.get("produit") or "", "boutique": str(bid or ""), "cases": cases, "demo": demo}
    sauve(esp, plan)
    log("✅ Ton plan des 30 jours est prêt")
    return {"id": pid}


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _sujets_demo(b: dict, cases: list) -> list[dict]:
    off = b.get("produit") or "ton offre"
    return [{"titre": f"[démo] {CATEGORIES[c['categorie']]['nom']} · {c['role'].split(':')[0]}",
             "angle": f"[démo] Angle pensé pour amener doucement vers « {off} »."} for c in cases]


def _contexte_brief(b: dict) -> str:
    prods = b.get("produits") or []
    if len(prods) > 1:
        offre = (f"Offres du mois ({len(prods)} produits) : " + " / ".join(prods) + f" — lien ou mot-clé : {b.get('lien')}\n"
                 "Chaque carrousel de vente ou de preuve sociale met en avant UN seul de ces produits ; "
                 "répartis-les sur le mois sans en oublier, le premier de la liste en priorité.")
    else:
        offre = f"Offre du mois : {b.get('produit')} — prix : {b.get('prix')} — lien ou mot-clé : {b.get('lien')}"
    l = [offre,
         f"Transformation promise : {b.get('transformation')}",
         f"Cliente idéale : {b.get('cible')}",
         "Ses problèmes : " + " / ".join(b.get("problemes") or []),
         "Ses objections à l'achat : " + " / ".join(b.get("objections") or []),
         f"Histoire de la marque : {b.get('histoire')}"]
    if b.get("date_cle"):
        l.append(f"Date de lancement ou de clôture : {b['date_cle']}")
    if b.get("resultats"):
        l.append("Résultats réels : " + " / ".join(b["resultats"]))
    l.append(f"Témoignages réels fournis : {len(b.get('temoignages') or [])}")
    return "\n".join(l)


def _sujets_ia(esp: Espace, cfg: dict, b: dict, cases: list) -> list[dict]:
    from apprentissage import voix
    from ia import ecrit_plan30
    lignes = []
    for i, c in enumerate(cases):
        s = c.get("source") or {}
        lignes.append(f"Carrousel {i + 1} — {c['jour']} — semaine « {SEMAINES[c['semaine']]} » — {CATEGORIES[c['categorie']]['nom']}\n"
                      f"  Rôle : {c['role']}\n  Modèle viral (structure seulement) : @{s.get('compte') or '?'}, « {s.get('accroche') or ''} »")
    res = ecrit_plan30(cfg, voix(cfg, esp.racine, []), _contexte_brief(b), "\n\n".join(lignes), _consigne_voix(b))
    if res.get("erreur"):
        raise RuntimeError(res["erreur"])
    sujets = res.get("carrousels")
    if isinstance(sujets, str):
        try:
            sujets = json.loads(sujets)
        except ValueError:
            sujets = []
    sujets = [x for x in (sujets or []) if isinstance(x, dict)]
    return (sujets + [{}] * len(cases))[:len(cases)]


def _consigne_voix(b: dict) -> str:
    emo = {"aucun": "aucun emoji", "quelques": "quelques emojis, avec parcimonie", "beaucoup": "des emojis volontiers"}[b.get("emojis") or "quelques"]
    return f"Ton : {b.get('ton') or 'Complice'}. {'Vouvoiement' if b.get('tutoiement') == 'vous' else 'Tutoiement'} partout. {emo.capitalize()} dans la légende."


# ------------------------------------------------------------
#  Modifications d'une case
# ------------------------------------------------------------
def modifie_case(esp: Espace, pid: str, i: int, champs: dict) -> dict:
    plan = charge(esp, pid)
    c = plan["cases"][i]
    if champs.get("jour"):
        try:
            c["jour"] = date.fromisoformat(str(champs["jour"])[:10]).isoformat()
        except ValueError:
            pass
    for k, n in (("titre", 110), ("angle", 300), ("cta", 160)):
        if k in champs:
            c[k] = str(champs[k] or "").strip()[:n] or c[k]
    if "publie" in champs:
        c["publie"] = bool(champs["publie"])
    if champs.get("categorie") in CATEGORIES and champs["categorie"] != c["categorie"]:
        c["categorie"] = champs["categorie"]
        champs["autre_modele"] = True
    if champs.get("autre_modele"):
        classees = publications_classees(esp)
        deja = {x["source"]["cle"] for x in plan["cases"] if x.get("source")}
        src = _choisit(classees, c["categorie"], deja)
        if not src:  # tous déjà utilisés : on tourne dans la catégorie
            l = classees.get(c["categorie"]) or []
            k = next((j for j, f in enumerate(l) if c.get("source") and f["cle"] == c["source"]["cle"]), -1)
            src = l[(k + 1) % len(l)] if l else None
        if src:
            c["source"] = src
    sauve(esp, plan)  # l'ordre des cases ne change jamais (les projets du studio y sont reliés par leur rang) : l'écran trie par date
    return plan


def ordre_respecte(plan: dict) -> str | None:
    """Avertissement (sans bloquer) si la vente passe avant la première preuve sociale ou avant tout storytelling."""
    cats = [c["categorie"] for c in sorted(plan["cases"], key=lambda x: x["jour"])]
    if "vente" in cats:
        v = cats.index("vente")
        if "preuve" not in cats[:v]:
            return "Ta vente arrive avant toute preuve sociale : tes abonnées n'ont pas encore de raison de te faire confiance."
        if "storytelling" not in cats[:v]:
            return "Ta vente arrive avant ton histoire : raconte d'abord qui tu es."
    return None


# ------------------------------------------------------------
#  Fabrication des carrousels (écriture + images + slides prêtes)
# ------------------------------------------------------------
def consigne_case(plan: dict, i: int, b: dict) -> str:
    c = plan["cases"][i]
    cat = CATEGORIES[c["categorie"]]
    avant = [x for x in sorted(plan["cases"], key=lambda x: x["jour"]) if x["jour"] < c["jour"]]
    l = [f"PLACE DANS LE TUNNEL DE VENTE DU MOIS : carrousel {i + 1} sur {len(plan['cases'])}, semaine « {SEMAINES[c['semaine']]} », type {cat['nom']} ({cat['objectif']}).",
         f"SUJET DE CE CARROUSEL (prioritaire sur le sujet du modèle) : {c['titre']}" + (f" — {c['angle']}" if c.get("angle") else ""),
         f"Rôle : {c['role']}",
         f"Règles de ce type : {cat['regles']}",
         "Le modèle viral ne sert qu'à la STRUCTURE (type d'accroche, nombre de slides, rythme, progression) : son sujet, ses phrases et ses chiffres ne sont pas repris.",
         _contexte_brief(b),
         _consigne_voix(b)]
    if c["categorie"] == "preuve":
        tem = b.get("temoignages") or []
        if tem and b.get("accord_temoignages"):
            l.append("TÉMOIGNAGES RÉELS À CITER TELS QUELS (aucun autre) :\n" + "\n".join(f"- « {t} »" for t in tem))
        else:
            l.append("AUCUN témoignage utilisable : ne cite AUCUN avis, prénom ni chiffre de cliente. Montre les coulisses de la méthode à la place.")
    else:
        l.append("N'invente aucun avis, prénom ni chiffre de cliente.")
    if avant:
        l.append("FIL ROUGE — carrousels déjà publiés ce mois-ci (tu peux y faire référence en une phrase) : "
                 + " / ".join(f"{x['jour']} {x['titre']}" for x in avant[-3:]))
    if c["categorie"] == "vente" and b.get("date_cle"):
        l.append(f"Date limite à rappeler : {b['date_cle']}.")
    l.append(f"APPEL À L'ACTION DE LA DERNIÈRE SLIDE (remplace le mot-clé habituel) : {c['cta']}"
             + (f" — lien ou mot-clé : {b.get('lien')}" if c["categorie"] in ("vente",) or "mot-clé" in c["cta"] else ""))
    return "\n".join(l)


def _post_source(esp: Espace, src: dict) -> dict:
    an = moteur.charge(esp, src["analyse_id"])
    return next(p for p in an["posts"] if p.get("cle") == src["cle"])


def fabrique(esp: Espace, cfg: dict, pid: str, indices: list[int], demo: bool = False, filigrane: bool = False,
             apres_chaque=None) -> dict:
    """Tâche de fond : pour chaque case, crée le projet du studio, fait écrire les slides, choisit les images et dessine les slides."""
    b = brief(esp, cfg, charge(esp, pid).get("boutique") or None)
    faits = []
    for n, i in enumerate(indices):
        plan = charge(esp, pid)
        c = plan["cases"][i]
        cat = CATEGORIES[c["categorie"]]
        log(f"Carrousel {n + 1} sur {len(indices)} : « {c['titre']} »")
        sid = c.get("projet")
        try:
            if sid:
                studio.charge(esp, sid)
        except FileNotFoundError:
            sid = None
        if not sid:
            if not c.get("source"):
                raise RuntimeError(f"Aucun modèle viral pour le carrousel du {c['jour']} : relance une veille ou change son type.")
            post = _post_source(esp, c["source"])
            p = studio.cree(esp, cfg, post, "carrousel", c["source"]["analyse_id"], cat["style"])
            sid = p["id"]
        p = studio.charge(esp, sid)
        p.update(titre=c["titre"][:90], plan30={"plan": pid, "case": i, "categorie": c["categorie"]},
                 consigne_plan=consigne_case(plan, i, b), cta=c["cta"])
        studio.sauve(esp, p)
        studio.ecrit_textes(esp, cfg, sid, demo=demo)          # écrit les slides et choisit les images de la banque
        deja = bool(studio.charge(esp, sid).get("genere_le"))
        studio.genere(esp, sid, demo=demo, filigrane=filigrane)  # slides 1080 × 1350 + package ZIP
        plan = charge(esp, pid)
        plan["cases"][i]["projet"] = sid
        sauve(esp, plan)
        if apres_chaque and not deja:
            apres_chaque(sid)
        faits.append(sid)
    log(f"✅ {len(faits)} carrousel{'s' if len(faits) > 1 else ''} prêt{'s' if len(faits) > 1 else ''} à publier")
    return {"id": pid, "projets": faits}


def vue(esp: Espace, plan: dict) -> dict:
    """Plan enrichi pour l'écran : statut et vignette des carrousels fabriqués."""
    for c in plan["cases"]:
        c["statut"], c["vignette"], c["zip"] = "a_faire", "", None
        if c.get("projet"):
            try:
                p = studio.charge(esp, c["projet"])
                c["statut"] = "publie" if c.get("publie") else p.get("statut") or "brouillon"
                img = next((f for f in p.get("fichiers") or [] if f.endswith(".jpg")), "")
                c["vignette"] = f"/studio/{p['id']}/sortie/{img}" if img and p.get("statut") == "pret" else ""
                c["zip"] = f"/studio/{p['id']}/sortie/{p['zip']}?telecharger=1" if p.get("zip") else None
            except FileNotFoundError:
                c["projet"] = None
    return {**plan, "alerte": ordre_respecte(plan), "semaines": SEMAINES,
            "categories": {k: {"nom": v["nom"], "objectif": v["objectif"]} for k, v in CATEGORIES.items()}}
