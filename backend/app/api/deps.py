"""Shared FastAPI dependencies.

Currently just the database session; spec 002 adds the authentication and
authorization dependencies here.
"""

from app.db import get_db_session

__all__ = ["get_db_session"]
