"""Bootstrap the platform admin:  python -m app.cli create-admin <email> <password-file>
The password is read from a file, never from argv or shell history."""
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import get_db
from app.models import User
from app.security import MIN_PASSWORD_LENGTH, hash_password


def create_admin(email: str, password_file: str) -> None:
    password = Path(password_file).read_text(encoding="utf-8").strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"password must have at least {MIN_PASSWORD_LENGTH} characters")
    db = next(get_db())
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        user = User(email=email.lower(), password_hash=hash_password(password), is_platform_admin=True,
                    email_verified=True)
        db.add(user)
    else:
        user.password_hash = hash_password(password)
        user.is_platform_admin = True
    db.commit()
    print(f"platform admin ready: {email.lower()}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "create-admin":
        create_admin(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
