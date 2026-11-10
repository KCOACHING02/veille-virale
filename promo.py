"""Compte de l'administrateur préparé pour promouvoir Virallink sur Instagram.

Un clic dans l'administration remplit le profil de marque, la voix, les niches de la bibliothèque et les infos de vente
du plan du mois avec ce que Virallink propose vraiment. L'administrateur crée ensuite ses Reels, carrousels et stories
avec le Studio, comme une cliente. Aucun témoignage ni chiffre inventé : ils restent vides tant qu'il n'y en a pas de vrais.
"""

from __future__ import annotations

import plan30
from espace import Espace

COMPTE = "virallink.app"  # compte Instagram de Virallink (choisi par Mohamed le 10 novembre 2026)

NICHE = {
    "nom": "Virallink : vendre sur Instagram",
    "description": "Virallink est une application française pour vendre sur Instagram : une boutique gratuite en lien dans la bio "
                   "(produits numériques, séances, liens d'affiliation, capture d'e-mails), les publications qui cartonnent "
                   "en ce moment dans sa niche, réécrites pour son audience, et un studio qui fabrique carrousels, Reels "
                   "sous-titrés, stories animées et un plan de 30 jours jusqu'à son offre.",
    "cible": "Créatrices, coachs, formatrices et entrepreneuses qui vendent (ou veulent vendre) un produit ou un service "
             "grâce à Instagram, sans équipe ni budget pub",
    "douleurs": [
        "Elle passe des heures à chercher quoi publier, et ses publications ne font presque pas de vues",
        "Elle a des abonnées mais presque aucune vente : son lien en bio ne mène à rien de clair",
        "Elle jongle entre cinq outils (Canva, Linktree, Stan, ManyChat, CapCut) et n'avance pas",
    ],
    "ton": "Complice, direct et concret, tutoiement. Phrases courtes. On montre l'outil en action plutôt que de le vanter.",
    "langue": "français",
    "offre": "Boutique en lien dans la bio gratuite, sans limite de durée et sans commission ; tout Virallink à essayer "
             "7 jours sans carte bancaire ; formule Créateur à 29,90 €/mois",
    "interdits": "Pas de promesse de revenus ni de résultat chiffré ou rapide. Pas de faux témoignage, pas de chiffre inventé "
                 "(abonnées, ventes, clientes). Ne jamais citer les outils techniques utilisés en coulisses : l'IA s'appelle Virall.ai. "
                 "Pas de dénigrement nominatif des autres outils.",
}

MARQUE = {
    "adresse": "tu", "emojis": "peu", "longueur": "moyenne",
    "mise_en_forme": ["phrases courtes", "sauts de ligne entre les idées", "une question au lecteur"],
    "signature": "Ta boutique gratuite : lien dans la bio ✨",
    "expressions": "« Tout pour vendre sur Instagram », « ta boutique en lien dans la bio », « ce qui cartonne dans ta niche »",
    "mots_interdits": "révolutionnaire, game changer, incroyable, booster, plonger, dans un monde où",
    "hashtags": "#venteinstagram #entrepreneuse #coachenligne #produitsnumeriques #instagramfrance",
    "consignes": "Chaque contenu montre une seule fonction de Virallink et finit par une seule action : créer sa boutique "
                 "gratuite (lien dans la bio) ou commenter un mot-clé. Exemples concrets du quotidien d'une créatrice.",
    "couleurs": {"fond": "#271B2D", "texte": "#FFFFFF", "accent": "#FF5C84"},
}

VOIX = """# Ma voix (Virallink)

- Je parle à une créatrice ou une coach qui vend sur Instagram, comme une amie qui s'y connaît : tutoiement, phrases courtes.
- Je pars d'une situation vécue (« Tu publies tous les jours et rien ne bouge ? »), puis je montre la solution dans Virallink, écran à l'appui.
- Une idée par publication, un seul appel à l'action à la fin : « Crée ta boutique gratuite, lien dans la bio » ou « Commente BOUTIQUE ».
- Pas de jargon marketing, pas de promesse de revenus, pas de chiffres inventés.
- Peu d'emojis, jamais en rafale.
"""

BRIEF = {
    "produit": "Virallink : boutique gratuite en lien dans la bio + les publications qui cartonnent dans ta niche, réécrites pour toi",
    "prix": "Boutique gratuite ; tout Virallink 7 jours gratuits, puis 29,90 €/mois",
    "lien": "virallink.fr (lien dans la bio)",
    "transformation": "Une boutique en ligne en quelques minutes, et chaque semaine des contenus prêts à publier qui amènent "
                      "des visites vers ce que tu vends",
    "cible": NICHE["cible"],
    "problemes": NICHE["douleurs"],
    "objections": [
        "Je n'ai pas encore de produit à vendre",
        "Je ne suis pas à l'aise avec la technique",
        "Encore un abonnement de plus",
    ],
    "temoignages": [], "accord_temoignages": False, "resultats": [],
    "ton": "Complice", "tutoiement": "tu", "emojis": "quelques",
}


def prepare(esp: Espace, bid=None) -> dict:
    """Remplit le profil, la voix, les niches et le brief du plan du mois. Ne touche ni aux comptes suivis ni aux créations."""
    cfg = esp.lit_config()
    cfg["niche"] = {**(cfg.get("niche") or {}), **NICHE}
    cfg["marque"] = {**(cfg.get("marque") or {}), **MARQUE}
    cfg.setdefault("bibliotheque", {})["niches"] = ["marketing", "business"]
    cfg.setdefault("mon_compte", {})["instagram"] = COMPTE  # signature @ des carrousels, Reels et stories
    esp.ecrit_config(cfg)
    esp.voix.write_text(VOIX, encoding="utf-8")
    # L'histoire du fondateur n'est jamais inventée ni reprise d'un ancien brief (autre produit) : le plan du mois la redemande
    b = plan30.sauve_brief(esp, {**BRIEF, "histoire": ""}, bid)
    # Les plans faits pour une autre offre sont rangés (pas effacés) : le Studio repart sur un plan Virallink
    racine = esp.racine / "plan30"
    archives = racine / "archives"
    for f in racine.glob("*.json"):
        if not f.name.startswith("brief"):
            archives.mkdir(exist_ok=True)
            f.replace(archives / f.name)
    return {"ok": True, "histoire_a_ecrire": not (b.get("histoire") or "").strip()}
