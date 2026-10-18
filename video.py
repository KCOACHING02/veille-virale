"""Lecture des vidéos : téléchargement, images clés, transcription de l'audio."""

from __future__ import annotations

import concurrent.futures as cf
import os
import shutil
import subprocess
from pathlib import Path

import requests

from collecte import apify_run
from modele import Post, log

TAILLE_MAX = 150 * 1024 * 1024  # 150 Mo


# ------------------------------------------------------------
#  URLs de téléchargement
# ------------------------------------------------------------
def urls_tiktok(posts: list[Post], cfg: dict, token: str):
    """TikTok ne fournit pas l'URL du fichier dans le scraping de profil : on passe par un actor dédié."""
    tt = [p for p in posts if p.plateforme == "TikTok" and not p.video_url]
    if not tt:
        return
    try:
        items = apify_run(cfg["video"]["actor_tiktok_video"], {
            "videoUrls": [{"url": p.url} for p in tt],
            "mediaMode": "video",
        }, token)
    except Exception as e:  # noqa: BLE001
        log(f"  ⚠️  Téléchargement TikTok indisponible : {e}")
        return
    for it in items:
        lien = it.get("mediaUrl") or it.get("downloadUrl") or (it.get("mediaUrls") or [None])[0]
        source = str(it.get("sourceUrl") or it.get("url") or it.get("videoId") or "")
        for p in tt:
            if p.id in source or (p.url and p.url in source):
                p.video_url = lien


def telecharge(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            total = 0
            with open(dest, "wb") as f:
                for bloc in r.iter_content(1 << 16):
                    total += len(bloc)
                    if total > TAILLE_MAX:
                        return False
                    f.write(bloc)
        return dest.stat().st_size > 2_000
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------
#  ffmpeg
# ------------------------------------------------------------
def duree(video: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, subprocess.SubprocessError):
        return None


def images_cles(video: Path, dossier: Path, nb: int, d: float | None) -> list[Path]:
    """Images à 0,3 s, 1,5 s, 3 s (le hook) puis réparties sur le reste de la vidéo."""
    instants = [0.3, 1.5, 3.0]
    if d and d > 6:
        reste = max(nb - 3, 0)
        instants += [3 + (d - 3) * (i + 1) / (reste + 1) for i in range(reste)]
    instants = [t for t in instants[:nb] if not d or t < d]
    chemins = []
    for i, t in enumerate(instants):
        sortie = dossier / f"img_{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "5", str(sortie)],
                       capture_output=True, timeout=60)
        if sortie.exists() and sortie.stat().st_size > 0:
            chemins.append(sortie)
    return chemins


SECONDES_TRANSCRITES = int(os.getenv("SECONDES_TRANSCRITES", "60"))  # le hook et la structure sont dans la première minute


def audio(video: Path, dossier: Path, secondes: int | None = SECONDES_TRANSCRITES) -> Path | None:
    sortie = dossier / "audio.wav"
    limite = ["-t", str(secondes)] if secondes else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *limite, "-vn", "-ac", "1", "-ar", "16000", str(sortie)],
                   capture_output=True, timeout=180)
    return sortie if sortie.exists() and sortie.stat().st_size > 1000 else None


# ------------------------------------------------------------
#  Transcription
# ------------------------------------------------------------
_MODELES: dict = {}   # modèle Whisper gardé en mémoire d'une analyse à l'autre (évite ~10 s de chargement)
_VERROU_MODELE = __import__("threading").Lock()


def modele_whisper(nom: str):
    with _VERROU_MODELE:
        if nom not in _MODELES:
            from faster_whisper import WhisperModel
            log(f"  Chargement du modèle Whisper « {nom} » (première fois : téléchargement)")
            _MODELES[nom] = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 2)
        return _MODELES[nom]


def lit_wav(wav: Path, secondes: int | None):
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        n = w.getnframes() if not secondes else min(w.getnframes(), w.getframerate() * secondes)
        return np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0


class Transcripteur:
    def __init__(self, cfg: dict):
        v = cfg["video"]
        self.moteur = v.get("transcription", "local")
        # Choix du serveur (pas du client) : « base » est ~3× plus rapide que « small » sur un petit serveur sans GPU
        self.modele_local = os.getenv("WHISPER_MODEL", "base")
        self._local = None
        if self.moteur == "openai" and not os.getenv("OPENAI_API_KEY"):
            log("  ⚠️  OPENAI_API_KEY absente : transcription locale à la place")
            self.moteur = "local"

    def __call__(self, wav: Path) -> str:
        try:
            if self.moteur == "aucun":
                return ""
            if self.moteur == "openai":
                with open(wav, "rb") as f:
                    r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                                      files={"file": ("audio.wav", f, "audio/wav")},
                                      data={"model": "whisper-1"}, timeout=300)
                r.raise_for_status()
                return r.json().get("text", "").strip()
            # Le WAV (16 kHz mono, produit par ffmpeg) est lu directement : on évite le décodeur PyAV,
            # dont les versions récentes sont incompatibles avec faster-whisper (« metadata_errors »).
            audio = lit_wav(wav, SECONDES_TRANSCRITES)
            if audio.size < 1600:
                return ""
            # vad_filter : les passages sans parole (musique seule) sont sautés → vidéos muettes traitées en un instant
            segments, _ = modele_whisper(self.modele_local).transcribe(
                audio, vad_filter=True, beam_size=1, condition_on_previous_text=False, without_timestamps=True)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  Transcription impossible : {e}")
            return ""


