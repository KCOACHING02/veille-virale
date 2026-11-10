"""Publications « faceless » : personne ne montre son visage (texte, mains, paysages, objets, voix off).

Détection locale et gratuite (OpenCV, détecteur YuNet, modèle libre `modeles/face_detection_yunet_2023mar.onnx`, licence MIT,
opencv_zoo) sur les images clés déjà préparées par la bibliothèque :
un visage compte s'il est assez grand pour être celui de la personne qui parle ou pose (pas un visage lointain dans la foule).
"""

from __future__ import annotations

from pathlib import Path

TAILLE_MIN = 0.14  # largeur du visage / largeur de l'image : en dessous, ce n'est pas « quelqu'un qui se montre »
_DETECTEUR = None


MODELE = Path(__file__).resolve().parent / "modeles" / "face_detection_yunet_2023mar.onnx"
CONFIANCE = 0.8


def _detecteur():
    global _DETECTEUR
    if _DETECTEUR is None:
        import cv2
        _DETECTEUR = cv2.FaceDetectorYN.create(str(MODELE), "", (320, 320), CONFIANCE, 0.3, 50)
    return _DETECTEUR


def visage(image: Path) -> bool:
    """Un visage bien visible sur l'image ?"""
    import cv2
    im = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if im is None:
        return False
    h, w = im.shape[:2]
    if w > 480:  # plus rapide et assez précis pour un visage en gros plan
        im = cv2.resize(im, (480, int(h * 480 / w)))
        h, w = im.shape[:2]
    d = _detecteur()
    d.setInputSize((w, h))
    _, faces = d.detect(im)
    return faces is not None and any(f[2] >= w * TAILLE_MIN and f[-1] >= CONFIANCE for f in faces)


def faceless(images: list[Path], fmt: str) -> bool | None:
    """True si personne ne se montre. Reel : visage sur 2 images clés au moins (ou la moitié) ; carrousel, photo : aucune slide avec un visage.
    None si on ne peut pas juger (OpenCV absent, aucune image)."""
    images = [Path(x) for x in images if Path(x).is_file()]
    if not images:
        return None
    try:
        avec = sum(1 for im in images[:12] if visage(im))
    except Exception:  # noqa: BLE001  (OpenCV absent ou image illisible)
        return None
    if fmt == "Reel":
        return avec < min(2, max(1, len(images) // 2))
    return avec == 0
