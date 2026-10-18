"""
Studio : transforme un Reel adapté en contenu prêt à publier.
  - Carrousel : slides 1080×1350 avec les textes posés sur les images de l'utilisateur (ou sur un fond uni).
  - Reel : la vidéo de l'utilisateur recadrée en 9:16, avec le hook et les sous-titres incrustés.
           Sans vidéo, un diaporama 9:16 est monté à partir de ses images et des textes des slides.
  - Package ZIP : visuels + légende + script + messages privés + consignes de publication.
Un projet = un dossier data/espaces/<id>/studio/<sid>/ (projet.json, sources/, sortie/).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from espace import CODE, Espace
from modele import log

POLICES = CODE / "static" / "fonts"
CARROUSEL = (1080, 1350)
VERTICAL = (1080, 1920)
EXT_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
EXT_VIDEOS = {".mp4", ".mov", ".m4v", ".webm"}
THEMES = {
    "sombre": {"fond": (39, 27, 45), "texte": (255, 255, 255), "accent": (255, 79, 121), "doux": (216, 206, 221)},
    "clair": {"fond": (246, 244, 248), "texte": (39, 27, 45), "accent": (255, 79, 121), "doux": (94, 81, 102)},
    "rose": {"fond": (255, 79, 121), "texte": (255, 255, 255), "accent": (39, 27, 45), "doux": (255, 227, 234)},
}
DUREE_MAX_REEL = 180
SLIDE_DIAPORAMA_S = 3.0


# ------------------------------------------------------------
#  Projets
# ------------------------------------------------------------
def _racine(esp: Espace) -> Path:
    return esp.racine / "studio"


def dossier(esp: Espace, sid: str) -> Path:
    d = _racine(esp) / Path(sid).name
    if not (d / "projet.json").exists():
        raise FileNotFoundError(sid)
    return d


def charge(esp: Espace, sid: str) -> dict:
    return json.loads((dossier(esp, sid) / "projet.json").read_text(encoding="utf-8"))


def sauve(esp: Espace, projet: dict):
    d = _racine(esp) / projet["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "projet.tmp"
    tmp.write_text(json.dumps(projet, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "projet.json")


def liste(esp: Espace) -> list[dict]:
    r = _racine(esp)
    res = []
    for f in sorted(r.glob("*/projet.json"), reverse=True) if r.exists() else []:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            res.append({k: p.get(k) for k in ("id", "cree", "titre", "type", "statut", "miniature", "compte", "fichiers", "zip")})
        except ValueError:
            continue
    return sorted(res, key=lambda p: p.get("cree") or "", reverse=True)


def supprime(esp: Espace, sid: str):
    shutil.rmtree(dossier(esp, sid), ignore_errors=True)


def cree(esp: Espace, cfg: dict, post: dict, typ: str, analyse_id: str | None) -> dict:
    """Nouveau projet à partir d'un Reel adapté (les textes des slides sont écrits ensuite par Claude)."""
    ad = post.get("adaptation") or {}
    hook = ad.get("hook_viral") or (ad.get("hooks_adaptes") or [""])[0]
    hashtags = " ".join("#" + h for h in (cfg["decouverte"].get("hashtags_instagram") or [])[:5])
    legende = ad.get("legende_adaptee") or ad.get("legende_reprise") or ""
    if hashtags and "#" not in legende:
        legende = legende.rstrip() + "\n\n" + hashtags
    sid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    projet = {
        "id": sid, "cree": datetime.now().isoformat(timespec="minutes"), "type": typ if typ in ("carrousel", "reel") else "carrousel",
        "titre": hook[:90] or "Sans titre", "analyse_id": analyse_id, "cle": post.get("cle"), "compte": post.get("compte"),
        "miniature": post.get("miniature"), "statut": "brouillon", "erreur": None,
        "hook": hook, "texte_ecran": ad.get("texte_ecran_adapte") or "", "script": ad.get("script_reel") or "",
        "cta": ad.get("cta_conversation") or "", "dm": ad.get("sequence_dm") or [], "legende": legende,
        "slides": [], "images": [], "video": None, "theme": "sombre", "sous_titres": True,
        "pseudo": (cfg.get("mon_compte") or {}).get("instagram") or "",
        "fichiers": [], "zip": None, "adaptation": ad,
    }
    sauve(esp, projet)
    return projet


