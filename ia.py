"""Tous les appels à Claude : analyse + adaptation, voix du client, classement des mécaniques."""

from __future__ import annotations

import base64
import concurrent.futures as cf
import time
from pathlib import Path

from modele import MECANIQUES, Post, log, nombre, pct

# ------------------------------------------------------------
#  Schémas de sortie (forcés via un outil : réponse toujours structurée)
# ------------------------------------------------------------
OUTIL_ADAPTATION = {
    "name": "enregistrer_adaptation",
    "description": "Enregistre l'analyse d'un Reel viral et son adaptation complète à la niche.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hook_original": {"type": "string", "description": "Le hook réel du Reel : ce qui est DIT et/ou ÉCRIT À L'ÉCRAN dans les 3 premières secondes (d'après la transcription et les images). Mot pour mot si possible."},
            "texte_ecran": {"type": "string", "description": "Le texte affiché à l'écran au début, s'il y en a (d'après les images). Vide sinon."},
            "analyse_visuelle": {"type": "string", "description": "Ce qu'on voit : cadrage, personne face caméra ou non, décor, sous-titres, rythme des plans, gestes."},
            "sujet": {"type": "string", "description": "De quoi parle le Reel, en une phrase."},
            "mecanique": {"type": "string", "enum": MECANIQUES, "description": "La mécanique principale du hook."},
            "pourquoi_ca_marche": {"type": "string", "description": "2-3 phrases : levier psychologique + éléments de format qui expliquent la viralité."},
            "structure": {"type": "string", "description": "Structure en étapes courtes avec timing approximatif (ex : 0-3 s hook → 3-15 s problème → …)."},
            "ce_que_dit_l_audience": {"type": "string", "description": "D'après les commentaires : ce qui a fait réagir, questions posées, objections, en 2-3 phrases. Vide s'il n'y a pas de commentaires."},
            "hooks_adaptes": {"type": "array", "items": {"type": "string"}, "description": "Hooks réécrits pour la niche, même mécanique, formulation originale."},
            "texte_ecran_adapte": {"type": "string", "description": "Le texte à afficher à l'écran pendant le hook (court, lisible sans le son)."},
            "script_reel": {"type": "string", "description": "Script adapté : [0-3 s] hook dit + texte écran / [corps] 3-5 phrases / [fin] CTA oral. 20 à 45 secondes."},
            "cta_conversation": {"type": "string", "description": "CTA qui déclenche une conversation : commenter le mot-clé (DM automatique) ou répondre à une question personnelle."},
            "sequence_dm": {
                "type": "array",
                "description": "Séquence de messages privés pour transformer le commentaire en conversation puis en client.",
                "items": {"type": "object", "properties": {
                    "etape": {"type": "string", "description": "Ex : « 1. Réponse automatique », « 2. Qualification (si elle répond) », « 3. Proposition », « Relance J+2 (si pas de réponse) »."},
                    "message": {"type": "string"}}, "required": ["etape", "message"]},
            },
            "legende_adaptee": {"type": "string", "description": "Légende complète prête à publier, avec CTA et 3-6 hashtags."},
            "format_conseille": {"type": "string", "description": "Format (face caméra, voix off, texte écran…) et durée."},
            "idee_visuelle": {"type": "string", "description": "Ce qu'on montre à l'écran dans les 3 premières secondes."},
            "pertinence": {"type": "integer", "description": "1 à 5 : à quel point ce Reel est transposable à la niche."},
        },
        "required": ["hook_original", "texte_ecran", "analyse_visuelle", "sujet", "mecanique", "pourquoi_ca_marche",
                     "structure", "ce_que_dit_l_audience", "hooks_adaptes", "texte_ecran_adapte", "script_reel",
                     "cta_conversation", "sequence_dm", "legende_adaptee", "format_conseille", "idee_visuelle", "pertinence"],
    },
}

