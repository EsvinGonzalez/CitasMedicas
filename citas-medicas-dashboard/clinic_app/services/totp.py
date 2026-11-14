"""
totp.py
Implementación mínima de TOTP (RFC 6238) usando solo la librería estándar
de Python (hmac, hashlib, struct, base64) para no depender de paquetes
externos como pyotp. Compatible con Google Authenticator / Authy.
"""

import base64
import hashlib
import hmac
import os
import struct
import time
import urllib.parse

DIGITS = 6
INTERVALO = 30  # segundos de validez de cada código


def generar_secreto(longitud: int = 20) -> str:
    """Genera un secreto aleatorio en Base32 (formato estándar para TOTP)."""
    return base64.b32encode(os.urandom(longitud)).decode("utf-8").rstrip("=")


def _hotp(secreto_b32: str, contador: int, digitos: int = DIGITS) -> str:
    relleno = "=" * ((8 - len(secreto_b32) % 8) % 8)
    clave = base64.b32decode(secreto_b32 + relleno)
    mensaje = struct.pack(">Q", contador)
    hash_bytes = hmac.new(clave, mensaje, hashlib.sha1).digest()
    offset = hash_bytes[-1] & 0x0F
    fragmento = struct.unpack(">I", hash_bytes[offset:offset + 4])[0] & 0x7FFFFFFF
    codigo = fragmento % (10 ** digitos)
    return str(codigo).zfill(digitos)


def generar_totp(secreto_b32: str, momento: float = None, intervalo: int = INTERVALO) -> str:
    if momento is None:
        momento = time.time()
    contador = int(momento // intervalo)
    return _hotp(secreto_b32, contador)


def verificar_totp(secreto_b32: str, token: str, ventana: int = 1, intervalo: int = INTERVALO) -> bool:
    """Verifica un código TOTP permitiendo un margen de +/- ventana intervalos
    para tolerar pequeños desfaces de reloj entre el servidor y el celular."""
    if not secreto_b32 or not token or not token.isdigit():
        return False
    ahora = time.time()
    for offset in range(-ventana, ventana + 1):
        if hmac.compare_digest(generar_totp(secreto_b32, ahora + offset * intervalo, intervalo), token):
            return True
    return False


verify_totp = verificar_totp


def uri_otpauth(secreto_b32: str, email: str, emisor: str = "Clinica San Jose") -> str:
    """URI otpauth:// que las apps autenticadoras leen para configurar la cuenta
    (se puede convertir en QR o pegar manualmente)."""
    etiqueta = urllib.parse.quote(f"{emisor}:{email}")
    return (
        f"otpauth://totp/{etiqueta}?secret={secreto_b32}"
        f"&issuer={urllib.parse.quote(emisor)}&digits={DIGITS}&period={INTERVALO}"
    )