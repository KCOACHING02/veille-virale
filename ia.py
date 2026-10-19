"""Tous les appels à Claude : analyse + adaptation, voix du client, classement des mécaniques."""

from __future__ import annotations

import base64
import json
import concurrent.futures as cf
import time
from pathlib import Path

from modele import MECANIQUES, TYPES_CONTENU, Post, log, nombre, pct

# ------------------------------------------------------------
#  Schémas de sortie (forcés via un outil : réponse toujours structurée)
# ------------------------------------------------------------
OUTIL_ADAPTATION = {
    "name": "enregistrer_adaptation",
    "description": "Enregistre l'analyse d'un Reel viral et son adaptation complète à la niche.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hook_original": {"type": "string", "description": "Le hook réel du Reel, MOT POUR MOT dans sa langue d'origine : ce qui est DIT et/ou ÉCRIT À L'ÉCRAN dans les 3 premières secondes (d'après la transcription et les images)."},
            "langue_originale": {"type": "string", "description": "Langue du Reel original, en un mot en français (ex. « français », « anglais », « arabe »)."},
            "hook_viral": {"type": "string", "description": "Le hook à reprendre : identique au hook original s'il est déjà dans la langue de la marque, sinon sa traduction FIDÈLE (même sens, même rythme, même construction, aucune réécriture)."},
            "legende_reprise": {"type": "string", "description": "La légende originale reprise telle quelle si elle est déjà dans la langue de la marque ; sinon sa traduction FIDÈLE, complète, en gardant la mise en forme, les emojis et les hashtags (hashtags traduits seulement s'ils ont un équivalent courant)."},
            "texte_ecran": {"type": "string", "description": "Le texte affiché à l'écran au début, s'il y en a (d'après les images). Vide sinon."},
            "analyse_visuelle": {"type": "string", "description": "Ce qu'on voit : cadrage, personne face caméra ou non, décor, sous-titres, rythme des plans, gestes."},
            "sujet": {"type": "string", "description": "De quoi parle le Reel, en une phrase."},
            "mecanique": {"type": "string", "enum": MECANIQUES, "description": "La mécanique principale du hook."},
            "pourquoi_ca_marche": {"type": "string", "description": "2-3 phrases : levier psychologique + éléments de format qui expliquent la viralité."},
            "structure": {"type": "string", "description": "Structure en étapes courtes avec timing approximatif (ex : 0-3 s hook → 3-15 s problème → …)."},
            "hooks_adaptes": {"type": "array", "items": {"type": "string"}, "description": "Variantes du hook adaptées à la niche de la marque (même mécanique), proposées en complément du hook viral repris."},
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
            "slides_modele": {
                "type": "array",
                "description": "UNIQUEMENT pour un carrousel : une entrée par slide du modèle, dans l'ordre, exactement autant que de slides jointes. Vide pour un Reel.",
                "items": {"type": "object", "properties": {
                    "original": {"type": "string", "description": "Le texte lu sur la slide, recopié tel quel (traduit fidèlement s'il n'est pas dans la langue de la marque). Vide s'il n'y a pas de texte."},
                    "visuel": {"type": "string", "description": "Ce qu'on voit : photo de quoi, fond, mise en page, place du texte."},
                    "adapte": {"type": "string", "description": "Le texte de cette slide pour la marque : même rôle et même longueur que l'original. Slide 1 : le hook viral repris tel quel."},
                    "photo": {"type": "string", "description": "La photo que la marque doit prendre elle-même pour reproduire cette slide, décrite concrètement. Vide si la slide est un fond uni avec du texte."},
                    "recherche": {"type": "string", "description": "3 à 5 mots-clés EN ANGLAIS pour trouver une photo libre de droits équivalente dans une banque d'images (ex. « woman holding belly morning light »). Vide si pas de photo."},
                    "sous_titre": {"type": "string", "description": "Si la slide a une petite ligne secondaire (ex. « Here's exactly what I'd do »), sa version adaptée/traduite. Sinon vide. Le texte « adapte » ne contient alors que le titre."},
                    "mise_en_page": {"type": "object", "description": "Où et comment le texte est posé sur la slide du modèle.", "properties": {
                        "position": {"type": "string", "enum": ["haut", "centre", "bas"]},
                        "alignement": {"type": "string", "enum": ["gauche", "centre"]},
                        "accent": {"type": "string", "description": "Le mot ou l'expression du texte ADAPTÉ mis en valeur comme dans le modèle (autre police, italique, couleur), recopié exactement tel qu'il figure dans « adapte ». Vide si aucun."},
                        "style_accent": {"type": "string", "enum": ["italique", "manuscrit", "couleur", "aucun"]}}}},
                    "required": ["original", "visuel", "adapte", "photo"]},
            },
            "style_visuel": {"type": "string", "description": "UNIQUEMENT pour un carrousel : le style du modèle en une phrase (couleurs, type de police, mise en page, photo ou fond uni)."},
            "typo_conseillee": {"type": "string", "enum": ["moderne", "geometrique", "minimal", "douce", "impact", "affiche", "brut", "elegant", "classique", "retro", "manuscrit", "signature"],
                                "description": "UNIQUEMENT pour un carrousel : la police du studio la plus proche de celle du modèle (moderne = sans-serif ronde, geometrique = sans-serif large, minimal = sans-serif technique, douce = arrondie, impact/affiche = capitales condensées, brut = très épaisse, elegant/classique/retro = à empattements, manuscrit/signature = écriture)."},
            "theme_conseille": {"type": "string", "enum": ["sombre", "clair", "rose"], "description": "UNIQUEMENT pour un carrousel : fond le plus proche du modèle (sombre, clair ou coloré)."},
        },
        "required": ["hook_original", "langue_originale", "hook_viral", "legende_reprise", "texte_ecran", "analyse_visuelle", "sujet", "mecanique", "pourquoi_ca_marche",
                     "structure", "hooks_adaptes", "texte_ecran_adapte", "script_reel",
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

OUTIL_TYPES = {
    "name": "classer_types",
    "description": "Donne le type de chaque publication : le rôle qu'elle joue auprès de l'audience.",
    "input_schema": {
        "type": "object",
        "properties": {"classement": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "type": {"type": "string", "enum": TYPES_CONTENU, "description":
                     "Éducatif : apprend quelque chose (astuces, erreurs, tutoriel). Storytelling : raconte une histoire vécue. "
                     "Inspirant : motive, citation, transformation. Divertissant : humour, tendance, POV pour faire rire ou réagir. "
                     "Commercial : met en avant une offre, un produit, un appel à acheter ou à s'inscrire. "
                     "Preuve sociale : témoignage, résultat client, avant/après d'un client. Coulisses : quotidien, journée, envers du décor."}},
            "required": ["id", "type"]}}},
        "required": ["classement"],
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
#  Coût Claude (estimé d'après les jetons consommés ; tarif à ajuster si besoin)
# ------------------------------------------------------------
PRIX_ENTREE_M, PRIX_SORTIE_M = 2.0, 10.0   # $ par million de jetons
_JETONS = {"in": 0, "out": 0}


