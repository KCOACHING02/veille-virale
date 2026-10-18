"""Structures de données partagées et petites fonctions utilitaires."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Liste fermée des mécaniques de contenu : elle permet de comparer les semaines entre elles
# (diversité du planning, apprentissage sur ce qui marche sur TON compte).
MECANIQUES = [
    "Erreur commune",
    "Mythe / contre-intuitif",
    "Liste d'astuces",
    "Avant / après",
    "POV / identification",
    "Storytelling perso",
    "Question / défi",
    "Tutoriel / recette",
    "Une journée / routine",
    "Opinion tranchée",
    "Autre",
]


@dataclass
class Post:
    plateforme: str
    compte: str
    id: str
    url: str
    date: str
    format: str
    legende: str
    likes: int | None = None
    commentaires: int | None = None
    vues: int | None = None
    partages: int | None = None
    enregistrements: int | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duree_s: float | None = None
    medias: list = field(default_factory=list)              # carrousel : URL de l'image de chaque slide, dans l'ordre
    # enrichissements
    commentaires_texte: list = field(default_factory=list)   # [{"texte":…, "likes":…}]
    transcription: str = ""
    images: list = field(default_factory=list)              # chemins locaux des images clés
    miniature: str = ""                                      # nom du fichier image dans data/media
    # calculés
    interactions: float = 0.0
    taux_engagement: float | None = None
    taux_commentaires: float | None = None
    score_viral: float = 0.0
    criteres_ok: bool = False
    seuil_vues: int | None = None  # seuil de vues appliqué à ce Reel (fixe ou propre à son compte)
    creneau: str = ""
    demande: bool = False          # Reel donné explicitement par l'utilisateur
    adaptation: dict = field(default_factory=dict)


def date_utc(v):
    """Date d'une publication, quel que soit le format renvoyé par les collecteurs, en UTC (ou None)."""
    from datetime import timezone
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
            n = float(v)
            return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, tz=timezone.utc)
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def entier(v):
    try:
        v = int(v)
        return v if v >= 0 else None  # Instagram renvoie -1 quand les likes sont masqués
    except (TypeError, ValueError):
        return None


LOG_HOOKS: list = []  # fonctions appelées à chaque ligne de log (suivi en direct dans l'interface)
# Les tâches du studio tournent en parallèle des analyses : leur fil d'exécution est marqué pour que
# leurs messages n'apparaissent que dans leur propre suivi (et inversement).
import threading as _th
FIL = _th.local()


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    studio = getattr(FIL, "studio", False)
    for h in list(LOG_HOOKS):
        try:
            if getattr(h, "studio", False) == studio:
                h(msg)
        except Exception:  # noqa: BLE001
            pass


def cle(p) -> str:
    return f"{p.plateforme}:{p.id}"


def pct(x):
    return f"{x * 100:.1f} %" if x is not None else ""


def nombre(x):
    return f"{x:,}".replace(",", " ") if isinstance(x, (int, float)) else ""