def ecrit_textes(esp: Espace, cfg: dict, sid: str, demo: bool = False) -> dict:
    """Tâche de fond : Claude écrit les textes des slides à partir de l'adaptation."""
    p = charge(esp, sid)
    log("J'écris les textes de tes slides…")
    if demo:
        res = {"slides": [{"titre": p["hook"] or "[démo] Ton hook", "texte": ""},
                          *({"titre": f"[démo] Idée n°{i}", "texte": "[démo] Une phrase courte qui développe l'idée, dans ton ton."} for i in range(1, 6)),
                          {"titre": f"Commente {cfg['objectifs']['mot_cle_cta']}", "texte": "[démo] et je t'envoie le guide en privé"}],
               "legende": p["legende"]}
    else:
        from apprentissage import voix
        from ia import IA
        res = IA(cfg, voix=voix(cfg, esp.racine, [])).carrousel(p.get("adaptation") or {})
        if res.get("erreur"):
            raise RuntimeError(res["erreur"])
    p = charge(esp, sid)  # relu : l'utilisateur a pu importer des fichiers pendant ce temps
    p["slides"] = [{"titre": s.get("titre", "").strip(), "texte": s.get("texte", "").strip()} for s in res.get("slides") or []][:10]
    if p["type"] == "carrousel" and res.get("legende"):
        p["legende"] = res["legende"]
    sauve(esp, p)
    log(f"✅ {len(p['slides'])} slides écrites")
    return {"id": sid}


def ajoute_fichier(esp: Espace, sid: str, nom: str, flux) -> dict:
    """Importe une image (convertie en JPEG) ou une vidéo dans le projet."""
    p = charge(esp, sid)
    src = dossier(esp, sid) / "sources"
    src.mkdir(exist_ok=True)
    ext = Path(nom or "").suffix.lower()
    if ext in EXT_VIDEOS:
        for ancien in src.glob("video.*"):
            ancien.unlink()
        dest = src / f"video{ext}"
        flux.save(dest)
        d = _duree(dest)
        if not d:
            dest.unlink(missing_ok=True)
            raise ValueError("Cette vidéo est illisible. Essaie un fichier .mp4 ou .mov.")
        p["video"] = dest.name
        p["video_duree"] = round(d, 1)
    elif ext in EXT_IMAGES:
        if len(p["images"]) >= 10:
            raise ValueError("10 images maximum par projet.")
        from PIL import Image, ImageOps
        if ext in (".heic", ".heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                raise ValueError("Format HEIC non pris en charge : exporte la photo en JPEG.") from None
        try:
            im = ImageOps.exif_transpose(Image.open(flux.stream)).convert("RGB")
        except Exception:  # noqa: BLE001
            raise ValueError(f"Image illisible : {nom}") from None
        im.thumbnail((2160, 2160))
        dest = src / f"img_{uuid.uuid4().hex[:8]}.jpg"
        im.save(dest, "JPEG", quality=90)
        p["images"].append(dest.name)
    else:
        raise ValueError("Format non pris en charge : images JPEG/PNG/WEBP/HEIC ou vidéos MP4/MOV.")
    sauve(esp, p)
    return p


def retire_fichier(esp: Espace, sid: str, nom: str) -> dict:
    p = charge(esp, sid)
    nom = Path(nom).name
    (dossier(esp, sid) / "sources" / nom).unlink(missing_ok=True)
    p["images"] = [i for i in p["images"] if i != nom]
    if p.get("video") == nom:
        p["video"] = None
    sauve(esp, p)
    return p


def modifie(esp: Espace, sid: str, champs: dict) -> dict:
    p = charge(esp, sid)
    for k in ("legende", "hook", "theme", "sous_titres", "type", "pseudo", "titre"):
        if k in champs:
            p[k] = champs[k]
    if isinstance(champs.get("slides"), list):
        p["slides"] = [{"titre": str(s.get("titre", ""))[:200], "texte": str(s.get("texte", ""))[:400]} for s in champs["slides"]][:10]
    if isinstance(champs.get("images"), list):  # nouvel ordre des images
        p["images"] = [i for i in champs["images"] if i in p["images"]] + [i for i in p["images"] if i not in champs["images"]]
    if p["theme"] not in THEMES:
        p["theme"] = "sombre"
    sauve(esp, p)
    return p


# ------------------------------------------------------------
#  Texte et images (Pillow)
# ------------------------------------------------------------
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍\U000E0000-\U000E007F]+")


