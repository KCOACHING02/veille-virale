"""Données fictives pour tester l'outil sans clé API (python veille.py --demo)."""

from __future__ import annotations

import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modele import MECANIQUES, Post

LEGENDES = [
    "Arrête de manger ça le matin si tu as toujours le ventre gonflé à 11h 👇",
    "3 erreurs que je faisais quand je voulais perdre du ventre (la 2e m'a coûté 2 ans)",
    "Ce que je mange en une journée quand je suis épuisée",
    "Personne ne te dit ça sur le grignotage du soir…",
    "POV : tu as tout essayé et rien ne marche",
    "Recette rapide du midi",
    "Mon petit-déjeuner du jour",
    "Routine du dimanche",
]
COMMENTAIRES = [
    "Mais du coup on mange quoi le matin si on n'a pas faim ?",
    "C'est exactement moi à 16h devant le placard 😭",
    "Et quand on travaille en horaires décalés on fait comment ?",
    "J'ai testé pendant une semaine, mon ventre est beaucoup moins gonflé",
    "Ça marche aussi après 45 ans avec la préménopause ?",
    "Je n'ai jamais le temps de cuisiner avec les enfants",
    "Tu as une version sans produits laitiers ?",
    "Le grignotage c'est surtout le stress chez moi",
]


def posts_concurrents(comptes: list[tuple[str, str]] | None = None) -> list[Post]:
    random.seed(7 if not comptes else sum(map(ord, "".join(c for _, c in comptes))))
    posts, now = [], datetime.now(timezone.utc)
    liste = [("Instagram", "coach_demo_a", 180000), ("Instagram", "nutri_demo_b", 60000), ("TikTok", "healthy_demo_c", 250000)]
    if comptes:
        liste = [(pl, c, random.choice([90000, 180000, 300000])) for pl, c in comptes]
    for plat, compte, base in liste:
        for i in range(45):
            viral = random.random() < 0.18
            vues = int(base * (random.uniform(3, 12) if viral else random.uniform(0.4, 1.6)))
            er = random.uniform(0.015, 0.09)
            p = Post(
                plateforme=plat, compte=compte, id=f"{compte}_{i}", url=f"https://example.com/{compte}/{i}",
                date=(now - timedelta(days=random.randint(3, 88))).isoformat(),
                format=random.choice(["Reel", "Reel", "Carrousel"]) if plat == "Instagram" else "Vidéo",
                legende=random.choice(LEGENDES[:5] if viral else LEGENDES),
                likes=int(vues * er * 0.8), commentaires=int(vues * er * random.uniform(0.02, 0.12)), vues=vues,
                partages=int(vues * er * 0.05), enregistrements=int(vues * er * 0.08), duree_s=random.randint(15, 45),
            )
            p.commentaires_texte = [{"texte": c, "likes": random.randint(3, 400)} for c in random.sample(COMMENTAIRES, 5)]
            posts.append(p)
    return posts


def video_test(dossier: Path) -> Path | None:
    """Fabrique une petite vidéo verticale de test (mire + son) pour vérifier ffmpeg."""
    if not shutil.which("ffmpeg"):
        return None
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / "test.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=25:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(f)], capture_output=True, timeout=120)
    return f if f.exists() else None


def lit_videos(posts: list[Post], dossier: Path, media: Path):
    """Démo : passe la vidéo de test dans la vraie chaîne d'extraction (images + audio)."""
    import shutil as sh
    from video import audio, duree, images_cles
    src = video_test(dossier)
    if not src:
        return
    media.mkdir(parents=True, exist_ok=True)
    for p in posts:
        d = dossier / p.id
        d.mkdir(parents=True, exist_ok=True)
        p.images = [str(c) for c in images_cles(src, d, 4, duree(src))]
        if p.images:
            p.miniature = f"{p.plateforme}_{p.id}.jpg"
            sh.copy(p.images[1], media / p.miniature)
        if audio(src, d):
            p.transcription = ("[démo] Si tu as le ventre gonflé tous les jours à 11h, ce n'est pas ce que tu crois. "
                               "Le problème, c'est souvent ton petit-déjeuner…")


def miniatures(posts: list[Post], dossier: Path, media: Path):
    """Démo : fabrique des miniatures variées à partir de la mire de test."""
    src = video_test(dossier)
    if not src:
        return
    media.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(p for p in posts if not p.miniature):
        nom = f"{p.plateforme}_{p.id}.jpg"
        if not (media / nom).exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{(i * 0.37) % 11:.2f}", "-i", str(src),
                            "-frames:v", "1", "-vf", f"scale=360:-2,hue=h={(i * 47) % 360}", "-q:v", "6", str(media / nom)],
                           capture_output=True, timeout=30)
        if (media / nom).exists():
            p.miniature = nom


