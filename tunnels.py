"""
Tunnels de vente de la boutique (formules payantes) : modèles pré-remplis, nettoyage, pages publiques.

Deux types :
  - quiz  : quiz-audit noté. Questions → note sur 100 et par critère → e-mail (facultatif) → résultat → offre.
  - vente : page de vente longue. Promesse, problème, bénéfices, contenu, avis, à propos, FAQ, offre.
Rangés dans page["tunnels"] (boutique). Page publique : /@pseudo/t/<id>. Le bouton d'offre mène au produit choisi
(/@pseudo/t/<id>/offre → /@pseudo/p/<pid>?src=tunnel-<id>).
"""

from __future__ import annotations

import copy
import json
import secrets

import boutique as bq
import boutique_ventes as bv

E = bq.E
TYPES = ("quiz", "vente")

# ------------------------------------------------------------
#  Modèles pré-remplis (à adapter par la cliente)
# ------------------------------------------------------------
def _q(texte, pilier, reponses):
    return {"texte": texte, "pilier": pilier, "reponses": [{"texte": t, "points": p} for t, p in reponses]}


_QUIZ_INSTA = {
    "type": "quiz", "titre": "Audit de ton compte Instagram",
    "accroche": {"surtitre": "Audit gratuit", "titre": "Découvre ce qui bloque", "titre_accent": "vraiment ton compte Instagram",
                 "texte": "10 questions, 3 minutes : ton compte passé au crible sur 5 critères. Tu sais exactement quoi corriger.",
                 "bouton": "Commencer mon audit", "puces": ["3 minutes", "100 % gratuit", "Résultat personnalisé"]},
    "promesse": {"titre": "À la fin, tu sais quoi faire", "items": [
        {"titre": "Ta note sur 100", "texte": "Et une note sur chacun des 5 critères."},
        {"titre": "Le point qui bloque", "texte": "Le maillon faible de ton compte, pas 20 conseils génériques."},
        {"titre": "Tes actions prioritaires", "texte": "Ce que tu dois corriger, dans l'ordre."},
        {"titre": "La suite", "texte": "Comment passer à l'étape d'après."}]},
    "piliers": [
        {"nom": "Positionnement", "conseil": "Ta cible est trop large. Écris en une phrase qui tu aides et à quoi : chaque publication doit parler à cette personne-là."},
        {"nom": "Profil", "conseil": "Ta bio doit dire en 2 lignes ce que tu fais et pour qui, avec un seul lien qui mène à ton offre."},
        {"nom": "Contenu", "conseil": "Commence chaque Reel par une phrase qui arrête le pouce : une promesse, un chiffre ou une erreur courante."},
        {"nom": "Régularité", "conseil": "Mieux vaut 3 publications par semaine pendant 3 mois que 10 la première semaine. Prépare tes contenus en lot."},
        {"nom": "Conversion", "conseil": "Termine tes contenus par une seule action claire : un mot-clé à commenter, un lien, un message privé."}],
    "questions": [
        _q("Peux-tu dire en une phrase à qui tu t'adresses ?", 0, [("Oui, très précisément", 4), ("À peu près", 2), ("Je parle à tout le monde", 0)]),
        _q("Tes abonnés ont-ils tous le même problème à résoudre ?", 0, [("Oui", 4), ("En partie", 2), ("Pas vraiment", 0)]),
        _q("En lisant ta bio, comprend-on ce que tu proposes en 3 secondes ?", 1, [("Oui", 4), ("Il faut chercher un peu", 2), ("Non", 0)]),
        _q("Le lien de ta bio mène-t-il à une seule offre claire ?", 1, [("Oui", 4), ("À une page avec plein de liens", 2), ("Je n'ai pas de lien", 0)]),
        _q("Tes Reels commencent-ils par une accroche forte ?", 2, [("Toujours", 4), ("Parfois", 2), ("Je n'y pense pas", 0)]),
        _q("Combien de vues fait un Reel moyen, par rapport à tes abonnés ?", 2, [("Plus que mes abonnés", 4), ("Autour de 30 %", 2), ("Moins de 10 %", 0)]),
        _q("Combien de fois publies-tu par semaine ?", 3, [("3 fois ou plus", 4), ("1 à 2 fois", 2), ("Moins d'une fois", 0)]),
        _q("As-tu des contenus d'avance ?", 3, [("Une semaine ou plus", 4), ("Un ou deux", 2), ("Jamais", 0)]),
        _q("Reçois-tu des messages privés de personnes intéressées ?", 4, [("Chaque semaine", 4), ("De temps en temps", 2), ("Presque jamais", 0)]),
        _q("Tes contenus se terminent-ils par une action à faire ?", 4, [("Toujours", 4), ("Parfois", 2), ("Rarement", 0)])],
    "email": {"actif": True, "titre": "Où t'envoyer ton résultat ?", "texte": "Ton audit s'affiche juste après. Tu le reçois aussi par e-mail pour le garder.", "bouton": "Voir mon résultat"},
    "niveaux": [
        {"min": 0, "titre": "Les bases sont à poser", "texte": "Bonne nouvelle : avec quelques réglages simples, la différence se verra vite."},
        {"min": 45, "titre": "Tu es sur la bonne voie", "texte": "Les fondations sont là. Corrige ton point bloquant et ton compte peut décoller."},
        {"min": 75, "titre": "Ton compte est solide", "texte": "Il te manque surtout une méthode pour passer à la vitesse supérieure."}],
    "offre": {"produit": "", "titre": "Aller plus loin", "texte": "Ma méthode pas à pas pour corriger tout ça en 30 jours.", "bouton": "Je découvre la méthode"},
}

