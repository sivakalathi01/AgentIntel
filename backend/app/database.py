import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(override=True)

DEFAULT_DATABASE_URL = "postgresql+psycopg://kiteai:kiteai_dev_password@localhost:5432/kiteai"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
DATABASE_ENABLED = os.getenv("DATABASE_ENABLED", "false").strip().lower() == "true"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_database() -> None:
    """Initialize schema only when DB mode is enabled."""
    if not DATABASE_ENABLED:
        return

    # Import models here so SQLAlchemy metadata is populated before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
