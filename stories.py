"""
Studio de stories : séquences guidées par objectif (4 à 6 stories qui s'enchaînent) ou story seule à partir d'un modèle,
textes écrits par Virall.ai, images de la cliente ou de la banque, rendues en vidéos 9:16 animées (MP4).

Les projets sont des projets du Studio (`studio.py`, type « stories ») : mêmes dossiers, envois de photos, banque d'images,
liste « Mes créations ». Chaque story est une « slide » : titre, texte, photo/recherche (image), sticker conseillé.
Les stickers interactifs d'Instagram (sondage, question, lien…) ne peuvent pas être incrustés dans une vidéo : la story
leur laisse la place et le guide dit lequel poser et où.

Rendu : images composées avec Pillow, 30 images/s, envoyées à ffmpeg (aucune API, seulement le processeur).
"""
from __future__ import annotations

import colorsys
import json
import math
import random
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import studio
from espace import Espace
from modele import log
from ressources import sacrifiable

TAILLE = studio.VERTICAL          # 1080 × 1920
FPS = 30
MARGE = 96

# Stickers Instagram à poser dans l'application au moment de publier (ils ne s'incrustent pas dans une vidéo)
STICKERS = {
    "": "Aucun",
    "sondage": "Sondage",
    "question": "Boîte à questions",
    "quiz": "Quiz",
    "curseur": "Curseur emoji",
    "lien": "Lien",
    "compte_a_rebours": "Compte à rebours",
}

# Séquences guidées : le rôle de chaque story, dans l'ordre (le sticker conseillé est écrit par Virall.ai)
OBJECTIFS = {
    "vendre": {"nom": "Vendre un produit", "emoji": "🛍️", "aide": "De son problème à ton offre, avec le lien à la fin.",
               "roles": ["Accroche : le problème que vit ta cliente, avec un sondage « ça t'arrive aussi ? »",
                         "Ce que ça lui coûte au quotidien (empathie, concret)",
                         "La solution : ton produit, en une phrase claire",
                         "Ce qu'elle obtient : 2 ou 3 bénéfices concrets",
                         "L'objection principale, et ta réponse",
                         "Appel à l'action : le lien (sticker lien) ou un mot à t'envoyer en privé"]},
    "lancement": {"nom": "Lancer une nouveauté", "emoji": "🚀", "aide": "Créer l'attente puis révéler ton offre.",
                  "roles": ["Teaser : quelque chose arrive (compte à rebours)", "Pourquoi tu l'as créé (ton déclic)",
                            "La révélation : ce que c'est", "Pour qui c'est (et pour qui ce n'est pas)",
                            "Ce qu'il y a dedans / le prix / la date", "Appel à l'action : rappel ou lien"]},
    "coulisses": {"nom": "Montrer les coulisses", "emoji": "🎬", "aide": "Ta journée, ton travail, ce qu'on ne voit pas.",
                  "roles": ["Où tu es / ce que tu fais en ce moment", "Ce sur quoi tu travailles",
                            "Le détail que personne ne voit", "Ce que tu en as appris", "Une question à tes abonnées (boîte à questions)"]},
    "engagement": {"nom": "Faire réagir", "emoji": "💬", "aide": "Sondages et questions pour remonter dans leur fil.",
                   "roles": ["Une question simple de son quotidien (sondage)", "Un mini quiz sur ton sujet (quiz)",
                             "La bonne réponse expliquée", "Une astuce bonus", "Invitation à t'écrire (boîte à questions)"]},
    "preuve": {"nom": "Prouver que ça marche", "emoji": "⭐", "aide": "Un résultat de cliente, raconté (avis réels seulement).",
               "roles": ["Le résultat obtenu, en accroche", "Où elle en était avant", "Ce que vous avez fait ensemble",
                         "Ce qui a changé pour elle", "Appel à l'action : comment obtenir la même chose"]},
    "conseil": {"nom": "Donner un conseil", "emoji": "💡", "aide": "Une astuce utile qui montre ton expertise.",
                "roles": ["L'erreur que beaucoup font (accroche)", "Pourquoi c'est un problème", "L'astuce, étape 1",
                          "L'astuce, étape 2", "Récap en une phrase + curseur emoji « utile ? »", "Appel à l'action en privé"]},
}

# Stories seules
MODELES = {
    "annonce": {"nom": "Annonce", "emoji": "📣", "role": "Une annonce forte (nouveauté, date, événement)", "sticker": ""},
    "citation": {"nom": "Citation", "emoji": "✨", "role": "Une phrase inspirante dans ta voix, qui donne envie de partager", "sticker": ""},
    "question": {"nom": "Question", "emoji": "❓", "role": "Une question ouverte à tes abonnées", "sticker": "question"},
    "sondage": {"nom": "Sondage", "emoji": "📊", "role": "Un sondage à deux réponses sur son quotidien", "sticker": "sondage"},
    "conseil": {"nom": "Conseil express", "emoji": "💡", "role": "Une astuce actionnable en une story", "sticker": "curseur"},
    "avant_apres": {"nom": "Avant / après", "emoji": "🔁", "role": "Avant / après (vrai résultat), en deux temps", "sticker": ""},
    "rebours": {"nom": "Compte à rebours", "emoji": "⏳", "role": "Une date importante qui approche", "sticker": "compte_a_rebours"},
    "produit": {"nom": "Mon produit", "emoji": "🛍️", "role": "Présenter un produit et donner le lien", "sticker": "lien"},
}

