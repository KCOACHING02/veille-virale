"""
E-mails transactionnels via Resend (https://resend.com) — sans SDK.
Variables : RESEND_API_KEY, EMAIL_EXPEDITEUR (ex. « Virallink <contact@virallink.fr> »).
Sans clé, rien n'est envoyé : le contenu est seulement écrit dans les logs du serveur.
"""

from __future__ import annotations

import html
import os
import threading

import requests

NOM_PRODUIT = os.getenv("NOM_PRODUIT", "Virallink")


def actif() -> bool:
    return bool(os.getenv("RESEND_API_KEY"))


def _gabarit(titre: str, corps: str, bouton: tuple[str, str] | None = None) -> str:
    b = ""
    if bouton:
        b = (f'<p style="margin:28px 0"><a href="{html.escape(bouton[1])}" style="background:#7A5C46;color:#fff;'
             f'padding:13px 22px;border-radius:10px;text-decoration:none;font-weight:600;display:inline-block">{html.escape(bouton[0])}</a></p>')
    return f"""<!doctype html><html><body style="margin:0;background:#F6F2EE;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#2B2420">
<div style="max-width:520px;margin:0 auto;padding:32px 20px">
  <p style="font-weight:700;font-size:15px;letter-spacing:.02em;color:#7A5C46;margin:0 0 20px">{html.escape(NOM_PRODUIT)}</p>
  <div style="background:#fff;border-radius:16px;padding:28px 26px;line-height:1.55;font-size:15px">
    <h1 style="font-size:20px;margin:0 0 14px">{html.escape(titre)}</h1>
    {corps}{b}
  </div>
  <p style="font-size:12px;color:#8A7F78;margin:18px 4px 0">Tu reçois cet e-mail parce que tu as un compte {html.escape(NOM_PRODUIT)}.</p>
</div></body></html>"""


def envoie(destinataire: str, sujet: str, contenu_html: str, attendre: bool = False) -> bool:
    """Envoi en arrière-plan (ne bloque jamais l'interface). Renvoie False si Resend n'est pas configuré."""
    if not actif():
        print(f"[e-mail non envoyé : RESEND_API_KEY absente] À {destinataire} — {sujet}")
        return False

    def go():
        try:
            r = requests.post("https://api.resend.com/emails", timeout=20,
                              headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}"},
                              json={"from": os.getenv("EMAIL_EXPEDITEUR", f"{NOM_PRODUIT} <onboarding@resend.dev>"),
                                    "to": [destinataire], "subject": sujet, "html": contenu_html})
            if r.status_code >= 400:
                print(f"[e-mail] échec Resend {r.status_code} : {r.text[:300]}")
        except Exception as e:  # noqa: BLE001
            print(f"[e-mail] échec : {e}")
    if attendre:
        go()
    else:
        threading.Thread(target=go, daemon=True).start()
    return True


def bienvenue(email: str, prenom: str, url: str, lien_confirmation: str = "", jours_essai: int = 7):
    p = html.escape(prenom or "")
    envoie(email, f"Bienvenue sur {NOM_PRODUIT} : confirme ton adresse", _gabarit(
        f"Bienvenue{' ' + p if p else ''} !",
        "<p>Ton compte est prêt. Confirme ton adresse en un clic, puis crée ta boutique : elle est gratuite, sans limite de durée.</p>"
        "<p>Ensuite, pour y amener du monde, Virallink te montre les publications qui cartonnent dans ta niche et les écrit pour toi. "
        f"Tu as {jours_essai} jours d'essai gratuit pour ça, à démarrer quand tu veux.</p>",
        ("Confirmer mon adresse", lien_confirmation or url)))


def confirmation(email: str, prenom: str, lien: str):
    p = html.escape(prenom or "")
    envoie(email, "Confirme ton adresse e-mail", _gabarit(
        f"{'Bonjour ' + p + ', u' if p else 'U'}n clic et c'est bon",
        "<p>Clique sur le bouton pour confirmer ton adresse e-mail. Ça débloque ton essai gratuit et l'écriture par Virall.ai.</p>"
        "<p style='color:#8A7F78;font-size:13px'>Si tu n'as pas créé de compte, ignore simplement cet e-mail.</p>",
        ("Confirmer mon adresse", lien)))