def cout_claude_reinitialise():
    _JETONS["in"] = _JETONS["out"] = 0


def cout_claude() -> float:
    return _JETONS["in"] / 1e6 * PRIX_ENTREE_M + _JETONS["out"] / 1e6 * PRIX_SORTIE_M


def _compte(rep):
    u = getattr(rep, "usage", None)
    if u:
        _JETONS["in"] += (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) \
            + int((getattr(u, "cache_read_input_tokens", 0) or 0) * 0.1)
        _JETONS["out"] += getattr(u, "output_tokens", 0) or 0


OUTIL_CARROUSEL = {
    "name": "enregistrer_carrousel",
    "description": "Textes d'un carrousel Instagram prêt à publier.",
    "input_schema": {
        "type": "object",
        "properties": {
            "slides": {
                "type": "array",
                "description": "Les slides dans l'ordre. La 1re porte le hook, la dernière le CTA mot-clé.",
                "items": {"type": "object", "properties": {
                    "titre": {"type": "string", "description": "Texte principal de la slide, très lisible : 3 à 10 mots."},
                    "texte": {"type": "string", "description": "Précision optionnelle sous le titre : 0 à 25 mots. Vide sur la 1re slide."},
                    "photo": {"type": "string", "description": "La photo à mettre en fond de cette slide, décrite concrètement pour que la personne la prenne elle-même (ex. « toi de profil devant ton miroir, lumière du matin »). Vide si la slide est sur fond uni."},
                    "recherche": {"type": "string", "description": "3 à 5 mots-clés EN ANGLAIS pour trouver une photo libre de droits équivalente (ex. « woman mirror morning light »). Vide si pas de photo."}},
                    "required": ["titre", "texte", "photo"]},
            },
            "legende": {"type": "string", "description": "Légende prête à publier, avec le CTA et 3 à 6 hashtags à la fin."},
            "script": {"type": "string", "description": "Uniquement pour un Reel : script à dire face caméra ou en voix off, [0-3 s] hook / [corps] / [fin] CTA, 20 à 45 secondes."},
        },
        "required": ["slides", "legende"],
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
#  Format d'écriture choisi par la marque (Réglages → Ta marque)
# ------------------------------------------------------------
def regles_marque(cfg: dict) -> str:
    """Consignes d'écriture saisies par l'utilisateur. Elles priment sur les règles générales de style."""
    m = cfg.get("marque") or {}
    lignes = []
    if m.get("adresse") in ("tu", "vous"):
        lignes.append("Toujours tutoyer le lecteur." if m["adresse"] == "tu" else "Toujours vouvoyer le lecteur.")
    lignes.append({"aucun": "Aucun emoji.", "peu": "Quelques emojis seulement (1 à 3 par légende, jamais dans le hook).",
                   "beaucoup": "Des emojis réguliers, en début de ligne ou pour rythmer, comme dans ses exemples."}.get(m.get("emojis"), ""))
    lignes.append({"courte": "Légendes courtes : 2 à 4 lignes.", "moyenne": "Légendes de longueur moyenne : 5 à 10 lignes.",
                   "longue": "Légendes longues et détaillées (mini-article), aérées."}.get(m.get("longueur"), ""))
    if m.get("mise_en_forme"):
        lignes.append("Mise en forme : " + ", ".join(m["mise_en_forme"]) + ".")
    if (m.get("signature") or "").strip():
        lignes.append(f"Termine les légendes par sa signature habituelle (adaptée si besoin au CTA) : « {m['signature'].strip()} ».")
    if (m.get("expressions") or "").strip():
        lignes.append(f"Expressions et mots qu'elle/il utilise (à placer avec naturel, sans en abuser) : {m['expressions'].strip()}.")
    if (m.get("mots_interdits") or "").strip():
        lignes.append(f"Mots et formulations à ne JAMAIS employer : {m['mots_interdits'].strip()}.")
    if (m.get("hashtags") or "").strip():
        lignes.append(f"Hashtags à toujours ajouter en fin de légende : {m['hashtags'].strip()}.")
    if (m.get("consignes") or "").strip():
        lignes.append("Autres consignes de la marque : " + m["consignes"].strip())
    lignes = [l for l in lignes if l]
    if not lignes:
        return ""
    return ("FORMAT D'ÉCRITURE DE LA MARQUE — choisi par la marque elle-même ; il prime sur les règles générales de style "
            "(mais jamais sur la reprise fidèle du hook viral et de la légende originale) :\n- " + "\n- ".join(lignes))


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
        """
        Appel à Claude avec réponse structurée par l'outil `outil`.
        Le choix d'outil est laissé en « auto » (certains modèles refusent un outil imposé) et une consigne explicite
        demande d'appeler l'outil ; en secours, un JSON écrit en texte est accepté.
        """
        import json as _json
        sys_ = systeme if systeme is not None else self.systeme
        consigne = f"Réponds uniquement en appelant l'outil « {outil['name']} », sans aucun texte autour."
        sys_ = (sys_ + "\n\n" + consigne) if isinstance(sys_, str) else [*sys_, {"type": "text", "text": consigne}]
        derniere = None
        for essai in range(3):
            try:
                rep = self.client.messages.create(
                    model=self.modele, max_tokens=max_tokens, system=sys_,
                    tools=[outil], tool_choice={"type": "auto"},
                    messages=[{"role": "user", "content": contenu}],
                )
                _compte(rep)
                for bloc in rep.content:
                    if getattr(bloc, "type", "") == "tool_use":
                        return bloc.input
                texte = "".join(getattr(b, "text", "") for b in rep.content)
                debut, fin = texte.find("{"), texte.rfind("}")
                if debut >= 0 and fin > debut:
                    try:
                        return _json.loads(texte[debut:fin + 1])
                    except ValueError:
                        pass
                raise ValueError("Claude n'a pas renvoyé de réponse structurée")
            except Exception as e:  # noqa: BLE001
                derniere = e
                bas = str(e).lower()
                if any(x in bas for x in ("invalid x-api-key", "credit balance", "not supported", "invalid_request")):
                    break  # inutile de réessayer une erreur de configuration
                if essai < 2:
                    time.sleep(5 * (essai + 1))
        return {"erreur": explique_erreur(derniere)}

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
1. REPRISE FIDÈLE : le hook viral et la légende sont repris tels quels (champs hook_viral et legende_reprise). S'ils ne sont pas en {n['langue']}, traduis-les fidèlement, sans les réécrire ni les « améliorer ». Les variantes de hooks, le script, le CTA et la séquence DM sont, eux, adaptés à la marque.
2. Le vrai hook est dans les 3 premières secondes : utilise la transcription et les images pour l'identifier. Si tu n'as que la légende, dis-le dans l'analyse.
3. Hooks : moins de 12 mots, compréhensibles sans le son, pas d'emoji en début.
4. Script dit face caméra, naturel, comme à une amie. Légende naturelle, phrases courtes, rien qui sonne « publicité » ou « écrit par une IA ».
5. Séquence DM : 3 à 4 messages courts. Le 1er livre ce qui a été promis et pose une question ouverte. On qualifie avant de proposer. Jamais de pression, jamais de promesse de résultat.
6. Respect strict des interdits de la marque.
7. Note de pertinence honnête."""
        blocs = [{"type": "text", "text": texte}]
        if regles_marque(self.cfg):
            blocs.append({"type": "text", "text": regles_marque(self.cfg)})
        if voix.strip():
            blocs.append({"type": "text", "text": "VOIX DE LA MARQUE — exemples réels de ses textes. Imite ce ton, ce vocabulaire, cette longueur de phrases, cette ponctuation et cet usage des emojis. Ne recopie pas ses légendes telles quelles ; ses expressions signature, elles, peuvent revenir naturellement.\n\n" + voix.strip()})
        if apprentissages.strip():
            blocs.append({"type": "text", "text": "CE QUI MARCHE SUR LE COMPTE DE LA MARQUE (données réelles) — privilégie ces mécaniques et formats dans tes adaptations :\n\n" + apprentissages.strip()})
        blocs[-1]["cache_control"] = {"type": "ephemeral"}  # mis en cache : moins cher sur les 20 appels
        return blocs

    # --------------------------------------------------------
    def adapte(self, p: Post) -> dict:
        nb = self.cfg["claude"]["hooks_par_post"]
        if p.format == "Carrousel":
            return self._adapte_carrousel(p, nb)
        texte = f"""Reel viral à analyser puis adapter.

Plateforme : {p.plateforme} · @{p.compte} · durée {round(p.duree_s) if p.duree_s else '?'} s
Performance : {nombre(p.vues) or 'n/a'} vues ({p.score_viral}× la médiane du compte) · engagement {pct(p.taux_engagement)} · commentaires/vues {pct(p.taux_commentaires)} · {nombre(p.commentaires)} commentaires · {nombre(p.partages)} partages · {nombre(p.enregistrements)} enregistrements

TRANSCRIPTION DE L'AUDIO :
\"\"\"{p.transcription or '(non disponible)'}\"\"\"

LÉGENDE :
\"\"\"{p.legende[:2500] or '(vide)'}\"\"\"

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
        res = self._appel(OUTIL_ADAPTATION, contenu, max_tokens=5000)
        # Même langue : la légende est recopiée telle quelle depuis la source (aucun risque de reformulation)
        if not res.get("erreur") and p.legende and str(res.get("langue_originale", "")).strip().lower() == str(self.cfg["niche"].get("langue", "français")).strip().lower():
            res["legende_reprise"] = p.legende
        return res

    def _adapte_carrousel(self, p: Post, nb: int) -> dict:
        n = len(p.images)
        seule_couverture = n <= 1 and (not p.medias or p.medias == [p.cover_url])
        if not n:  # aucune image : on ne devine pas le hook à partir de la légende
            return {"erreur": "Les images de ce carrousel n'ont pas pu être récupérées (liens Instagram expirés) : relance une veille pour le relire."}
        texte = f"""CARROUSEL viral à analyser puis adapter ({n or '?'} slides jointes, dans l'ordre).

Plateforme : {p.plateforme} · @{p.compte}
Performance : {nombre(p.likes) or 'n/a'} j'aime · {nombre(p.commentaires)} commentaires ({p.score_viral}× les carrousels habituels du compte)

LÉGENDE :
\"\"\"{p.legende[:2500] or '(vide)'}\"\"\"

Lis chaque slide (texte ET visuel).
LE HOOK EST LE TEXTE ÉCRIT SUR LA SLIDE 1 (la couverture), en entier : titre ET sous-titre éventuel. Recopie-le mot pour mot dans hook_original. Dans hook_viral, mets sa traduction fidèle et complète en {self.cfg['niche'].get('langue', 'français')} (même sens, même longueur, mêmes mots forts, aucune reformulation, rien d'ajouté ni de retiré). Ne prends JAMAIS la légende comme hook.
Pour chaque slide, relève aussi sa mise en page (champ mise_en_page) pour que la version adaptée soit posée exactement au même endroit et de la même façon.
{"Seule la COUVERTURE (slide 1) est jointe : la suite n'a pas pu être récupérée. Remplis slides_modele avec la couverture puis 5 à 7 slides que tu déduis de la légende et de la promesse de la couverture, dans le même esprit." if seule_couverture else f"Remplis slides_modele avec exactement {n} entrée(s), une par slide, dans l'ordre :"} le texte original, ce qu'on voit, le texte adapté à la marque (même rôle, même longueur) et la photo que la marque doit prendre elle-même pour reproduire la slide.
Décris le style du modèle (style_visuel) et choisis la police et le fond du studio les plus proches (typo_conseillee, theme_conseille).
Les champs script_reel, texte_ecran et texte_ecran_adapte concernent une version Reel du même contenu : remplis-les quand même, brièvement.
Propose {nb} hooks adaptés. Remplis l'outil enregistrer_adaptation."""
        contenu = []
        for chemin in p.images[:10]:
            try:
                contenu.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.b64encode(Path(chemin).read_bytes()).decode()}})
            except OSError:
                pass
        contenu.append({"type": "text", "text": texte})
        res = self._appel(OUTIL_ADAPTATION, contenu, max_tokens=7000)
        if not res.get("erreur"):
            sl = res.get("slides_modele")
            if isinstance(sl, str):
                try:
                    res["slides_modele"] = json.loads(sl)
                except ValueError:
                    res["slides_modele"] = []
            if p.legende and str(res.get("langue_originale", "")).strip().lower() == str(self.cfg["niche"].get("langue", "français")).strip().lower():
                res["legende_reprise"] = p.legende
        return res

    def carrousel(self, ad: dict, nb: int | None = None, style: str = "", reel: bool = False, source: dict | None = None) -> dict:
        """
        Transforme le Reel modèle et son adaptation en textes de slides (+ script pour un Reel), dans le style demandé.
        La structure du modèle est reproduite : une slide par temps fort, et pour chaque slide la photo à prévoir.
        """
        src = source or {}
        combien = f"{nb} " if nb else "5 à 9 "
        quoi = (f"Reel : {combien}plans texte (diaporama, une phrase forte par plan) ET le script à dire (champ script)" if reel
                else f"carrousel Instagram de {combien}slides")
        slides_src = "".join(f"\n  Slide {i + 1} : « {x.get('original', '')} » — {x.get('visuel', '')}" for i, x in enumerate(src.get("slides_modele") or []))
        modele = f"""LE MODÈLE À REPRODUIRE (@{src.get('compte') or '?'}, {src.get('format') or 'Reel'}, {round(src['duree_s']) if src.get('duree_s') else '?'} s) :
{("Slides du carrousel modèle :" + slides_src + chr(10) + "Style : " + (src.get('style_visuel') or '') + chr(10) + "Garde exactement le même nombre de slides et le même rôle pour chacune." + chr(10)) if slides_src else ""}
Hook original : {src.get('hook_original') or ''}
Texte à l'écran : {src.get('texte_ecran') or ''}
Structure : {src.get('structure') or ''}
Ce qu'on voit : {src.get('analyse_visuelle') or ''}
Transcription : \"\"\"{src.get('transcription') or '(non disponible)'}\"\"\"
Légende : \"\"\"{src.get('legende') or ''}\"\"\"
""" if src else ""
        texte = f"""{modele}
Transforme ce modèle et son adaptation en {quoi}. Reprends SA structure : une slide par temps fort du modèle, dans le même ordre, avec le même type de progression (même nombre d'étapes s'il en a). Choisis le nombre de slides qui colle au modèle.
Pour chaque slide, dis quelle photo la personne doit prendre elle-même (champ photo), en t'inspirant de ce qu'on voit dans le modèle. Ne demande une photo que là où elle apporte quelque chose ; laisse vide pour une slide sur fond uni.

Hook viral : {ad.get('hook_viral') or ''}
Hooks adaptés : {' / '.join(ad.get('hooks_adaptes') or [])}
Sujet : {ad.get('sujet') or ''}
Mécanique : {ad.get('mecanique') or ''}
Script du Reel :
\"\"\"{ad.get('script_reel') or ''}\"\"\"
CTA : {ad.get('cta_conversation') or ''}

Règles :
- Slide 1 : le hook viral repris tel quel (ou traduit fidèlement), rien d'autre. Il doit donner envie de faire glisser.
- Slides suivantes : une seule idée par slide, phrases courtes, concrètes, dans le ton de la marque. Chaque slide donne envie de passer à la suivante.
- Dernière slide : le CTA qui fait commenter le mot-clé « {self.cfg['objectifs']['mot_cle_cta']} ».
- Rien qui sonne publicité ou texte d'IA, pas de liste de bénéfices creux, pas d'emoji dans les titres.

STYLE D'ÉCRITURE DEMANDÉ : {style or "sa voix habituelle, exactement comme sur son compte"}
Le style change la construction (récit, rythme, angle). Il ne change JAMAIS sa voix : garde son vocabulaire, son tutoiement ou vouvoiement, sa ponctuation, son usage des emojis dans la légende et ses expressions signature.
Remplis l'outil enregistrer_carrousel."""
        return self._appel(OUTIL_CARROUSEL, texte, max_tokens=2000)

    def adapte_tous(self, posts: list[Post], apres_chaque=None):
        log(f"Analyse et adaptation par Claude de {len(posts)} Reels…")
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(self.adapte, p): p for p in posts}
            for i, f in enumerate(cf.as_completed(futures), 1):
                futures[f].adaptation = f.result()
                if apres_chaque:
                    try:
                        apres_chaque(futures[f])
                    except Exception as e:  # noqa: BLE001
                        log(f"  ⚠️  Sauvegarde intermédiaire impossible : {e}")
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

    def classe_types(self, posts: list[Post]) -> dict[str, str]:
        """Type de contenu de chaque publication (éducatif, storytelling, commercial…), par lots, d'après la légende."""
        res: dict[str, str] = {}
        for i in range(0, len(posts), 40):
            lot = posts[i:i + 40]
            texte = "Donne le type de chacune de ces publications Instagram/TikTok, d'après sa légende (et son texte à l'écran s'il est connu).\n\n" + "\n\n".join(
                f"id={p.id}\nformat: {p.format}\nlégende: {(p.legende or '')[:500]}" + (f"\ntexte à l'écran: {p.transcription[:200]}" if p.transcription else "")
                for p in lot)
            r = self._appel(OUTIL_TYPES, texte, max_tokens=3000, systeme="Tu es analyste de contenu social media.")
            res.update({str(c["id"]): c["type"] for c in r.get("classement", []) if c.get("type") in TYPES_CONTENU})
        return res

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


