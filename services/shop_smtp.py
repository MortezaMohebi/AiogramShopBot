"""Explicit TLS-only SMTP transport for transactional staff email."""

from __future__ import annotations

import base64
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from services.shop_email_templates import TransactionalEmail


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    """Private SMTP connection settings loaded from the service environment."""

    host: str
    port: int
    username: str
    password: str
    sender: str
    security: str


def configured_settings() -> SmtpSettings | None:
    """Return None until every mandatory SMTP setting is supplied."""
    values = {
        key: os.environ.get("SHOP_SMTP_" + key.upper(), "").strip()
        for key in ("host", "port", "username", "sender", "security")
    }
    encoded_password = os.environ.get("SHOP_SMTP_PASSWORD_B64", "")
    try:
        password = (
            base64.b64decode(encoded_password, validate=True).decode("utf-8")
            if encoded_password else ""
        )
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid SMTP credential encoding.") from error
    if not any(values.values()) and not encoded_password:
        return None
    try:
        port = int(values["port"])
    except ValueError as error:
        raise ValueError("SMTP port must be a number.") from error
    if (not all(values.values()) or not password or not 1 <= port <= 65535
            or values["security"] not in {"ssl", "starttls"}
            or any(char in values["host"] for char in "\r\n/@")
            or not _address(values["sender"])):
        raise ValueError("Incomplete or unsafe SMTP configuration.")
    return SmtpSettings(values["host"], port, values["username"],
                        password, values["sender"], values["security"])


def _address(value: str) -> bool:
    """Reject address display names and header delimiters."""
    parsed_name, parsed_address = parseaddr(value)
    return bool(value and not parsed_name and parsed_address == value
                and "@" in value and not any(char in value for char in "\r\n,;<>"))


def send_email(settings: SmtpSettings, destination: str, content: TransactionalEmail) -> None:
    """Send one plain/HTML email over verified TLS without logging secrets."""
    if not _address(destination) or not _address(settings.sender):
        raise ValueError("Invalid transactional email address.")
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = destination
    message["Subject"] = content.subject
    message.set_content(content.plain)
    message.add_alternative(content.html, subtype="html")
    tls = ssl.create_default_context()
    if settings.security == "ssl":
        with smtplib.SMTP_SSL(settings.host, settings.port, timeout=10, context=tls) as smtp:
            smtp.login(settings.username, settings.password)
            smtp.send_message(message)
    elif settings.security == "starttls":
        with smtplib.SMTP(settings.host, settings.port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=tls)
            smtp.ehlo()
            smtp.login(settings.username, settings.password)
            smtp.send_message(message)
    else:
        raise ValueError("SMTP requires TLS.")
