"""SQLAlchemy declarative base.

Money columns are BigInteger paise. There is no Numeric, no Float and no
Decimal column anywhere in this schema: the integer is the source of truth all
the way from the source file to the database row.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ReconGuard table."""