_QUIZ_BILAN = {
    "type": "quiz", "titre": "Bilan énergie",
    "accroche": {"surtitre": "Bilan offert", "titre": "Pourquoi tu es", "titre_accent": "fatiguée en permanence ?",
                 "texte": "10 questions pour comprendre ce qui pompe ton énergie, et par quoi commencer.",
                 "bouton": "Faire mon bilan", "puces": ["3 minutes", "Gratuit", "Conseils personnalisés"]},
    "promesse": {"titre": "Ce que ton bilan te donne", "items": [
        {"titre": "Ta note sur 100", "texte": "Et une note pour chacun des 5 piliers de ton énergie."},
        {"titre": "Ce qui te fatigue le plus", "texte": "Le pilier à soigner en premier."},
        {"titre": "3 actions simples", "texte": "À mettre en place dès cette semaine."},
        {"titre": "La suite", "texte": "Comment retrouver une énergie stable."}]},
    "piliers": [
        {"nom": "Sommeil", "conseil": "Couche-toi à heure fixe et coupe les écrans 45 minutes avant : c'est le levier le plus rapide."},
        {"nom": "Alimentation", "conseil": "Un petit-déjeuner avec des protéines évite le coup de barre de 11 h."},
        {"nom": "Stress", "conseil": "Trois respirations lentes avant chaque repas : ton corps sort du mode alerte."},
        {"nom": "Mouvement", "conseil": "20 minutes de marche par jour suffisent pour sentir la différence."},
        {"nom": "Récupération", "conseil": "Bloque un vrai moment pour toi chaque semaine, sans téléphone."}],
    "questions": [
        _q("Te réveilles-tu reposée ?", 0, [("Presque toujours", 4), ("Une fois sur deux", 2), ("Rarement", 0)]),
        _q("Combien d'heures dors-tu par nuit ?", 0, [("7 h ou plus", 4), ("6 à 7 h", 2), ("Moins de 6 h", 0)]),
        _q("As-tu un coup de fatigue après les repas ?", 1, [("Jamais", 4), ("Parfois", 2), ("Presque tous les jours", 0)]),
        _q("As-tu des envies de sucre dans la journée ?", 1, [("Rarement", 4), ("L'après-midi", 2), ("Tout le temps", 0)]),
        _q("Te sens-tu souvent sous pression ?", 2, [("Rarement", 4), ("Certains jours", 2), ("Tout le temps", 0)]),
        _q("Arrives-tu à décrocher le soir ?", 2, [("Oui", 4), ("Avec du mal", 2), ("Non, je rumine", 0)]),
        _q("Bouges-tu au moins 20 minutes par jour ?", 3, [("Oui", 4), ("Quelques jours", 2), ("Presque jamais", 0)]),
        _q("Passes-tu plus de 6 h assise par jour ?", 3, [("Non", 4), ("Environ", 2), ("Oui, bien plus", 0)]),
        _q("Prends-tu du temps rien que pour toi ?", 4, [("Chaque semaine", 4), ("De temps en temps", 2), ("Jamais", 0)]),
        _q("Tes week-ends te reposent-ils ?", 4, [("Oui", 4), ("Un peu", 2), ("Non, ils m'épuisent", 0)])],
    "email": {"actif": True, "titre": "Où t'envoyer ton bilan ?", "texte": "Ton résultat s'affiche juste après, et tu le reçois aussi par e-mail.", "bouton": "Voir mon bilan"},
    "niveaux": [
        {"min": 0, "titre": "Ton énergie est dans le rouge", "texte": "Ton corps t'envoie des signaux. Commence par ton pilier le plus faible, un petit pas à la fois."},
        {"min": 45, "titre": "Ton énergie fait le yo-yo", "texte": "Quelques habitudes à ajuster, et tu retrouves une énergie stable."},
        {"min": 75, "titre": "Ton énergie est plutôt bonne", "texte": "Bravo. Quelques réglages fins peuvent encore faire la différence."}],
    "offre": {"produit": "", "titre": "Retrouver ton énergie", "texte": "Mon programme de 21 jours pour remettre tes 5 piliers d'aplomb.", "bouton": "Je découvre le programme"},
}

_VENTE_FORMATION = {
    "type": "vente", "titre": "Page de vente : formation",
    "accroche": {"surtitre": "Formation en ligne", "titre": "Le titre de ta formation,", "titre_accent": "avec ta grande promesse",
                 "texte": "Pour qui elle est, et le résultat concret qu'elle apporte, en une ou deux phrases.", "bouton": "Je m'inscris"},
    "probleme": {"titre": "Tu te reconnais ?", "items": ["Le premier blocage de ta cliente idéale", "Le deuxième, dit avec ses mots à elle", "Ce qu'elle a déjà essayé, sans résultat"]},
    "benefices": {"titre": "Ce qui change pour toi", "items": [
        {"titre": "Premier résultat", "texte": "Ce qu'elle obtient dès les premières semaines."},
        {"titre": "Deuxième résultat", "texte": "Un gain concret : du temps, de l'argent, de la confiance…"},
        {"titre": "Troisième résultat", "texte": "Ce qu'elle ressent une fois la formation terminée."}]},
    "contenu": {"titre": "Ce que tu reçois", "items": ["Module 1 : …", "Module 2 : …", "Module 3 : …", "Bonus : …"]},
    "temoignages": {"titre": "Elles l'ont suivie", "items": []},
    "a_propos": {"titre": "Qui suis-je ?", "texte": "Ton parcours en quelques lignes : pourquoi tu es la bonne personne pour l'aider."},
    "faq": {"titre": "Questions fréquentes", "items": [
        {"q": "Combien de temps ai-je accès à la formation ?", "r": "À vie, mises à jour comprises."},
        {"q": "Combien de temps faut-il par semaine ?", "r": "Environ 1 h 30, à ton rythme."},
        {"q": "Et si ça ne me convient pas ?", "r": "Écris-moi dans les 14 jours, je te rembourse."}]},
    "offre": {"produit": "", "titre": "Rejoins la formation", "texte": "Accès immédiat après le paiement.", "bouton": "Je m'inscris", "garantie": "Satisfaite ou remboursée pendant 14 jours"},
}

