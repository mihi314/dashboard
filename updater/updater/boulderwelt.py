from datetime import datetime as dt, timezone
from typing import Optional

import requests
import sqlalchemy as sa

from database import create_engine


# Data retrieval
#
urls = {
    "Boulderwelt München Ost": "https://www.boulderwelt-muenchen-ost.de/wp-admin/admin-ajax.php",
    "Boulderwelt München West": "https://www.boulderwelt-muenchen-west.de/wp-admin/admin-ajax.php",
    "Boulderwelt München Süd": "https://www.boulderwelt-muenchen-sued.de/wp-admin/admin-ajax.php",
}


def get_level(url: str) -> Optional[float | int]:
    headers = {"User-Agent": "Private Boulderhallenfüllstandsabfrage - Kontakt: aijan.me@gmail.com"}
    request = requests.post(url, data={"action": "cxo_get_crowd_indicator"}, headers=headers)
    data = request.json()
    return data["level"] if data["success"] else None


# Storage
#
db_engine = create_engine()
metadata_obj = sa.MetaData()

table_name = "gym_levels"
table = sa.Table(
    table_name,
    metadata_obj,
    sa.Column("time", sa.DateTime(timezone=True), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("level", sa.Float, nullable=True, comment="Fill level between 0 and 100. NULL means the gym was closed."),
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


def update():
    now = dt.now(timezone.utc)
    rows = []

    for name, url in urls.items():
        level = get_level(url)
        rows.append({"time": now, "name": name, "level": level})

    with db_engine.begin() as conn:
        conn.execute(sa.insert(table), rows)


if __name__ == "__main__":
    init()

    while True:
        print("querying")
        # Updates every 5 minutes on the five minute mark, e.g. 21:30, 21:35, ...
        update()
        print("sleeping")
        import time

        time.sleep(60 * 5)
