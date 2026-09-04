"""Shared test fixtures."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import docgrity.core.db as db
from docgrity.core.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_db_engine():
    """Use a NullPool engine per test so asyncpg connections never cross event loops."""
    db._engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    db._session_factory = async_sessionmaker(db._engine, expire_on_commit=False)
    yield
    db._engine = None
    db._session_factory = None