_VENTE_ACCOMPAGNEMENT = {
    "type": "vente", "titre": "Page de vente : accompagnement",
    "accroche": {"surtitre": "Accompagnement individuel", "titre": "En 8 semaines,", "titre_accent": "le résultat que tu promets",
                 "texte": "Un accompagnement sur mesure pour les personnes qui veulent avancer vite, avec quelqu'un à leurs côtés.", "bouton": "Je réserve ma place"},
    "probleme": {"titre": "Tu en as assez de…", "items": ["Tourner en rond seule", "Accumuler les conseils sans passer à l'action", "Ne pas savoir par où commencer"]},
    "benefices": {"titre": "Ce qu'on fait ensemble", "items": [
        {"titre": "Un plan sur mesure", "texte": "Construit à partir de ta situation, pas d'un modèle tout fait."},
        {"titre": "Un suivi chaque semaine", "texte": "On ajuste au fur et à mesure, tu n'es jamais bloquée."},
        {"titre": "Des résultats durables", "texte": "Tu repars avec une méthode que tu gardes."}]},
    "contenu": {"titre": "Ce qui est inclus", "items": ["8 séances individuelles en visio", "Un échange par message entre les séances", "Tes fiches et exercices personnalisés"]},
    "temoignages": {"titre": "Ce qu'elles en disent", "items": []},
    "a_propos": {"titre": "Qui suis-je ?", "texte": "Ton parcours, ta méthode et pourquoi tu fais ce métier."},
    "faq": {"titre": "Questions fréquentes", "items": [
        {"q": "Comment se passent les séances ?", "r": "En visio, une fois par semaine, à l'horaire qui te convient."},
        {"q": "Puis-je payer en plusieurs fois ?", "r": "Oui, écris-moi pour en parler."}]},
    "offre": {"produit": "", "titre": "Réserve ta place", "texte": "Places limitées chaque mois pour garder un vrai suivi.", "bouton": "Je réserve ma place", "garantie": ""},
}

MODELES = {
    "quiz_insta": ("Quiz-audit : compte Instagram", "Pour les créatrices et les coachs business : une note sur 5 critères, puis ton offre.", _QUIZ_INSTA),
    "quiz_bilan": ("Quiz-audit : bilan énergie", "Pour le bien-être, la naturopathie, le coaching : un bilan noté, puis ton programme.", _QUIZ_BILAN),
    "vente_formation": ("Page de vente : formation", "Promesse, problème, bénéfices, modules, FAQ et offre avec garantie.", _VENTE_FORMATION),
    "vente_accompagnement": ("Page de vente : accompagnement", "Pour vendre un coaching ou un suivi individuel.", _VENTE_ACCOMPAGNEMENT),
}


def modeles() -> list[dict]:
    return [{"id": k, "nom": n, "description": d, "type": m["type"], "contenu": m} for k, (n, d, m) in MODELES.items()]


def styles() -> list[dict]:
    return [{"id": k, "nom": v["nom"], "groupe": v["groupe"], "fond": v["design"]["fond1"], "accent": v["design"]["accent"], "carte": v["design"]["bloc_fond"]}
            for k, v in STYLES.items()]


def nouveau(modele: str) -> dict | None:
    m = MODELES.get(modele)
    if not m:
        return None
    t = copy.deepcopy(m[2])
    t.update({"id": secrets.token_hex(4), "publie": True, "modele": modele})
    return t


# ------------------------------------------------------------
#  Nettoyage de ce que le navigateur envoie
# ------------------------------------------------------------
def _s(x, lim: int) -> str:
    return str(x or "").strip()[:lim] if isinstance(x, (str, int, float)) else ""


def _liste(x, maxi: int) -> list:
    return [i for i in x if isinstance(i, (dict, str))][:maxi] if isinstance(x, list) else []


