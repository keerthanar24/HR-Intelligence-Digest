"""SMTP sending, shared by the digest and the red-flag alert.

Credentials come from the environment and never from this repo:

    SMTP_HOST  SMTP_PORT (587 STARTTLS, 465 implicit TLS)
    SMTP_USER  SMTP_PASSWORD  SMTP_FROM
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def smtp_settings() -> tuple[dict, list[str]]:
    """(settings, what is missing)."""
    cfg = {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM", "").strip(),
    }
    missing = [f"SMTP_{k.upper()}" for k in ("host", "user", "password")
               if not cfg[k]]
    return cfg, missing


def build_message(subject: str, to: list[str], sender: str,
                  body_text: str, body_html: str | None = None,
                  reply_to: str = "") -> EmailMessage:
    """Plain text, with an HTML alternative when one is given. No attachments."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")
    return message


def send(message: EmailMessage, cfg: dict) -> None:
    """Raises smtplib.SMTPException or OSError on failure; callers report it."""
    context = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=30) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(message)
