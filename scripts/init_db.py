"""Bootstrap script — creates first reviewer if none exists.
Run during deploy: `python scripts/init_db.py`
"""
import sys
import os
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from passlib.context import CryptContext
from app.db import engine, SessionLocal, Base
from app.models import Reviewer
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("init")
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    settings = get_settings()
    log.info("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(Reviewer).count()
        if existing > 0:
            log.info(f"Reviewers exist already ({existing}). Skipping default seed.")
            return

        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "ChangeMeNow!2026")
        admin_email = os.getenv("ADMIN_EMAIL", "admin@medidordeespectaculares.com")
        admin_name = os.getenv("ADMIN_NAME", "Administrator")

        reviewer = Reviewer(
            username=admin_username,
            email=admin_email,
            full_name=admin_name,
            hashed_password=pwd_ctx.hash(admin_password),
            role="admin",
            is_active=True,
        )
        db.add(reviewer)
        db.commit()
        log.info(f"✓ Created admin reviewer: {admin_username} / {admin_password}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