def reinitialisation(email: str, lien: str):
    envoie(email, "Choisis un nouveau mot de passe", _gabarit(
        "Nouveau mot de passe",
        "<p>Tu as demandé à changer ton mot de passe. Clique sur le bouton ci-dessous : le lien est valable 1 heure.</p>"
        "<p style='color:#8A7F78;font-size:13px'>Si tu n'es pas à l'origine de cette demande, ignore simplement cet e-mail.</p>",
        ("Choisir un nouveau mot de passe", lien)))


def veille_prete(email: str, prenom: str, nb: int, url: str):
    p = html.escape(prenom or "")
    envoie(email, f"Ta veille de la semaine est prête : {nb} Reels adaptés", _gabarit(
        f"{'Bonjour ' + p + ', t' if p else 'T'}a veille est prête",
        f"<p><b>{nb} Reels viraux</b> ont été trouvés et adaptés à ta niche, avec ton planning de la semaine.</p>"
        "<p>Ouvre la galerie, choisis tes préférés et passe au tournage.</p>",
        ("Voir mes Reels", url)))


def contenu_pret(email: str, prenom: str, type_: str, titre: str, url: str):
    """Le studio a fini un Reel ou un carrousel : lien direct vers le contenu, à ouvrir sur le téléphone pour publier."""
    p = html.escape(prenom or "")
    quoi = "Ton Reel est monté" if type_ == "reel" else "Tes stories sont prêtes" if type_ == "stories" else "Ton carrousel est prêt"
    envoie(email, f"{quoi} : il n'y a plus qu'à publier", _gabarit(
        f"{'Bonjour ' + p + ', ' if p else ''}{quoi[0].lower() + quoi[1:] if p else quoi}",
        (f"<p><b>{html.escape(titre)}</b></p>" if titre else "")
        + "<p>Ouvre ce lien <b>sur ton téléphone</b> : un bouton envoie le contenu directement dans Instagram, "
          "un autre copie la légende. Le son à ajouter est indiqué juste en dessous.</p>",
        ("Publier mon contenu", url)))


def synthese(email: str, prenom: str, blocs: list[tuple[str, str]], url: str, url_reglages: str):
    """Récapitulatif du lundi : veille, publications, boutique. blocs = [(titre, html)]."""
    p = html.escape(prenom or "")
    corps = "".join(f'<h2 style="font-size:16px;margin:22px 0 8px">{html.escape(t)}</h2>{h}' for t, h in blocs)
    corps += (f'<p style="font-size:12px;color:#8A7F78;margin-top:26px">Tu reçois ce récapitulatif chaque lundi. '
              f'<a href="{html.escape(url_reglages)}" style="color:#8A7F78">Le désactiver</a></p>')
    envoie(email, "Ta semaine sur " + NOM_PRODUIT, _gabarit(f"Bonjour{' ' + p if p else ''}, voici ta semaine", corps, ("Ouvrir mon espace", url)))


def relance(email: str, prenom: str, url: str):
    p = html.escape(prenom or "")
    envoie(email, "Du nouveau dans ta niche", _gabarit(
        f"{'Coucou ' + p + ', t' if p else 'T'}u nous manques !",
        "<p>Ça fait quelques jours qu'on ne t'a pas vue. Pendant ce temps, de nouvelles publications ont explosé dans ta niche : "
        "elles t'attendent dans ton espace.</p><p>Dix minutes suffisent pour choisir les trois prochaines à refaire à ta façon.</p>",
        ("Voir ce qui cartonne", url)))


