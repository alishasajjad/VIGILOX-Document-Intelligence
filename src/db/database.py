import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    sessionmaker,
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()


# ==========================================================
# DATABASE URL
# ==========================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL"
)


if not DATABASE_URL:

    raise RuntimeError(
        "DATABASE_URL is not configured. "
        "Add it to the .env file."
    )


# ==========================================================
# DECLARATIVE BASE
# ==========================================================

class Base(
    DeclarativeBase
):
    pass


# ==========================================================
# DATABASE ENGINE
# ==========================================================

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# ==========================================================
# SESSION FACTORY
# ==========================================================

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)