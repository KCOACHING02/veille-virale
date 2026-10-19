"""
Notifications push (application installée sur le téléphone ou navigateur) — Web Push standard, sans dépendance :
clés VAPID (ES256) générées une fois dans DATA/vapid.pem, chiffrement aes128gcm (RFC 8291).
"""

from __future__ import annotations

import base64
import json
import os
import struct
import threading
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import abonnements as ab
from espace import DATA

_cle = None
_v = threading.Lock()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _deb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def cle_privee():
    global _cle
    with _v:
        if _cle is None:
            f = DATA / "vapid.pem"
            if f.exists():
                _cle = serialization.load_pem_private_key(f.read_bytes(), password=None)
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                _cle = ec.generate_private_key(ec.SECP256R1())
                f.write_bytes(_cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return _cle


def cle_publique() -> str:
    pub = cle_privee().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(pub)


def _jwt(aud: str) -> str:
    entete = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    contact = os.getenv("EMAIL_CONTACT") or "mailto:contact@veille-virale.fr"
    corps = _b64(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": contact if contact.startswith("mailto:") else "mailto:" + contact}).encode())
    signature = cle_privee().sign(f"{entete}.{corps}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(signature)
    return f"{entete}.{corps}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def _hmac(cle: bytes, donnees: bytes) -> bytes:
    h = hmac.HMAC(cle, hashes.SHA256())
    h.update(donnees)
    return h.finalize()


def chiffre(message: bytes, p256dh: str, auth: str) -> bytes:
    """Chiffrement aes128gcm d'un message Web Push (RFC 8291)."""
    ua_pub = _deb64(p256dh)
    secret_auth = _deb64(auth)
    eph = ec.generate_private_key(ec.SECP256R1())
    as_pub = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    partage = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    prk_cle = _hmac(secret_auth, partage)
    ikm = _hmac(prk_cle, b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")
    sel = os.urandom(16)
    prk = _hmac(sel, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    chiffre_ = AESGCM(cek).encrypt(nonce, message + b"\x02", None)
    return sel + struct.pack(">I", 4096) + bytes([len(as_pub)]) + as_pub + chiffre_


def envoie_a(abonnement: dict, titre: str, texte: str, url: str = "/app") -> bool:
    ep = abonnement["endpoint"]
    p = urlparse(ep)
    corps = chiffre(json.dumps({"titre": titre, "texte": texte, "url": url}, ensure_ascii=False).encode(), abonnement["p256dh"], abonnement["auth"])
    r = requests.post(ep, data=corps, timeout=15, headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "86400", "Urgency": "normal",
        "Authorization": f"vapid t={_jwt(f'{p.scheme}://{p.netloc}')}, k={cle_publique()}"})
    if r.status_code in (404, 410):  # appareil désinscrit
        ab.retire_push(ep)
        return False
    return r.status_code < 300


def notifie(uid: int, titre: str, texte: str, url: str = "/app"):
    """Envoie à tous les appareils de l'utilisatrice, en arrière-plan (ne bloque jamais une requête)."""
    appareils = ab.push_de(uid)
    if not appareils:
        return

    def go():
        for a in appareils:
            try:
                envoie_a(a, titre, texte, url)
            except Exception as e:  # noqa: BLE001
                print(f"[push] échec : {e}")
    threading.Thread(target=go, daemon=True).start()
