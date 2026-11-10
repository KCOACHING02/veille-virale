"""Compte de l'administrateur préparé pour promouvoir Virallink sur Instagram.

Un clic dans l'administration remplit le profil de marque, la voix, les niches de la bibliothèque et les infos de vente
du plan du mois avec ce que Virallink propose vraiment. L'administrateur crée ensuite ses Reels, carrousels et stories
avec le Studio, comme une cliente. Aucun témoignage ni chiffre inventé : ils restent vides tant qu'il n'y en a pas de vrais.
"""

from __future__ import annotations

import boutique as bq
import plan30
from pathlib import Path

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


def prepare(esp: Espace, uid: int) -> dict:
    """Remplit le profil, la voix, les niches et le brief du plan du mois. Ne touche ni aux comptes suivis ni aux créations."""
    cfg = esp.lit_config()
    cfg["niche"] = {**(cfg.get("niche") or {}), **NICHE}
    cfg["marque"] = {**(cfg.get("marque") or {}), **MARQUE}
    cfg.setdefault("bibliotheque", {})["niches"] = ["marketing", "business"]
    cfg["visuels_marque"] = "promo"  # captures de Virallink (static/promo) à la place de la banque d'images
    cfg.setdefault("mon_compte", {})["instagram"] = COMPTE  # signature @ des carrousels, Reels et stories
    esp.ecrit_config(cfg)
    esp.voix.write_text(VOIX, encoding="utf-8")
    # L'histoire du fondateur n'est jamais inventée ni reprise d'un ancien brief (autre produit) : le plan du mois la redemande
    bid = boutique(uid)
    page = bq.lit_page(bid) or {}
    ids = ",".join(x["id"] for x in page.get("produits") or [])
    b = plan30.sauve_brief(esp, {**BRIEF, "histoire": "", "produit_id": ids,
                                 "produits": [f"{x['titre']} ({x['prix'] / 100:.2f} €)".replace(".", ",") if x["prix"] else f"{x['titre']} (gratuit)"
                                              for x in page.get("produits") or []]}, bid)
    # Les plans faits pour une autre offre sont rangés (pas effacés) : le Studio repart sur un plan Virallink
    racine = esp.racine / "plan30"
    archives = racine / "archives"
    for f in racine.glob("*.json"):
        if not f.name.startswith("brief"):
            archives.mkdir(exist_ok=True)
            f.replace(archives / f.name)
    return {"ok": True, "bid": str(bid), "pseudo": bq.pseudo_de(bid), "histoire_a_ecrire": not (b.get("histoire") or "").strip()}


# ------------------------------------------------------------
#  Boutique « Virallink » de l'administrateur : ce que vendent ses publications (le plan du mois choisit parmi ces produits)
# ------------------------------------------------------------
NOM_BOUTIQUE = "Virallink"
PSEUDOS = ("virallink", "virallink.app", "virallink-app")
PRODUITS = [
    {"titre": "Ta boutique en lien dans la bio, gratuite", "sous_titre": "Gratuite, sans limite de durée et sans commission",
     "prix": 0, "lien": "https://www.virallink.fr/connexion?offre=boutique", "bouton": "Créer ma boutique"},
    {"titre": "Virallink Créateur : 7 jours gratuits", "sous_titre": "Ce qui cartonne dans ta niche, écrit pour toi, et le Studio. Puis 29,90 €/mois",
     "prix": 2990, "lien": "https://www.virallink.fr/connexion", "bouton": "Essayer 7 jours"},
]


def boutique(uid: int):
    """La boutique « Virallink » de l'administrateur : retrouvée, ou créée avec ses deux offres (liens vers le site, sans paiement Stripe)."""
    for b in bq.boutiques_de(uid):
        page = bq.lit_page(b) or {}
        if page.get("nom") == NOM_BOUTIQUE and page.get("promo_virallink"):
            return b
    bid = bq.nouvelle_boutique(uid)
    if bq.lit_page(bid):  # sa première boutique existe déjà (autre activité) : on en ouvre une autre
        bid = bq.nouvelle_boutique(uid)
    for ps in PSEUDOS:
        if not bq.reserve_pseudo(bid, ps):
            break
    page = bq.page_initiale(uid, None, NOM_BOUTIQUE)
    page.update(nom=NOM_BOUTIQUE, publie=True, promo_virallink=True, reseaux={"instagram": COMPTE},
                bio="Tout pour vendre sur Instagram ✨ Ta boutique en lien dans la bio, et ce qui cartonne dans ta niche, écrit pour toi.")
    page["produits"] = [{"id": bq.nouvel_id(), "visible": True, "description": "", "prix_barre": 0, "devise": "eur", "image": "",
                         "type": "telechargement", "externe": True, "mot_cle": "", "inclus": [], **x} for x in PRODUITS]
    page["blocs"] = [{"id": "b1", "type": "produits", "visible": True, "titre": "Commence ici"}]
    page["design"].update({"fond1": "#271B2D", "fond2": "#271B2D", "texte": "#FFFFFF", "bouton_fond": "#FF5C84", "bouton_texte": "#FFFFFF",
                           "bloc_fond": "#33253A", "bloc_texte": "#FFFFFF", "accent": "#FF5C84"})
    try:  # le logo de Virallink en photo de la boutique
        with open(Path(__file__).resolve().parent / "static" / "icones" / "icone-512.png", "rb") as f:
            page["photo"] = bq.enregistre_image(bid, f, 512)
    except Exception:  # noqa: BLE001
        pass
    bq.ecrit_page(bid, page)
    return bid
