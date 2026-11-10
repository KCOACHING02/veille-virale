"""Voix off des Reels : Virall.ai lit le script.

ElevenLabs en priorité (ELEVENLABS_API_KEY : voix françaises natives de leur bibliothèque, choisies et ajoutées au compte
automatiquement, ou imposées par ELEVENLABS_VOIX_FEMME / _DOUCE / _HOMME), sinon OpenAI (OPENAI_API_KEY, nettement moins
naturel en français). Sans clé la voix off n'est pas proposée ; en mode démo, une piste muette de la bonne durée la remplace.
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


ELEVEN = "https://api.elevenlabs.io/v1"
ELEVEN_MODELE = os.getenv("ELEVENLABS_MODELE", "eleven_multilingual_v2")
ELEVEN_USD_PAR_CARACTERE = 0.00018  # formule Starter : ~5 $ pour 30 000 caractères
# Ce qu'on cherche dans la bibliothèque d'ElevenLabs pour chaque voix (voix françaises natives, les plus utilisées)
RECHERCHE_ELEVEN = {"femme": {"gender": "female", "age": "young"}, "douce": {"gender": "female", "descriptives": "calm"},
                    "homme": {"gender": "male", "age": "middle_aged"}}


def _cle_eleven() -> str:
    return os.getenv("ELEVENLABS_API_KEY", "").strip().strip('"').strip("'")


def _cle_openai() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip().strip('"').strip("'")


def fournisseur() -> str:
    return "elevenlabs" if _cle_eleven() else "openai" if _cle_openai() else ""


def dispo(demo: bool = False) -> bool:
    return demo or bool(fournisseur())


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


def _memo_eleven() -> Path:
    return DATA / "voix_elevenlabs.json"


def voix_eleven(cle: str) -> str:
    """Identifiant ElevenLabs de la voix : imposé par variable, sinon une voix française native de la bibliothèque,
    choisie une fois (la plus utilisée correspondant au profil) et ajoutée au compte."""
    import json
    impose = os.getenv(f"ELEVENLABS_VOIX_{cle.upper()}", "").strip()
    if impose:
        return impose
    memo = {}
    try:
        memo = json.loads(_memo_eleven().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if memo.get(cle):
        return memo[cle]
    h = {"xi-api-key": _cle_eleven()}
    deja = set(memo.values())
    choisie = None
    for filtres in (RECHERCHE_ELEVEN.get(cle, {}), {"gender": RECHERCHE_ELEVEN.get(cle, {}).get("gender", "female")}):
        r = requests.get(f"{ELEVEN}/shared-voices", headers=h, timeout=30,
                         params={"language": "fr", "page_size": 40, "sort": "usage_character_count_1y", **filtres})
        if r.status_code >= 400:
            log(f"  ⚠️  Bibliothèque ElevenLabs illisible ({r.status_code}) : {r.text[:200]}")
            break
        voix_ = [v for v in r.json().get("voices", []) if v.get("voice_id") not in deja
                 and (v.get("language") or "fr").startswith("fr") and (v.get("accent") or "").lower() not in ("canadian", "quebecois", "québécois", "african", "belgian", "swiss")]
        if voix_:
            choisie = voix_[0]
            break
    vid = None
    if choisie and choisie.get("is_added_by_user"):
        vid = choisie["voice_id"]
    elif choisie:
        r = requests.post(f"{ELEVEN}/voices/add/{choisie['public_owner_id']}/{choisie['voice_id']}", headers=h, timeout=30,
                          json={"new_name": f"Virallink {cle}"})
        if r.status_code < 400:
            vid = r.json().get("voice_id") or choisie["voice_id"]
        else:  # compte gratuit : les voix de la bibliothèque sont réservées aux abonnements payants
            log(f"  Voix de la bibliothèque non ajoutée ({r.status_code}) : voix d'ElevenLabs à la place")
    if not vid:  # voix fournies avec tout compte (multilingues : elles parlent français)
        genre = RECHERCHE_ELEVEN.get(cle, {}).get("gender", "female")
        r = requests.get(f"{ELEVEN}/voices", headers=h, timeout=30)
        r.raise_for_status()
        siennes = [v for v in r.json().get("voices", []) if v.get("voice_id") not in deja
                   and (v.get("labels") or {}).get("gender") == genre]
        if not siennes:
            raise RuntimeError("Aucune voix disponible chez ElevenLabs.")
        douces = [v for v in siennes if any(m in str(v.get("labels")) .lower() for m in ("calm", "soft", "warm"))]
        choisie = (douces if cle == "douce" and douces else siennes)[0]
        vid = choisie["voice_id"]
    log(f"  Voix « {cle} » : {choisie.get('name')} ({choisie.get('accent') or 'français'})")
    memo[cle] = vid
    _memo_eleven().write_text(json.dumps(memo), encoding="utf-8")
    return vid


def _eleven(texte: str, voix: str, dest: Path) -> Path:
    r = requests.post(f"{ELEVEN}/text-to-speech/{voix_eleven(voix)}", params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": _cle_eleven()}, timeout=180,
                      json={"text": texte, "model_id": ELEVEN_MODELE,
                            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}})
    if r.status_code >= 400:
        log(f"  ⚠️  Voix off ElevenLabs refusée ({r.status_code}) : {r.text[:200]}")
        if r.status_code in (400, 404) and "voice" in r.text.lower():  # voix retirée de la bibliothèque : on en choisira une autre
            _memo_eleven().unlink(missing_ok=True)
        raise RuntimeError("La voix off n'a pas pu être créée. Réessaie dans un instant.")
    dest.write_bytes(r.content)
    _ajoute_cout(len(texte) * ELEVEN_USD_PAR_CARACTERE)
    return dest


def synthese(texte: str, voix: str, dest: Path, demo: bool = False) -> Path:
    """Fichier MP3 de la voix qui lit le texte."""
    texte = (texte or "").strip()
    if not texte:
        raise ValueError("Écris le texte que la voix off doit lire.")
    if not fournisseur():
        if demo:
            log("  (démo : voix off muette de la bonne durée)")
            return _silence(max(3.0, len(texte.split()) / 2.6), dest)
        raise ValueError("La voix off n'est pas encore disponible.")
    if fournisseur() == "elevenlabs":
        return _eleven(texte, voix if voix in VOIX else "femme", dest)
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {_cle_openai()}"},
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
    if voix not in VOIX or not fournisseur():
        return None
    dossier = DATA / "voix_exemples"
    dossier.mkdir(parents=True, exist_ok=True)
    f = dossier / f"{fournisseur()}_{voix}.mp3"
    if not f.exists():
        synthese(EXEMPLE, voix, f)
    return f
