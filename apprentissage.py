"""Boucle de résultats : ce qui marche sur TON compte + ta voix de marque."""

from __future__ import annotations

import statistics
from pathlib import Path


from modele import Post, log

COLS_SUIVI = {"mecanique": "Mécanique", "vues": "Vues J+2", "mots_cles": "Commentaires mot-clé", "conv": "Conversations DM"}


def _num(v):
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------
#  1. Tes Reels publiés (scraping de ton compte)
# ------------------------------------------------------------
def mon_compte(cfg: dict, token: str, ia) -> list[Post]:
    m, ap = cfg.get("mon_compte") or {}, cfg["apprentissage"]
    from collecte import collecte_comptes
    posts = collecte_comptes([(pl, m[k]) for pl, k in (("Instagram", "instagram"), ("TikTok", "tiktok")) if m.get(k)],
                             ap["jours"], 40, cfg, token)
    posts = [p for p in posts if p.format in ("Reel", "Vidéo") and p.vues]
    if not posts:
        return []
    log(f"Ton compte : {len(posts)} Reels sur {ap['jours']} jours, classement des mécaniques…")
    classement = ia.classe_mecaniques(posts)
    for p in posts:
        p.adaptation = {"mecanique": classement.get(p.id, "Autre")}
    return posts


# ------------------------------------------------------------
#  2. Ton suivi Excel (conversations réellement obtenues)
# ------------------------------------------------------------
def suivi_excel(dossiers: list[Path]) -> list[dict]:
    """Lit l'onglet « Planning & suivi » de tous les Excel remplis (dossier suivi/ et anciens rapports)."""
    import openpyxl
    lignes, vus = [], set()
    for d in dossiers:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.xlsx")):
            if f.name.startswith("~$"):
                continue
            try:
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            except Exception:  # noqa: BLE001
                continue
            if "Planning & suivi" not in wb.sheetnames:
                continue
            rows = list(wb["Planning & suivi"].iter_rows(values_only=True))
            if not rows:
                continue
            entete = [str(c or "") for c in rows[0]]
            idx = {k: entete.index(v) for k, v in COLS_SUIVI.items() if v in entete}
            if "mecanique" not in idx:
                continue
            for r in rows[1:]:
                mec = r[idx["mecanique"]] if idx["mecanique"] < len(r) else None
                if not mec:
                    continue
                vals = {k: _num(r[i]) if i < len(r) else None for k, i in idx.items() if k != "mecanique"}
                if all(v is None for v in vals.values()):
                    continue  # ligne non remplie
                cle = (f.stem.split("_")[-1], r[0], mec)
                if cle in vus:
                    continue
                vus.add(cle)
                lignes.append({"mecanique": str(mec), **vals})
    return lignes


# ------------------------------------------------------------
#  3. Synthèse
# ------------------------------------------------------------
def synthese(mes_posts: list[Post], suivi: list[dict]) -> dict:
    res = {"par_mecanique": [], "mecaniques_top": [], "mecaniques_flop": [], "texte": "",
           "nb_reels": len(mes_posts), "nb_suivi": len(suivi), "meilleures_legendes": []}
    if not mes_posts and not suivi:
        return res

    med_vues = statistics.median([p.vues for p in mes_posts]) if mes_posts else None
    med_com = statistics.median([(p.commentaires or 0) / p.vues for p in mes_posts]) if mes_posts else None
    conv_glob = [s["conv"] for s in suivi if s.get("conv") is not None]
    moy_conv = statistics.mean(conv_glob) if conv_glob else None

    mecs = sorted({(p.adaptation or {}).get("mecanique", "Autre") for p in mes_posts} | {s["mecanique"] for s in suivi})
    for mec in mecs:
        lst = [p for p in mes_posts if (p.adaptation or {}).get("mecanique") == mec]
        conv = [s["conv"] for s in suivi if s["mecanique"] == mec and s.get("conv") is not None]
        ligne = {"mecanique": mec, "n_reels": len(lst), "n_suivi": len(conv)}
        scores = []
        if lst and med_vues:
            ligne["vues_vs_moyenne"] = round(statistics.median([p.vues for p in lst]) / med_vues, 2)
            scores.append((ligne["vues_vs_moyenne"], 1))
            if med_com:
                ligne["commentaires_vs_moyenne"] = round(statistics.median([(p.commentaires or 0) / p.vues for p in lst]) / med_com, 2)
                scores.append((ligne["commentaires_vs_moyenne"], 1))
        if conv:
            ligne["conversations_moy"] = round(statistics.mean(conv), 1)
            if moy_conv:
                scores.append((ligne["conversations_moy"] / moy_conv, 2))  # les conversations comptent double
        ligne["indice"] = round(sum(v * w for v, w in scores) / sum(w for _, w in scores), 2) if scores else None
        res["par_mecanique"].append(ligne)
        if (ligne["n_reels"] + ligne["n_suivi"]) >= 2 and ligne["indice"]:
            if ligne["indice"] >= 1.2:
                res["mecaniques_top"].append(mec)
            elif ligne["indice"] <= 0.7:
                res["mecaniques_flop"].append(mec)
    res["par_mecanique"].sort(key=lambda l: l["indice"] or 0, reverse=True)

    t = []
    for l in res["par_mecanique"]:
        if l["indice"] is None:
            continue
        morceaux = []
        if "vues_vs_moyenne" in l:
            morceaux.append(f"vues ×{l['vues_vs_moyenne']} vs ta moyenne")
        if "commentaires_vs_moyenne" in l:
            morceaux.append(f"commentaires ×{l['commentaires_vs_moyenne']}")
        if "conversations_moy" in l:
            morceaux.append(f"{l['conversations_moy']} conversations DM en moyenne")
        t.append(f"- {l['mecanique']} ({l['n_reels'] + l['n_suivi']} Reels) : " + ", ".join(morceaux))
    if res["mecaniques_top"]:
        t.append(f"Mécaniques qui marchent le mieux : {', '.join(res['mecaniques_top'])}.")
    if res["mecaniques_flop"]:
        t.append(f"Mécaniques qui sous-performent : {', '.join(res['mecaniques_flop'])}.")
    res["texte"] = "\n".join(t)

    # Les légendes de tes meilleurs Reels servent d'exemples de voix
    meilleurs = sorted(mes_posts, key=lambda p: ((p.commentaires or 0) / p.vues, p.vues), reverse=True)
    res["meilleures_legendes"] = [p.legende.strip() for p in meilleurs if len(p.legende.strip()) > 40][:6]
    return res


# ------------------------------------------------------------
#  4. Voix de marque
# ------------------------------------------------------------
def voix(cfg: dict, racine: Path, legendes_auto: list[str]) -> str:
    morceaux = []
    f = racine / cfg["voix"]["fichier"]
    if f.exists():
        contenu = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith("<!--")).strip()
        if contenu and "COLLE ICI" not in contenu:
            morceaux.append(contenu)
    if cfg["voix"].get("legendes_auto", True) and legendes_auto:
        morceaux.append("Légendes de ses Reels qui ont le mieux marché :\n\n" + "\n\n---\n\n".join(legendes_auto))
    return "\n\n".join(morceaux)[:12000]
