# Veille virale — notes pour Claude

Application web par abonnement (Flask) qui repère les Reels et carrousels Instagram/TikTok viraux de comptes à copier, les analyse (vidéo, transcription, slides) et les adapte à la niche de l'utilisateur avec Claude. Le propriétaire est francophone : code, interface, messages et commits en **français**.

## Lancer et tester
- `python app.py --demo --port 8000` : application complète avec données fictives (aucune clé API consommée). Sans clés dans `.env`, le mode démo est automatique.
- `python veille.py --demo` : moteur en ligne de commande.
- Pas de suite de tests : vérifier chaque changement en mode démo (inscription → assistant → analyse → galerie), sur ordinateur et à 390 px de large.
- Dépendance système : ffmpeg (avec libass). La lecture des commentaires a été retirée (coût Apify, peu utile).

## Architecture
- `app.py` : serveur, API JSON, file de tâches (une à la fois), veille automatique du lundi.
- `abonnements.py` : utilisateurs SQLite (`data/app.db`), formules (`plans.yaml`), quotas, Stripe sans SDK.
- `espace.py` : un dossier par client dans `data/espaces/<id>/` (config.yaml, historique, analyses, médias, suivi).
- `moteur.py` : orchestration d'une analyse (`executer`), adaptation unitaire, assistant (analyse du compte, hashtags).
- `collecte.py` (Apify ; Reels, carrousels, son utilisé), `video.py` (ffmpeg + Whisper), `suggestions.py` (comptes à copier proposés par Claude puis vérifiés par collecte), `banque.py` (images et vidéos libres de droits Pexels, démo sans clé), `commentaires.py`, `ia.py` (tous les appels Claude, sorties forcées par outil), `selection.py`, `apprentissage.py`, `decouverte.py`, `rapports.py`.
- `studio.py` : studio de création (carrousels Pillow, Reels montés ffmpeg + libass avec hook et sous-titres Whisper, diaporamas, package ZIP). File de tâches séparée (`FILE_STUDIO`), quota `studio_par_mois`.
- `emails.py` (Resend, sans SDK), `legal.py` + `societe.yaml` (CGV, confidentialité, mentions légales), `static/admin.html` (tableau de bord, réservé à `ADMIN_EMAILS`).
- `static/accueil.html` (page publique sur `/` quand on n'est pas connecté), `static/index.html` (application sur `/` ou `/app` : galerie, planning, studio, assistant, paramètres, abonnement) et `static/connexion.html` (inscription, connexion, mot de passe oublié) : HTML/CSS/JS sans framework.
- `static/fonts/` : Poppins (OFL), utilisée pour les textes incrustés.
- `config.exemple.yaml` : modèle d'un nouvel espace client. `config.yaml` : usage local (CLI).

## Règles
- Ne jamais committer `.env`, `data/`, `rapports/`.
- Toute nouvelle consommation d'API doit respecter les quotas (`abonnements.peut`) et passer par la file de tâches.
- Les textes générés ne doivent pas « sonner IA » ; respecter les interdits de la niche de chaque client.