OUTIL_VOIX_CLIENT = {
    "name": "enregistrer_voix_client",
    "description": "Synthèse de ce que dit l'audience dans les commentaires.",
    "input_schema": {
        "type": "object",
        "properties": {
            "questions": {"type": "array", "items": {"type": "string"}, "description": "Questions récurrentes, reformulées, de la plus fréquente à la moins fréquente (8 max)."},
            "douleurs": {"type": "array", "items": {"type": "string"}, "description": "Problèmes / frustrations exprimés (8 max)."},
            "objections": {"type": "array", "items": {"type": "string"}, "description": "Doutes, freins, « oui mais… » (6 max)."},
            "expressions": {"type": "array", "items": {"type": "string"}, "description": "Formulations exactes et typiques de la cible, à réutiliser telles quelles dans les hooks (10 max, courtes)."},
            "idees_reels": {"type": "array", "description": "Idées de Reels qui répondent directement à ces questions/douleurs.",
                            "items": {"type": "object", "properties": {"hook": {"type": "string"}, "pourquoi": {"type": "string"}},
                                      "required": ["hook", "pourquoi"]}},
        },
        "required": ["questions", "douleurs", "objections", "expressions", "idees_reels"],
    },
}

OUTIL_MECANIQUES = {
    "name": "classer_mecaniques",
    "description": "Classe chaque Reel dans une mécanique.",
    "input_schema": {
        "type": "object",
        "properties": {"classement": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "mecanique": {"type": "string", "enum": MECANIQUES}}, "required": ["id", "mecanique"]}}},
        "required": ["classement"],
    },
}


# ------------------------------------------------------------
#  Messages d'erreur compréhensibles
# ------------------------------------------------------------
def explique_erreur(e) -> str:
    t = str(e)
    bas = t.lower()
    if "credit balance" in bas or "billing" in bas or "insufficient" in bas:
        return ("Pas de crédit sur l'organisation de ta clé Claude. Vérifie dans la console Claude (Facturation) que la clé "
                "appartient bien à l'organisation qui a les 100 $ de crédits, sinon crée la clé dans la bonne organisation.")
    if "invalid x-api-key" in bas or "authentication" in bas or " 401" in t:
        return "La clé Claude est refusée : invalide, incomplète ou supprimée. Remplace-la dans les variables Railway."
    if "not_found" in bas or "model:" in bas or " 404" in t:
        return f"Le modèle Claude configuré n'est pas disponible pour cette clé ({t[:160]})."
    if "rate_limit" in bas or " 429" in t:
        return "Trop de requêtes vers Claude en même temps (limite de débit). Relance dans quelques minutes."
    if "overloaded" in bas or " 529" in t:
        return "Claude est momentanément surchargé. Relance dans quelques minutes."
    return t[:300]


