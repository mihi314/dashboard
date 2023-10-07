import time
import pytz
import functools
from datetime import datetime
from typing import Callable

import typer
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from updater import boulderwelt, gas_storage, workflowy, nergie


timezone = pytz.timezone("Europe/Berlin")


def make_job(update: Callable, name: str):
    @functools.wraps(update)
    def wrapper(*args, **kwargs):
        start = time.time()
        print(f'Job "{name}" starting at {datetime.now(timezone).isoformat()}')
        result = update(*args, **kwargs)
        elapsed = time.time() - start
        print(f'Job "{name}" completed in {elapsed:.2f} seconds')
        return result

    # Makes the output of scheduler.print_jobs use `name` as the job name
    wrapper.__qualname__ = name
    return wrapper


def test_job():
    print(datetime.now(), "test job")


def main(print_jobs: bool = False):
    # Initialize the database tables etc
    boulderwelt.init()
    gas_storage.init()
    workflowy.init()
    nergie.init()

    # Schedule
    scheduler = BackgroundScheduler(timezone=timezone, executors={"default": ThreadPoolExecutor(max_workers=10)})

    scheduler.add_job(make_job(boulderwelt.update, "boulderwelt"), "cron", minute="*/5", second="10")
    scheduler.add_job(make_job(gas_storage.update, "gas_storage"), "cron", hour="23", minute="30")
    scheduler.add_job(make_job(workflowy.update, "workflowy"), "cron", hour="3", minute="0")
    scheduler.add_job(make_job(nergie.update, "nergie"), "cron", hour="6", minute="30")
    # scheduler.add_job(make_job(test_job, "test_job"), "cron", second="*/10")

    scheduler.start()

    if print_jobs:
        scheduler.print_jobs()

    try:
        while True:
            time.sleep(100)
    except KeyboardInterrupt:
        print("Shutting down")
        scheduler.shutdown()


if __name__ == "__main__":
    typer.run(main)