# Effets visuels
EFFETS = {
    "doux": {"nom": "Doux", "aide": "Zoom lent, texte qui apparaît en fondu"},
    "dynamique": {"nom": "Dynamique", "aide": "Texte qui glisse, flash d'entrée"},
    "paillettes": {"nom": "Paillettes", "aide": "Étincelles qui scintillent"},
    "neon": {"nom": "Néon", "aide": "Texte lumineux qui grésille"},
    "surligneur": {"nom": "Surligneur", "aide": "Le titre se surligne"},
    "machine": {"nom": "Machine à écrire", "aide": "Le titre s'écrit lettre par lettre"},
    "grain": {"nom": "Film", "aide": "Grain de pellicule et lumière chaude"},
}

# Couleurs : (fond haut, fond bas, titre, texte, accent)
PALETTES = {
    "nuit": ("#1B1026", "#3A1C4A", "#FFFFFF", "#E9DDF2", "#FF4F79"),
    "rose": ("#FFD6E0", "#FF8FAB", "#3B0A1E", "#5A1A33", "#FFFFFF"),
    "creme": ("#F7F1E8", "#E8D9C4", "#2B2118", "#5B4A3A", "#C8763B"),
    "ocean": ("#0E2A47", "#1F6F8B", "#FFFFFF", "#D7ECF5", "#FFD166"),
    "foret": ("#14281D", "#2F5D3A", "#F4F1DE", "#DCE6D2", "#E9C46A"),
    "soleil": ("#FFB347", "#FF6F61", "#2B0F0A", "#3E1C14", "#FFFFFF"),
    "noir": ("#0B0B0F", "#1E1E26", "#FFFFFF", "#CFCFD6", "#B9FF66"),
}
NOMS_PALETTES = {"nuit": "Nuit", "rose": "Rose", "creme": "Crème", "ocean": "Océan", "foret": "Forêt", "soleil": "Soleil",
                 "noir": "Noir", "marque": "Ma marque"}


# Réglages du rendu, modifiables par les consignes données à Virall.ai (retouche) : valeurs permises et valeurs par défaut
REGLAGES = {
    "taille_titre": (1.0, 0.6, 1.5),      # facteur sur la taille du titre
    "taille_texte": (1.0, 0.7, 1.5),
    "position": ("centre", ("haut", "centre", "bas")),
    "alignement": ("centre", ("centre", "gauche")),
    "majuscules": (None, (None, True, False)),   # None = selon la typo
    "duree": (0.0, -3.0, 6.0),             # secondes ajoutées à la durée calculée
    "vitesse": ("normale", ("lente", "normale", "rapide")),
    "intensite": ("normale", ("douce", "normale", "forte")),
    "voile": (92, 0, 200),                 # assombrissement des photos (lisibilité du texte)
    "signature": (False, (False, True)),   # @pseudo discret en bas
    "ombre": (True, (True, False)),
}
VITESSES = {"lente": 1.6, "normale": 1.0, "rapide": 0.6}
INTENSITES = {"douce": 0.6, "normale": 1.0, "forte": 1.7}


def reglages(p: dict) -> dict:
    """Réglages du projet, nettoyés (valeurs inconnues ou hors bornes ramenées aux valeurs permises)."""
    brut, res = p.get("reglages") or {}, {}
    for k, regle in REGLAGES.items():
        v = brut.get(k, regle[0])
        if len(regle) == 3:
            try:
                v = max(regle[1], min(regle[2], float(v)))
            except (TypeError, ValueError):
                v = regle[0]
        elif v not in regle[1]:
            v = regle[0]
        res[k] = v
    return res


def _rgb(h: str) -> tuple:
    return studio._rgb(h)


def _clair(c: tuple) -> bool:
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) > 160


def couleurs_story(pal: dict, photo: bool, effet: str) -> dict:
    """Sur une photo (voilée de sombre), le texte passe en clair ; surligné, il prend la couleur qui contraste avec le surligneur."""
    pal = dict(pal)
    if photo:
        pal["titre"], pal["texte"] = (255, 255, 255), (238, 234, 242)
    pal["mot"] = pal["accent"]
    if effet == "surligneur":
        pal["titre"] = (24, 18, 28) if _clair(pal["accent"]) else (255, 255, 255)
        pal["mot"] = pal["haut"] if _clair(pal["haut"]) != _clair(pal["accent"]) else ((255, 255, 255) if pal["titre"] != (255, 255, 255) else (24, 18, 28))
    return pal


def palette_de(p: dict, cfg: dict | None = None) -> dict:
    nom = p.get("palette") or "nuit"
    if nom == "marque" and p.get("couleurs_marque"):
        m = p["couleurs_marque"]
        f = _rgb(m["fond"])
        bas = tuple(max(0, int(c * 0.78)) for c in f)  # même couleur, un peu plus sombre en bas
        return {"haut": f, "bas": bas, "titre": _rgb(m["texte"]), "texte": _rgb(m["texte"]), "accent": _rgb(m["accent"])}
    h, b, t, x, a = PALETTES.get(nom, PALETTES["nuit"])
    return {"haut": _rgb(h), "bas": _rgb(b), "titre": _rgb(t), "texte": _rgb(x), "accent": _rgb(a)}


