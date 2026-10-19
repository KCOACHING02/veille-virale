"""CGV, politique de confidentialité et mentions légales (informations de la société dans societe.yaml)."""

from __future__ import annotations

import html
import re

import yaml

from espace import CODE


def infos() -> dict:
    return yaml.safe_load((CODE / "societe.yaml").read_text(encoding="utf-8"))


def _v(s: dict, cle: str) -> str:
    """Valeur échappée ; surlignée tant qu'elle n'est pas complétée."""
    val = html.escape(str(s.get(cle, "")))
    return f'<mark title="À compléter dans societe.yaml">{val}</mark>' if val.startswith("[") else val


def _editeur(s):
    return (f"{_v(s, 'societe')}, {_v(s, 'forme_juridique')} au capital de {_v(s, 'capital')}, dont le siège est situé "
            f"{_v(s, 'siege')}, immatriculée {_v(s, 'immatriculation')} ({_v(s, 'tva')})")


SOUS_TRAITANTS = [
    ("Railway Corporation", "hébergement de l'application et des données", "États-Unis"),
    ("Stripe", "paiement et facturation des abonnements", "Irlande / États-Unis"),
    ("Fournisseur d'intelligence artificielle", "moteur de Virall.ai (analyse des vidéos et rédaction des adaptations)", "États-Unis"),
    ("Prestataire de collecte de données publiques", "collecte des publications publiques Instagram et TikTok", "Union européenne"),
    ("Resend", "envoi des e-mails du service", "États-Unis"),
    ("Google Fonts", "affichage des polices de caractères", "États-Unis"),
]


