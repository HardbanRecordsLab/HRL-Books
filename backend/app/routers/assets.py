"""File uploads (print designs, covers). Stored in FILES_DIR; public read only by unguessable token."""
import hashlib
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.deps import require
from app.models import Asset, Book, Membership

router = APIRouter(tags=["assets"])

ALLOWED = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf"}
MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".pdf": b"%PDF"}


def asset_public_url(asset: Asset) -> str:
    return f"{get_settings().APP_URL}/api/v1/public/assets/{asset.public_token}"


def store_asset(db: Session, ws_id: str, book_id: str | None, kind: str, data: bytes, content_type: str,
                original_name: str = "") -> Asset:
    """Write bytes to FILES_DIR and register the Asset (caller validates type and commits)."""
    folder = Path(get_settings().FILES_DIR) / ws_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{secrets.token_hex(16)}{ALLOWED[content_type]}"
    path.write_bytes(data)
    a = Asset(workspace_id=ws_id, book_id=book_id, kind=kind[:20], original_name=original_name[:300],
              content_type=content_type, path=str(path), size=len(data), checksum=hashlib.sha256(data).hexdigest(),
              public_token=secrets.token_urlsafe(32))
    db.add(a)
    db.flush()
    return a


def asset_out(a: Asset) -> dict:
    return {"id": a.id, "book_id": a.book_id, "kind": a.kind, "original_name": a.original_name,
            "content_type": a.content_type, "size": a.size, "url": asset_public_url(a), "created_at": a.created_at}


@router.post("/api/v1/workspaces/{ws}/assets", status_code=201)
async def upload(file: UploadFile = File(...), kind: str = Form("design"), book_id: str = Form(""),
                 m: Membership = Depends(require("upload_files")), db: Session = Depends(get_db)):
    ext = ALLOWED.get(file.content_type or "")
    if ext is None:
        raise HTTPException(415, "Dozwolone pliki: PNG, JPG, PDF")
    data = await file.read(get_settings().MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > get_settings().MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Plik większy niż {get_settings().MAX_UPLOAD_MB} MB")
    if not data.startswith(MAGIC[ext]):
        raise HTTPException(415, "Zawartość pliku nie pasuje do jego typu")
    if book_id and db.scalar(select(Book).where(Book.id == book_id, Book.workspace_id == m.workspace_id)) is None:
        raise HTTPException(404, "Nie znaleziono tytułu")
    a = store_asset(db, m.workspace_id, book_id or None, kind, data, file.content_type, file.filename or "")
    audit(db, "asset.uploaded", m.user_id, m.workspace_id, target=a.id, size=len(data))
    db.commit()
    return asset_out(a)


@router.get("/api/v1/workspaces/{ws}/assets")
def list_assets(book_id: str = "", m: Membership = Depends(require("read_books")), db: Session = Depends(get_db)):
    q = select(Asset).where(Asset.workspace_id == m.workspace_id)
    if book_id:
        q = q.where(Asset.book_id == book_id)
    return [asset_out(a) for a in db.scalars(q.order_by(Asset.created_at.desc()))]


@router.get("/api/v1/public/assets/{token}")
def public_asset(token: str, db: Session = Depends(get_db)):
    a = db.scalar(select(Asset).where(Asset.public_token == token))
    if a is None or not Path(a.path).exists():
        raise HTTPException(404, "Nie znaleziono")
    return FileResponse(a.path, media_type=a.content_type, headers={"Cache-Control": "public, max-age=86400",
                                                                     "X-Content-Type-Options": "nosniff"})
