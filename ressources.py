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


@lru_cache(maxsize=1)
def coeurs() -> int:
    """Cœurs réellement alloués au conteneur (quota cgroup), pas ceux de la machine hôte :
    sur Railway, os.cpu_count() voit des dizaines de cœurs alors que le conteneur n'en a que quelques-uns."""
    n = None
    try:
        q, per = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if q != "max":
            n = max(1, round(int(q) / int(per)))
    except (OSError, ValueError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            per = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if q > 0:
                n = max(1, round(q / per))
        except (OSError, ValueError):
            pass
    try:
        visibles = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        visibles = os.cpu_count() or 2
    n = min(n or visibles, visibles)
    return max(1, int(os.getenv("COEURS", n)))


def threads_calcul() -> int:
    """Fils pour un calcul lourd (transcription) : un cœur reste libre pour le site au-delà de 2 cœurs."""
    c = coeurs()
    return c - 1 if c >= 3 else c


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