# ------------------------------------------------------------
#  Projet
# ------------------------------------------------------------
def options(cfg: dict) -> dict:
    return {"objectifs": [{"id": k, **{c: v[c] for c in ("nom", "emoji", "aide")}, "n": len(v["roles"])} for k, v in OBJECTIFS.items()],
            "modeles": [{"id": k, "nom": v["nom"], "emoji": v["emoji"], "aide": v["role"]} for k, v in MODELES.items()],
            "effets": [{"id": k, **v} for k, v in EFFETS.items()],
            "palettes": [{"id": k, "nom": NOMS_PALETTES[k], "couleurs": list(v)} for k, v in PALETTES.items()]
                        + ([{"id": "marque", "nom": "Ma marque", "couleurs": [m["fond"], m["fond"], m["texte"], m["texte"], m["accent"]]}]
                           if (m := studio.couleurs_marque(cfg)) else []),
            "stickers": STICKERS}


def _court(t: str, n: int) -> str:
    """Coupe à n caractères sans couper un mot."""
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def cree(esp: Espace, cfg: dict, c: dict) -> dict:
    """Nouveau projet de stories (textes provisoires, réécrits ensuite par Virall.ai)."""
    mode = "sequence" if c.get("mode") == "sequence" else "unique"
    if mode == "sequence":
        obj = OBJECTIFS.get(c.get("objectif")) or OBJECTIFS["vendre"]
        roles, titre = obj["roles"], obj["nom"]
        def sticker_du_role(r):
            mots = set(re.findall(r"[a-zà-ÿ]+", r.lower()))
            return ("lien" if "lien" in mots else "sondage" if "sondage" in mots else "question" if "questions" in mots
                    else "quiz" if "quiz" in mots else "compte_a_rebours" if "rebours" in mots else "curseur" if "curseur" in mots else "")
        stickers = [sticker_du_role(r) for r in roles]
    else:
        m = MODELES.get(c.get("modele")) or MODELES["annonce"]
        roles, titre, stickers = [m["role"]], m["nom"], [m["sticker"]]
    sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    sujet = str(c.get("sujet") or "").strip()[:300]
    p = {"id": sid, "cree": datetime.now().isoformat(timespec="minutes"), "type": "stories", "mode": mode,
         "objectif": c.get("objectif") if mode == "sequence" else None, "modele": c.get("modele") if mode == "unique" else None,
         "titre": f"Stories · {titre}" + (f" · {_court(sujet, 42)}" if sujet else ""), "sujet": sujet,
         "produit": c.get("produit") or None, "effet": c.get("effet") if c.get("effet") in EFFETS else "doux",
         "palette": c.get("palette") if c.get("palette") in (*PALETTES, "marque") else "nuit",
         "couleurs_marque": studio.couleurs_marque(cfg), "typo": c.get("typo") if c.get("typo") in studio.TYPOS else "moderne",
         "photos": "miennes" if c.get("photos") == "miennes" else "banque",
         "slides": [{"role": r, "titre": "", "texte": "", "photo": "", "recherche": "", "sticker": s, "sticker_texte": ""}
                    for r, s in zip(roles, stickers)],
         "images": [], "video": None, "statut": "brouillon", "erreur": None, "miniature": None, "fichiers": [], "zip": None,
         "analyse_id": None, "cle": None, "compte": None, "pseudo": (cfg.get("mon_compte") or {}).get("instagram") or ""}
    studio.sauve(esp, p)
    return p


def modifie(esp: Espace, sid: str, champs: dict) -> dict:
    p = studio.charge(esp, sid)
    for k in ("effet", "palette", "typo"):
        if k in champs and (champs[k] in EFFETS if k == "effet" else champs[k] in (*PALETTES, "marque") if k == "palette" else champs[k] in studio.TYPOS):
            p[k] = champs[k]
    if isinstance(champs.get("slides"), list):
        anciennes = p["slides"]
        p["slides"] = [{**(anciennes[i] if i < len(anciennes) else {}),
                        "titre": str(s.get("titre") or "")[:140], "texte": str(s.get("texte") or "")[:280],
                        "sticker": s.get("sticker") if s.get("sticker") in STICKERS else "",
                        "sticker_texte": str(s.get("sticker_texte") or "")[:80]}
                       for i, s in enumerate(champs["slides"][:8]) if isinstance(s, dict)]
    p["statut"] = "brouillon" if p.get("statut") == "pret" else p.get("statut")
    studio.sauve(esp, p)
    return p