OUTIL_COMPTES = {
    "name": "proposer_comptes",
    "description": "Comptes Instagram publics à surveiller pour une niche.",
    "input_schema": {
        "type": "object",
        "properties": {"comptes": {"type": "array", "items": {"type": "object", "properties": {
            "pseudo": {"type": "string", "description": "Nom d'utilisateur Instagram exact, sans @."},
            "pourquoi": {"type": "string", "description": "En 10 mots maximum : ce qu'on peut leur copier."}},
            "required": ["pseudo", "pourquoi"]}}},
        "required": ["comptes"],
    },
}


def propose_comptes(cfg: dict, deja: list[str]) -> list[dict]:
    """Candidats à vérifier ensuite (Claude peut se tromper de pseudo : chaque compte est contrôlé par une vraie collecte)."""
    ia = IA.__new__(IA)
    import anthropic
    ia.client, ia.cfg, ia.modele, ia.systeme = anthropic.Anthropic(), cfg, cfg["claude"]["modele"], ""
    n = cfg["niche"]
    texte = (f"Niche : {n.get('description', '')}\nCible : {n.get('cible', '')}\nLangue du marché : {n.get('langue', 'français')}\n"
             f"Déjà surveillés (à exclure) : {', '.join(deja) or 'aucun'}\n\n"
             "Propose 18 comptes Instagram publics, actifs, qui publient des Reels ou des carrousels à forte audience : "
             "la moitié dans cette niche et cette langue, l'autre moitié dans des niches voisines ou à l'international "
             "dont les formats sont faciles à transposer. Donne uniquement des pseudos dont tu es sûr qu'ils existent.")
    res = ia._appel(OUTIL_COMPTES, texte, max_tokens=1500, systeme="Tu es expert Instagram et veille de contenus viraux.")
    if res.get("erreur"):
        raise RuntimeError(res["erreur"])
    c = res.get("comptes")
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except ValueError:
            c = []
    return [x for x in c or [] if isinstance(x, dict) and x.get("pseudo")]


