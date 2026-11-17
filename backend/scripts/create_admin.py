"""Create the first Super Admin account. No demo credentials are shipped.

Usage (from backend/):
    python -m scripts.create_admin --phone 9876543210 --name "Owner Name"

Password is read from ADMIN_INITIAL_PASSWORD env var, or prompted securely.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password, validate_password
from app.models.identity import Role, User, UserRole
from app.schemas.auth import normalize_phone


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Super Admin user")
    parser.add_argument("--phone", required=True, help="10-digit Indian mobile number")
    parser.add_argument("--name", required=True, help="Full name")
    parser.add_argument("--email", default=None)
    args = parser.parse_args()

    try:
        phone = normalize_phone(args.phone)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    password = os.environ.get("ADMIN_INITIAL_PASSWORD") or getpass.getpass("Initial password: ")
    try:
        validate_password(password)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    with SessionLocal() as db:
        if db.execute(select(User).where(User.phone == phone)).scalars().first():
            print("ERROR: a user with this phone already exists.")
            return 1
        user = User(
            phone=phone,
            email=args.email.lower() if args.email else None,
            password_hash=hash_password(password),
            full_name=args.name,
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        role = db.execute(select(Role).where(Role.code == "SUPER_ADMIN")).scalars().first()
        if role is None:
            print("ERROR: roles are not seeded. Run `python -m app.seed` first.")
            return 1
        db.add(UserRole(user_id=user.id, role_id=role.id, granted_by_id=user.id))
        db.commit()
        print(f"Super Admin created: {phone} (id={user.id}). Change the password after first login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