def bienvenue_boutique(email: str, prenom: str, url: str, lien_confirmation: str = ""):
    p = html.escape(prenom or "")
    envoie(email, "Ta boutique t'attend : confirme ton adresse", _gabarit(
        f"Bienvenue{' ' + p if p else ''} !",
        "<p>Ton compte est prêt. Confirme ton adresse en un clic, puis termine ta boutique : ton nom, tes couleurs, "
        "ta première offre. Compte quelques minutes, les questions arrivent une par une.</p>"
        "<p>C'est gratuit, sans limite de durée. Tu pourras ajouter tes produits, récolter des e-mails et suivre tes visites.</p>",
        ("Confirmer et finir ma boutique", lien_confirmation or url)))


def _pied_conseils(url_reglages: str) -> str:
    return (f'<p style="font-size:12px;color:#8A7F78;margin-top:26px">Tu reçois quelques conseils pendant tes premiers jours. '
            f'<a href="{html.escape(url_reglages)}" style="color:#8A7F78">Ne plus les recevoir</a></p>')


def conseil_boutique(n: int, email: str, prenom: str, publiee: bool, jours_essai: int, url_boutique: str, url_essai: str, url_reglages: str,
                     commencee: bool = True, url_tendances: str = ""):
    """Suite d'e-mails des comptes dont l'essai n'a pas encore servi : la boutique d'abord, puis ce qui lui amène du monde
    (les tendances de sa niche, gratuites), puis l'essai, sans insister. `url_tendances` vide : bibliothèque de niche coupée."""
    p = html.escape(prenom or "")
    salut = f"<p>Bonjour{' ' + p if p else ''},</p>"
    if n == 1:
        if not commencee:
            sujet, titre = "Ta boutique gratuite t'attend", "Quelques minutes et elle est en ligne"
            corps = (salut + "<p>Tu as créé ton compte, mais pas encore ta boutique. Virallink te pose les questions une par une : "
                     "ton nom, tes couleurs, ta première offre. À la fin, tu as un lien à coller dans ta bio Instagram.</p>"
                     "<p>C'est gratuit, sans limite de durée.</p>")
            bouton = ("Créer ma boutique", url_boutique)
        elif not publiee:
            sujet, titre = "Ta boutique n'est pas encore en ligne", "Il ne manque presque rien"
            corps = (salut + "<p>Tu as commencé ta boutique mais elle n'est pas encore en ligne. Le plus long est fait : "
                     "tes réponses sont gardées, tu reprends là où tu t'es arrêtée.</p>"
                     "<p>Ensuite, colle ton lien dans ta bio Instagram. Tes abonnés le voient dès la minute suivante.</p>")
            bouton = ("Finir ma boutique", url_boutique)
        else:
            sujet, titre = "3 réglages qui font vendre une boutique", "Trois réglages qui changent tout"
            corps = (salut + "<p>Ta boutique est en ligne, bravo. Voici ce qui fait la différence chez celles qui vendent :</p>"
                     "<p><b>1. Un cadeau contre un e-mail.</b> Une checklist, un mini-guide, un code promo. Les gens laissent leur adresse "
                     "bien plus facilement quand ils repartent avec quelque chose.</p>"
                     "<p><b>2. Un seul bouton mis en avant.</b> Ton offre principale en premier, les autres liens dessous.</p>"
                     "<p><b>3. Le lien partout.</b> Dans ta bio, mais aussi en story une fois par semaine, avec le sticker lien.</p>")
            bouton = ("Ouvrir ma boutique", url_boutique)
        return envoie(email, sujet, _gabarit(titre, corps + _pied_conseils(url_reglages), bouton))
    if n == 2:
        corps = salut + ("<p>Une boutique ne vend que si des gens arrivent dessus. Sur Instagram, ils viennent des publications "
                         "qui accrochent dès la première seconde.</p>")
        if url_tendances:
            corps += ("<p>Dans ton espace, tu vois déjà celles qui explosent en ce moment dans ta niche. C'est gratuit, "
                      "et mis à jour chaque jour.</p>"
                      "<p>Quand l'une te plaît, Virall.ai peut la réécrire pour ton audience : accroche, texte, légende, prête à publier. "
                      f"C'est ce que tu peux essayer {jours_essai} jours, sans carte bancaire. Si tu ne choisis rien ensuite, tu restes "
                      "en gratuit et ta boutique ne bouge pas.</p>")
            bouton = ("Voir ce qui cartonne dans ma niche", url_tendances)
        else:
            corps += ("<p>C'est ce que fait le reste de Virallink : il repère les publications qui ont explosé dans ta niche "
                      "et te les réécrit pour ton audience. Accroche, texte, légende, prêtes à publier.</p>"
                      f"<p>Tu peux l'essayer {jours_essai} jours, sans carte bancaire. Si tu ne choisis rien ensuite, tu restes en gratuit "
                      "et ta boutique ne bouge pas.</p>")
            bouton = (f"Essayer {jours_essai} jours", url_essai)
        return envoie(email, "D'où viennent les visites d'une boutique", _gabarit(
            "Ce qui se passe avant la boutique", corps + _pied_conseils(url_reglages), bouton))
    corps = (salut + f"<p>Petit rappel : tes {jours_essai} jours d'essai sont toujours disponibles. "
             "Virall.ai réécrit pour toi les publications qui ont explosé dans ta niche, prépare ton mois de carrousels "
             "et les met en images au studio.</p>"
             "<p>Pas de carte bancaire, pas d'engagement. C'est le dernier message à ce sujet.</p>")
    return envoie(email, f"Tes {jours_essai} jours d'essai t'attendent toujours", _gabarit(
        "Toujours partante ?", corps + _pied_conseils(url_reglages), ("Démarrer mon essai", url_essai)))