# ------------------------------------------------------------
#  Boutique : idées de produits, guide PDF, séquence d'e-mails (dans la voix de la marque)
# ------------------------------------------------------------
OUTIL_IDEES_PRODUITS = {
    "name": "proposer_produits",
    "description": "Idées de produits numériques à vendre ou offrir dans la boutique en lien dans la bio.",
    "input_schema": {
        "type": "object",
        "properties": {"idees": {"type": "array", "description": "3 idées, de la plus facile à lancer à la plus ambitieuse.", "items": {
            "type": "object", "properties": {
                "type": {"type": "string", "enum": ["guide", "checklist", "template", "mini-formation", "appel", "pack"],
                         "description": "Nature du produit."},
                "titre": {"type": "string", "description": "Titre vendeur, concret, sans superlatif creux (moins de 8 mots)."},
                "sous_titre": {"type": "string", "description": "La promesse en une ligne : pour qui, quel résultat."},
                "description": {"type": "string", "description": "Fiche produit prête à publier : 4 à 8 lignes courtes, ce qu'il y a dedans (tirets), pour qui c'est. Ton de la marque, rien qui sonne publicité ou IA."},
                "prix_conseille": {"type": "integer", "description": "Prix conseillé en centimes d'euro. 0 pour un aimant à e-mails gratuit."},
                "pourquoi": {"type": "string", "description": "Pourquoi ce produit, en 1-2 phrases, en s'appuyant sur les données fournies (Reels qui marchent, douleurs de la cible, questions récurrentes)."},
                "plan": {"type": "array", "items": {"type": "string"}, "description": "Sommaire : 4 à 7 parties."},
                "mot_cle": {"type": "string", "description": "Mot-clé à faire commenter sous les Reels pour recevoir ce produit (un mot, MAJUSCULES, sans accent)."},
                "bouton": {"type": "string", "description": "Texte du bouton d'achat (2 à 5 mots)."}},
            "required": ["type", "titre", "sous_titre", "description", "prix_conseille", "pourquoi", "plan", "mot_cle", "bouton"]}}},
        "required": ["idees"],
    },
}

