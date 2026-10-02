"""Create or rotate the only local owner without storing plaintext credentials."""

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import func, select

from app.infrastructure.db.session import SessionFactory, close_database
from app.modules.auth.models import AuthSession, User
from app.modules.auth.service import hash_password, normalize_login


async def configure_owner(login: str, password: str, *, rotate: bool) -> str:
    normalized = normalize_login(login)
    async with SessionFactory() as session:
        count = int(await session.scalar(select(func.count(User.id))) or 0)
        owner = await session.scalar(select(User).limit(1))
        if owner is not None and not rotate:
            raise RuntimeError("Owner already exists; pass --rotate to replace the credentials")
        password_hash = hash_password(password)
        if owner is None:
            if count:
                raise RuntimeError("Single-owner invariant violated")
            owner = User(login_identifier=normalized, password_hash=password_hash)
            session.add(owner)
            action = "created"
        else:
            owner.login_identifier = normalized
            owner.password_hash = password_hash
            await session.execute(
                AuthSession.__table__.delete().where(AuthSession.user_id == owner.id)
            )
            action = "rotated"
        await session.commit()
        return action


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", help="Owner login; prompted when omitted")
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args()
    login = args.login or input("Owner login: ").strip()
    password = getpass("Owner password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")

    async def run() -> str:
        try:
            return await configure_owner(login, password, rotate=args.rotate)
        finally:
            await close_database()

    result = asyncio.run(run())
    print(f"Owner credentials {result}; active sessions revoked when rotated.")


if __name__ == "__main__":
    main()
