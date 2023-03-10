from datetime import date
from typing import Optional

import pandas as pd
import requests
import sqlalchemy as sa

from updater.database import create_engine
from updater.settings import settings


# Data retrieval
#

# Documentation of the API / data
# https://agsi.gie.eu/account
# https://www.gie.eu/transparency-platform/GIE_API_documentation_v007.pdf

# The data is available in daily frequency and represents gas in Storage / LNG at the end of the previous gas day. Data
# is updated every day at 19:30 CET and a second time at 23:00. Some SSO/LSO are not able to provide their data before
# 19:30 but these will be included in the second publication time.


def get_data(since: Optional[date] = None) -> pd.DataFrame:
    params = {"country": "DE", "size": 10000}
    if since:
        params["from"] = since.isoformat()

    request = requests.get("https://agsi.gie.eu/api", params=params, headers={"x-key": settings.AGSI_API_KEY})
    request.raise_for_status()

    # with open("data/gas.json") as f:
    #     data = json.load(f)

    data = request.json()
    df = pd.DataFrame(data["data"])

    df.gasDayStart = pd.to_datetime(df.gasDayStart).apply(lambda t: t.date())

    float_columns = [
        "gasInStorage",
        "consumption",
        "consumptionFull",
        "injection",
        "withdrawal",
        "netWithdrawal",
        "workingGasVolume",
        "injectionCapacity",
        "withdrawalCapacity",
        "trend",
        "full",
    ]
    for column in float_columns:
        df[column] = df[column].apply(lambda value: float(value))

    # Only take a subset of the columns, in order to not break when new columns get added
    subset_columns = [
        "name",
        "code",
        "url",
        "gasDayStart",
        "gasInStorage",
        "consumption",
        "consumptionFull",
        "injection",
        "withdrawal",
        "netWithdrawal",
        "workingGasVolume",
        "injectionCapacity",
        "withdrawalCapacity",
        "status",
        "trend",
        "full",
        "info",
    ]
    return df.loc[:, subset_columns]


# Storage
#
table_name = "gas_storage"
time_column = "gasDayStart"

db_engine = create_engine()
metadata_obj = sa.MetaData()


def init():
    if sa.inspect(db_engine).has_table(table_name):
        return

    df = get_data()

    with db_engine.begin() as conn:
        df.to_sql(table_name, conn, index=False, if_exists="fail")

        # quote = db_engine.dialect.identifier_preparer.quote
        # stmt = sa.text(f"ALTER TABLE {quote(table_name)} ADD PRIMARY KEY ({quote(time_column)})")
        # conn.execute(stmt)

        stmt = sa.text("SELECT create_hypertable(:table, :time_column, migrate_data => true, if_not_exists => true)")
        conn.execute(stmt, {"table": table_name, "time_column": time_column})


def update():
    table = sa.Table(table_name, metadata_obj, autoload_with=db_engine)

    with db_engine.begin() as conn:
        (latest_date,) = conn.execute(sa.select(sa.func.max(table.c[time_column]))).one()
        df = get_data(since=latest_date)
        filtered_df = df.loc[df[time_column] > latest_date]
        filtered_df.to_sql(table_name, conn, index=False, if_exists="append")


if __name__ == "__main__":
    init()
    update()