def propre(t: dict, produits: set[str]) -> dict | None:
    if not isinstance(t, dict) or t.get("type") not in TYPES:
        return None
    ac = t.get("accroche") if isinstance(t.get("accroche"), dict) else {}
    of = t.get("offre") if isinstance(t.get("offre"), dict) else {}
    r = {"id": "".join(c for c in _s(t.get("id"), 12) if c.isalnum()) or secrets.token_hex(4), "type": t["type"],
         "titre": _s(t.get("titre"), 80) or "Mon tunnel", "publie": t.get("publie", True) is not False, "modele": _s(t.get("modele"), 30),
         "style": t.get("style") if t.get("style") in STYLES else "",
         "accroche": {"surtitre": _s(ac.get("surtitre"), 60), "titre": _s(ac.get("titre"), 120), "titre_accent": _s(ac.get("titre_accent"), 120),
                      "texte": _s(ac.get("texte"), 400), "bouton": _s(ac.get("bouton"), 40) or "Commencer",
                      "puces": [_s(p, 40) for p in _liste(ac.get("puces"), 4) if _s(p, 40)]},
         "offre": {"produit": _s(of.get("produit"), 12) if _s(of.get("produit"), 12) in produits else "", "titre": _s(of.get("titre"), 100),
                   "texte": _s(of.get("texte"), 400), "bouton": _s(of.get("bouton"), 40) or "Je découvre", "garantie": _s(of.get("garantie"), 120)}}
    sec = lambda k: t.get(k) if isinstance(t.get(k), dict) else {}  # noqa: E731
    if t["type"] == "quiz":
        pr = sec("promesse")
        r["promesse"] = {"titre": _s(pr.get("titre"), 100), "items": [{"titre": _s(i.get("titre"), 60), "texte": _s(i.get("texte"), 200)}
                                                                      for i in _liste(pr.get("items"), 6) if isinstance(i, dict)]}
        r["piliers"] = [{"nom": _s(p.get("nom"), 40) or f"Critère {n + 1}", "conseil": _s(p.get("conseil"), 400)}
                        for n, p in enumerate(_liste(t.get("piliers"), 6)) if isinstance(p, dict)] or [{"nom": "Critère 1", "conseil": ""}]
        nb = len(r["piliers"])
        qs = []
        for q in _liste(t.get("questions"), 20):
            if not isinstance(q, dict):
                continue
            try:
                pil = min(nb - 1, max(0, int(q.get("pilier") or 0)))
            except (TypeError, ValueError):
                pil = 0
            reps = []
            for a in _liste(q.get("reponses"), 6):
                if isinstance(a, dict) and _s(a.get("texte"), 120):
                    try:
                        pts = min(4, max(0, int(a.get("points") or 0)))
                    except (TypeError, ValueError):
                        pts = 0
                    reps.append({"texte": _s(a.get("texte"), 120), "points": pts})
            qs.append({"texte": _s(q.get("texte"), 200), "pilier": pil, "reponses": reps})
        r["questions"] = qs
        em = sec("email")
        r["email"] = {"actif": em.get("actif", True) is not False, "titre": _s(em.get("titre"), 100), "texte": _s(em.get("texte"), 300),
                      "bouton": _s(em.get("bouton"), 40) or "Voir mon résultat"}
        niv = []
        for n in _liste(t.get("niveaux"), 5):
            if isinstance(n, dict):
                try:
                    mini = min(100, max(0, int(n.get("min") or 0)))
                except (TypeError, ValueError):
                    mini = 0
                niv.append({"min": mini, "titre": _s(n.get("titre"), 100), "texte": _s(n.get("texte"), 400)})
        r["niveaux"] = sorted(niv, key=lambda x: x["min"])
    else:
        for k in ("probleme", "contenu"):
            s = sec(k)
            r[k] = {"titre": _s(s.get("titre"), 100), "items": [_s(i, 200) for i in _liste(s.get("items"), 12) if _s(i, 200)]}
        b = sec("benefices")
        r["benefices"] = {"titre": _s(b.get("titre"), 100), "items": [{"titre": _s(i.get("titre"), 80), "texte": _s(i.get("texte"), 300)}
                                                                      for i in _liste(b.get("items"), 8) if isinstance(i, dict)]}
        te = sec("temoignages")
        r["temoignages"] = {"titre": _s(te.get("titre"), 100), "items": [{"texte": _s(i.get("texte"), 500), "nom": _s(i.get("nom"), 60)}
                                                                         for i in _liste(te.get("items"), 10) if isinstance(i, dict) and _s(i.get("texte"), 500)]}
        ap = sec("a_propos")
        r["a_propos"] = {"titre": _s(ap.get("titre"), 100), "texte": _s(ap.get("texte"), 1500)}
        fq = sec("faq")
        r["faq"] = {"titre": _s(fq.get("titre"), 100), "items": [{"q": _s(i.get("q"), 200), "r": _s(i.get("r"), 800)}
                                                                 for i in _liste(fq.get("items"), 12) if isinstance(i, dict) and _s(i.get("q"), 200)]}
    return r


