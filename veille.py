#!/usr/bin/env python3
"""
VEILLE VIRALE — ligne de commande
---------------------------------
Pour l'interface web, lance plutôt :  python app.py

    python veille.py                         # veille de la semaine (comptes de config.yaml)
    python veille.py --comptes "@compte1, tt:compte2, https://www.instagram.com/reel/XXXX/"
                                             # analyse et copie de comptes / Reels précis
    python veille.py --demo                  # test sans clé API
    python veille.py --sans-ia               # classement seul, sans Claude
    python veille.py --depuis rapports/brut_….json   # ré-analyse sans re-scraper
"""

import argparse
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import moteur
from espace import Espace, espace_local


def main():
    ap = argparse.ArgumentParser(description="Veille virale Instagram / TikTok")
    ap.add_argument("--espace", help="Dossier d'un espace client (par défaut : utilisation locale)")
    ap.add_argument("--comptes", help="Comptes ou liens de Reels à analyser et copier (mode copie)")
    ap.add_argument("--plateforme", default="Instagram", choices=["Instagram", "TikTok"],
                    help="Plateforme par défaut pour les noms sans préfixe")
    ap.add_argument("--nb", type=int, help="Nombre de Reels à adapter")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--sans-ia", action="store_true")
    ap.add_argument("--depuis")
    args = ap.parse_args()

    esp = Espace(Path(args.espace)) if args.espace else espace_local()
    cfg = esp.lit_config()
    saisie, mode = None, "veille"
    if args.comptes:
        saisie = moteur.parse_saisie(args.comptes, args.plateforme)
        if saisie["ignores"]:
            print("Non reconnus :", ", ".join(saisie["ignores"]))
        mode = "copie"
    try:
        a = moteur.executer(esp, cfg, mode=mode, saisie=saisie, nb_adapter=args.nb, demo=args.demo,
                            sans_ia=args.sans_ia, depuis=args.depuis)
    except RuntimeError as e:
        sys.exit(f"❌ {e}")
    print(f"Rapports : {esp.rapports / a['fichiers']['html']} et {a['fichiers']['xlsx']}")


if __name__ == "__main__":
    main()
