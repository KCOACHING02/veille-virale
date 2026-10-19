"""
E-mails transactionnels via Resend (https://resend.com) — sans SDK.
Variables : RESEND_API_KEY, EMAIL_EXPEDITEUR (ex. « Virallink <bonjour@ton-domaine.fr> »).
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


def bienvenue(email: str, prenom: str, url: str):
    p = html.escape(prenom or "")
    envoie(email, f"Bienvenue sur {NOM_PRODUIT}", _gabarit(
        f"Bienvenue{' ' + p if p else ''} !",
        "<p>Ton compte est prêt. En 5 minutes, l'assistant configure ta niche, ta voix et les comptes à surveiller.</p>"
        "<p>Ensuite, chaque semaine, tu reçois les Reels qui ont explosé chez les autres, déjà adaptés à ta niche : "
        "hook, script, légende et séquence DM.</p>",
        ("Ouvrir mon espace", url)))


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
    quoi = "Ton Reel est monté" if type_ == "reel" else "Ton carrousel est prêt"
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
    envoie(email, "Ta veille t'attend", _gabarit(
        f"{'Coucou ' + p + ', t' if p else 'T'}u nous manques !",
        "<p>Ça fait quelques jours qu'on ne t'a pas vue. Pendant ce temps, les comptes que tu surveilles ont continué à publier : "
        "les Reels qui ont explosé cette semaine t'attendent, déjà adaptés à ta niche.</p><p>Dix minutes suffisent pour choisir les trois prochains à tourner.</p>",
        ("Voir mes Reels", url)))
