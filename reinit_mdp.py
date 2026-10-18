#!/usr/bin/env python3
"""
Réinitialise le mot de passe d'un compte (dépannage, en attendant le « mot de passe oublié » par e-mail).

    python reinit_mdp.py adresse@exemple.fr                → génère un mot de passe provisoire
    python reinit_mdp.py adresse@exemple.fr MonNouveauMdp   → définit ce mot de passe

Sur Railway : bloc du service → onglet Console → taper la commande.
"""

import secrets
import sys

from werkzeug.security import generate_password_hash

import abonnements as ab


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    email = sys.argv[1].strip().lower()
    mdp = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(9)
    if len(mdp) < 8:
        sys.exit("Le mot de passe doit faire au moins 8 caractères.")
    ab.init()
    with ab._db() as c:
        n = c.execute("UPDATE utilisateurs SET mdp=? WHERE email=?", (generate_password_hash(mdp), email)).rowcount
    if not n:
        comptes = [u["email"] for u in ab.tous()]
        sys.exit(f"Aucun compte avec l'adresse {email}. Comptes existants : {', '.join(comptes) or 'aucun'}")
    print(f"Mot de passe de {email} réinitialisé.\nNouveau mot de passe : {mdp}\nChange-le ensuite si tu veux, en relançant cette commande avec le mot de passe de ton choix.")


if __name__ == "__main__":
    main()
