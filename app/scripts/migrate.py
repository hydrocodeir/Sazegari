from __future__ import annotations

import os
import time
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings


def wait_for_db(engine, timeout_s: int = 60) -> None:
    """Wait until MySQL is accepting connections."""
    start = time.time()
    delay = 1.0
    last_err: Exception | None = None

    while True:
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as e:
            last_err = e
            if time.time() - start > timeout_s:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)


def run(cmd: list[str]) -> int:
    p = subprocess.run(cmd, check=False)
    return p.returncode


def main() -> int:
    dsn = os.getenv("MYSQL_DSN") or settings.MYSQL_DSN
    engine = create_engine(dsn, future=True, pool_pre_ping=True)

    # Wait for DB readiness (important in docker-compose)
    wait_for_db(engine, timeout_s=int(os.getenv("DB_WAIT_TIMEOUT", "90")))

    with engine.begin() as conn:
        has_alembic = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name='alembic_version'"
            )
        ).scalar()

        has_orgs = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name='orgs'"
            )
        ).scalar()

    # Run alembic
    if not has_alembic and has_orgs:
        # Existing schema without alembic tracking: stamp head
        rc = run(["alembic", "stamp", "head"])
        if rc != 0:
            return rc
    else:
        rc = run(["alembic", "upgrade", "head"])
    if rc != 0:
        # Don't stamp on failure; fail fast so schema doesn't drift from alembic_version.
        return rc

    # Seed default admin once (idempotent)
    from sqlalchemy.orm import Session
    from app.db.session import SessionLocal
    from app.db.models.user import User, Role
    from app.core.security import hash_password

    if settings.AUTO_CREATE_ADMIN:
        db: Session = SessionLocal()
        try:
            exists = db.query(User).filter(User.username == settings.DEFAULT_ADMIN_USERNAME).first()
            if not exists:
                admin = User(
                    full_name=settings.DEFAULT_ADMIN_FULL_NAME,
                    username=settings.DEFAULT_ADMIN_USERNAME,
                    password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
                    role=Role.SECRETARIAT_ADMIN,
                    org_id=None,
                    county_id=None,
                )
                db.add(admin)
                db.commit()
        finally:
            db.close()
    # Seed sample dataset (idempotent)
    if settings.AUTO_SEED_SAMPLE:
        from app.scripts.seed_sample import seed_sample

        db2: Session = SessionLocal()
        try:
            seed_sample(db2)
            db2.commit()
        finally:
            db2.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
