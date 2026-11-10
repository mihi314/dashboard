# mpi

Runs on a Raspberry Pi, listens for the BLE advertisements of ThermoPro thermo-hygrometers (e.g. TP357S) using
[thermopro-ble](https://github.com/Bluetooth-Devices/thermopro-ble) and pushes the readings to the dashboard's ingest
API (`POST /ingest/climate`, see `updater/updater/api.py`). Best effort: readings that can't be pushed are dropped.

## Setup

Requirements: 64-bit Raspberry Pi OS (prebuilt wheels for the BLE dependencies), Bluetooth/BlueZ enabled, time synced
via NTP (readings are timestamped on the Pi), [uv](https://docs.astral.sh/uv/).

1. Copy this directory to `~/dashboard/integrations/mpi` on the Pi (or adjust `WorkingDirectory` in `mpi.service`)
2. Create `.env`:

   ```sh
   MPI_INGEST_URL=https://<DASH_DOMAIN>:4443/ingest/climate
   MPI_INGEST_TOKEN=<DASH_INGEST_TOKEN of the server>
   MPI_DEVICES={"AA:BB:CC:DD:EE:FF": "living_room"}
   # optional: MPI_SCAN_SECONDS=30, MPI_INTERVAL_MINUTES=5, MPI_HTTP_TIMEOUT_SECONDS=10
   ```

   The MAC address can be found with `bluetoothctl scan on` (the sensor shows up as e.g. `TP357S (EEFF)`).
3. Test a single run: `uv run mpi --once`
4. Install the systemd unit, see the comment at the top of `mpi.service`

Note: Don't keep the ThermoPro phone app connected to the sensor, it can stop the advertisements.
