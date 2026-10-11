from datetime import timedelta

from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.mailer import send_mail
from app.models import Invitation, Workspace, utcnow
from app.security import new_opaque_token, sha256

ROLE_LABELS = {"owner": "właściciel", "editor": "redaktor", "author": "autor", "reviewer": "recenzent"}


def create_invitation(db: Session, ws: Workspace, email: str, role: str, created_by: str) -> str:
    raw = new_opaque_token()
    db.add(Invitation(token_hash=sha256(raw), email=email.lower(), workspace_id=ws.id, role=role,
                      expires_at=utcnow() + timedelta(days=get_settings().INVITATION_DAYS), created_by=created_by))
    audit(db, "invitation.created", created_by, ws.id, target=email.lower(), role=role)
    link = f"{get_settings().APP_URL}/rejestracja?token={raw}"
    send_mail(email, f"Zaproszenie do {ws.name} w HRL Books",
              f"Zaproszono Cię do workspace'u „{ws.name}” w HRL Books jako: {ROLE_LABELS.get(role, role)}.\n\n"
              f"Załóż konto: {link}\n\nZaproszenie jest jednorazowe i wygasa za {get_settings().INVITATION_DAYS} dni.\n"
              "Jeśli to pomyłka, zignoruj tę wiadomość.\n\n— HRL Books · HardbanRecords Lab")
    return raw
