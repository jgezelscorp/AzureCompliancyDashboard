"""Database engine and request-scoped session dependency."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings


@lru_cache
def get_engine(database_url: str) -> Engine:
    # A stopped or unreachable server must fail fast: unbounded TCP connects block the worker
    # thread pool and starve unrelated endpoints (/auth/config, health probes, sign-in).
    if database_url.startswith("postgresql"):
        return create_engine(
            database_url,
            pool_pre_ping=True,
            pool_timeout=5,
            connect_args={"connect_timeout": 5},
        )
    return create_engine(database_url, pool_pre_ping=True)


def get_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    with Session(get_engine(settings.database_url)) as session:
        yield session