def adaptation(p: Post, i: int) -> dict:
    mec = MECANIQUES[i % 6]
    return {
        "hook_original": "[démo] Si tu as le ventre gonflé tous les jours à 11h, ce n'est pas ce que tu crois.",
        "texte_ecran": "[démo] Ventre gonflé à 11h ?", "analyse_visuelle": "[démo] Face caméra, cuisine lumineuse, sous-titres jaunes.",
        "sujet": "[démo] Ventre gonflé le matin", "mecanique": mec,
        "pourquoi_ca_marche": "[démo] Lance sans --demo avec ta clé Anthropic pour une vraie analyse.",
        "structure": "0-3 s hook → 3-15 s erreur → 15-30 s solution → CTA",
        "langue_originale": "anglais", "hook_viral": "[démo] Ton ventre gonflé à 11 h ? Ce n'est pas ce que tu crois.",
        "legende_reprise": "[démo] Légende originale traduite fidèlement, avec ses emojis et ses hashtags 👇 #nutrition",
        "hooks_adaptes": [f"[démo] Hook {mec} n°1", "[démo] Hook n°2", "[démo] Hook n°3"],
        "texte_ecran_adapte": "[démo] Texte écran",
        "script_reel": "[0-3 s] [démo] hook\n[corps] [démo] 3 phrases\n[fin] Commente START et je t'envoie le guide",
        "cta_conversation": "Commente START et je t'envoie le guide en privé",
        "sequence_dm": [
            {"etape": "1. Réponse automatique", "message": "[démo] Coucou ! Voici le guide 🌿 Dis-moi, c'est quoi le plus dur pour toi en ce moment ?"},
            {"etape": "2. Qualification (si elle répond)", "message": "[démo] Je comprends. Ça dure depuis combien de temps ?"},
            {"etape": "3. Proposition", "message": "[démo] Si tu veux, on peut en parler 15 min cette semaine."},
            {"etape": "Relance J+2 (si pas de réponse)", "message": "[démo] Tu as pu lire le guide ?"},
        ],
        "legende_adaptee": "[démo] La légende adaptée apparaîtra ici.", "format_conseille": "Face caméra, 25 s",
        "idee_visuelle": "[démo] Toi qui poses la main sur le ventre", "pertinence": 3 + i % 3,
    }


def voix_client() -> dict:
    return {
        "questions": ["[démo] Quoi manger le matin quand on n'a pas faim ?", "[démo] Ça marche après 45 ans ?"],
        "douleurs": ["[démo] Grignotage lié au stress", "[démo] Pas le temps de cuisiner avec les enfants"],
        "objections": ["[démo] « J'ai déjà tout essayé »"],
        "expressions": ["devant le placard à 16h", "ventre gonflé", "pas le temps"],
        "idees_reels": [{"hook": "[démo] Ton grignotage de 16h n'est pas un manque de volonté", "pourquoi": "Question n°1 des commentaires"}],
    }


def apprentissages() -> dict:
    return {
        "nb_reels": 24, "nb_suivi": 9, "mecaniques_top": ["Erreur commune"], "mecaniques_flop": ["Une journée / routine"],
        "par_mecanique": [
            {"mecanique": "Erreur commune", "n_reels": 6, "n_suivi": 3, "vues_vs_moyenne": 1.6, "commentaires_vs_moyenne": 2.1, "conversations_moy": 22.0, "indice": 1.9},
            {"mecanique": "POV / identification", "n_reels": 5, "n_suivi": 2, "vues_vs_moyenne": 1.1, "commentaires_vs_moyenne": 1.0, "conversations_moy": 14.0, "indice": 1.05},
            {"mecanique": "Une journée / routine", "n_reels": 7, "n_suivi": 2, "vues_vs_moyenne": 0.7, "commentaires_vs_moyenne": 0.5, "conversations_moy": 4.0, "indice": 0.45},
        ],
        "texte": "", "meilleures_legendes": [],
    }


def decouvertes() -> list[dict]:
    return [{"plateforme": "Instagram", "compte": "compte_decouvert_demo", "reels_au_dessus_seuil": 5, "vues_max": 2400000,
             "engagement_median": 0.045, "exemple": "https://example.com/decouvert", "legende": "[démo]"}]


def profil() -> dict:
    return {
        "nom_marque": "[démo] Brille & Vibre",
        "description_niche": "[démo] Coaching nutrition pour femmes actives qui veulent dégonfler et retrouver de l'énergie sans régime.",
        "cible": "[démo] Femmes de 30 à 50 ans, actives, fatiguées des régimes",
        "douleurs": ["[démo] Ventre gonflé en fin de journée", "[démo] Grignotage le soir", "[démo] Fatigue à 16h", "[démo] Pas le temps de cuisiner"],
        "ton": "[démo] Chaleureux, complice, tutoiement, quelques emojis",
        "guide_voix": ["[démo] Phrases très courtes, souvent une idée par ligne", "[démo] Ouvre par une question qui interpelle (« Toi aussi tu… ? »)",
                       "[démo] Tutoiement systématique, ton de grande sœur bienveillante", "[démo] 1 à 3 emojis maximum, plutôt en fin de phrase",
                       "[démo] Termine presque toujours par une question ou un mot-clé à commenter"],
        "expressions_signature": ["[démo] « on se dit tout »", "[démo] « sans prise de tête »", "[démo] « dis-moi en commentaire »"],
        "offre": "[démo] Ebook gratuit puis accompagnement",
        "hashtags": ["nutritionfemme", "ventreplat", "grignotage", "energie", "reequilibragealimentaire"],
        "points_forts": ["[démo] Tes Reels « erreur commune » font 2× plus de commentaires"],
        "a_ameliorer": ["[démo] Hook trop lent : la promesse arrive après 4 secondes", "[démo] Pas de CTA mot-clé"],
    }


def bio(compte: str) -> dict:
    return {"instagram": {"nom": "[démo] Karine | Business digital faceless", "abonnes": 12400, "publications": 186, "categorie": "Créateur de contenu",
                          "bio": "[démo] J'aide les débutantes à lancer leur business en ligne depuis leur téléphone 📱\nSans se montrer, sans prise de tête\n⬇️ Ton ebook gratuit pour démarrer",
                          "lien": "https://stan.store/demo"}}
