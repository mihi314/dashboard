import asyncio
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import typer
from apscheduler.schedulers.blocking import BlockingScheduler
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
from thermopro_ble import ThermoProBluetoothDeviceData

from mpi.settings import settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mpi")

timezone_berlin = ZoneInfo("Europe/Berlin")


# Scanning
#
async def scan() -> list[dict]:
    """Listen for advertisements of the configured sensors and return the latest measurement of each."""
    devices = {mac.upper(): name for mac, name in settings.DEVICES.items()}
    # One parser per sensor that lives for the whole scan: the TP357S encodes part of its data in the manufacturer ID,
    # so the parser has to compare against previous advertisements to find the current one
    parsers = {mac: ThermoProBluetoothDeviceData() for mac in devices}
    latest: dict[str, dict] = {}

    def on_advertisement(device: BLEDevice, advertisement_data: AdvertisementData):
        mac = device.address.upper()
        if mac not in devices:
            return

        service_info = BluetoothServiceInfoBleak.from_device_and_advertisement_data(
            device, advertisement_data, source="local", time=time.monotonic(), connectable=False
        )
        values = {key.key: value.native_value for key, value in parsers[mac].update(service_info).entity_values.items()}
        if "temperature" not in values or "humidity" not in values:
            return

        latest[mac] = {
            "device": devices[mac],
            "time": datetime.now(timezone.utc).isoformat(),
            "temperature_C": values["temperature"],
            "humidity_percent": values["humidity"],
            "battery_percent": values.get("battery"),
        }

    async with BleakScanner(detection_callback=on_advertisement):
        await asyncio.sleep(settings.SCAN_SECONDS)

    for mac, name in devices.items():
        if mac not in latest:
            logger.warning(f'No measurement received from "{name}" ({mac}) within {settings.SCAN_SECONDS}s')

    return list(latest.values())


# Pushing
#
def push(measurements: list[dict]):
    """Best effort: failures are logged and the measurements dropped."""
    try:
        response = requests.post(
            settings.INGEST_URL,
            json={"measurements": measurements},
            headers={"Authorization": f"Bearer {settings.INGEST_TOKEN}"},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Pushing {len(measurements)} measurement(s) failed: {e}")
        return
    logger.info(f"Pushed {len(measurements)} measurement(s): {measurements}")


def update():
    start = time.time()
    measurements = asyncio.run(scan())
    if measurements:
        push(measurements)
    logger.info(f"Update completed in {time.time() - start:.2f} seconds")


def main(once: bool = typer.Option(False, help="Run a single scan and push, then exit")):
    if once:
        update()
        return

    scheduler = BlockingScheduler(timezone=timezone_berlin)
    scheduler.add_job(update, "cron", minute=f"*/{settings.INTERVAL_MINUTES}", max_instances=1, coalesce=True)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")


def cli():
    typer.run(main)


if __name__ == "__main__":
    cli()