def ecrit(esp: Espace, cfg: dict, sid: str, contexte: str = "", demo: bool = False) -> dict:
    """Virall.ai écrit le texte de chaque story (et l'image à chercher, le sticker), puis la banque propose des images."""
    p = studio.charge(esp, sid)
    log("Virall.ai écrit tes stories…")
    if demo:
        res = {"stories": [{"titre": f"[démo] {s['role'].split(':')[0][:48]}", "texte": "[démo] Une phrase courte, dans ton ton.",
                            "photo": "[démo] Toi au bureau, lumière du matin", "recherche": "woman laptop morning light",
                            "sticker": s.get("sticker", ""), "sticker_texte": "Ça t'arrive aussi ?" if s.get("sticker") == "sondage" else ""}
                           for s in p["slides"]]}
    else:
        from apprentissage import voix
        from ia import ecrit_stories
        roles = "\n".join(f"Story {i + 1} : {s['role']}" + (f" (sticker conseillé : {STICKERS.get(s.get('sticker'), '')})" if s.get("sticker") else "")
                          for i, s in enumerate(p["slides"]))
        res = ecrit_stories(cfg, voix(cfg, esp.racine, []), roles, p.get("sujet") or "", contexte)
    stories = [x for x in (res.get("stories") or []) if isinstance(x, dict)]
    if not stories:
        raise RuntimeError("Virall.ai n'a pas proposé de texte : réessaie dans un instant.")
    p = studio.charge(esp, sid)
    for s, x in zip(p["slides"], stories):
        s.update({"titre": studio.propre(x.get("titre") or "")[:140], "texte": studio.propre(x.get("texte") or "")[:280],
                  "photo": (x.get("photo") or "").strip()[:200], "recherche": (x.get("recherche") or "").strip()[:120],
                  "sticker": x.get("sticker") if x.get("sticker") in STICKERS else s.get("sticker", ""),
                  "sticker_texte": (x.get("sticker_texte") or "").strip()[:80]})
    studio.sauve(esp, p)
    log(f"✅ {len(p['slides'])} stories écrites")
    if p.get("photos") == "banque":
        studio.remplit_banque(esp, sid, demo=demo, toutes=True)
    return {"id": sid}


def _etat_texte(p: dict) -> str:
    """Résumé lisible de l'état des stories, donné à Virall.ai pour la retouche."""
    reg = reglages(p)
    lignes = [f"Effet : {p.get('effet')} (possibles : {', '.join(EFFETS)}) · couleurs : {p.get('palette')} (possibles : {', '.join([*PALETTES, 'marque'])})",
              f"Police : {p.get('typo')} (possibles : {', '.join(studio.TYPOS)})",
              "Réglages : " + ", ".join(f"{k} = {v}" for k, v in reg.items()), ""]
    for i, s in enumerate(p["slides"]):
        lignes.append(f"Story {i + 1} ({s.get('role', '')}) : titre « {s.get('titre', '')} » · texte « {s.get('texte', '')} »"
                      + (f" · mot en couleur « {s['mot']} »" if s.get("mot") else "")
                      + (f" · effet propre {s['effet']}" if s.get("effet") else "")
                      + (f" · sticker {s['sticker']} « {s.get('sticker_texte', '')} »" if s.get("sticker") else "")
                      + f" · durée {duree_story(s, p)} s")
    return "\n".join(lignes)


def applique_retouche(p: dict, r: dict) -> dict:
    """Applique les changements renvoyés par Virall.ai (valeurs vérifiées une à une)."""
    if r.get("effet") in EFFETS:
        p["effet"] = r["effet"]
    if r.get("palette") in (*PALETTES, "marque") and (r["palette"] != "marque" or p.get("couleurs_marque")):
        p["palette"] = r["palette"]
    if r.get("typo") in studio.TYPOS:
        p["typo"] = r["typo"]
    if isinstance(r.get("reglages"), dict):
        p["reglages"] = reglages({"reglages": {**(p.get("reglages") or {}), **r["reglages"]}})
    retirer = set()
    for c in r.get("stories") or []:
        try:
            i = int(c.get("numero")) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= i < len(p["slides"])):
            continue
        s = p["slides"][i]
        if c.get("supprimer"):
            retirer.add(i)
            continue
        for k, n in (("titre", 140), ("texte", 280), ("mot", 60), ("sticker_texte", 80)):
            if isinstance(c.get(k), str):
                s[k] = studio.propre(c[k])[:n] if k in ("titre", "texte") else c[k].strip()[:n]
        if "effet" in c and (c["effet"] in EFFETS or c["effet"] == ""):
            s["effet"] = c["effet"]
        if "sticker" in c and c["sticker"] in STICKERS:
            s["sticker"] = c["sticker"]
        if "duree" in c:
            try:
                s["duree"] = max(3.0, min(15.0, float(c["duree"]))) if float(c["duree"]) else None
            except (TypeError, ValueError):
                pass
    if retirer and len(retirer) < len(p["slides"]):
        garde = [i for i in range(len(p["slides"])) if i not in retirer]
        p["slides"] = [p["slides"][i] for i in garde]  # chaque story garde son image (champ « image »)
    for a in (r.get("ajouter") or [])[: max(0, 8 - len(p["slides"]))]:
        if isinstance(a, dict) and a.get("titre"):
            p["slides"].append({"role": "Story ajoutée", "titre": studio.propre(a["titre"])[:140], "texte": studio.propre(a.get("texte") or "")[:280],
                                "photo": "", "recherche": (a.get("recherche") or "")[:120],
                                "sticker": a.get("sticker") if a.get("sticker") in STICKERS else "", "sticker_texte": ""})
    return p