# ------------------------------------------------------------
#  Pages publiques
# ------------------------------------------------------------
CSS = """
.tn{max-width:640px;margin:0 auto}
.tn-sur{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--a);margin-bottom:10px}
.tn h1{font:700 clamp(30px,8vw,46px)/1.08 var(--tf);margin:0 0 14px;letter-spacing:-.01em}
.tn h1 em{font-style:italic;color:var(--a)}
.tn h2{font:700 clamp(24px,6vw,32px)/1.15 var(--tf);margin:0 0 16px}
.tn .chapo{font-size:17px;opacity:.85;margin:0 0 22px}
.tn .cta{display:flex;justify-content:center;width:100%;font:700 17px var(--tx);padding:17px 22px;text-decoration:none;text-align:center;background:var(--a)!important;color:var(--ac)!important;border:0!important;border-radius:var(--r);box-shadow:0 12px 28px -12px var(--a)!important;cursor:pointer;transition:transform .15s}
.tn .cta:hover{transform:translateY(-2px)}
.tn-puces{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 16px;margin:12px 0 0;font-size:14px;opacity:.85}
.tn-puces span::before{content:"✓ ";color:var(--a);font-weight:700}
.tn-tete{text-align:center;padding:24px 0 8px}
.tn-sec{margin:34px 0}
.tn-carte{background:var(--k);color:var(--kt);border-radius:var(--rk);padding:20px}
.tn-items{display:grid;gap:14px;margin:0;padding:0;list-style:none}
.tn-items li{display:grid;grid-template-columns:42px 1fr;gap:12px;align-items:start}
.tn-items .ic{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:color-mix(in srgb,var(--a) 16%,transparent);color:var(--a);font-weight:800}
.tn-items b{display:block;font-size:16px}.tn-items small{opacity:.8;font-size:14.5px}
.tn-coches{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.tn-coches li{padding-left:30px;position:relative}
.tn-coches li::before{content:"✓";position:absolute;left:0;top:0;width:22px;height:22px;border-radius:50%;background:var(--a);color:var(--ac);display:grid;place-items:center;font-size:13px;font-weight:800}
.tn-croix li::before{content:"✕";background:color-mix(in srgb,var(--t) 15%,transparent);color:var(--t)}
.tn-avis{display:grid;gap:12px}.tn-avis blockquote{margin:0}.tn-avis cite{display:block;margin-top:8px;font-style:normal;font-weight:700;font-size:14px}
.tn-faq details{border-bottom:1px solid color-mix(in srgb,var(--t) 15%,transparent);padding:12px 0}.tn-faq summary{font-weight:700;cursor:pointer}
.tn-offre{text-align:center}.tn-offre .prix{font:800 40px/1 var(--tf);margin:10px 0}.tn-offre .prix s{font-size:20px;opacity:.55;margin-right:8px}
.tn-offre .garantie{font-size:13.5px;opacity:.8;margin-top:10px}
.tn-offre img{width:100%;border-radius:calc(var(--rk) - 6px);margin-bottom:14px;aspect-ratio:16/10;object-fit:cover}
/* Variantes de style */
.v-halo .tn-tete{position:relative;isolation:isolate}
.v-halo .tn-tete::before{content:"";position:absolute;left:50%;top:-30px;width:min(560px,120%);height:340px;transform:translateX(-50%);background:radial-gradient(closest-side,color-mix(in srgb,var(--a) 34%,transparent),transparent);z-index:-1;pointer-events:none}
.v-cadre .tn-carte{border:1px solid color-mix(in srgb,var(--kt) 14%,transparent);box-shadow:none}
.v-cadre .tn-items .ic{border:1px solid color-mix(in srgb,var(--a) 45%,transparent);background:color-mix(in srgb,var(--a) 10%,transparent)}
.v-impact h1{text-transform:uppercase;letter-spacing:-.02em;line-height:1.02}
.v-impact h1 em{font-style:normal;background:var(--a);color:var(--ac);padding:0 .14em;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.v-doux .tn-carte{box-shadow:0 22px 44px -28px rgba(40,20,30,.35)}
/* Quiz */
.qz-etape[hidden]{display:none!important}
.qz-barre{height:6px;border-radius:9px;background:color-mix(in srgb,var(--t) 14%,transparent);overflow:hidden;margin:6px 0 18px}
.qz-barre i{display:block;height:100%;background:var(--a);width:0;transition:width .35s}
.qz-num{font-size:13px;opacity:.7;font-weight:600}
.qz-q{font:700 22px/1.25 var(--tf);margin:0 0 18px}
.qz-rep{display:grid;gap:10px}
.qz-rep button{font:600 16px var(--tx);text-align:left;padding:15px 18px;border-radius:var(--rk);border:1.5px solid color-mix(in srgb,var(--kt) 18%,transparent);background:var(--k);color:var(--kt);cursor:pointer;transition:transform .12s,border-color .12s}
.qz-rep button:hover{border-color:var(--a);transform:translateY(-1px)}
.qz-retour{background:none;border:0;color:var(--t);opacity:.7;margin-top:14px;cursor:pointer;font:inherit}
.qz-mail input{width:100%;font:16px var(--tx);padding:14px 16px;border-radius:12px;border:1.5px solid color-mix(in srgb,var(--kt) 20%,transparent);background:#fff;color:#1a1a1a;margin-bottom:10px}
.qz-note{text-align:center}.qz-note .n{font:800 84px/1 var(--tf);color:var(--a)}.qz-note .n small{font-size:26px;opacity:.6;color:var(--t)}
.qz-piliers{display:grid;gap:12px;margin-top:6px}
.qz-pil .l{display:flex;justify-content:space-between;font-weight:600;font-size:15px;margin-bottom:5px}
.qz-pil .b{height:8px;border-radius:9px;background:color-mix(in srgb,var(--kt) 12%,transparent);overflow:hidden}
.qz-pil .b i{display:block;height:100%;border-radius:9px;background:var(--a);transition:width 1s}
.qz-pil.faible .b i{background:#E5484D}
.qz-bloque{border-left:4px solid #E5484D}
.qz-actions{counter-reset:a;list-style:none;padding:0;margin:0;display:grid;gap:10px}
.qz-actions li{counter-increment:a;padding-left:38px;position:relative}
.qz-actions li::before{content:counter(a);position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;background:var(--a);color:var(--ac);display:grid;place-items:center;font-weight:800;font-size:14px}
"""


