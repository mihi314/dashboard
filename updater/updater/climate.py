from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, Response, status
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert

from updater.database import create_engine

# Data retrieval
#
router = APIRouter()


class Measurement(BaseModel):
    device: str = Field(min_length=1)
    time: AwareDatetime
    # The ranges match the sensors' specs and also filter out occasional garbage readings
    temperature_C: float = Field(ge=-40, le=70)
    humidity_percent: float = Field(ge=0, le=100)
    battery_percent: Optional[float] = Field(None, ge=0, le=100)


class Measurements(BaseModel):
    measurements: list[Measurement] = Field(max_length=1000)


@router.post("/climate", status_code=status.HTTP_204_NO_CONTENT)
def ingest(body: Measurements):
    insert([m.model_dump() for m in body.measurements])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Storage
#
# Measurements get pushed to the ingest API (see api.py), e.g. by integrations/mpi running on a Raspberry Pi
db_engine = create_engine()
metadata_obj = sa.MetaData()

table_name = "climate_measurements"
table = sa.Table(
    table_name,
    metadata_obj,
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("device", sa.Text, nullable=False),
    sa.Column("temperature_C", sa.Float, nullable=False),
    sa.Column("humidity_percent", sa.Float, nullable=False, comment="Relative humidity"),
    sa.Column("battery_percent", sa.Float, nullable=True),
    # Makes repeated deliveries of the same measurement idempotent (see insert())
    sa.UniqueConstraint("device", "time"),
)


def init():
    # Create the table if it does not exist
    if not sa.inspect(db_engine).has_table(table_name):
        with db_engine.begin() as conn:
            table.create(conn, checkfirst=True)
            stmt = sa.text(
                "SELECT create_hypertable(:table, :time_column, migrate_data => true, if_not_exists => true)"
            )
            conn.execute(stmt, {"table": table_name, "time_column": "time"})


def insert(rows: list[dict]):
    if not rows:
        return
    with db_engine.begin() as conn:
        conn.execute(pg_insert(table).on_conflict_do_nothing(), rows)
