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
- Formule gratuite (`gratuit` dans `plans.yaml`) : fin d'essai, résiliation ou impayé y basculent automatiquement (`abonnements.plan_effectif`). Ses options (`ia`, `montage_reel`, `suivi_publications`, `sequences_emails`, `filigrane`, `mention_boutique`, `commission_boutique`) se vérifient avec `reserve(u, option)` dans `app.py` ; une analyse y est un simple classement (`moteur.executer(classement_seul=True)`).
- `espace.py` : un dossier par client dans `data/espaces/<id>/` (config.yaml, historique, analyses, médias, suivi).
- `moteur.py` : orchestration d'une analyse (`executer`), adaptation unitaire, assistant (analyse du compte, hashtags).
- `collecte.py` (Apify ; Reels, carrousels, son utilisé), `video.py` (ffmpeg + Whisper), `suggestions.py` (comptes à copier proposés par Claude puis vérifiés par collecte), `banque.py` (images et vidéos libres de droits Pixabay ou Pexels, démo sans clé), `commentaires.py`, `ia.py` (tous les appels Claude, sorties forcées par outil), `selection.py`, `apprentissage.py`, `decouverte.py`, `rapports.py`.
- `studio.py` : studio de création (carrousels Pillow, Reels montés ffmpeg + libass avec hook et sous-titres Whisper, diaporamas, couvertures de Reel en 7 styles avec aperçu grille 3:4, package ZIP). File de tâches séparée (`FILE_STUDIO`), quota `studio_par_mois`.
- `boutique.py` : boutique en lien dans la bio (page publique `/@pseudo`, thèmes et design, produits numériques, capture d'e-mails, kit média, statistiques). Paiements via Stripe Connect sur le compte de chaque cliente (`BOUTIQUE_COMMISSION` en %, 0 par défaut) ; achats simulés en démo. Données dans `data/espaces/<id>/boutique/`, pseudos uniques dans la table `boutiques`.
- `boutique_ventes.py` (prix en promo et compte à rebours, codes promo, avis vérifiés, packs, offre complémentaire, rendez-vous, sources des visites, QR code, séquence d'e-mails envoyée par `planificateur_emails`), `boutique_ia.py` (idées de produits, guide PDF, séquence écrite par Claude : file `FILE_STUDIO` et quotas) et `guide_pdf.py` (reportlab, A5).
- `notifications.py` : notifications push (Web Push, clés VAPID dans `data/vapid.pem`, chiffrement aes128gcm sans dépendance) ; application installable (`/manifest.webmanifest`, `static/sw.js`, `static/icones/`). Parrainage dans `abonnements.py` (code, mois offerts), récapitulatif du lundi (`envoie_syntheses`), boutiques en exemple sur l'accueil (`/api/vitrines`).
- `emails.py` (Resend, sans SDK), `legal.py` + `societe.yaml` (CGV, confidentialité, mentions légales), `static/admin.html` (tableau de bord, réservé à `ADMIN_EMAILS`).
- `static/accueil.html` (page publique sur `/` quand on n'est pas connecté), `static/index.html` (application sur `/` ou `/app` : galerie, planning, studio, assistant, paramètres, abonnement) et `static/connexion.html` (inscription, connexion, mot de passe oublié) : HTML/CSS/JS sans framework.
- `static/fonts/` : Poppins (OFL), utilisée pour les textes incrustés.
- `config.exemple.yaml` : modèle d'un nouvel espace client. `config.yaml` : usage local (CLI).

## Règles
- Ne jamais committer `.env`, `data/`, `rapports/`.
- Toute nouvelle consommation d'API doit respecter les quotas (`abonnements.peut`) et passer par la file de tâches.
- Les textes générés ne doivent pas « sonner IA » ; respecter les interdits de la niche de chaque client.