def cgv(s: dict) -> str:
    p = _v(s, "nom_produit")
    ttc = "toutes taxes comprises" if s.get("prix_ttc", True) else "hors taxes"
    return f"""
<h1>Conditions générales de vente et d'utilisation</h1>
<p class="maj">Dernière mise à jour : {_v(s, 'date_maj')}</p>

<h2>1. Objet</h2>
<p>Les présentes conditions régissent l'accès et l'utilisation du service en ligne {p} (le « Service »), édité par {_editeur(s)} (l'« Éditeur »). Toute inscription vaut acceptation sans réserve des présentes conditions.</p>

<h2>2. Description du Service</h2>
<p>{p} est un outil en ligne d'aide à la création de contenus pour les réseaux sociaux. Il permet notamment :</p>
<ul>
<li>de repérer, parmi les publications <b>publiquement accessibles</b> de comptes Instagram et TikTok choisis par l'utilisateur, celles qui ont obtenu le plus d'audience ;</li>
<li>d'en analyser les ressorts (accroche, structure, format) à l'aide d'une intelligence artificielle ;</li>
<li>de proposer des adaptations à la thématique de l'utilisateur (accroches, scripts, légendes, messages privés) ;</li>
<li>de fabriquer des carrousels et des vidéos à partir des images et vidéos fournies par l'utilisateur ;</li>
<li>de suivre les performances des publications de l'utilisateur.</li>
</ul>
<p>Le Service ne publie rien sur les comptes de l'utilisateur : la publication reste à son initiative.</p>

<h2>3. Inscription et compte</h2>
<p>Le Service est réservé aux personnes majeures. L'utilisateur fournit une adresse e-mail valide et choisit un mot de passe qu'il garde confidentiel. Il est responsable de l'utilisation de son compte. Un compte est personnel et ne peut pas être partagé.</p>

<h2>4. Essai gratuit</h2>
<p>Toute nouvelle inscription bénéficie d'une période d'essai gratuite, sans moyen de paiement, dans les limites d'utilisation indiquées sur le site. À la fin de l'essai, les fonctions d'analyse sont suspendues jusqu'à la souscription d'une formule ; les contenus déjà produits restent consultables.</p>

<h2>5. Formules, prix et quotas</h2>
<p>Les formules, leurs prix et leurs limites mensuelles (analyses, adaptations, comptes surveillés, créations) sont présentés sur le site. Les prix sont indiqués en euros, {ttc}. Les quotas sont remis à zéro chaque mois civil et ne sont pas reportables. Une veille utilise une analyse et une adaptation par publication adaptée d'office ; chaque adaptation demandée ensuite (bouton « Adapter », idées de produits, séquence d'e-mails) en utilise une ; un carrousel, un Reel monté ou un guide PDF créé au studio utilise une création (retoucher ou refaire une création ne compte pas). Afin de garantir le Service à tous, une limite d'usage raisonnable des ressources techniques s'applique en complément ; elle n'est pas atteinte dans un usage normal des limites affichées. L'Éditeur peut modifier ses prix ; le nouveau prix s'applique à la période suivante après information de l'utilisateur au moins 30 jours à l'avance.</p>

<h2>6. Paiement, renouvellement et résiliation</h2>
<p>L'abonnement est payable mensuellement et d'avance par carte bancaire, via le prestataire de paiement Stripe. Il se renouvelle automatiquement chaque mois. L'utilisateur peut le résilier à tout moment depuis la page « Abonnement » : la résiliation prend effet à la fin de la période déjà payée, sans remboursement de la période en cours. En cas d'échec de paiement, l'accès aux analyses peut être suspendu.</p>

<h2>7. Droit de rétractation</h2>
<p>Le Service s'adresse principalement à des professionnels (créateurs, entrepreneurs, agences). Lorsque l'utilisateur a la qualité de consommateur, il dispose d'un délai de 14 jours à compter de la souscription pour se rétracter. En demandant l'accès immédiat au Service, il reconnaît que celui-ci commence avant la fin de ce délai ; s'il se rétracte, il reste redevable du montant correspondant au service fourni jusqu'à sa demande (article L. 221-25 du Code de la consommation). La demande se fait par e-mail à {_v(s, 'email_contact')}.</p>

<h2>8. Utilisation responsable et contenus de tiers</h2>
<p>Le Service analyse uniquement des informations rendues publiques par leurs auteurs. Les publications analysées restent la propriété de leurs auteurs. Les analyses et adaptations sont fournies à titre d'inspiration : <b>l'utilisateur est seul responsable des contenus qu'il publie</b>. Il s'engage à respecter les droits des tiers (droit d'auteur, droit à l'image, marques), à ne pas reproduire à l'identique les vidéos, images ou textes d'autrui lorsqu'ils sont protégés, et à respecter les conditions d'utilisation d'Instagram et de TikTok. Il s'interdit toute utilisation du Service à des fins illicites, de harcèlement ou de collecte de données personnelles.</p>
<p>Les images et vidéos que l'utilisateur importe dans le Service doivent lui appartenir ou être utilisées avec l'autorisation de leurs titulaires.</p>

<h2>9. Intelligence artificielle</h2>
<p>Les analyses et textes sont produits automatiquement par une intelligence artificielle. Ils peuvent contenir des erreurs ou des imprécisions et doivent être relus avant publication. L'Éditeur ne garantit ni un nombre de vues, ni un nombre de conversations ou de ventes.</p>

<h2>10. Propriété intellectuelle</h2>
<p>Le Service (logiciel, interface, marques, textes du site) appartient à l'Éditeur. L'utilisateur conserve tous les droits sur ses propres contenus et sur les contenus produits pour lui par le Service, qu'il peut utiliser librement, sous réserve de l'article 8.</p>

<h2>11. Disponibilité et responsabilité</h2>
<p>L'Éditeur s'efforce d'assurer l'accès au Service en continu, sans pouvoir le garantir : maintenance, pannes des prestataires (hébergement, intelligence artificielle, collecte) ou changements des réseaux sociaux peuvent l'interrompre ou en limiter certaines fonctions. Sauf faute lourde ou dommage corporel, la responsabilité de l'Éditeur est limitée aux sommes payées par l'utilisateur au cours des 12 derniers mois.</p>

<h2>12. Suspension du compte</h2>
<p>L'Éditeur peut suspendre ou fermer un compte en cas de manquement grave aux présentes conditions, après mise en demeure restée sans effet pendant 8 jours, ou sans délai en cas d'usage illicite.</p>

<h2>13. Données personnelles</h2>
<p>Le traitement des données personnelles est décrit dans la <a href="/confidentialite">politique de confidentialité</a>.</p>

<h2>14. Modification des conditions</h2>
<p>L'Éditeur peut faire évoluer les présentes conditions. L'utilisateur est informé de toute modification importante au moins 30 jours avant son entrée en vigueur et peut résilier son abonnement s'il la refuse.</p>

<h2>15. Droit applicable et litiges</h2>
<p>Les présentes conditions sont soumises au droit français. En cas de réclamation, l'utilisateur écrit d'abord à {_v(s, 'email_contact')}. Le consommateur peut recourir gratuitement au médiateur de la consommation : {_v(s, 'mediateur')}. À défaut d'accord amiable, les tribunaux français sont compétents ; entre professionnels, compétence exclusive est attribuée aux tribunaux du ressort du siège de l'Éditeur.</p>
"""