def propre(t: str) -> str:
    """Retire les emojis (absents de la police) et les espaces superflus."""
    return re.sub(r"[ \t]+", " ", _EMOJI.sub("", t or "")).strip()


def _police(graisse: str, taille: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(POLICES / f"Poppins-{graisse}.ttf"), taille)


def _lignes(dessin, texte: str, police, largeur: int) -> list[str]:
    res = []
    for paragraphe in texte.split("\n"):
        ligne = ""
        for mot in paragraphe.split():
            essai = (ligne + " " + mot).strip()
            if dessin.textlength(essai, font=police) <= largeur or not ligne:
                ligne = essai
            else:
                res.append(ligne)
                ligne = mot
        res.append(ligne)
    return [l for l in res if l is not None]


def _ajuste(dessin, texte, graisse, largeur, hauteur, maxi, mini, interligne=1.18):
    """Plus grande taille de police pour laquelle le texte tient dans la boîte."""
    taille = maxi
    while True:
        pol = _police(graisse, taille)
        lignes = _lignes(dessin, texte, pol, largeur)
        h = int(len(lignes) * taille * interligne)
        if h <= hauteur or taille <= mini:
            return pol, lignes, h, taille
        taille -= 4


def _couvre(im, taille):
    """Recadre l'image pour remplir exactement le format (comme object-fit: cover)."""
    from PIL import ImageOps
    return ImageOps.fit(im, taille, method=3, centering=(0.5, 0.4))


def _degrade(taille, debut: float, alpha_max: int = 215):
    """Calque noir transparent en haut, de plus en plus opaque vers le bas (pour lire le texte sur la photo)."""
    from PIL import Image
    l, h = taille
    calque = Image.new("L", (1, h), 0)
    for y in range(h):
        r = (y / h - debut) / (1 - debut)
        calque.putpixel((0, y), int(alpha_max * max(0.0, min(1.0, r)) ** 1.3))
    noir = Image.new("RGBA", taille, (15, 10, 18, 0))
    noir.putalpha(calque.resize(taille))
    return noir


def slide(slide_: dict, i: int, n: int, image: Path | None, theme: str, pseudo: str, taille=CARROUSEL, reel: bool = False):
    """Dessine une slide. Avec image : texte en bas sur un dégradé. Sans image : fond uni du thème."""
    from PIL import Image, ImageDraw
    th = THEMES.get(theme, THEMES["sombre"])
    l, h = taille
    marge = int(l * 0.085)
    titre, texte = propre(slide_.get("titre", "")), propre(slide_.get("texte", ""))
    premiere, derniere = i == 0, i == n - 1
    if image and image.exists():
        fond = _couvre(Image.open(image).convert("RGB"), taille).convert("RGBA")
        fond.alpha_composite(_degrade(taille, 0.32 if (texte or premiere) else 0.45))
        couleur, couleur2, accent = (255, 255, 255), (235, 228, 238), th["accent"] if theme != "rose" else (255, 79, 121)
        sur_photo = True
    else:
        fond = Image.new("RGBA", taille, th["fond"] + (255,))
        couleur, couleur2, accent = th["texte"], th["doux"], th["accent"]
        sur_photo = False
    d = ImageDraw.Draw(fond)
    largeur = l - 2 * marge
    # Zone de texte : bas de l'image sur photo, centrée sur fond uni
    h_titre_max = int(h * (0.42 if premiere else 0.30))
    pol_t, lignes_t, ht, taille_t = _ajuste(d, titre, "Bold", largeur, h_titre_max, 104 if premiere else (82 if sur_photo else 96), 46)
    pol_x, lignes_x, hx, taille_x = (None, [], 0, 0)
    if texte:
        pol_x, lignes_x, hx, taille_x = _ajuste(d, texte, "Regular", largeur, int(h * 0.26), 46, 30, 1.32)
    ecart = int(taille_t * 0.55) if texte else 0
    bloc = ht + ecart + hx + int(h * 0.025)
    y = (h - int(h * 0.12) - bloc) if sur_photo else (h - bloc) // 2
    # Barre d'accent au-dessus du titre
    d.rounded_rectangle([marge, y - 34, marge + 86, y - 22], radius=6, fill=accent)
    for ligne in lignes_t:
        d.text((marge, y), ligne, font=pol_t, fill=couleur)
        y += int(taille_t * 1.18)
    y += ecart
    for ligne in lignes_x:
        d.text((marge, y), ligne, font=pol_x, fill=couleur2)
        y += int(taille_x * 1.32)
    # Compteur, pseudo, invitation à faire glisser
    petit = _police("Medium", 30)
    haut = int(h * (0.09 if reel else 0.045))  # en Reel, on laisse la place à l'interface d'Instagram
    if n > 1 and not reel:
        cpt = f"{i + 1}/{n}"
        d.text((l - marge - d.textlength(cpt, font=petit), haut), cpt, font=petit, fill=couleur2)
    if pseudo:
        d.text((marge, haut), "@" + pseudo.lstrip("@"), font=petit, fill=couleur2)
    if n > 1 and not derniere and not reel:
        g, c_g = "Glisse", (accent if not sur_photo else couleur)
        y_g = h - int(h * 0.065)
        x_fleche = l - marge - 34
        d.text((x_fleche - 14 - d.textlength(g, font=petit), y_g), g, font=petit, fill=c_g)
        y_m = y_g + 22  # flèche dessinée (la police n'a pas le caractère →)
        d.line([(x_fleche, y_m), (x_fleche + 30, y_m)], fill=c_g, width=4)
        d.line([(x_fleche + 19, y_m - 11), (x_fleche + 31, y_m), (x_fleche + 19, y_m + 11)], fill=c_g, width=4, joint="curve")
    return fond.convert("RGB")


