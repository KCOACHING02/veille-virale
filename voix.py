"""Voix off des Reels : Virall.ai lit le script (synthèse vocale OpenAI, modèle « mini », moins d'un centime par Reel).

Sans clé OPENAI_API_KEY la voix off n'est pas proposée ; en mode démo, une piste muette de la bonne durée la remplace.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests

from espace import DATA
from modele import log

MODELE = os.getenv("VOIX_MODELE", "gpt-4o-mini-tts")
PRIX_MINUTE_USD = 0.015  # estimation du modèle « mini » (jetons audio en sortie)
VOIX = {  # clé Virallink → (voix OpenAI, libellé)
    "femme": ("coral", "Voix féminine dynamique"),
    "douce": ("shimmer", "Voix féminine douce"),
    "homme": ("onyx", "Voix masculine"),
}
CONSIGNES = ("Voix off d'un Reel Instagram, en français de France, accent neutre. Ton naturel, complice et énergique, "
             "comme une créatrice qui parle à son amie. Rythme vif mais articulé, petites pauses entre les idées. "
             "Jamais de ton publicitaire ni robotique.")
EXEMPLE = "Tu publies tous les jours et rien ne bouge ? Regarde ce qui cartonne dans ta niche, et fais pareil, à ta façon."


def dispo(demo: bool = False) -> bool:
    return demo or bool(os.getenv("OPENAI_API_KEY", "").strip())


def options() -> list[dict]:
    return [{"cle": k, "nom": n} for k, (_, n) in VOIX.items()]


def texte_du_script(script: str) -> str:
    """Ce qui se dit vraiment : sans les repères [0-3 s], les indications de plan (entre parenthèses) ni le texte écran."""
    lignes = []
    for ligne in (script or "").splitlines():
        ligne = re.sub(r"\[[^\]]*\]", " ", ligne)  # [0-3 s], [corps], [fin], [démo…]
        ligne = re.sub(r"\([^)]*\)", " ", ligne)  # (plan sur l'écran), (sourire)…
        ligne = re.split(r"(?i)\b(?:texte (?:à l')?écran|texte écran|à l'écran|sur l'écran)\s*:", ligne)[0]
        ligne = re.sub(r"(?i)^\s*(?:hook|corps|fin|cta|voix off|intro|outro)\s*:\s*", "", ligne)
        ligne = re.sub(r"[+*_#>|]+", " ", ligne)
        ligne = re.sub(r"\s+", " ", ligne).strip(" -–—:")
        if ligne:
            lignes.append(ligne if ligne[-1] in ".?!…" else ligne + ".")
    return " ".join(lignes)[:3500]


def _ajoute_cout(usd: float):
    try:
        import ia
        ia._JETONS["usd"] += usd
        ia._JETONS["total_usd"] += usd
    except Exception:  # noqa: BLE001
        pass


def _silence(secondes: float, dest: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secondes:.1f}",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(dest)], check=True, timeout=120)
    return dest


def synthese(texte: str, voix: str, dest: Path, demo: bool = False) -> Path:
    """Fichier MP3 de la voix qui lit le texte."""
    texte = (texte or "").strip()
    if not texte:
        raise ValueError("Écris le texte que la voix off doit lire.")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        if demo:
            log("  (démo : voix off muette de la bonne durée)")
            return _silence(max(3.0, len(texte.split()) / 2.6), dest)
        raise ValueError("La voix off n'est pas encore disponible.")
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY'].strip()}"},
                      json={"model": MODELE, "voice": VOIX.get(voix, VOIX["femme"])[0], "input": texte,
                            "instructions": CONSIGNES, "response_format": "mp3"}, timeout=180)
    if r.status_code >= 400:
        log(f"  ⚠️  Voix off refusée ({r.status_code}) : {r.text[:200]}")
        raise RuntimeError("La voix off n'a pas pu être créée. Réessaie dans un instant.")
    dest.write_bytes(r.content)
    from video import duree
    _ajoute_cout((duree(dest) or len(texte.split()) / 2.6) / 60 * PRIX_MINUTE_USD)
    return dest


def exemple(voix: str) -> Path | None:
    """Petit extrait pour écouter une voix avant de la choisir (créé une fois, gardé ensuite)."""
    if voix not in VOIX or not os.getenv("OPENAI_API_KEY", "").strip():
        return None
    dossier = DATA / "voix_exemples"
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"{voix}.mp3"
    if not f.exists():
        synthese(EXEMPLE, voix, f)
    return f