def fin_essai(n: int, email: str, prenom: str, adaptes: int, formule: dict, url: str, url_reglages: str, crees: int = 0):
    """n=1 : deux jours avant la fin ; n=2 : le jour où l'essai se termine. Le bilan ne cite que ce qu'elle a vraiment utilisé."""
    p = html.escape(prenom or "")
    prix = f"{formule.get('prix', 0):.2f}".replace(".", ",").replace(",00", "")
    nom = html.escape(formule.get("nom") or "Créateur")
    faits = [f"Virall.ai a écrit <b>{adaptes} publication{'s' if adaptes > 1 else ''}</b> pour toi" if adaptes else "",
             f"tu as créé <b>{crees} contenu{'s' if crees > 1 else ''}</b> au studio" if crees else ""]
    faits = [x for x in faits if x]
    bilan = f"<p>Pendant ton essai, {' et '.join(faits)}.</p>" if faits else ""
    pied = (f'<p style="font-size:12px;color:#8A7F78;margin-top:26px">Sans engagement, résiliable en un clic. '
            f'<a href="{html.escape(url_reglages)}" style="color:#8A7F78">Ne plus recevoir ces e-mails</a></p>')
    if n == 1:
        corps = (f"<p>Bonjour{' ' + p if p else ''},</p><p>Ton essai gratuit se termine dans deux jours.</p>" + bilan +
                 f"<p>Pour continuer à recevoir chaque lundi les publications qui cartonnent dans ta niche, écrites pour toi, "
                 f"la formule <b>{nom}</b> est à <b>{prix} € par mois</b>.</p>"
                 "<p>Si tu ne choisis rien, rien n'est prélevé : tu passes en gratuit et ta boutique reste en ligne.</p>")
        return envoie(email, "Ton essai se termine dans 2 jours", _gabarit("Plus que deux jours", corps + pied, ("Choisir ma formule", url)))
    corps = (f"<p>Bonjour{' ' + p if p else ''},</p><p>Ton essai gratuit est terminé, et rien n'est prélevé. Ton compte reste ouvert "
             "en gratuit : tu gardes ta boutique en ligne et tout ce que tu as créé.</p>" + bilan +
             f"<p>L'écriture par Virall.ai, ton plan du mois et le studio sont en pause. Pour les retrouver, la formule <b>{nom}</b> est à "
             f"<b>{prix} € par mois</b>.</p>")
    return envoie(email, "Ton essai est terminé", _gabarit("Ton essai est terminé", corps + pied, ("Choisir ma formule", url)))
