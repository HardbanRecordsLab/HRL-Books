from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, action: str, actor_id: str | None = None, workspace_id: str | None = None,
          target: str = "", **meta) -> None:
    db.add(AuditLog(action=action, actor_id=actor_id, workspace_id=workspace_id, target=target, meta=meta))
