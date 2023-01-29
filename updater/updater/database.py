from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker, Session
from settings import settings


def make_db_url() -> sa.engine.URL:
    return sa.engine.URL.create(
        drivername="postgresql",
        host=settings.DASH_PGHOST,
        port=settings.DASH_PGPORT,
        database=settings.DASH_PGDATABASE,
        username=settings.DASH_PGUSER,
        password=settings.DASH_PGPASSWORD,
    )


def create_engine(echo_sql: bool = settings.ECHO_SQL) -> sa.engine.Engine:
    return sa.create_engine(make_db_url(), echo=echo_sql, future=True)


def create_sessionmaker(bind: Union[sa.engine.Connection, sa.engine.Engine, None] = None) -> sessionmaker[Session]:
    if not bind:
        bind = create_engine()
    return sessionmaker(bind=bind, autocommit=False, future=True)
