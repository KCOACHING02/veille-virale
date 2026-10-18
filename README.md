# Veille virale

Application web par abonnement pour créateurs de contenu et coachs : elle repère les Reels Instagram et TikTok qui ont cartonné chez les comptes que l'utilisateur veut copier, comprend pourquoi ils ont marché et les réécrit pour sa niche. Chaque Reel adapté arrive avec ses hooks, son script, sa légende et une séquence de messages privés pour transformer les commentaires en conversations.

> « Veille virale » est un nom de travail : le nom et le logo se changent dans `static/index.html` et `static/connexion.html`.

## Le parcours client

1. **Inscription** : 7 jours d'essai gratuit, sans carte bancaire.
2. **Assistant de configuration** en 8 étapes :
   1. **Ton compte** : Claude lit ses Reels, mesure ses performances et propose son positionnement, sa cible, son ton et ses hashtags.
   2. **Ton activité** : ce qu'il fait, son offre, sa langue (pré-rempli à l'étape 1).
   3. **Ton client idéal** : qui il vise, ses problèmes, ce qu'il ne faut jamais dire.
   4. **Tes objectifs** : 1, 2 ou 3 Reels par jour, nombre de conversations visées, mot-clé à faire commenter.
   5. **Ton cahier des charges** : vues minimum, engagement minimum, période.
   6. **Les comptes à copier** : comptes surveillés et hashtags de la niche (suggérés par l'IA).
   7. **Ta voix** : ses textes, ou les légendes de ses meilleurs Reels en un clic.
   8. **Récapitulatif** puis lancement de la première analyse.
3. **L'application** :
   - **Reels** : galerie des Reels qui entrent dans le cahier des charges, avec filtres et tri. La fiche de chaque Reel contient l'adaptation, la séquence DM, l'analyse et les commentaires. Un Reel non adapté s'adapte en un clic.
   - **Nouvelle analyse** : coller des comptes ou des liens de Reels précis à analyser et copier, ou lancer la veille de la semaine.
   - **Planning** : 2 Reels par jour sur 7 jours, diversifiés, avec l'Excel de suivi à télécharger.
   - **Voix du client** : les questions, douleurs, objections et expressions exactes lues dans les commentaires, avec des idées de Reels.
   - **Mes résultats** : les mécaniques qui rapportent le plus de vues, de commentaires et de conversations sur son compte.
   - **Comptes** : comptes surveillés et nouveaux comptes repérés dans la niche.
   - **Paramètres** : chaque étape de l'assistant se modifie séparément, et la veille automatique s'active ici.
   - **Abonnement** : consommation du mois, choix ou changement de formule, factures.
4. **Chaque lundi matin**, pour les formules payantes, la veille de la semaine tourne toute seule.

## Démarrer en local

```
pip install -r requirements.txt        # + ffmpeg installé sur la machine
cp .env.example .env                   # puis remplir les clés
python app.py                          # → http://localhost:8000
python app.py --demo                   # données fictives, aucune clé consommée
```

Sans clés API, l'application démarre automatiquement en mode démo. Mets ton e-mail dans `ADMIN_EMAILS` pour avoir un accès illimité.

## Mise en ligne (VPS OVH ou autre)

1. Pointe ton nom de domaine vers le serveur et remplace `ton-domaine.fr` dans `Caddyfile`.
2. Copie le dossier sur le serveur, crée `.env`, puis lance `docker compose up -d`.
3. Le HTTPS est automatique (Caddy). Les données des clients sont dans `data/` : à sauvegarder chaque jour.

## Activer le paiement (Stripe)

1. Dans Stripe, crée un produit par formule, avec un prix mensuel récurrent, et copie chaque identifiant `price_…` dans `plans.yaml`.
2. Ajoute `STRIPE_SECRET_KEY` dans `.env`.
3. Crée un webhook vers `https://ton-domaine.fr/api/stripe/webhook` avec les événements `checkout.session.completed`, `customer.subscription.updated` et `customer.subscription.deleted`, puis mets son secret dans `STRIPE_WEBHOOK_SECRET`.
4. Active le portail client Stripe : il permet de changer de formule, de mettre à jour sa carte et de télécharger ses factures.

## Formules (`plans.yaml`)

Les prix et quotas sont des **propositions à ajuster**. Chaque formule fixe un nombre d'analyses par mois, de Reels adaptés par mois et de comptes surveillés, et précise si la veille automatique est incluse.

**Coût de revient indicatif** : environ 0,10 à 0,20 € par Reel adapté (Apify + Claude), et 1 à 3 € par veille hebdomadaire. Vérifie ces chiffres sur tes premières factures avant de fixer tes prix.

## Utilisation personnelle en ligne de commande

```
python veille.py                                  # veille (config.yaml à la racine)
python veille.py --comptes "@compte, tt:compte2"  # analyser et copier des comptes précis
python veille.py --demo
```

## Architecture

| Fichier | Rôle |
|---|---|
| `app.py` | Serveur web : comptes, API, tâches en file, veille du lundi |
| `abonnements.py` | Utilisateurs (SQLite), formules, quotas, Stripe |
| `espace.py` | Un dossier de données par client (`data/espaces/<id>/`) |
| `moteur.py` | Orchestration d'une analyse, assistant (analyse du compte, hashtags) |
| `collecte.py`, `video.py`, `commentaires.py` | Apify, lecture des vidéos (ffmpeg + Whisper), commentaires |
| `ia.py` | Tous les appels à Claude |
| `selection.py`, `apprentissage.py`, `decouverte.py` | Critères, historique, diversité, ce qui marche, nouveaux comptes |
| `static/` | Interface (connexion, assistant, application) |

## Avant de commercialiser : points à traiter

- **Conditions d'utilisation des plateformes** : le scraping va à l'encontre des CGU de Meta et TikTok. Pour un usage commercial, le risque augmente (blocages, mises en demeure). Fais valider le montage par un avocat spécialisé, et envisage à terme l'API officielle Instagram pour le compte du client lui-même.
- **RGPD** : les commentaires collectés sont des données personnelles de tiers. Il faut une base légale, une durée de conservation limitée, un registre des traitements et une politique de confidentialité. Un sous-traitant hors UE (Apify, Anthropic) impose aussi un encadrement des transferts.
- **CGV / CGU, mentions légales, politique de confidentialité** : l'écran d'inscription y fait référence, mais les textes sont à rédiger.
- **Sécurité** : les mots de passe sont hachés et les sessions protégées. Avant le lancement, ajoute la réinitialisation du mot de passe par e-mail et une sauvegarde automatique de `data/`.
- **Charge** : les analyses passent une par une dans une file, ce qui suffit pour quelques dizaines de clients. Au-delà, il faudra plusieurs workers.
