from datetime import datetime as dt, timezone
from typing import Optional

import requests
import sqlalchemy as sa
from pydantic import BaseModel

from updater.database import create_engine


# Data retrieval
#
class NearestBus(BaseModel):
    gridID: str
    busID: str
    lat: float
    lon: float
    type: str


class Response(BaseModel):
    rating: Optional[str]
    message: str
    distance: Optional[float]
    nearestBus: Optional[NearestBus]


def make_request(request) -> Response:
    url = "https://connect-n-ergie.adaptricity.com/api/evaluate"
    data = {"lat": request.lat, "lon": request.lon, "type": request.type, "powerInKW": request.power_kW}
    response = requests.post(url, json=data)
    response.raise_for_status()
    return Response.parse_raw(response.text)


# Storage
#
db_engine = create_engine()
metadata_obj = sa.MetaData()

table_requests = sa.Table(
    "nergie_requests",
    metadata_obj,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("disabled", sa.Boolean, server_default=sa.sql.false(), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("power_kW", sa.Integer, nullable=False),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
)


table_name = "nergie_results"
table = sa.Table(
    table_name,
    metadata_obj,
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("nergie_request_id", sa.Integer, sa.ForeignKey("nergie_requests.id"), nullable=False),
    sa.Column("distance_m", sa.Float, nullable=True),
    sa.Column("message", sa.Text, nullable=True),
    sa.Column("rating", sa.Text, nullable=True),
    sa.Column("nearestBus_busID", sa.Text, nullable=True),
    sa.Column("nearestBus_gridID", sa.Text, nullable=True),
    sa.Column("nearestBus_lat", sa.Float, nullable=True),
    sa.Column("nearestBus_lon", sa.Float, nullable=True),
    sa.Column("nearestBus_type", sa.Text, nullable=True),
)


def init():
    # Create the table if it does not exist
    if not sa.inspect(db_engine).has_table(table_name):
        with db_engine.begin() as conn:
            table_requests.create(conn, checkfirst=True)
            table.create(conn, checkfirst=True)
            stmt = sa.text(
                "SELECT create_hypertable(:table, :time_column, migrate_data => true, if_not_exists => true)"
            )
            conn.execute(stmt, {"table": table_name, "time_column": "time"})


def update():
    with db_engine.begin() as conn:
        nergie_requests = conn.execute(sa.select(table_requests).where(table_requests.c.disabled == False)).fetchall()

    now = dt.now(timezone.utc)
    for request in nergie_requests:
        resp = make_request(request)
        row = {
            "time": now,
            "nergie_request_id": request.id,
            "distance_m": resp.distance,
            "message": resp.message,
            "rating": resp.rating,
            "nearestBus_busID": resp.nearestBus.busID if resp.nearestBus else None,
            "nearestBus_gridID": resp.nearestBus.gridID if resp.nearestBus else None,
            "nearestBus_lat": resp.nearestBus.lat if resp.nearestBus else None,
            "nearestBus_lon": resp.nearestBus.lon if resp.nearestBus else None,
            "nearestBus_type": resp.nearestBus.type if resp.nearestBus else None,
        }
        with db_engine.begin() as conn:
            conn.execute(sa.insert(table), row)


if __name__ == "__main__":
    init()
    update()