def confidentialite(s: dict) -> str:
    st = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in SOUS_TRAITANTS)
    return f"""
<h1>Politique de confidentialité</h1>
<p class="maj">Dernière mise à jour : {_v(s, 'date_maj')}</p>

<h2>Responsable du traitement</h2>
<p>{_editeur(s)}. Contact : {_v(s, 'email_contact')}.</p>

<h2>Données traitées</h2>
<ul>
<li><b>Compte</b> : prénom, adresse e-mail, mot de passe (stocké chiffré, jamais en clair), dates d'inscription et de connexion, acceptation des conditions.</li>
<li><b>Abonnement</b> : formule, historique d'utilisation. Les données de carte bancaire sont traitées uniquement par Stripe et ne sont jamais stockées par l'Éditeur.</li>
<li><b>Paramétrage</b> : niche, cible, ton, textes de référence, comptes surveillés, hashtags, publications suivies et résultats saisis.</li>
<li><b>Fichiers importés</b> : images et vidéos utilisées pour créer des contenus.</li>
<li><b>Données publiques de comptes tiers</b> : publications publiques des comptes Instagram et TikTok que l'utilisateur choisit de surveiller (légendes, statistiques, vidéos analysées puis supprimées ; seules des images extraites et la transcription sont conservées).</li>
</ul>

<h2>Finalités et bases légales</h2>
<ul>
<li>Fournir le Service et gérer le compte : exécution du contrat.</li>
<li>Facturation et obligations comptables : obligation légale.</li>
<li>E-mails de service (bienvenue, nouveau mot de passe, veille prête) : exécution du contrat.</li>
<li>Analyse de publications publiques de tiers : intérêt légitime de l'utilisateur et de l'Éditeur à étudier les tendances de contenus, limité aux informations rendues publiques et à des statistiques agrégées.</li>
<li>Sécurité et prévention des abus : intérêt légitime.</li>
</ul>
<p>Aucune donnée n'est vendue ni utilisée à des fins publicitaires.</p>

<h2>Destinataires et sous-traitants</h2>
<p>Les données ne sont accessibles qu'à l'Éditeur et aux prestataires techniques suivants, dans la limite de leur mission :</p>
<div class="tab"><table><thead><tr><th>Prestataire</th><th>Rôle</th><th>Localisation</th></tr></thead><tbody>{st}</tbody></table></div>
<p>Les transferts hors de l'Union européenne sont encadrés par les clauses contractuelles types de la Commission européenne ou par le cadre de protection des données UE–États-Unis lorsque le prestataire y adhère.</p>

<h2>Durées de conservation</h2>
<ul>
<li>Données du compte et contenus : pendant toute la durée du compte, puis supprimées dans les 3 mois suivant sa fermeture.</li>
<li>Données de facturation : 10 ans (obligation comptable).</li>
<li>Données publiques collectées sur les comptes surveillés : au plus 24 heures en mémoire partagée, puis uniquement dans les analyses de l'utilisateur.</li>
<li>Liens de réinitialisation de mot de passe : 1 heure.</li>
</ul>

<h2>Cookies</h2>
<p>Le Service utilise un seul cookie, strictement nécessaire, pour garder l'utilisateur connecté. Aucun cookie publicitaire ni de mesure d'audience n'est déposé. Les polices de caractères sont chargées depuis Google Fonts, qui reçoit à cette occasion l'adresse IP du visiteur.</p>

<h2>Vos droits</h2>
<p>Vous disposez d'un droit d'accès, de rectification, d'effacement, de limitation, d'opposition et de portabilité de vos données, ainsi que du droit de définir des directives sur leur sort après votre décès. Pour les exercer, écrivez à {_v(s, 'email_contact')}. Vous pouvez aussi introduire une réclamation auprès de la CNIL (www.cnil.fr).</p>
<p>Si vous êtes l'auteur d'un compte public analysé par un utilisateur et souhaitez vous y opposer, écrivez à la même adresse : vos publications seront exclues des analyses.</p>
"""