def retouche(esp: Espace, cfg: dict, sid: str, consigne: str, demo: bool = False) -> dict:
    """Consigne libre de la cliente (« titre plus gros », « plus de paillettes », « réécris la story 3 »…) appliquée par Virall.ai."""
    p = studio.charge(esp, sid)
    log("Virall.ai applique ta consigne…")
    if demo:
        c = consigne.lower()
        r = {"reponse": "[démo] C'est fait.", "reglages": {}}
        if "gros" in c or "grand" in c:
            r["reglages"]["taille_titre"] = 1.3
        if "petit" in c:
            r["reglages"]["taille_titre"] = 0.8
        if "haut" in c:
            r["reglages"]["position"] = "haut"
        if "bas" in c:
            r["reglages"]["position"] = "bas"
        if "lent" in c:
            r["reglages"]["vitesse"] = "lente"
        if "@" in c or "signature" in c:
            r["reglages"]["signature"] = True
        for e in EFFETS:
            if e in c:
                r["effet"] = e
        for pal in PALETTES:
            if pal in c:
                r["palette"] = pal
    else:
        from ia import retouche_stories
        r = retouche_stories(cfg, _etat_texte(p), consigne)
    p = applique_retouche(studio.charge(esp, sid), r)
    if not p.get("pseudo"):
        p["pseudo"] = (cfg.get("mon_compte") or {}).get("instagram") or ""
    if reglages(p)["signature"] and not p.get("pseudo"):
        r["reponse"] = ((r.get("reponse") or "") + " Pour afficher ton @, ajoute ton compte Instagram dans Réglages → Mon profil.").strip()
    p.setdefault("retouches", []).append({"consigne": consigne[:500], "reponse": (r.get("reponse") or "")[:400],
                                          "le": datetime.now().isoformat(timespec="minutes")})
    p["retouches"] = p["retouches"][-20:]
    if p.get("statut") == "pret":
        p["statut"] = "brouillon"
    studio.sauve(esp, p)
    log("✅ " + ((r.get("reponse") or "Retouche appliquée")[:200]))
    return {"id": sid, "reponse": r.get("reponse") or ""}


