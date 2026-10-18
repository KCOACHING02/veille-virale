"""Un espace = les données d'un client (ou de l'utilisation en local) : config, historique, analyses, médias."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml

CODE = Path(__file__).resolve().parent
# Dossier des données (comptes, analyses, médias). Sur Railway, le volume attaché est détecté automatiquement,
# quel que soit son chemin de montage : les données survivent aux mises à jour.
DATA = Path(os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or CODE / "data")


class Espace:
    def __init__(self, racine: Path, donnees: Path | None = None):
        self.racine = Path(racine)
        self.donnees = Path(donnees) if donnees else self.racine
        self.racine.mkdir(parents=True, exist_ok=True)
        if not self.config.exists():
            shutil.copy(CODE / "config.exemple.yaml", self.config)
        for d in (self.suivi, self.analyses, self.media, self.rapports):
            d.mkdir(parents=True, exist_ok=True)

    # chemins
    config = property(lambda s: s.racine / "config.yaml")
    historique = property(lambda s: s.racine / "historique.json")
    suivi = property(lambda s: s.racine / "suivi")
    voix = property(lambda s: s.racine / "ma_voix.md")
    profil_compte = property(lambda s: s.racine / "mon_compte.json")
    analyses = property(lambda s: s.donnees / "analyses")
    media = property(lambda s: s.donnees / "media")
    rapports = property(lambda s: s.racine / "rapports")

    def lit_config(self) -> dict:
        return yaml.safe_load(self.config.read_text(encoding="utf-8"))

    def ecrit_config(self, cfg: dict):
        self.config.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def espace_local() -> Espace:
    """Utilisation en local, mono-utilisateur (ligne de commande) : config.yaml à côté du code."""
    return Espace(CODE, DATA)


def espace_client(uid: int | str) -> Espace:
    return Espace(DATA / "espaces" / str(uid))
