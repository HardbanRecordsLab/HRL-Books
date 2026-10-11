from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import platform_admin
from app.invitations import create_invitation
from app.models import AuditLog, Book, User, Workspace
from app.schemas import WorkspaceCreateIn, WorkspaceOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/workspaces")
def list_workspaces(admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Book.workspace_id, func.count()).where(Book.deleted_at.is_(None))
                             .group_by(Book.workspace_id)).all())
    return [{**WorkspaceOut.model_validate(ws).model_dump(), "titles": counts.get(ws.id, 0), "limits": ws.limits}
            for ws in db.scalars(select(Workspace).order_by(Workspace.created_at))]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceCreateIn, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    """FR-ACC-07: the platform admin creates a workspace and invites its owner."""
    if db.scalar(select(Workspace).where(Workspace.slug == body.slug)):
        raise HTTPException(409, "Taki slug już istnieje")
    ws = Workspace(name=body.name, slug=body.slug)
    db.add(ws)
    db.flush()
    audit(db, "workspace.created", admin.id, ws.id, target=ws.slug)
    create_invitation(db, ws, body.owner_email, "owner", admin.id)
    db.commit()
    return ws


@router.get("/audit")
def audit_log(limit: int = 100, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 500)))
    return [{"at": r.at, "action": r.action, "actor_id": r.actor_id, "workspace_id": r.workspace_id,
             "target": r.target, "meta": r.meta} for r in rows]