# ------------------------------------------------------------
#  Styles propres aux tunnels (couleurs, polices, effets), indépendants du thème de la boutique
# ------------------------------------------------------------
def _st(nom, groupe, fond, texte, carte, accent, titre, corps, variantes, fond2=None, sur=None, cadre="ombre", rayon=16):
    sur = sur or ("#1A1A1A" if bq._clair(accent) else "#FFFFFF")
    d = {"fond_type": "degrade" if fond2 else "uni", "fond1": fond, "fond2": fond2 or fond, "texte": texte, "bloc_fond": carte, "bloc_texte": texte if not bq._clair(carte) == bq._clair(texte) else ("#1A1A1A" if bq._clair(carte) else "#F5F1E8"),
         "accent": accent, "bouton_fond": accent, "bouton_texte": sur, "bouton_ombre": accent, "police_titre": titre, "police_texte": corps,
         "carte_cadre": cadre, "rayon": rayon, "bouton_style": "plein", "decor": "aucun"}
    return {"nom": nom, "groupe": groupe, "design": d, "variantes": variantes}


STYLES = {
    "nuit_doree": _st("Nuit dorée", "Sombre", "#0B0B0D", "#F5F1E8", "#17171B", "#F2C14E", "Playfair Display", "Inter", "halo cadre"),
    "minuit_rose": _st("Minuit rose", "Sombre", "#140A17", "#F8EEF3", "#1F1124", "#FF4F79", "Fraunces", "DM Sans", "halo cadre"),
    "encre_neon": _st("Encre néon", "Sombre", "#0A0F1A", "#E8F1FF", "#121A2A", "#3DF2C4", "Space Grotesk", "Inter", "impact cadre", rayon=10),
    "foret_nuit": _st("Forêt de nuit", "Sombre", "#0E1A15", "#ECF3EE", "#15241D", "#A8DDB0", "Cormorant Garamond", "Manrope", "halo cadre"),
    "violet_electrique": _st("Violet électrique", "Sombre", "#24104F", "#FFFFFF", "#311A66", "#FFD23F", "Unbounded", "Inter", "halo impact", fond2="#3A1680"),
    "creme_elegant": _st("Crème élégant", "Clair", "#F6F1E9", "#2A211C", "#FFFFFF", "#9A6B3F", "Cormorant Garamond", "Lora", "doux"),
    "blanc_minimal": _st("Blanc minimal", "Clair", "#FFFFFF", "#111111", "#F5F5F5", "#111111", "Instrument Serif", "Inter", "cadre", cadre="contour", rayon=8),
    "lavande": _st("Lavande", "Clair", "#F3EEFB", "#2B2140", "#FFFFFF", "#7B5CD6", "Fraunces", "Nunito", "doux"),
    "sauge": _st("Sauge", "Clair", "#EEF2EA", "#1F2B22", "#FFFFFF", "#4F7A5A", "DM Serif Display", "DM Sans", "doux"),
    "sable": _st("Sable chaud", "Clair", "#F4EDE4", "#2A211C", "#FFFFFF", "#B4693E", "Libre Baskerville", "Poppins", "doux"),
    "rose_pop": _st("Rose pop", "Coloré", "#FFE4EC", "#2B0A16", "#FFFFFF", "#E6195C", "Archivo Black", "Poppins", "impact", rayon=12),
    "citron": _st("Citron", "Coloré", "#FFF3B8", "#1A1A1A", "#FFFFFF", "#1A1A1A", "Bricolage Grotesque", "Manrope", "impact cadre", cadre="decale", rayon=6),
    "ocean": _st("Océan", "Coloré", "#E4F1FB", "#0E2238", "#FFFFFF", "#1166CC", "Sora", "Inter", "doux"),
    "terracotta": _st("Terracotta", "Coloré", "#F7E3D7", "#3A1D12", "#FFF8F3", "#C2502E", "Gloock", "Outfit", "doux"),
    "peche": _st("Pêche", "Coloré", "#FFD9C2", "#3B1420", "#FFFFFF", "#D9415E", "Yeseva One", "Nunito", "doux", fond2="#FFC1D1", rayon=22),
}


def _sur(ac: dict) -> str:
    return f'<span class="tn-sur">{E(ac["surtitre"])}</span>' if ac.get("surtitre") else ""


def _cite(i: dict) -> str:
    return f'<cite>{E(i["nom"])}</cite>' if i.get("nom") else ""


def _titre(ac: dict) -> str:
    t, a = E(ac.get("titre") or ""), E(ac.get("titre_accent") or "")
    return f"{t} <em>{a}</em>" if a else t


def _offre(page: dict, pseudo: str, t: dict, avec_titre: bool = True) -> str:
    of = t["offre"]
    p = next((x for x in page.get("produits", []) if x.get("id") == of.get("produit") and x.get("visible", True)), None)
    prix = ""
    img = ""
    if p:
        pe = bv.prix_effectif(p)
        barre = f"<s>{E(bq.prix_txt(pe['barre'], p.get('devise', 'eur')))}</s>" if pe["barre"] else ""
        prix = f'<div class="prix">{barre}{E(bq.prix_txt(pe["prix"], p.get("devise", "eur")))}</div>'
        if p.get("image"):
            img = f'<img src="{bq._img(pseudo, p["image"])}" alt="">'
    lien = f"/@{pseudo}/t/{t['id']}/offre"
    garantie = f'<p class="garantie">🛡️ {E(of["garantie"])}</p>' if of.get("garantie") else ""
    titre = f'<h2>{E(of.get("titre") or (p or {}).get("titre") or "")}</h2>' if avec_titre else ""
    return (f'<div class="tn-carte tn-offre">{img}{titre}<p>{E(of.get("texte") or "")}</p>{prix}'
            f'<a class="bouton cta" href="{lien}">{E(of.get("bouton") or "Je découvre")}</a>{garantie}</div>')


