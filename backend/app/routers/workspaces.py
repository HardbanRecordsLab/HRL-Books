from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import current_user, membership, require
from app.invitations import create_invitation
from app.models import Membership, User, Workspace
from app.schemas import InviteIn, MemberOut, MyWorkspaceOut, WorkspaceOut, WorkspacePatchIn

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


@router.get("", response_model=list[MyWorkspaceOut])
def my_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Workspace, Membership.role).join(Membership, Membership.workspace_id == Workspace.id)
                      .where(Membership.user_id == user.id).order_by(Workspace.name)).all()
    return [MyWorkspaceOut(**WorkspaceOut.model_validate(ws).model_dump(), role=role) for ws, role in rows]


@router.get("/{ws}", response_model=WorkspaceOut)
def get_workspace(m: Membership = Depends(membership), db: Session = Depends(get_db)):
    return db.get(Workspace, m.workspace_id)


@router.get("/{ws}/members", response_model=list[MemberOut])
def members(m: Membership = Depends(membership), db: Session = Depends(get_db)):
    rows = db.execute(select(User, Membership.role).join(Membership, Membership.user_id == User.id)
                      .where(Membership.workspace_id == m.workspace_id).order_by(User.email)).all()
    return [MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=role) for u, role in rows]


@router.patch("/{ws}", response_model=WorkspaceOut)
def patch_workspace(body: WorkspacePatchIn, m: Membership = Depends(require("manage_workspace")),
                    db: Session = Depends(get_db)):
    ws = db.get(Workspace, m.workspace_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(ws, k, v)
    audit(db, "workspace.updated", m.user_id, ws.id, **changes)
    db.commit()
    return ws


@router.post("/{ws}/invitations", status_code=201)
def invite(body: InviteIn, m: Membership = Depends(require("invite_members")), db: Session = Depends(get_db)):
    ws = db.get(Workspace, m.workspace_id)
    create_invitation(db, ws, body.email, body.role, m.user_id)
    db.commit()
    return {"status": "sent", "email": body.email.lower(), "role": body.role}
