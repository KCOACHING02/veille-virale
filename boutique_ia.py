"""Tâches de fond de la boutique qui appellent Claude : idées de produits, guide PDF prêt à vendre, séquence d'e-mails."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import boutique as bq
from espace import Espace
from modele import log


def _voix(esp: Espace, cfg: dict) -> str:
    from apprentissage import voix
    try:
        return voix(cfg, esp.racine, [])
    except Exception:  # noqa: BLE001
        return ""


def contexte(esp: Espace, cfg: dict) -> str:
    """Ce que l'on sait de la niche et de l'audience : profil analysé, Reels qui marchent chez elle et chez les comptes copiés."""
    n = cfg["niche"]
    morceaux = [f"Niche : {n.get('description', '')}", f"Cible : {n.get('cible', '')}",
                f"Problèmes de la cible : {'; '.join(n.get('douleurs') or [])}", f"Offre actuelle : {n.get('offre', '')}"]
    if esp.profil_compte.exists():
        pr = json.loads(esp.profil_compte.read_text(encoding="utf-8"))
        prop = pr.get("proposition") or {}
        if prop:
            morceaux.append(f"Profil de marque : {prop.get('description_niche', '')} — douleurs : {'; '.join(prop.get('douleurs') or [])}")
        app = (pr.get("apprentissage") or {}).get("texte")
        if app:
            morceaux.append("Ce qui marche sur son compte :\n" + app[:1500])
        tops = [t.get("legende", "")[:140] for t in pr.get("top") or []][:5]
        if tops:
            morceaux.append("Ses Reels les plus vus :\n- " + "\n- ".join(tops))
    analyses = sorted(esp.analyses.glob("*.json"), reverse=True)
    if analyses:
        try:
            a = json.loads(analyses[0].read_text(encoding="utf-8"))
            vus = sorted([p for p in a.get("posts", []) if p.get("adaptation")], key=lambda p: p.get("vues") or 0, reverse=True)[:12]
            if vus:
                morceaux.append("Sujets viraux dans la niche (veille) :\n- " + "\n- ".join(
                    f"{(p['adaptation'].get('hook_viral') or '')[:110]} — {p['adaptation'].get('sujet', '')[:120]} ({p.get('vues') or 0} vues)" for p in vus))
            vc = a.get("voix_client") or {}
            if vc.get("questions"):
                morceaux.append("Questions récurrentes de l'audience :\n- " + "\n- ".join(vc["questions"][:8]))
        except (json.JSONDecodeError, OSError):
            pass
    return "\n\n".join(m for m in morceaux if m.strip())[:9000]


IDEES_DEMO = {"idees": [
    {"type": "guide", "titre": "Ventre plat sans régime : 7 jours", "sous_titre": "Le guide pour dégonfler avec ce que tu as déjà dans tes placards",
     "description": "Tu te réveilles le ventre plat et le soir tu ressembles à une montgolfière ?\n\nDans ce guide :\n- les 5 erreurs du matin qui font gonfler\n- 7 petits-déjeuners anti-ballonnements\n- la liste de courses toute prête\n\nPour toi si tu veux des résultats sans compter les calories.",
     "prix_conseille": 0, "pourquoi": "[démo] Tes Reels « erreur du matin » font 2× plus de commentaires : c'est l'aimant à e-mails idéal.",
     "plan": ["Pourquoi tu gonfles", "Les 5 erreurs du matin", "7 petits-déjeuners", "La liste de courses", "Ton plan sur 7 jours"], "mot_cle": "VENTRE", "bouton": "Je le veux gratuitement"},
    {"type": "mini-formation", "titre": "Stop au grignotage du soir", "sous_titre": "14 jours pour reprendre la main, sans frustration",
     "description": "Le grignotage du soir n'est pas un manque de volonté.\n\nTu reçois :\n- 14 mini-vidéos de 5 minutes\n- un carnet d'exercices\n- mes 20 collations qui calent vraiment\n\nPour les femmes actives qui craquent après 21 h.",
     "prix_conseille": 2900, "pourquoi": "[démo] « Grignotage » revient dans 1 question sur 4 de ton audience.",
     "plan": ["Comprendre tes envies", "Le dîner qui cale", "Les rituels du soir", "Les collations", "Tenir sur la durée"], "mot_cle": "SOIR", "bouton": "Je commence"},
    {"type": "appel", "titre": "Appel découverte 30 min", "sous_titre": "On fait le point sur ton alimentation, sans jugement",
     "description": "30 minutes en visio pour comprendre ce qui bloque et repartir avec 3 actions concrètes.\n\nPour toi si tu as déjà tout essayé et que tu veux un plan à ta mesure.",
     "prix_conseille": 4900, "pourquoi": "[démo] Ton offre d'accompagnement a besoin d'une première marche simple.",
     "plan": ["Ton bilan", "Tes blocages", "3 actions"], "mot_cle": "APPEL", "bouton": "Je réserve"},
]}


def idees(esp: Espace, cfg: dict, demo: bool = False) -> dict:
    log("Je regarde ce qui marche dans ta niche…")
    if demo:
        return IDEES_DEMO
    from ia import idees_produits
    log("Claude imagine tes produits…")
    r = idees_produits(cfg, _voix(esp, cfg), contexte(esp, cfg))
    if r.get("erreur"):
        raise RuntimeError(r["erreur"])
    for i in r.get("idees") or []:
        i["mot_cle"] = re.sub(r"[^A-Z0-9]", "", (i.get("mot_cle") or "").upper())[:20]
    return r


def _guide_demo(p: dict) -> dict:
    plan = p.get("plan") or ["Comprendre", "Les erreurs à éviter", "La méthode", "Ton plan d'action"]
    return {"titre": p.get("titre") or "Mon guide", "sous_titre": p.get("sous_titre") or "",
            "introduction": "[démo] Ce guide se lit en 10 minutes. Garde-le sous la main et applique une seule chose à la fois.\n\nOn y va ?",
            "parties": [{"titre": t, "texte": f"[démo] Un premier paragraphe concret sur « {t} », avec un exemple de la vraie vie.\n\nUn second paragraphe qui donne la méthode, étape par étape, applicable dès demain.",
                         "a_retenir": ["[démo] Un point clé à retenir", "[démo] Une action simple à faire aujourd'hui"]} for t in plan],
            "conclusion": "[démo] Tu as toutes les clés. Choisis une seule habitude cette semaine et tiens-la sept jours.",
            "appel_action": "[démo] Envie d'aller plus loin ? Écris-moi en message privé, on en parle."}


def guide(esp: Espace, cfg: dict, uid: int, pid: str, plan: list[str] | None = None, demo: bool = False, base: str = "") -> dict:
    """Écrit le guide avec Claude, le met en page aux couleurs de la boutique et l'attache au produit."""
    import guide_pdf
    page = bq.lit_page(uid)
    p = next((x for x in page["produits"] if x["id"] == pid), None)
    if not p:
        raise RuntimeError("Produit introuvable : enregistre-le puis réessaie.")
    p = {**p, "plan": plan or p.get("plan") or []}
    log("J'écris ton guide…")
    if demo:
        contenu = _guide_demo(p)
    else:
        from ia import ecrit_guide
        contenu = ecrit_guide(cfg, _voix(esp, cfg), p, contexte(esp, cfg))
        if contenu.get("erreur"):
            raise RuntimeError(contenu["erreur"])
    log("Je mets le guide en page…")
    nom = uuid.uuid4().hex + ".pdf"
    sortie = bq.dossier(uid) / "fichiers" / nom
    image = bq.dossier(uid) / "images" / p["image"] if p.get("image") else None
    url = f"{base or _url()}/@{bq.pseudo_de(uid)}"
    guide_pdf.genere(contenu, page["design"], sortie, page.get("nom") or "", url, image, bq.POLICES[page["design"]["police_titre"]][2])
    titre_fichier = re.sub(r"[^\w\- ]+", "", contenu.get("titre") or p.get("titre") or "guide").strip()[:60] or "guide"
    with bq.verrou(uid):
        page = bq.lit_page(uid)
        x = next((y for y in page["produits"] if y["id"] == pid), None)
        if not x:
            sortie.unlink(missing_ok=True)
            raise RuntimeError("Le produit a été supprimé pendant l'écriture.")
        ancien = x.get("fichier")
        x["fichier"], x["fichier_nom"], x["lien"] = nom, titre_fichier + ".pdf", ""
        x["type"] = "telechargement"
        bq.ecrit_page(uid, page)
    if ancien and ancien != nom:
        (bq.dossier(uid) / "fichiers" / ancien).unlink(missing_ok=True)
    log("✅ Ton guide est prêt et attaché au produit")
    return {"fichier_nom": titre_fichier + ".pdf", "pages": len(contenu.get("parties") or []) + 3}