def rendu(page: dict, pseudo: str, t: dict, apercu: bool = False) -> str:
    st = STYLES.get(t.get("style") or "")
    if st:  # style propre au tunnel : remplace les couleurs et polices de la boutique
        page = {**page, "design": bq.design_propre({**page["design"], **st["design"]})}
    corps = rendu_quiz(page, pseudo, t, apercu) if t["type"] == "quiz" else rendu_vente(page, pseudo, t)
    variantes = " ".join("v-" + v for v in (st or {}).get("variantes", "").split())
    corps = f'<style>{CSS}</style><div class="{variantes}">{corps}</div>{bq.badge(page)}'
    ac = t["accroche"]
    return bq.document(page, pseudo, corps, f'{ac.get("titre", "")} {ac.get("titre_accent", "")}'.strip() or page.get("nom") or pseudo,
                       ac.get("texte", "")[:160], apercu)


def rendu_vente(page: dict, pseudo: str, t: dict) -> str:
    ac = t["accroche"]
    h = [f'<div class="tn"><header class="tn-tete">{_sur(ac)}'
         f'<h1>{_titre(ac)}</h1><p class="chapo">{E(ac.get("texte") or "")}</p>'
         f'<a class="bouton cta" href="#offre">{E(ac.get("bouton") or "Je découvre")}</a></header>']
    pb = t.get("probleme") or {}
    if pb.get("items"):
        h.append(f'<section class="tn-sec"><h2>{E(pb.get("titre") or "")}</h2><ul class="tn-coches tn-croix">'
                 + "".join(f"<li>{E(i)}</li>" for i in pb["items"]) + "</ul></section>")
    bf = t.get("benefices") or {}
    if bf.get("items"):
        h.append(f'<section class="tn-sec"><h2>{E(bf.get("titre") or "")}</h2><ul class="tn-items">'
                 + "".join(f'<li><span class="ic">{n + 1}</span><div><b>{E(i["titre"])}</b><small>{E(i["texte"])}</small></div></li>'
                           for n, i in enumerate(bf["items"])) + "</ul></section>")
    ct = t.get("contenu") or {}
    if ct.get("items"):
        h.append(f'<section class="tn-sec tn-carte"><h2>{E(ct.get("titre") or "")}</h2><ul class="tn-coches">'
                 + "".join(f"<li>{E(i)}</li>" for i in ct["items"]) + "</ul></section>")
    te = t.get("temoignages") or {}
    if te.get("items"):
        h.append(f'<section class="tn-sec"><h2>{E(te.get("titre") or "")}</h2><div class="tn-avis">'
                 + "".join(f'<blockquote class="tn-carte">« {E(i["texte"])} »{_cite(i)}</blockquote>'
                           for i in te["items"]) + "</div></section>")
    ap = t.get("a_propos") or {}
    if ap.get("texte"):
        photo = f'<img src="{bq._img(pseudo, page["photo"])}" alt="" style="width:84px;height:84px;border-radius:50%;object-fit:cover;float:left;margin:0 14px 6px 0">' if page.get("photo") else ""
        h.append(f'<section class="tn-sec tn-carte"><h2>{E(ap.get("titre") or "")}</h2>{photo}<p style="margin:0;white-space:pre-line">{E(ap["texte"])}</p></section>')
    h.append(f'<section class="tn-sec" id="offre">{_offre(page, pseudo, t)}</section>')
    fq = t.get("faq") or {}
    if fq.get("items"):
        h.append(f'<section class="tn-sec tn-faq"><h2>{E(fq.get("titre") or "")}</h2>'
                 + "".join(f"<details><summary>{E(i['q'])}</summary><p>{E(i['r'])}</p></details>" for i in fq["items"]) + "</section>")
    h.append("</div>")
    return "".join(h)


