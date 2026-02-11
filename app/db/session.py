import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

POOL_SIZE = int(os.environ.get('DB_POOL_SIZE','10'))
MAX_OVERFLOW = int(os.environ.get('DB_MAX_OVERFLOW','20'))

engine = create_engine(
    settings.MYSQL_DSN,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=30,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
