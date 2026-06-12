"""
Initialize the database schema.

Creates all tables directly from the SQLAlchemy models via
Base.metadata.create_all — works on SQLite (the project's catalog store) with
no migration tooling required.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from src.database.connection import engine
from src.database.models import Base  # noqa: F401  (imports register all models)


def init_database():
    logger.info(f"Creating schema on {engine.url} ...")
    Base.metadata.create_all(bind=engine)
    tables = sorted(Base.metadata.tables.keys())
    logger.info(f"Schema ready. Tables: {tables}")


if __name__ == "__main__":
    init_database()
