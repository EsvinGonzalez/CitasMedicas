"""Notificaciones por correo, SMS (simulado) e in-app."""

import os
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env.local")

from clinic_app.infrastructure.database import get_cursor

logger = logging.getLogger(__name__)


def enviar_notificacion(paciente_id, cita_id, canal, tipo, asunto, mensaje):
    estado = "enviada"
    try:
        with get_cursor() as cur:
            pac = cur.execute("SELECT email, telefono, nombre FROM pacientes WHERE id=?", (paciente_id,)).fetchone()
        destino = (pac["email"] if pac else "") or ""
        if canal == "email":
            if not destino:
                raise ValueError("El paciente no tiene correo registrado")
            if os.environ.get("RESEND_API_KEY"):
                _enviar_resend(destino, asunto, mensaje)
            elif os.environ.get("SMTP_HOST"):
                _enviar_smtp(destino, asunto, mensaje)
            else:
                raise RuntimeError("Configura Resend o SMTP para enviar correos")
        elif canal == "sms" and os.environ.get("TWILIO_ACCOUNT_SID"):
            estado = "enviada"
    except Exception:
        logger.exception("No se pudo enviar la notificacion %s de la cita %s", canal, cita_id)
        estado = "fallida"

    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO notificaciones
               (paciente_id, cita_id, canal, tipo, asunto, mensaje, estado, creado_en)
               VALUES (?,?,?,?,?,?,?,?)""",
            (paciente_id, cita_id, canal, tipo, asunto, mensaje, estado, datetime.now().isoformat()),
        )

    if canal == "email":
        from clinic_app.services.auditoria import registrar_auditoria

        registrar_auditoria(
            "enviar",
            "notificaciones",
            "cita",
            cita_id,
            f"Correo {estado}; tipo: {tipo}; paciente: #{paciente_id}",
        )


def _enviar_resend(destino, asunto, mensaje):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    remitente = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY no está configurada")
    if not remitente:
        raise RuntimeError("RESEND_FROM_EMAIL no está configurado")

    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": remitente, "to": [destino], "subject": asunto, "text": mensaje},
        timeout=15,
    )
    response.raise_for_status()


def notificar_cita(cita_id, tipo, asunto, mensaje, reforzado=False):
    with get_cursor() as cur:
        cita = cur.execute(
            "SELECT paciente_id FROM citas WHERE id=?", (cita_id,)
        ).fetchone()
    if not cita:
        return
    canales = ["email", "inapp"]
    if reforzado:
        canales.append("sms")
    for canal in canales:
        enviar_notificacion(cita["paciente_id"], cita_id, canal, tipo, asunto, mensaje)


def _enviar_smtp(destino, asunto, mensaje):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    msg = MIMEText(mensaje, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = user
    msg["To"] = destino
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.sendmail(user, [destino], msg.as_string())
