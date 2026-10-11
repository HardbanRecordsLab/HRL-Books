"""Transactional e-mail via SMTP (home.pl, no-reply@). Without SMTP_HOST it only logs (dev/tests)."""
import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)
SENT: list[EmailMessage] = []  # captured in tests when SMTP is not configured


def send_mail(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = f"HRL Books <{s.SENDER_EMAIL}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if not s.SMTP_HOST:
        SENT.append(msg)
        log.info("mail (not sent, no SMTP_HOST) to=%s subject=%s", to, subject)
        return False
    try:
        with smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(s.SMTP_USER or s.SENDER_EMAIL, s.SMTP_PASSWORD or "")
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 — mail failure must not break the request
        log.error("mail to %s failed: %s", to, exc)
        return False