# ------------------------------------------------------------
#  Rendu
# ------------------------------------------------------------
def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_rebond(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def duree_story(s: dict, p: dict | None = None) -> float:
    """5 à 9 s : le temps de lire (plus ou moins selon les réglages et la story)."""
    mots = len(((s.get("titre") or "") + " " + (s.get("texte") or "")).split())
    base = min(9.0, max(5.0, 2.5 + mots * 0.32))
    bonus = reglages(p)["duree"] if p else 0.0
    if s.get("duree"):
        return round(max(3.0, min(15.0, float(s["duree"]))), 1)
    return round(max(3.0, min(15.0, base + bonus)), 1)


def _fond(p: dict, pal: dict, image: Path | None):  # noqa: C901
    """Fond agrandi de 12 % (pour le zoom lent) : la photo, ou un dégradé des couleurs choisies."""
    from PIL import Image
    w, h = TAILLE
    W, H = int(w * 1.12), int(h * 1.12)
    if image and Path(image).is_file():
        im = studio._couvre(Image.open(image).convert("RGB"), (W, H)).convert("RGBA")
        # voile sombre + dégradé : le texte reste lisible sur n'importe quelle photo
        im.alpha_composite(Image.new("RGBA", (W, H), (10, 6, 14, int(reglages(p)["voile"]))))
        im.alpha_composite(studio._degrade((W, H), 0.45, 170))
        return im.convert("RGB"), True
    bande = Image.new("RGB", (1, 256))
    for y in range(256):
        k = y / 255
        bande.putpixel((0, y), tuple(int(pal["haut"][i] * (1 - k) + pal["bas"][i] * k) for i in range(3)))
    return bande.resize((W, H), Image.BILINEAR), False


def _calque_texte(s: dict, pal: dict, typo: str, avec_sticker: bool, n_lettres: int | None = None, reg: dict | None = None,
                  pseudo: str = ""):
    """Calque RGBA du titre + texte. n_lettres : titre tronqué (effet machine à écrire)."""
    from PIL import Image, ImageDraw
    reg = reg or reglages({})
    w, h = TAILLE
    t = studio._typo(typo)
    calque = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    largeur = w - 2 * MARGE
    titre = studio.insecables(studio.propre(s.get("titre") or ""))
    maj = t["maj"] if reg["majuscules"] is None else reg["majuscules"]
    if maj:
        titre = titre.upper()
    texte = studio.propre(s.get("texte") or "")
    mot = studio.propre(s.get("mot") or "").strip()
    zone_haut, zone_bas = 260, (1180 if avec_sticker else 1600)  # au-dessus de la place laissée au sticker
    pol_t, lignes_t, h_t, taille = studio._ajuste(d, titre, t["police"], largeur, int((zone_bas - zone_haut) * 0.62),
                                                  int(118 * t["facteur"] * reg["taille_titre"]), int(54 * min(1.0, reg["taille_titre"])),
                                                  t.get("interligne", 1.12))
    pol_x, lignes_x, h_x, _ = (studio._ajuste(d, texte, t["texte"], largeur, int((zone_bas - zone_haut) * 0.3), int(50 * reg["taille_texte"]),
                                              int(34 * min(1.0, reg["taille_texte"])), 1.3) if texte else (None, [], 0, 0))
    total = h_t + (40 + h_x if texte else 0)
    libre = max(0, (zone_bas - zone_haut) - total)
    y = zone_haut + {"haut": 0, "centre": libre // 2, "bas": libre}[reg["position"]]
    gauche = reg["alignement"] == "gauche"
    ombre = reg["ombre"]
    boites = []
    restant = n_lettres
    for ligne in lignes_t:
        if restant is not None:
            if restant <= 0:
                break
            ligne_visible = ligne[:restant]
            restant -= len(ligne) + 1
        else:
            ligne_visible = ligne
        lw = d.textlength(ligne, font=pol_t)
        x = MARGE if gauche else (w - lw) / 2
        boites.append((x, y, x + lw, y + taille))
        if ombre:
            d.text((x + 3, y + 4), ligne_visible, font=pol_t, fill=(0, 0, 0, 90))  # ombre douce
        d.text((x, y), ligne_visible, font=pol_t, fill=pal["titre"] + (255,))
        # Mot mis en valeur : redessiné dans la couleur d'accent
        if mot and mot.lower() in ligne_visible.lower():
            i0 = ligne_visible.lower().index(mot.lower())
            x0 = x + d.textlength(ligne_visible[:i0], font=pol_t)
            d.text((x0, y), ligne_visible[i0:i0 + len(mot)], font=pol_t, fill=pal.get("mot", pal["accent"]) + (255,))
        y += int(taille * t.get("interligne", 1.12))
    if texte and (n_lettres is None or restant is None or restant > 0):
        y += 40
        for ligne in lignes_x:
            lw = d.textlength(ligne, font=pol_x)
            d.text((MARGE if gauche else (w - lw) / 2, y), ligne, font=pol_x, fill=pal["texte"] + (255,))
            y += int(pol_x.size * 1.3)
    if reg["signature"] and pseudo:
        f = studio._police("Medium", 38)
        sig = "@" + pseudo.lstrip("@")
        d.text(((w - d.textlength(sig, font=f)) / 2, h - 150), sig, font=f, fill=pal["texte"] + (200,))
    return calque, boites


def _etincelles(n: int, graine: int):
    r = random.Random(graine)
    w, h = TAILLE
    return [(r.uniform(40, w - 40), r.uniform(120, h - 160), r.uniform(4, 13), r.uniform(0, 2 * math.pi), r.uniform(1.5, 3.5))
            for _ in range(n)]


def _grain(graine: int):
    """Quelques textures de grain pré-calculées (rapide)."""
    import numpy as np
    from PIL import Image
    r = np.random.default_rng(graine)
    w, h = TAILLE[0] // 2, TAILLE[1] // 2
    res = []
    for _ in range(6):
        a = (r.random((h // 2, w // 2)) * 30).astype("uint8")
        im = Image.fromarray(np.dstack([np.full((h // 2, w // 2), 128, "uint8")] * 3 + [a]), "RGBA").resize(TAILLE)
        res.append(im)
    return res


def images_story(p: dict, s: dict, image: Path | None, graine: int = 0):
    """Générateur des images (PIL RGB) d'une story animée, et sa durée."""
    from PIL import Image, ImageDraw, ImageFilter
    pal = palette_de(p)
    reg = reglages(p)
    eff = s.get("effet") if s.get("effet") in EFFETS else (p.get("effet") or "doux")  # effet propre à la story, sinon celui du projet
    vit, inten = VITESSES[reg["vitesse"]], INTENSITES[reg["intensite"]]
    duree = duree_story(s, p)
    n = int(duree * FPS)
    w, h = TAILLE
    fond, photo = _fond(p, pal, image)
    pal = couleurs_story(pal, photo, eff)
    avec_sticker = bool(s.get("sticker"))
    pseudo = p.get("pseudo") or ""
    calque, boites = _calque_texte(s, pal, p.get("typo") or "moderne", avec_sticker, reg=reg, pseudo=pseudo)
    lettres = len(studio.propre(s.get("titre") or ""))
    lueur = None
    if eff == "neon":
        masque = calque.split()[3].filter(ImageFilter.GaussianBlur(18))
        lueur = Image.new("RGBA", (w, h), pal["accent"] + (0,))
        lueur.putalpha(masque)
    etinc = _etincelles(int(70 * inten), graine) if eff == "paillettes" else []
    grains = _grain(graine) if eff == "grain" else []
    if grains:  # lumière chaude floutée une seule fois, déplacée ensuite
        fuite = Image.new("RGBA", (1100, 1300), (0, 0, 0, 0))
        ImageDraw.Draw(fuite).ellipse((150, 150, 950, 1150), fill=(255, 150, 60, 70))
        fuite = fuite.filter(ImageFilter.GaussianBlur(110))
    cache_machine = {}
    for k in range(n):
        t = k / FPS
        # Fond : zoom lent (Ken Burns), légèrement décentré pour donner du mouvement
        z = 1.0 + min(0.12, 0.10 * inten) * (t / duree) if photo else 1.0 + 0.04 * inten * (t / duree)
        W, H = fond.size
        cw, ch = int(W / 1.12 / z * 1.0), int(H / 1.12 / z * 1.0)
        cx = (W - cw) / 2 + (W - cw) * 0.15 * math.sin(t / duree * math.pi / 2)
        cy = (H - ch) / 2
        im = fond.crop((int(cx), int(cy), int(cx) + cw, int(cy) + ch)).resize(TAILLE, Image.BILINEAR).convert("RGBA")
        # Texte selon l'effet
        ta = t / vit  # temps « ralenti » ou « accéléré » des animations d'entrée
        apparition = _ease((ta - 0.25) / 0.8)
        dx = dy = 0
        alpha = apparition
        couche = calque
        if eff == "doux":
            dy = int(40 * (1 - apparition))
        elif eff == "dynamique":
            alpha = 1.0 if ta > 0.2 else 0.0
            dx = int(-w * (1 - _ease_rebond((ta - 0.2) / 0.6))) if ta < 0.8 else 0
        elif eff == "machine":
            nl = min(lettres, int(max(0.0, ta - 0.3) * 22))
            if nl < lettres:
                if nl not in cache_machine:
                    cache_machine = {nl: _calque_texte(s, pal, p.get("typo") or "moderne", avec_sticker, n_lettres=nl, reg=reg, pseudo=pseudo)[0]}
                couche = cache_machine[nl]
            alpha = 1.0
        elif eff == "neon":
            alpha = 0.0 if ta < 0.3 else (0.25 if 0.45 < ta < 0.55 or 0.7 < ta < 0.75 else 1.0)
        elif eff == "surligneur":
            prog = _ease((ta - 0.2) / 0.9)
            d = ImageDraw.Draw(im)
            for (x0, y0, x1, y1) in boites:
                d.rectangle((x0 - 18, y0 + (y1 - y0) * 0.18, x0 - 18 + (x1 - x0 + 36) * prog, y1 + 10), fill=pal["accent"] + (235,))
            alpha = _ease((ta - 0.5) / 0.5)
        # Lueur néon (pulsation)
        if lueur is not None and alpha > 0:
            l = lueur.copy()
            l.putalpha(l.split()[3].point(lambda v: int(v * (0.75 + 0.25 * math.sin(t * 6)))))
            im.alpha_composite(l)
        if alpha > 0:
            if alpha < 1:
                c = couche.copy()
                c.putalpha(c.split()[3].point(lambda v, a=alpha: int(v * a)))
            else:
                c = couche
            im.alpha_composite(c, (dx, dy)) if (dx or dy) else im.alpha_composite(c)
        if eff == "dynamique" and t < 0.35:  # flash d'entrée
            im.alpha_composite(Image.new("RGBA", TAILLE, (255, 255, 255, int(min(255, 200 * inten) * (1 - t / 0.35)))))
        if etinc:
            d = ImageDraw.Draw(im)
            for (x, y, r, ph, v) in etinc:
                a = max(0.0, math.sin(t * v + ph))
                if a > 0.15:
                    rr = r * a
                    col = (255, 255, 255, int(230 * a))
                    d.line((x - rr * 2.2, y, x + rr * 2.2, y), fill=col, width=2)
                    d.line((x, y - rr * 2.2, x, y + rr * 2.2), fill=col, width=2)
                    d.ellipse((x - rr / 2, y - rr / 2, x + rr / 2, y + rr / 2), fill=col)
        if grains:
            im.alpha_composite(grains[(k // 3) % len(grains)])  # grain qui change toutes les 3 images (vidéo légère)
            lx = int((t / duree) * w * 1.6 - w * 0.3) - 550  # lumière chaude qui traverse l'image
            im.alpha_composite(fuite, (max(-1100, min(w, lx)), -350)) if -1100 < lx < w else None
        if t > duree - 0.25:  # fondu de sortie
            im.alpha_composite(Image.new("RGBA", TAILLE, (0, 0, 0, int(255 * (t - (duree - 0.25)) / 0.25 * 0.6))))
        yield im.convert("RGB")
    return duree


def apercu(esp: Espace, sid: str, i: int) -> bytes:
    """Image fixe de la story i telle qu'elle apparaît une fois l'animation terminée (avec la place du sticker)."""
    import io

    from PIL import ImageDraw
    p = studio.charge(esp, sid)
    if not (0 <= i < len(p["slides"])):
        raise IndexError(i)
    d = studio.dossier(esp, sid)
    images = studio.attribue(p["slides"], [d / "sources" / x for x in p["images"]])
    s = p["slides"][i]
    pal = palette_de(p)
    fond, photo = _fond(p, pal, images[i])
    eff = s.get("effet") if s.get("effet") in EFFETS else (p.get("effet") or "doux")
    pal = couleurs_story(pal, photo, eff)
    w, h = TAILLE
    W, H = fond.size
    im = fond.crop(((W - w) // 2, (H - h) // 2, (W - w) // 2 + w, (H - h) // 2 + h)).convert("RGBA")
    calque, boites = _calque_texte(s, pal, p.get("typo") or "moderne", bool(s.get("sticker")), reg=reglages(p), pseudo=p.get("pseudo") or "")
    if eff == "surligneur":
        dd = ImageDraw.Draw(im)
        for (x0, y0, x1, y1) in boites:
            dd.rectangle((x0 - 18, y0 + (y1 - y0) * 0.18, x1 + 18, y1 + 10), fill=pal["accent"] + (235,))
    im.alpha_composite(calque)
    if s.get("sticker"):  # place du sticker (aperçu seulement : il se pose dans Instagram)
        dd = ImageDraw.Draw(im)
        dd.rounded_rectangle((200, 1260, w - 200, 1520), radius=40, outline=(255, 255, 255, 200), width=5)
        f = studio._police("Medium", 44)
        lib = f"Sticker « {STICKERS[s['sticker']]} »"
        dd.text(((w - dd.textlength(lib, font=f)) / 2, 1360), lib, font=f, fill=(255, 255, 255, 230))
    buf = io.BytesIO()
    im.convert("RGB").resize((w // 2, h // 2)).save(buf, "JPEG", quality=82)
    return buf.getvalue()


def _encode(frames, sortie: Path, duree: float):
    w, h = TAILLE
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS),
           "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{duree:.2f}", "-map", "0:v", "-map", "1:a",
           "-c:a", "aac", "-b:a", "64k", *studio.ENCODAGE, str(sortie)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=sacrifiable)
    try:
        for im in frames:
            pr.stdin.write(im.tobytes())
        pr.stdin.close()
        err = pr.stderr.read().decode(errors="replace")
        if pr.wait(timeout=600) != 0:
            print(f"[stories] ffmpeg : {err[-1500:]}", flush=True)
            raise RuntimeError("La fabrication de la vidéo a échoué : réessaie dans un instant.")
    except BrokenPipeError:
        raise RuntimeError("La fabrication de la vidéo a été interrompue par le serveur (mémoire).") from None


def genere(esp: Espace, sid: str, demo: bool = False, filigrane: bool = False) -> dict:
    p = studio.charge(esp, sid)
    d = studio.dossier(esp, sid)
    sortie = d / "sortie"
    shutil.rmtree(sortie, ignore_errors=True)
    sortie.mkdir()
    p.update(statut="en_cours", erreur=None)
    studio.sauve(esp, p)
    try:
        if not p["slides"]:
            raise ValueError("Ajoute au moins une story.")
        images = studio.attribue(p["slides"], [d / "sources" / x for x in p["images"]])
        fichiers = []
        for i, s in enumerate(p["slides"]):
            log(f"Je fabrique la story {i + 1}/{len(p['slides'])}…")
            nom = f"story_{i + 1:02d}.mp4"
            gen = images_story(p, s, images[i], graine=i + 7)
            _encode(gen, sortie / nom, duree_story(s, p))
            fichiers.append(nom)
            if i == 0:  # vignette pour « Mes créations »
                (sortie / "vignette.jpg").write_bytes(apercu(esp, sid, 0))
        log("Je prépare ton package…")
        p = studio.charge(esp, sid)
        p.update(fichiers=fichiers, zip=package(p, sortie, fichiers), statut="pret", miniature="vignette.jpg",
                 genere_le=datetime.now().isoformat(timespec="minutes"))
        studio.sauve(esp, p)
        log("✅ Stories prêtes")
        return {"id": sid}
    except Exception as e:
        p = studio.charge(esp, sid)
        p.update(statut="erreur", erreur=str(e)[:300])
        studio.sauve(esp, p)
        raise


def guide(p: dict) -> list[str]:
    """Où poser chaque sticker, story par story."""
    res = []
    for i, s in enumerate(p["slides"]):
        st = s.get("sticker")
        if st:
            res.append(f"Story {i + 1} : ajoute le sticker « {STICKERS[st]} » dans la zone libre en bas"
                       + (f" — « {s['sticker_texte']} »" if s.get("sticker_texte") else "") + ".")
    return res


def package(p: dict, sortie: Path, fichiers: list[str]) -> str:
    nom = f"stories_{p['id'][:15]}.zip"
    lisez = ["TES STORIES PRÊTES À PUBLIER", "=" * 28, "",
             "1. Ouvre Instagram > Story, et publie les vidéos dans l'ordre (story_01, story_02…).",
             "2. Ajoute les stickers indiqués ci-dessous dans la zone laissée libre (ils ne peuvent pas être intégrés dans la vidéo) :",
             *([f"   - {x}" for x in guide(p)] or ["   (aucun sticker pour ces stories)"]),
             "3. Si tu veux de la musique, ajoute-la dans Instagram (sticker Musique) : le son reste ainsi à jour et autorisé.", ""]
    with zipfile.ZipFile(sortie / nom, "w", zipfile.ZIP_DEFLATED) as z:
        for f in fichiers:
            z.write(sortie / f, f)
        z.writestr("LISEZ-MOI.txt", "\n".join(lisez))
        z.writestr("textes.txt", "\n\n".join(f"Story {i + 1}\n{s.get('titre', '')}\n{s.get('texte', '')}" for i, s in enumerate(p["slides"])))
    return nom