def rendu_quiz(page: dict, pseudo: str, t: dict, apercu: bool = False) -> str:
    ac = t["accroche"]
    pr = t.get("promesse") or {}
    puces = "".join(f"<span>{E(p)}</span>" for p in ac.get("puces") or [])
    promesse = ""
    if pr.get("items"):
        promesse = (f'<section class="tn-sec"><h2 style="text-align:center">{E(pr.get("titre") or "")}</h2><ul class="tn-items">'
                    + "".join(f'<li><span class="ic">{n + 1}</span><div><b>{E(i["titre"])}</b><small>{E(i["texte"])}</small></div></li>'
                              for n, i in enumerate(pr["items"])) + "</ul></section>")
    intro = (f'<div class="qz-etape" data-e="intro"><header class="tn-tete">{_sur(ac)}'
             f'<h1>{_titre(ac)}</h1><p class="chapo">{E(ac.get("texte") or "")}</p>'
             f'<button class="bouton cta" data-go="q0">{E(ac.get("bouton") or "Commencer")} →</button><div class="tn-puces">{puces}</div></header>{promesse}'
             f'<button class="bouton cta" data-go="q0" style="margin-top:6px">{E(ac.get("bouton") or "Commencer")} →</button></div>')
    em = t.get("email") or {}
    mail = (f'<div class="qz-etape tn-carte qz-mail" data-e="mail" hidden><h2>{E(em.get("titre") or "")}</h2><p>{E(em.get("texte") or "")}</p>'
            f'<form data-mail><input type="text" name="prenom" placeholder="Ton prénom" autocomplete="given-name">'
            f'<input type="email" name="email" placeholder="Ton e-mail" required autocomplete="email">'
            f'<button class="bouton cta" type="submit">{E(em.get("bouton") or "Voir mon résultat")}</button></form></div>') if em.get("actif") else ""
    resultat = (f'<div class="qz-etape" data-e="res" hidden><div class="tn-carte qz-note"><div class="qz-num">TA NOTE</div><div class="n"><span data-total>0</span><small>/100</small></div>'
                f'<h2 data-niv-titre style="margin:10px 0 6px"></h2><p data-niv-texte style="margin:0"></p></div>'
                f'<section class="tn-sec tn-carte"><div class="qz-piliers" data-piliers></div></section>'
                f'<section class="tn-sec tn-carte qz-bloque"><div class="qz-num">TON POINT BLOQUANT</div><h2 data-bloque style="margin:6px 0 8px"></h2><p data-bloque-txt style="margin:0"></p></section>'
                f'<section class="tn-sec"><h2>Tes actions prioritaires</h2><ol class="qz-actions" data-actions></ol></section>'
                f'<section class="tn-sec">{_offre(page, pseudo, t)}</section></div>')
    data = {"q": [{"t": q["texte"], "p": q["pilier"], "r": [[a["texte"], a["points"]] for a in q["reponses"]]} for q in t["questions"] if q["reponses"]],
            "pil": [[p["nom"], p["conseil"]] for p in t["piliers"]], "niv": [[n["min"], n["titre"], n["texte"]] for n in t["niveaux"]],
            "mail": bool(em.get("actif")), "url": f"/@{pseudo}/t/{t['id']}/email", "apercu": apercu}
    js = """<script>(()=>{const D=%s,$=s=>document.querySelector(s),Q=document.getElementById("qz-q"),rep=[];
const voir=e=>{document.querySelectorAll(".qz-etape").forEach(x=>x.hidden=x.dataset.e!==e);scrollTo({top:0,behavior:"smooth"})};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function question(i){if(i>=D.q.length)return D.mail?voir("mail"):resultat();const q=D.q[i];voir("q");
$("#qz-n").textContent="Question "+(i+1)+" sur "+D.q.length;$("#qz-b").style.width=(i/D.q.length*100)+"%%";
Q.innerHTML='<p class="qz-q">'+esc(q.t)+'</p><div class="qz-rep">'+q.r.map((r,k)=>'<button data-k="'+k+'">'+esc(r[0])+'</button>').join("")+'</div>'+(i?'<button class="qz-retour" data-ret>← Question précédente</button>':'');
Q.querySelectorAll("[data-k]").forEach(b=>b.onclick=()=>{rep[i]=+b.dataset.k;question(i+1)});
const r=Q.querySelector("[data-ret]");if(r)r.onclick=()=>question(i-1)}
function resultat(){const n=D.pil.length,pts=Array(n).fill(0),max=Array(n).fill(0);
D.q.forEach((q,i)=>{const m=Math.max(...q.r.map(r=>r[1]),1);max[q.p]+=m;if(rep[i]!=null)pts[q.p]+=q.r[rep[i]][1]});
const pc=pts.map((p,i)=>max[i]?p/max[i]:0),tot=Math.round(pc.reduce((a,b)=>a+b,0)/n*100);
const ord=pc.map((v,i)=>[v,i]).sort((a,b)=>a[0]-b[0]);
const niv=D.niv.filter(x=>tot>=x[0]).pop()||D.niv[0]||[0,"",""];
$("[data-niv-titre]").textContent=niv[1];$("[data-niv-texte]").textContent=niv[2];
$("[data-piliers]").innerHTML=D.pil.map((p,i)=>'<div class="qz-pil'+(pc[i]<.45?' faible':'')+'"><div class="l"><span>'+esc(p[0])+'</span><span>'+Math.round(pc[i]*20)+'/20</span></div><div class="b"><i style="width:0" data-w="'+Math.round(pc[i]*100)+'"></i></div></div>').join("");
$("[data-bloque]").textContent=D.pil[ord[0][1]][0];$("[data-bloque-txt]").textContent=D.pil[ord[0][1]][1];
$("[data-actions]").innerHTML=ord.slice(0,3).map(([,i])=>'<li><b>'+esc(D.pil[i][0])+'</b> : '+esc(D.pil[i][1])+'</li>').join("");
voir("res");setTimeout(()=>document.querySelectorAll("[data-w]").forEach(x=>x.style.width=x.dataset.w+"%%"),80);
let c=0;const el=$("[data-total]"),pas=Math.max(1,Math.ceil(tot/40)),t=setInterval(()=>{c=Math.min(tot,c+pas);el.textContent=c;if(c>=tot)clearInterval(t)},25)}
document.querySelectorAll("[data-go]").forEach(b=>b.onclick=()=>question(0));
const f=document.querySelector("[data-mail]");if(f)f.onsubmit=async e=>{e.preventDefault();if(D.apercu)return resultat();const b=f.querySelector("button");b.disabled=true;
try{const r=await fetch(D.url,{method:"POST",body:new FormData(f)});const j=await r.json();if(!r.ok)throw new Error(j.erreur||"Erreur");resultat()}catch(er){b.disabled=false;alert(er.message)}}})()</script>""" % json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    question = ('<div class="qz-etape" data-e="q" hidden><div class="qz-num" id="qz-n"></div><div class="qz-barre"><i id="qz-b"></i></div>'
                '<div class="tn-carte" id="qz-q"></div></div>')
    return f'<div class="tn">{intro}{question}{mail}{resultat}</div>{js}'