# ------------------------------------------------------------
#  Client
# ------------------------------------------------------------
class IA:
    def __init__(self, cfg: dict, voix: str = "", apprentissages: str = ""):
        import anthropic
        self.client = anthropic.Anthropic()
        self.cfg = cfg
        self.modele = cfg["claude"]["modele"]
        self.systeme = self._systeme(voix, apprentissages)

    def _appel(self, outil: dict, contenu, max_tokens: int = 3000, systeme=None) -> dict:
        for essai in range(3):
            try:
                rep = self.client.messages.create(
                    model=self.modele, max_tokens=max_tokens,
                    system=systeme if systeme is not None else self.systeme,
                    tools=[outil], tool_choice={"type": "tool", "name": outil["name"]},
                    messages=[{"role": "user", "content": contenu}],
                )
                for bloc in rep.content:
                    if bloc.type == "tool_use":
                        return bloc.input
                raise ValueError("Réponse sans outil")
            except Exception as e:  # noqa: BLE001
                if essai == 2:
                    return {"erreur": explique_erreur(e)}
                time.sleep(5 * (essai + 1))
        return {}

    def _systeme(self, voix: str, apprentissages: str) -> list:
        n, o = self.cfg["niche"], self.cfg["objectifs"]
        texte = f"""Tu es stratège de contenu social media, spécialiste des Reels viraux Instagram et TikTok.

Tu analyses des Reels qui ont surperformé chez d'autres comptes, puis tu les transposes à cette marque :
- Marque : {n['nom']}
- Niche : {n['description'].strip()}
- Client idéal : {n['cible']}
- Ses problèmes : {'; '.join(n.get('douleurs') or []) or 'non précisés'}
- Ton : {n['ton']}
- Offre : {n['offre']}
- Interdits : {n['interdits'].strip()}
- Langue de sortie : {n['langue']}

Objectif business : {o['reels_par_jour']} Reels par jour, au moins {o['conversations_par_jour']} conversations privées par jour.
Chaque Reel se termine par un CTA qui fait commenter le mot-clé « {o['mot_cle_cta']} » (DM automatique) ou répondre à une question personnelle. Les vues ne suffisent pas : on veut des conversations avec le client idéal, puis des clients.

Règles :
1. Reprends la MÉCANIQUE (type de hook, structure, levier émotionnel, format visuel), jamais le texte. Pas de copie, pas de paraphrase proche.
2. Le vrai hook est dans les 3 premières secondes : utilise la transcription et les images pour l'identifier. Si tu n'as que la légende, dis-le dans l'analyse.
3. Hooks : moins de 12 mots, compréhensibles sans le son, pas d'emoji en début. Réutilise les expressions de l'audience quand c'est pertinent.
4. Script dit face caméra, naturel, comme à une amie. Légende naturelle, phrases courtes, rien qui sonne « publicité » ou « écrit par une IA ».
5. Séquence DM : 3 à 4 messages courts. Le 1er livre ce qui a été promis et pose une question ouverte. On qualifie avant de proposer. Jamais de pression, jamais de promesse de résultat.
6. Respect strict des interdits de la marque.
7. Note de pertinence honnête."""
        blocs = [{"type": "text", "text": texte}]
        if voix.strip():
            blocs.append({"type": "text", "text": "VOIX DE LA MARQUE — exemples réels de ses textes. Imite ce ton, ce vocabulaire, cette longueur de phrases, cette ponctuation et cet usage des emojis. Ne réutilise pas ces phrases telles quelles.\n\n" + voix.strip()})
        if apprentissages.strip():
            blocs.append({"type": "text", "text": "CE QUI MARCHE SUR LE COMPTE DE LA MARQUE (données réelles) — privilégie ces mécaniques et formats dans tes adaptations :\n\n" + apprentissages.strip()})
        blocs[-1]["cache_control"] = {"type": "ephemeral"}  # mis en cache : moins cher sur les 20 appels
        return blocs

    # --------------------------------------------------------
    def adapte(self, p: Post) -> dict:
        nb = self.cfg["claude"]["hooks_par_post"]
        coms = "\n".join(f"- ({c['likes']} ❤) {c['texte'][:250]}" for c in p.commentaires_texte[:40]) or "(aucun)"
        texte = f"""Reel viral à analyser puis adapter.

Plateforme : {p.plateforme} · @{p.compte} · durée {round(p.duree_s) if p.duree_s else '?'} s
Performance : {nombre(p.vues) or 'n/a'} vues ({p.score_viral}× la médiane du compte) · engagement {pct(p.taux_engagement)} · commentaires/vues {pct(p.taux_commentaires)} · {nombre(p.commentaires)} commentaires · {nombre(p.partages)} partages · {nombre(p.enregistrements)} enregistrements

TRANSCRIPTION DE L'AUDIO :
\"\"\"{p.transcription or '(non disponible)'}\"\"\"

LÉGENDE :
\"\"\"{p.legende[:2500] or '(vide)'}\"\"\"

COMMENTAIRES LES PLUS LIKÉS :
{coms}

{"IMAGES CLÉS jointes, dans l'ordre : 0,3 s / 1,5 s / 3 s / suite de la vidéo." if p.images else "(pas d'images disponibles)"}

Propose {nb} hooks adaptés. Remplis l'outil enregistrer_adaptation."""
        contenu = []
        for chemin in p.images[:6]:
            try:
                data = base64.b64encode(Path(chemin).read_bytes()).decode()
                contenu.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
            except OSError:
                pass
        contenu.append({"type": "text", "text": texte})
        return self._appel(OUTIL_ADAPTATION, contenu, max_tokens=4000)

    def adapte_tous(self, posts: list[Post]):
        log(f"Analyse et adaptation par Claude de {len(posts)} Reels…")
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(self.adapte, p): p for p in posts}
            for i, f in enumerate(cf.as_completed(futures), 1):
                futures[f].adaptation = f.result()
                if i % 5 == 0 or i == len(posts):
                    log(f"  {i}/{len(posts)}")
        erreurs = [p for p in posts if p.adaptation.get("erreur")]
        if erreurs:
            log(f"  ⚠️  {len(erreurs)} adaptation(s) en erreur : {erreurs[0].adaptation['erreur'][:300]}")
        if posts and len(erreurs) == len(posts):
            # Rien n'a marché : on arrête avec le vrai motif au lieu d'afficher une analyse vide
            raise RuntimeError("Aucun Reel n'a pu être adapté. " + erreurs[0].adaptation["erreur"])

    # --------------------------------------------------------
    def voix_client(self, posts: list[Post]) -> dict:
        lignes = [f"[{p.compte}] ({c['likes']} ❤) {c['texte'][:200]}" for p in posts for c in p.commentaires_texte]
        if len(lignes) < 15:
            return {}
        log(f"Synthèse de la voix du client ({len(lignes)} commentaires)…")
        n = self.cfg["niche"]
        texte = (f"Voici des commentaires laissés sous des Reels viraux de la niche « {n['description'].strip()} ». "
                 f"Client idéal : {n['cible']}.\n\nSynthétise ce que dit l'audience : questions, douleurs, objections, "
                 f"expressions typiques, et propose 6 idées de Reels en {n['langue']} qui y répondent (hooks dans le ton de la marque).\n\n"
                 + "\n".join(lignes[:600]))
        return self._appel(OUTIL_VOIX_CLIENT, texte, max_tokens=3000)

    def classe_mecaniques(self, posts: list[Post]) -> dict[str, str]:
        if not posts:
            return {}
        texte = "Classe chacun de ces Reels dans sa mécanique principale, d'après sa légende et sa transcription.\n\n" + "\n\n".join(
            f"id={p.id}\nlégende: {p.legende[:400]}\ntranscription: {p.transcription[:400]}" for p in posts)
        res = self._appel(OUTIL_MECANIQUES, texte, max_tokens=4000, systeme="Tu es analyste de contenu social media.")
        return {c["id"]: c["mecanique"] for c in res.get("classement", [])}


