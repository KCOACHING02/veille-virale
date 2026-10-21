"""
Nettoyage automatique du disque (une fois par jour, depuis le planificateur).

On ne supprime que ce qui se recrée ou ne sert plus :
  - les dossiers de travail temporaires laissés par une analyse interrompue (plus d'un jour) ;
  - le cache de collecte partagé de plus de 3 jours (il n'est utilisé que 24 h) ;
  - les données brutes de collecte (rapports/brut_*.json) de plus de 14 jours ;
  - les images des Reels (miniatures, slides) de plus de 30 jours qui ne sont plus utilisées
    par aucune analyse ni aucun projet du studio (analyse supprimée, etc.).
Jamais touchés : boutiques (photos, fichiers vendus), projets du studio, analyses, rapports Excel/HTML,
comptes et réglages des clientes.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from espace import DATA

JOURS_CACHE = 3
JOURS_BRUT = 14
JOURS_IMAGES = 30
_ETAT = DATA / "nettoyage.json"


def _vieux(f: Path, jours: int) -> bool:
    try:
        return time.time() - f.stat().st_mtime > jours * 86400
    except OSError:
        return False


def _supprime(f: Path) -> int:
    try:
        taille = f.stat().st_size
        f.unlink()
        return taille
    except OSError:
        return 0


def _textes_utilises(espace: Path) -> str:
    """Tout le texte de l'espace (analyses, historique, suivi, studio, rapports HTML…) : une image y est citée si elle sert encore."""
    morceaux = []
    for f in espace.rglob("*"):
        if f.suffix not in (".json", ".html", ".yaml") or f.name.startswith("brut_") or not f.is_file():
            continue
        try:
            morceaux.append(f.read_text(encoding="utf-8"))
        except OSError:
            pass
    return "\n".join(morceaux)


def nettoie(simulation: bool = False) -> dict:
    """Renvoie le bilan : {"fichiers": n, "mo": x, "date": ...}. simulation=True : compte sans rien effacer."""
    liberes, n = 0, 0

    def efface(f: Path):
        nonlocal liberes, n
        if simulation:
            try:
                liberes += f.stat().st_size
            except OSError:
                return
        else:
            liberes += _supprime(f)
        n += 1

    # 0. Dossiers de travail temporaires d'analyses interrompues (plus d'un jour)
    for d in Path(tempfile.gettempdir()).glob("veille*_*"):
        if d.is_dir() and _vieux(d, 1):
            for f in d.rglob("*"):
                if f.is_file():
                    efface(f)
            if not simulation:
                shutil.rmtree(d, ignore_errors=True)

    # 1. Cache de collecte partagé
    for f in (DATA / "cache").glob("*.json"):
        if _vieux(f, JOURS_CACHE):
            efface(f)

    for esp in (DATA / "espaces").glob("*"):
        if not esp.is_dir():
            continue
        # 2. Données brutes de collecte
        for f in (esp / "rapports").glob("brut_*.json"):
            if _vieux(f, JOURS_BRUT):
                efface(f)
        # 3. Images de Reels qui ne servent plus
        media = esp / "media"
        anciennes = [f for f in media.glob("*") if f.is_file() and _vieux(f, JOURS_IMAGES)] if media.exists() else []
        if anciennes:
            utilises = _textes_utilises(esp)
            for f in anciennes:
                if f.name not in utilises:
                    efface(f)

    bilan = {"fichiers": n, "mo": round(liberes / 2**20, 1), "date": datetime.now().isoformat(timespec="minutes")}
    if not simulation:
        try:
            _ETAT.write_text(json.dumps(bilan), encoding="utf-8")
        except OSError:
            pass
        if n:
            print(f"[nettoyage] {n} fichier(s) supprimé(s), {bilan['mo']} Mo libérés")
    return bilan


def dernier() -> dict:
    try:
        return json.loads(_ETAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def a_faire() -> bool:
    """Une fois par jour."""
    d = dernier().get("date")
    if not d:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(d)).total_seconds() > 86400
    except ValueError:
        return True