def mentions(s: dict) -> str:
    return f"""
<h1>Mentions légales</h1>
<h2>Éditeur du site</h2>
<p>{_editeur(s)}.<br>Directeur de la publication : {_v(s, 'directeur_publication')}.<br>Contact : {_v(s, 'email_contact')}.</p>
<h2>Hébergement</h2>
<p>Railway Corporation, San Francisco, Californie, États-Unis — <a href="https://railway.com" rel="noopener">railway.com</a>.</p>
<h2>Propriété intellectuelle</h2>
<p>L'ensemble des éléments du site (textes, interface, logiciel, marque {_v(s, 'nom_produit')}) est protégé. Toute reproduction sans autorisation est interdite. Les publications Instagram et TikTok citées ou analysées restent la propriété de leurs auteurs.</p>
<h2>Données personnelles</h2>
<p>Voir la <a href="/confidentialite">politique de confidentialité</a>.</p>
"""


PAGES = {"cgv": ("Conditions générales", cgv), "confidentialite": ("Confidentialité", confidentialite),
         "mentions-legales": ("Mentions légales", mentions)}


def page(nom: str) -> str:
    s = infos()
    titre, f = PAGES[nom]
    corps = f(s)
    a_completer = len(re.findall(r"<mark", corps))
    alerte = (f'<p class="alerte">{a_completer} information(s) surlignée(s) restent à compléter dans <code>societe.yaml</code>.</p>'
              if a_completer else "")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre} — {html.escape(s.get('nom_produit', ''))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@12..96,75..100,400..800&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#F6F4F8;--surface:#fff;--ink:#271B2D;--ink-2:#5E5166;--ink-3:#8E8296;--line:#E2DCE7;--glow:#FF4F79;--warn-soft:#FDF0D9;--warn:#B86E00}}
@media (prefers-color-scheme:dark){{:root{{--paper:#17111B;--surface:#211A26;--ink:#F3EEF6;--ink-2:#C2B7C9;--ink-3:#8F8398;--line:#352B3B;--glow:#FF5C84;--warn-soft:#3A2A12;--warn:#F0A63A}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 "Instrument Sans",system-ui,sans-serif}}
.haut{{max-width:820px;margin:0 auto;padding:22px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
.marque{{font:800 21px/1 "Bricolage Grotesque",sans-serif;font-stretch:80%;display:flex;align-items:center;gap:9px;color:inherit;text-decoration:none}}
.marque i{{width:11px;height:20px;border-radius:4px;background:var(--glow);display:inline-block;transform:skewX(-10deg)}}
nav a{{color:var(--ink-2);margin-left:14px;font-size:14px}}
article{{max-width:820px;margin:0 auto 60px;background:var(--surface);border-radius:20px;padding:34px clamp(18px,5vw,48px)}}
h1{{font:800 34px/1.1 "Bricolage Grotesque",sans-serif;font-stretch:85%;margin:0 0 6px}}
h2{{font:700 20px/1.25 "Bricolage Grotesque",sans-serif;margin:30px 0 8px}}
.maj{{color:var(--ink-3);margin:0 0 10px;font-size:14px}}
a{{color:var(--glow)}} ul{{padding-left:22px}} li{{margin:4px 0}}
mark{{background:#FFE58A;color:#271B2D;border-radius:4px;padding:0 3px}}
.alerte{{background:var(--warn-soft);color:var(--warn);border-radius:10px;padding:10px 14px;font-size:14px}}
.tab{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14.5px}} th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}
</style></head><body>
<div class="haut"><a class="marque" href="/"><i></i>{html.escape(s.get('nom_produit', ''))}</a>
<nav><a href="/cgv">CGV</a><a href="/confidentialite">Confidentialité</a><a href="/mentions-legales">Mentions légales</a></nav></div>
<article>{alerte}{corps}</article></body></html>"""