def sequence(esp: Espace, cfg: dict, uid: int, demo: bool = False) -> dict:
    page = bq.lit_page(uid)
    log("J'écris ta séquence d'e-mails…")
    produits = [p for p in page.get("produits", []) if p.get("visible", True)]
    if demo:
        payant = next((p for p in produits if p.get("prix")), None)
        return {"emails": [
            {"delai_jours": 0, "sujet": "[démo] Bienvenue, c'est noté !", "produit": "",
             "texte": "Coucou {prenom},\n\n[démo] Merci de m'avoir rejointe ! Voici ce que tu vas recevoir : un conseil par semaine, testé sur moi avant.\n\nÀ très vite"},
            {"delai_jours": 2, "sujet": "[démo] Le petit truc qui change tout", "produit": "",
             "texte": "Coucou {prenom},\n\n[démo] Un seul conseil aujourd'hui : bois un grand verre d'eau tiède au réveil. C'est tout. Fais-le 5 jours et dis-moi."},
            {"delai_jours": 5, "sujet": "[démo] Ce que m'a écrit Julie", "produit": payant["id"] if payant else "",
             "texte": "Coucou {prenom},\n\n[démo] Julie m'a écrit la semaine dernière : « je ne grignote plus le soir ». Voilà comment elle a fait.\n\nSi tu veux le même déclic, tout est expliqué ici."},
        ]}
    from ia import ecrit_sequence
    r = ecrit_sequence(cfg, _voix(esp, cfg), produits, page.get("nom") or "")
    if r.get("erreur"):
        raise RuntimeError(r["erreur"])
    ids = {p["id"] for p in produits}
    for e in r.get("emails") or []:
        if e.get("produit") not in ids:
            e["produit"] = ""
    return r


def _url() -> str:
    import os
    if os.getenv("URL_PUBLIQUE"):
        return os.environ["URL_PUBLIQUE"].rstrip("/")
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        return "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
    return "http://localhost:8000"