# ------------------------------------------------------------
#  Vidéo (ffmpeg + libass)
# ------------------------------------------------------------
def _duree(f: Path) -> float | None:
    from video import duree
    return duree(f)


def _dimensions(f: Path) -> tuple[int, int]:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
                              "-of", "json", str(f)], capture_output=True, text=True, timeout=60).stdout
        st = json.loads(out)["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        rot = abs(int(next((x.get("rotation", 0) for x in st.get("side_data_list") or [] if "rotation" in x), 0)))
        return (h, w) if rot in (90, 270) else (w, h)
    except Exception:  # noqa: BLE001
        return (1080, 1920)


def _a_du_son(f: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True, timeout=60).stdout
    return bool(out.strip())


def _t(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def _ass_txt(t: str) -> str:
    return propre(t).replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def sous_titres(fichier: Path, dossier_: Path) -> list[tuple[float, float, str]]:
    """Transcription mot à mot (Whisper local) → blocs de 2 à 4 mots."""
    from video import audio, lit_wav, modele_whisper
    import os
    wav = audio(fichier, dossier_, secondes=DUREE_MAX_REEL)
    if not wav:
        return []
    try:
        son = lit_wav(wav, DUREE_MAX_REEL)
        if son.size < 1600:
            return []
        segments, _ = modele_whisper(os.getenv("WHISPER_MODEL", "base")).transcribe(
            son, vad_filter=True, beam_size=1, word_timestamps=True, condition_on_previous_text=False)
        mots = [(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or []) if w.word.strip()]
    finally:
        wav.unlink(missing_ok=True)
    blocs, courant = [], []
    for m in mots:
        courant.append(m)
        texte = " ".join(x[2] for x in courant)
        if len(courant) >= 4 or len(texte) >= 20 or m[2][-1:] in ".?!,":
            blocs.append((courant[0][0], courant[-1][1], texte))
            courant = []
    if courant:
        blocs.append((courant[0][0], courant[-1][1], " ".join(x[2] for x in courant)))
    # Pas de trou de clignotement entre deux blocs proches
    res = []
    for i, (a, b, t) in enumerate(blocs):
        suivant = blocs[i + 1][0] if i + 1 < len(blocs) else None
        res.append((a, min(suivant, b + 0.4) if suivant and suivant - b < 0.6 else b + 0.15, t))
    return res


def fichier_ass(hook: str, duree_hook: float, blocs: list, chemin: Path):
    entete = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Poppins,74,&H002D1B27,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,20,0,8,110,110,250,1
Style: Sous,Poppins,82,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,7,3,2,90,90,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lignes = []
    if hook:
        lignes.append(f"Dialogue: 1,{_t(0)},{_t(duree_hook)},Hook,,0,0,0,,{{\\fad(0,250)}}{_ass_txt(hook)}")
    for a, b, t in blocs:
        lignes.append(f"Dialogue: 0,{_t(a)},{_t(b)},Sous,,0,0,0,,{_ass_txt(t)}")
    chemin.write_text(entete + "\n".join(lignes) + "\n", encoding="utf-8")


def _ffmpeg(args: list[str], cwd: Path, timeout: int = 1800):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("Le montage vidéo a échoué : " + (r.stderr.strip().splitlines() or ["erreur inconnue"])[-1][:200])


ENCODAGE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def monte_reel(p: dict, d: Path, sortie: Path) -> list[str]:
    src = d / "sources" / p["video"]
    duree = min(_duree(src) or 0, DUREE_MAX_REEL)
    log("Je recadre ta vidéo au format Reel…")
    blocs = []
    if p.get("sous_titres", True):
        log("J'écoute ta vidéo pour écrire les sous-titres…")
        try:
            blocs = sous_titres(src, d)
            log(f"  {len(blocs)} sous-titres" if blocs else "  Aucune parole détectée : pas de sous-titres")
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️  Sous-titres impossibles ({str(e)[:120]}) : le Reel est monté sans")
    fichier_ass(propre(p.get("hook") or ""), min(3.5, duree or 3.5), blocs, d / "sous.ass")
    w, h = _dimensions(src)
    ass = f"ass=sous.ass:fontsdir={POLICES}"
    if w / h > 0.75:  # vidéo horizontale ou carrée : fond flou + vidéo entière au centre
        filtre = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[fond];"
                  "[0:v]scale=1080:-2[av];[fond][av]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1," + ass + "[v]")
    else:
        filtre = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1," + ass + "[v]"
    log("Montage de ton Reel (hook + sous-titres)…")
    son = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "128k"] if _a_du_son(src) else []
    _ffmpeg(["-i", str(src), "-t", str(DUREE_MAX_REEL), "-filter_complex", filtre, "-map", "[v]", *son, *ENCODAGE, str(sortie / "reel.mp4")], d)
    # Couverture : une image du début avec le hook
    from PIL import Image
    _ffmpeg(["-ss", "0.6", "-i", str(sortie / "reel.mp4"), "-frames:v", "1", "-q:v", "3", str(d / "cadre.jpg")], d, 120)
    if (d / "cadre.jpg").exists():
        couv = slide({"titre": p.get("hook") or "", "texte": ""}, 0, 1, d / "cadre.jpg", p.get("theme", "sombre"), "", VERTICAL, reel=True)
        couv.save(sortie / "couverture.jpg", "JPEG", quality=90)
        (d / "cadre.jpg").unlink(missing_ok=True)
    return ["reel.mp4", "couverture.jpg"] if (sortie / "couverture.jpg").exists() else ["reel.mp4"]


