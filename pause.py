"""Pause des services payants (Claude, Apify, ElevenLabs, OpenAI) décidée par Mohamed le 27 novembre 2026.

Tant que la variable SERVICES_PAYANTS n'est pas à « 1 » (Railway → Variables), aucun appel payant ne part :
Virall.ai, collectes Instagram, voix off et transcription OpenAI refusent poliment ; la boutique, les paiements
Stripe, les e-mails et tout ce qui est gratuit continuent de fonctionner. Pour relancer : SERVICES_PAYANTS=1.
"""
from __future__ import annotations

import os

MESSAGE = "Virall.ai est en pause pour le moment : cette fonction revient très bientôt."


class EnPause(RuntimeError):
    pass


def actif() -> bool:
    return os.getenv("SERVICES_PAYANTS", "0").strip() != "1"


def verifie() -> None:
    if actif():
        raise EnPause(MESSAGE)


def installe() -> None:
    """Bloque à la source tout client Anthropic créé pendant la pause (tous les appels de Virall.ai passent par là)."""
    try:
        import anthropic
    except ImportError:
        return
    init = anthropic.Anthropic.__init__
    if getattr(init, "_vv_pause", False):
        return

    def init_surveille(self, *a, **k):
        verifie()
        init(self, *a, **k)

    init_surveille._vv_pause = True
    anthropic.Anthropic.__init__ = init_surveille
