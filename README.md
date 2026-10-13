# Wattr for Home Assistant

Read your Wattr measurements and energy plans in Home Assistant. No inverter or charger commands are sent by this integration.

## Install with HACS

In HACS, open **Custom repositories**, add `https://github.com/gpalsson/wattr-home-assistant`, and select **Integration**. Download Wattr, restart Home Assistant, then go to **Settings → Devices & services → Add integration → Wattr**.

Open the Wattr approval link, sign in with your normal Wattr account (including two-factor authentication when enabled), and approve read access. Return to Home Assistant and continue. Home Assistant stores revocable connection tokens, never your Wattr password.

## What you get

Each installation has battery, house, grid and optional PV readings, today's purchases, sales and savings, and the stored battery plan. Connected cars have SoC and connection/charging sensors. Charger sensors include power, planned energy, cost and start/end times. The plan sensor contains up to 400 interval records as attributes; it does not create a sensor for every interval.

Measurements refresh every 30 seconds. API reads use Wattr's stored data and do not poll hardware or rebuild plans. A measurement may have an older source timestamp; it retains its known value. Unknown values remain unknown, rather than zero. If Wattr cannot be reached, entities become unavailable until the connection recovers. Battery power is positive when charging and negative when discharging; grid power is positive for import and negative for export. All costs use DKK.

Today's energy sensors reset each Danish calendar day and use Home Assistant's `total` state class; they are daily totals, not lifetime meters. Power/SoC sensors use `measurement`. See the source timestamp on the installation/device to distinguish a stored measurement from a fresh one.

New installations and cars appear automatically. Removed ownership makes their entities unavailable. Delete the integration to revoke its connection (best effort if Wattr is offline); you can also revoke it from Wattr settings. Expired or revoked access prompts you to reconnect.

## Manual installation

Copy `custom_components/wattr` into your Home Assistant `config/custom_components/` directory and restart. Home Assistant 2025.10 or later is required.

This repository is installable as a HACS custom repository. It has not been submitted to or accepted into the default HACS catalogue.

## Development

Create a Python 3.13+ virtual environment and install `requirements-test.txt`. Run `pytest` and `ruff check .`. Tests use synthetic accounts and an in-process HTTP API; they do not call real customer accounts, send messages or control equipment.

The read-only API contract is maintained by Wattr at `docs/HOME-ASSISTANT-API.md` in its server repository. Contributions use feature branches and pull requests.