def monte_diaporama(p: dict, d: Path, sortie: Path) -> list[str]:
    """Reel sans vidéo : chaque slide (texte + image) devient un plan de 3 s, en 9:16."""
    log("Je prépare les plans de ton Reel…")
    slides = p["slides"] or [{"titre": p.get("hook") or "", "texte": ""}]
    images = [d / "sources" / i for i in p["images"]]
    plans = d / "plans"
    shutil.rmtree(plans, ignore_errors=True)
    plans.mkdir()
    for i, s in enumerate(slides):
        img = images[i % len(images)] if images else None
        slide(s, i, len(slides), img, p.get("theme", "sombre"), p.get("pseudo", ""), VERTICAL, reel=True).save(plans / f"{i:02d}.jpg", "JPEG", quality=92)
    liste_ = "".join(f"file 'plans/{i:02d}.jpg'\nduration {SLIDE_DIAPORAMA_S}\n" for i in range(len(slides)))
    liste_ += f"file 'plans/{len(slides) - 1:02d}.jpg'\n"
    (d / "plans.txt").write_text(liste_, encoding="utf-8")
    log("Montage du diaporama…")
    duree = SLIDE_DIAPORAMA_S * len(slides)
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", "plans.txt", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-vf", "fps=30,format=yuv420p,setsar=1", "-t", f"{duree:.1f}", "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "64k",
             *ENCODAGE, str(sortie / "reel.mp4")], d)
    shutil.copy(plans / "00.jpg", sortie / "couverture.jpg")
    shutil.rmtree(plans, ignore_errors=True)
    return ["reel.mp4", "couverture.jpg"]