# ------------------------------------------------------------
#  Assistant de configuration
# ------------------------------------------------------------
OUTIL_PROFIL = {
    "name": "proposer_profil",
    "description": "Propose un profil de marque à partir des Reels d'un compte.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nom_marque": {"type": "string"},
            "description_niche": {"type": "string", "description": "2 phrases : ce que fait la marque, pour qui, quel résultat."},
            "cible": {"type": "string", "description": "Le client idéal en une phrase (âge, situation, problème principal)."},
            "douleurs": {"type": "array", "items": {"type": "string"}, "description": "4 à 6 problèmes que vit la cible."},
            "ton": {"type": "string", "description": "Le ton observé dans les légendes, en quelques mots (ex. « Chaleureux, cash, tutoiement, un peu d'humour »)."},
            "guide_voix": {"type": "array", "items": {"type": "string"}, "description": "5 à 8 constats concrets sur sa façon d'écrire, pour qu'un rédacteur puisse l'imiter : longueur des phrases, façon d'ouvrir et de conclure, ponctuation, usage des emojis et des hashtags, tutoiement ou vouvoiement, mots et tournures qui reviennent, niveau de langue. Uniquement ce qui est observé dans les légendes."},
            "expressions_signature": {"type": "array", "items": {"type": "string"}, "description": "3 à 6 expressions ou formules qu'il emploie vraiment, citées telles quelles depuis ses légendes."},
            "offre": {"type": "string", "description": "Ce que la marque semble vendre ou offrir (lead magnet, accompagnement…). Vide si inconnu."},
            "hashtags": {"type": "array", "items": {"type": "string"}, "description": "8 hashtags de la niche, sans #, pour trouver des comptes similaires."},
            "points_forts": {"type": "array", "items": {"type": "string"}, "description": "3 constats sur ce qui marche dans ses Reels."},
            "a_ameliorer": {"type": "array", "items": {"type": "string"}, "description": "3 pistes concrètes d'amélioration."},
        },
        "required": ["nom_marque", "description_niche", "cible", "douleurs", "ton", "guide_voix", "expressions_signature", "offre", "hashtags", "points_forts", "a_ameliorer"],
    },
}