OUTIL_GUIDE = {
    "name": "ecrire_guide",
    "description": "Contenu complet d'un guide PDF court et utile.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titre": {"type": "string"}, "sous_titre": {"type": "string"},
            "introduction": {"type": "string", "description": "3 à 5 phrases, à la 2e personne, dans la voix de la marque."},
            "parties": {"type": "array", "description": "4 à 7 parties.", "items": {"type": "object", "properties": {
                "titre": {"type": "string"},
                "texte": {"type": "string", "description": "2 à 4 paragraphes courts séparés par une ligne vide. Concret, actionnable, exemples précis."},
                "a_retenir": {"type": "array", "items": {"type": "string"}, "description": "2 à 4 points à retenir ou étapes, une ligne chacun."}},
                "required": ["titre", "texte", "a_retenir"]}},
            "conclusion": {"type": "string", "description": "2 à 4 phrases."},
            "appel_action": {"type": "string", "description": "Invitation finale vers l'offre de la marque (sans pression), 1 à 2 phrases."},
        },
        "required": ["titre", "sous_titre", "introduction", "parties", "conclusion", "appel_action"],
    },
}

OUTIL_SEQUENCE = {
    "name": "ecrire_sequence",
    "description": "Séquence d'e-mails envoyée automatiquement aux nouvelles inscrites.",
    "input_schema": {
        "type": "object",
        "properties": {"emails": {"type": "array", "description": "3 à 4 e-mails.", "items": {"type": "object", "properties": {
            "delai_jours": {"type": "integer", "description": "Jours après l'inscription (0 = tout de suite)."},
            "sujet": {"type": "string", "description": "Objet court, naturel, qu'on ouvrirait (pas de majuscules partout, pas d'emoji en début)."},
            "texte": {"type": "string", "description": "Corps de l'e-mail : 4 à 10 lignes courtes, tutoiement si c'est le ton de la marque. Peut contenir {prenom}."},
            "produit": {"type": "string", "description": "Identifiant du produit à mettre en avant avec un bouton (parmi ceux fournis), ou vide."}},
            "required": ["delai_jours", "sujet", "texte", "produit"]}}},
        "required": ["emails"],
    },
}