# ------------------------------------------------------------
#  Génération + package
# ------------------------------------------------------------
def genere(esp: Espace, sid: str, demo: bool = False) -> dict:
    p = charge(esp, sid)
    d = dossier(esp, sid)
    sortie = d / "sortie"
    shutil.rmtree(sortie, ignore_errors=True)
    sortie.mkdir()
    p.update(statut="en_cours", erreur=None)
    sauve(esp, p)
    try:
        if p["type"] == "carrousel":
            if not p["slides"]:
                raise ValueError("Ajoute au moins une slide.")
            n = len(p["slides"])
            log(f"Je dessine tes {n} slides…")
            images = [d / "sources" / i for i in p["images"]]
            fichiers = []
            for i, s in enumerate(p["slides"]):
                nom = f"slide_{i + 1:02d}.jpg"
                img = images[i] if i < len(images) else None
                slide(s, i, n, img, p.get("theme", "sombre"), p.get("pseudo", "")).save(sortie / nom, "JPEG", quality=92)
                fichiers.append(nom)
        elif p.get("video"):
            fichiers = monte_reel(p, d, sortie)
        else:
            if not (p["slides"] or p["images"]):
                raise ValueError("Ajoute ta vidéo, ou des images pour un Reel en diaporama.")
            fichiers = monte_diaporama(p, d, sortie)
        log("Je prépare ton package prêt à publier…")
        p = charge(esp, sid)
        p.update(fichiers=fichiers, zip=package(p, d, sortie, fichiers), statut="pret",
                 genere_le=datetime.now().isoformat(timespec="minutes"))
        sauve(esp, p)
        log("✅ Contenu prêt")
        return {"id": sid}
    except Exception as e:
        p = charge(esp, sid)
        p.update(statut="erreur", erreur=str(e)[:300])
        sauve(esp, p)
        raise


def _txt_dm(p: dict) -> str:
    lignes = [f"Appel à l'action dans la vidéo / la légende :\n{p.get('cta') or ''}", ""]
    for e in p.get("dm") or []:
        lignes += [e.get("etape", ""), e.get("message", ""), ""]
    return "\n".join(lignes).strip() + "\n"


def package(p: dict, d: Path, sortie: Path, fichiers: list[str]) -> str:
    nom = f"{'carrousel' if p['type'] == 'carrousel' else 'reel'}_{p['id'][:15]}.zip"
    lisez = [
        "TON CONTENU PRÊT À PUBLIER", "=" * 26, "",
        "1. Ouvre Instagram > + > " + ("Publication, et sélectionne les slides dans l'ordre (slide_01, slide_02…)."
                                      if p["type"] == "carrousel" else "Reel, et choisis reel.mp4. Mets couverture.jpg comme couverture."),
        "2. Colle la légende de « legende.txt ».",
        "3. Ajoute un son tendance dans Instagram si tu veux (volume bas si tu parles).",
        "4. Active la réponse automatique au mot-clé avec le premier message de « messages-prives.txt ».",
        "5. Publie, puis colle le lien du post dans Veille virale (« J'ai publié ») pour suivre ses résultats.", "",
    ]
    with zipfile.ZipFile(sortie / nom, "w", zipfile.ZIP_DEFLATED) as z:
        for f in fichiers:
            z.write(sortie / f, f)
        z.writestr("legende.txt", (p.get("legende") or "").strip() + "\n")
        if p["type"] == "reel":
            z.writestr("script.txt", f"HOOK (texte à l'écran)\n{p.get('hook') or ''}\n\nSCRIPT\n{p.get('script') or ''}\n")
        z.writestr("messages-prives.txt", _txt_dm(p))
        z.writestr("LISEZ-MOI.txt", "\n".join(lisez))
    return nom
