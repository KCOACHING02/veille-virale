"""
Suivi des Reels publiés par l'utilisateur (bouton « J'ai publié ») :
relevé automatique des vues / likes / commentaires à la publication, à J+2 et à J+7,
conversations saisies par l'utilisateur, et données réinjectées dans l'apprentissage.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from espace import Espace
from modele import log

JALONS_JOURS = (2, 7)   # relevés après publication


def _fichier(esp: Espace):
    return esp.racine / "publications.json"


def charge(esp: Espace) -> list[dict]:
    f = _fichier(esp)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except ValueError:
        return []


def _sauve(esp: Espace, pubs: list[dict]):
    f = _fichier(esp)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(pubs, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def analyse_lien(url: str) -> tuple[str, str, str] | None:
    """(plateforme, url normalisée, identifiant) d'un lien de Reel / vidéo, ou None."""
    url = (url or "").strip()
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([\w-]+)", url)
    if m:
        return "Instagram", f"https://www.instagram.com/reel/{m.group(1)}/", m.group(1)
    m = re.search(r"tiktok\.com/@([\w.]+)/(?:video|photo)/(\d+)", url)
    if m:
        return "TikTok", f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}", m.group(2)
    return None


def ajoute(esp: Espace, url: str, inspiration: dict | None = None) -> dict:
    lien = analyse_lien(url)
    if not lien:
        raise ValueError("Lien non reconnu : colle le lien de ton Reel Instagram (…/reel/…) ou de ta vidéo TikTok (…/video/…).")
    plateforme, url_n, ident = lien
    pubs = charge(esp)
    if any(p["ident"] == ident for p in pubs):
        raise ValueError("Ce Reel est déjà suivi.")
    ins = inspiration or {}
    ad = ins.get("adaptation") or {}
    pub = {
        "id": uuid.uuid4().hex[:10], "plateforme": plateforme, "url": url_n, "ident": ident,
        "ajoute_le": datetime.now(timezone.utc).isoformat(timespec="minutes"), "publie_le": None,
        "inspiration": {"cle": ins.get("cle"), "compte": ins.get("compte"), "url": ins.get("url"),
                        "vues": ins.get("vues"), "miniature": ins.get("miniature")},
        "mecanique": ad.get("mecanique") or "Autre",
        "hook": ad.get("hook_viral") or (ad.get("hooks_adaptes") or [""])[0],
        "releves": [], "conversations": None, "clients": None,
    }
    pubs.insert(0, pub)
    _sauve(esp, pubs)
    return pub


def modifie(esp: Espace, pid: str, **champs) -> dict:
    pubs = charge(esp)
    for p in pubs:
        if p["id"] == pid:
            for k in ("conversations", "clients"):
                if k in champs:
                    v = champs[k]
                    p[k] = None if v in (None, "") else max(0, int(v))
            _sauve(esp, pubs)
            return p
    raise KeyError(pid)


def supprime(esp: Espace, pid: str):
    _sauve(esp, [p for p in charge(esp) if p["id"] != pid])


def _age_jours(p: dict, maintenant: datetime) -> float:
    ref = p.get("publie_le") or p["ajoute_le"]
    return (maintenant - datetime.fromisoformat(ref.replace("Z", "+00:00"))).total_seconds() / 86400


def a_relever(p: dict, maintenant: datetime | None = None) -> bool:
    """Premier relevé tout de suite, puis un relevé à J+2 et à J+7."""
    maintenant = maintenant or datetime.now(timezone.utc)
    if not p["releves"]:
        return True
    age = _age_jours(p, maintenant)
    faits = {r.get("jalon") for r in p["releves"]}
    return any(age >= j and j not in faits for j in JALONS_JOURS) and age < 30


def a_relever_esp(esp: Espace) -> list[dict]:
    return [p for p in charge(esp) if a_relever(p)]


def _demo(cibles):
    """Mode démo : statistiques fictives mais plausibles."""
    import random
    from modele import Post
    res = []
    for p in cibles:
        rnd = random.Random(p["ident"])
        vues = rnd.randint(2000, 90000)
        res.append(Post(plateforme=p["plateforme"], compte="moi", id=p["ident"], url=p["url"],
                        date=(datetime.now(timezone.utc) - timedelta(days=rnd.randint(0, 8))).isoformat(),
                        format="Reel", legende="", vues=vues, likes=int(vues * .05), commentaires=int(vues * .006),
                        partages=int(vues * .004), enregistrements=int(vues * .007)))
    return res


def releve(esp: Espace, cfg: dict, token: str | None, forcer: bool = False, demo: bool = False) -> int:
    """Récupère les statistiques des publications à relever (un seul run Apify pour toutes)."""
    from collecte import collecte_posts
    pubs = charge(esp)
    cibles = [p for p in pubs if forcer or a_relever(p)]
    if not cibles:
        log("Aucune publication à mettre à jour pour l'instant")
        return 0
    log(f"Mise à jour de {len(cibles)} publication(s)…")
    trouves_l = _demo(cibles) if demo else collecte_posts([(p["plateforme"], p["url"]) for p in cibles], cfg, token)
    trouves = {p.id: p for p in trouves_l}
    maintenant = datetime.now(timezone.utc)
    n = 0
    for pub in cibles:
        post = trouves.get(pub["ident"]) or next((x for i, x in trouves.items() if pub["ident"] in (x.url or "") or pub["ident"] == i), None)
        if not post:
            log(f"  ⚠️  {pub['url']} introuvable (Reel supprimé, privé ou lien erroné)")
            continue
        if post.date and not pub.get("publie_le"):
            pub["publie_le"] = post.date
        age = _age_jours(pub, maintenant)
        jalon = max([j for j in JALONS_JOURS if age >= j] or [0])
        pub["releves"] = [r for r in pub["releves"] if r.get("jalon") != jalon] + [{
            "le": maintenant.isoformat(timespec="minutes"), "jalon": jalon, "age_jours": round(age, 1),
            "vues": post.vues, "likes": post.likes, "commentaires": post.commentaires,
            "partages": post.partages, "enregistrements": post.enregistrements,
        }]
        pub["miniature"] = pub.get("miniature") or post.cover_url
        n += 1
    _sauve(esp, pubs)
    log(f"✅ {n} publication(s) mises à jour")
    return n


def dernier(p: dict) -> dict:
    return p["releves"][-1] if p["releves"] else {}


def pour_apprentissage(esp: Espace) -> list[dict]:
    """Lignes au format du suivi Excel, pour l'apprentissage « ce qui marche chez toi »."""
    lignes = []
    for p in charge(esp):
        r = dernier(p)
        if not r and p.get("conversations") is None:
            continue
        lignes.append({"mecanique": p.get("mecanique") or "Autre", "vues": r.get("vues"),
                       "mots_cles": None, "conv": p.get("conversations")})
    return lignes


def bilan_semaine(esp: Espace, cfg: dict) -> dict:
    o = cfg["objectifs"]
    debut = datetime.now(timezone.utc) - timedelta(days=7)
    pubs = [p for p in charge(esp)
            if datetime.fromisoformat((p.get("publie_le") or p["ajoute_le"]).replace("Z", "+00:00")) >= debut]
    return {
        "publies": len(pubs), "objectif_publies": o["reels_par_jour"] * 7,
        "vues": sum(dernier(p).get("vues") or 0 for p in pubs),
        "conversations": sum(p.get("conversations") or 0 for p in pubs),
        "objectif_conversations": o["conversations_par_jour"] * 7,
        "clients": sum(p.get("clients") or 0 for p in pubs),
    }
