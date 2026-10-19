"""
Ressources du serveur (mémoire, disque) : l'application s'adapte à la taille de la machine.
Sur une petite instance (ex. Railway Trial : 1 Go de RAM, 0,5 Go de disque), les traitements vidéo
tournent un par un, le modèle de transcription est libéré après usage et ffmpeg est « sacrifiable » :
s'il manque de mémoire, c'est lui que le système arrête, pas le site.
"""

from __future__ import annotations

import gc
import os
import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def memoire_mo() -> int:
    """Mémoire disponible pour le conteneur (limite cgroup), en Mo."""
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = Path(f).read_text().strip()
            if v.isdigit() and int(v) < (1 << 50):
                return int(v) // (1024 * 1024)
        except OSError:
            pass
    try:
        for ligne in Path("/proc/meminfo").read_text().splitlines():
            if ligne.startswith("MemTotal:"):
                return int(ligne.split()[1]) // 1024
    except OSError:
        pass
    return 4096


def petite_machine() -> bool:
    return memoire_mo() <= int(os.getenv("SEUIL_PETITE_MACHINE_MO", "2048"))


def travaux_video() -> int:
    """Nombre de vidéos traitées en parallèle pendant une veille."""
    m = memoire_mo()
    return 1 if m <= 2048 else 2 if m <= 4096 else 4


def sacrifiable():
    """À passer en preexec_fn : en cas de manque de mémoire, ce processus (ffmpeg) est arrêté en premier."""
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass


def disque(chemin: Path) -> dict:
    try:
        u = shutil.disk_usage(chemin)
        return {"total_mo": u.total // 2**20, "utilise_mo": u.used // 2**20, "libre_mo": u.free // 2**20}
    except OSError:
        return {}


def libere_memoire():
    """Libère le modèle de transcription (≈ 300 Mo) sur une petite machine, après usage."""
    if not petite_machine():
        return
    try:
        import video
        with video._VERROU_MODELE:
            video._MODELES.clear()
    except Exception:  # noqa: BLE001
        pass
    gc.collect()
    try:  # rend au système la mémoire libérée
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass
