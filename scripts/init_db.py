"""
Run once to initialize the database.
Creates all tables via Alembic and confirms structure.
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from loguru import logger


def init_database():
    """Run Alembic migrations to create all tables."""
    logger.info("Running Alembic migrations...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"Migration failed: {result.stderr}")
        sys.exit(1)
    logger.info("Database initialized successfully.")
    logger.info(result.stdout)


if __name__ == "__main__":
    init_database()