# ------------------------------------------------------------
#  Orchestration
# ------------------------------------------------------------
def traite_videos(posts: list[Post], cfg: dict, token: str | None, dossier: Path, media: Path | None = None):
    """Remplit p.images, p.miniature, p.transcription, p.duree_s pour chaque Reel."""
    if not shutil.which("ffmpeg"):
        log("⚠️  ffmpeg introuvable : lecture vidéo désactivée (voir README)")
        return
    v = cfg["video"]
    if token:
        urls_tiktok(posts, cfg, token)
    dossier.mkdir(parents=True, exist_ok=True)

    def prepare(p: Post):
        if not p.video_url:
            return p, None
        d = dossier / f"{p.plateforme}_{p.id}"
        d.mkdir(exist_ok=True)
        fichier = d / "video.mp4"
        if not telecharge(p.video_url, fichier):
            return p, None
        p.duree_s = p.duree_s or duree(fichier)
        p.images = [str(c) for c in images_cles(fichier, d, v["images_par_video"], p.duree_s)]
        if p.images and media is not None:
            vignette = p.images[1] if len(p.images) > 1 else p.images[0]
            media.mkdir(parents=True, exist_ok=True)
            nom = f"{p.plateforme}_{p.id}.jpg"
            shutil.copy(vignette, media / nom)
            p.miniature = nom
        wav = audio(fichier, d)
        fichier.unlink(missing_ok=True)  # on ne garde pas la vidéo
        return p, wav

    log(f"Lecture de {len(posts)} vidéos (images clés + audio)…")
    transcrire = Transcripteur(cfg) if v.get("transcription", "local") != "aucun" else None
    # Chaîne de production : chaque audio est transcrit dès qu'il est prêt, pendant que les vidéos suivantes se téléchargent
    import queue
    import threading
    file_audio: queue.Queue = queue.Queue()
    faits = [0]

    def transcripteur_en_continu():
        while True:
            el = file_audio.get()
            if el is None:
                return
            p, wav = el
            try:
                p.transcription = transcrire(wav)[:4000]
            finally:
                wav.unlink(missing_ok=True)
            faits[0] += 1
            if faits[0] % 5 == 0:
                log(f"  {faits[0]} vidéos transcrites")
    fil = threading.Thread(target=transcripteur_en_continu, daemon=True) if transcrire else None
    if fil:
        fil.start()
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for fut in cf.as_completed([ex.submit(prepare, p) for p in posts]):
            p, wav = fut.result()
            if wav and fil:
                file_audio.put((p, wav))
            elif wav:
                wav.unlink(missing_ok=True)
    lues = sum(1 for p in posts if p.images)
    log(f"  {lues}/{len(posts)} vidéos lues" + ("" if lues == len(posts) else " (liens expirés ou indisponibles pour les autres)"))
    if fil:
        if not file_audio.empty():
            log("Transcription des derniers audios…")
        file_audio.put(None)
        fil.join()


def miniatures(posts: list[Post], media: Path):
    """Télécharge la couverture de chaque Reel affiché dans l'interface (si pas déjà d'image)."""
    media.mkdir(parents=True, exist_ok=True)

    def un(p: Post):
        nom = f"{p.plateforme}_{p.id}.jpg"
        if (media / nom).exists():
            p.miniature = nom
            return
        if p.cover_url and telecharge(p.cover_url, media / nom):
            p.miniature = nom
        else:
            (media / nom).unlink(missing_ok=True)
    a_faire = [p for p in posts if not p.miniature]
    if a_faire:
        log(f"Récupération de {len(a_faire)} miniatures…")
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(un, a_faire))


def slides_carrousels(posts: list[Post], dossier: Path, media: Path | None = None):
    """Carrousels : télécharge l'image de chaque slide (réduite à 900 px) pour que Claude lise texte et visuels."""
    a_faire = [p for p in posts if p.medias]
    if not a_faire:
        return
    log(f"Lecture de {len(a_faire)} carrousel(s), slide par slide…")
    from PIL import Image

    def un(p: Post):
        d = dossier / f"{p.plateforme}_{p.id}"
        d.mkdir(parents=True, exist_ok=True)
        chemins = []
        for i, u in enumerate(p.medias):
            f = d / f"slide_{i + 1:02d}.jpg"
            if telecharge(u, f):
                try:
                    im = Image.open(f).convert("RGB")
                    im.thumbnail((900, 900))
                    im.save(f, "JPEG", quality=82)
                    chemins.append(str(f))
                except Exception:  # noqa: BLE001
                    f.unlink(missing_ok=True)
        p.images = chemins
        if chemins and media is not None and not p.miniature:
            media.mkdir(parents=True, exist_ok=True)
            nom = f"{p.plateforme}_{p.id}.jpg"
            shutil.copy(chemins[0], media / nom)
            p.miniature = nom
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(un, a_faire))
    log(f"  {sum(1 for p in a_faire if p.images)}/{len(a_faire)} carrousels lus")