def _ia_simple(cfg: dict) -> "IA":
    ia = IA.__new__(IA)
    import anthropic
    ia.client, ia.cfg, ia.modele, ia.systeme = anthropic.Anthropic(), cfg, cfg["claude"]["modele"], ""
    return ia


def _systeme_marque(cfg: dict, voix: str, role: str) -> list:
    n = cfg["niche"]
    blocs = [{"type": "text", "text": f"""{role}

Marque : {n.get('nom', '')}
Niche : {(n.get('description') or '').strip()}
Client idéal : {n.get('cible', '')}
Ses problèmes : {'; '.join(n.get('douleurs') or []) or 'non précisés'}
Ton : {n.get('ton', '')}
Offre actuelle : {n.get('offre', '')}
Interdits : {(n.get('interdits') or '').strip()}
Langue : {n.get('langue', 'français')}

Règles : écris comme la marque parle à une amie, phrases courtes, rien qui sonne publicité ou texte écrit par une IA
(pas de « plongeons », « découvrez », « ultime », « incontournable », pas de listes d'adjectifs). Aucune promesse de résultat
chiffrée ou médicale. Respect strict des interdits."""}]
    if regles_marque(cfg):
        blocs.append({"type": "text", "text": regles_marque(cfg)})
    if voix.strip():
        blocs.append({"type": "text", "text": "VOIX DE LA MARQUE — exemples réels de ses textes, à imiter (ton, vocabulaire, longueur, emojis) :\n\n" + voix.strip()[:6000]})
    return blocs