OUTIL_HASHTAGS = {
    "name": "proposer_hashtags",
    "description": "Hashtags d'une niche.",
    "input_schema": {"type": "object", "properties": {
        "instagram": {"type": "array", "items": {"type": "string"}, "description": "8 hashtags Instagram, sans #."},
        "tiktok": {"type": "array", "items": {"type": "string"}, "description": "8 hashtags TikTok, sans #."}},
        "required": ["instagram", "tiktok"]},
}


def propose_profil(cfg: dict, posts: list[Post], resume_chiffres: str, bio: dict | None = None) -> dict:
    ia = IA.__new__(IA)
    import anthropic
    ia.client, ia.cfg, ia.modele, ia.systeme = anthropic.Anthropic(), cfg, cfg["claude"]["modele"], ""
    profils = []
    for plat, b in (bio or {}).items():
        profils.append(f"PROFIL {plat.upper()}\nNom affiché : {b.get('nom') or '-'}\nBio : {b.get('bio') or '-'}\n"
                       f"Lien en bio : {b.get('lien') or '-'}\nAbonnés : {b.get('abonnes') or '-'}\nCatégorie : {b.get('categorie') or '-'}")
    entete = ("\n\n".join(profils) + "\n\nLa bio est la source la plus fiable pour le nom de marque, la promesse, la cible "
              "et l'offre (lien en bio, ressource gratuite, appel à l'action). Les légendes servent surtout pour le ton, la voix et les douleurs de la cible.\n\n") if profils else ""
    texte = (entete + f"Voici les Reels récents du compte ({resume_chiffres}). Déduis-en son profil de marque, en "
             f"{cfg['niche'].get('langue', 'français')}.\n\n" + "\n\n".join(
                 f"[{p.vues or 0} vues, {p.commentaires or 0} commentaires, mécanique : {(p.adaptation or {}).get('mecanique', '?')}]\n{p.legende[:900]}"
                 for p in posts[:40]))
    return ia._appel(OUTIL_PROFIL, texte, max_tokens=2500, systeme="Tu es stratège de marque pour créateurs de contenu.")


def propose_hashtags(cfg: dict) -> dict:
    ia = IA.__new__(IA)
    import anthropic
    ia.client, ia.cfg, ia.modele, ia.systeme = anthropic.Anthropic(), cfg, cfg["claude"]["modele"], ""
    n = cfg["niche"]
    texte = f"Niche : {n['description']}\nCible : {n['cible']}\nLangue du marché : {n.get('langue', 'français')}\nPropose des hashtags où publient les comptes qui cartonnent dans cette niche."
    return ia._appel(OUTIL_HASHTAGS, texte, max_tokens=800, systeme="Tu es expert Instagram et TikTok.")