def idees_produits(cfg: dict, voix: str, contexte: str) -> dict:
    return _ia_simple(cfg)._appel(OUTIL_IDEES_PRODUITS, "Données sur le compte et la niche :\n\n" + contexte +
                                  "\n\nPropose 3 produits numériques adaptés : au moins un gratuit pour récolter des e-mails, au moins un payant.",
                                  max_tokens=3500, systeme=_systeme_marque(cfg, voix, "Tu es stratège en produits numériques pour créatrices de contenu."))


def ecrit_guide(cfg: dict, voix: str, produit: dict, contexte: str) -> dict:
    texte = (f"Écris le guide « {produit.get('titre')} » ({produit.get('sous_titre') or ''}).\n"
             f"Fiche produit : {produit.get('description') or ''}\n"
             f"Plan souhaité : {' / '.join(produit.get('plan') or []) or 'à toi de le construire'}\n\n"
             f"Ce qui intéresse l'audience (données réelles) :\n{contexte}\n\n"
             "Le guide doit être vraiment utile, concret, lisible en 10 minutes sur téléphone.")
    return _ia_simple(cfg)._appel(OUTIL_GUIDE, texte, max_tokens=7000, systeme=_systeme_marque(cfg, voix, "Tu écris des guides pratiques pour une créatrice de contenu."))


def ecrit_sequence(cfg: dict, voix: str, produits: list[dict], boutique: str) -> dict:
    liste = "\n".join(f"- id {p['id']} : {p.get('titre')} ({'gratuit' if not p.get('prix') else str(p['prix'] / 100) + ' €'}) — {p.get('sous_titre') or ''}"
                      for p in produits) or "aucun produit"
    texte = (f"Boutique : {boutique}\nProduits :\n{liste}\n\nÉcris la séquence de bienvenue des nouvelles inscrites : "
             "1) bienvenue + ce qu'elles vont recevoir, 2) un conseil utile sans rien vendre, 3) une histoire ou un témoignage qui amène "
             "doucement au produit payant le plus adapté, 4) éventuellement une dernière relance courte. Pas de pression, pas de fausse urgence.")
    return _ia_simple(cfg)._appel(OUTIL_SEQUENCE, texte, max_tokens=3500, systeme=_systeme_marque(cfg, voix, "Tu écris des e-mails pour une créatrice de contenu."))
