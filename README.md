# Wattr for Home Assistant

Read your Wattr measurements and energy plans in Home Assistant. No inverter or charger commands are sent by this integration.

## Install with HACS

In HACS, open **Custom repositories**, add `https://github.com/gpalsson/wattr-home-assistant`, and select **Integration**. Download Wattr, restart Home Assistant, then go to **Settings → Devices & services → Add integration → Wattr**.

Open the Wattr approval link, sign in with your normal Wattr account (including two-factor authentication when enabled), and approve read access. Return to Home Assistant and continue. Home Assistant stores revocable connection tokens, never your Wattr password.

## What you get

Each installation has battery SoC/power/voltage/temperature, measured battery charge/discharge energy, house, grid and optional PV readings, today's purchases, sales and savings, and the stored battery plan. Connected cars have SoC and connection/charging sensors. Charger sensors include power, planned energy, cost and start/end times. The plan sensor contains up to 400 interval records as attributes; it does not create a sensor for every interval.

Measurements refresh every 30 seconds. API reads use Wattr's stored data and do not poll hardware or rebuild plans. A measurement may have an older source timestamp; it retains its known value. Unknown values remain unknown, rather than zero. If Wattr cannot be reached, entities become unavailable until the connection recovers. Battery power is positive when charging and negative when discharging; grid power is positive for import and negative for export. All costs use DKK.

Today's energy sensors reset each Danish calendar day and use Home Assistant's `total` state class; they are daily totals, not lifetime meters. Power/SoC sensors use `measurement`. See the source timestamp on the installation/device to distinguish a stored measurement from a fresh one.

New installations and cars appear automatically. Removed ownership makes their entities unavailable. Delete the integration to revoke its connection (best effort if Wattr is offline); you can also revoke it from Wattr settings. Expired or revoked access prompts you to reconnect.

## Manual installation

Copy `custom_components/wattr` into your Home Assistant `config/custom_components/` directory and restart. Home Assistant 2025.10 or later is required.

This repository is installable as a HACS custom repository. It has not been submitted to or accepted into the default HACS catalogue.

## Development

Create a Python 3.13+ virtual environment and install `requirements-test.txt`. Run `pytest` and `ruff check .`. Tests use synthetic accounts and an in-process HTTP API; they do not call real customer accounts, send messages or control equipment.

The read-only API contract is maintained by Wattr at `docs/HOME-ASSISTANT-API.md` in its server repository. Contributions use feature branches and pull requests.

## Historical 15-minute energy readings

Version 0.2.0 adds **Wattr: Get history** under Developer tools → Actions. Select an installation and Danish calendar date: today or any of the previous 30 days. The installation ID is shown in the attributes of your Wattr sensors. For multiple Wattr accounts, select the matching connection.

```yaml
action: wattr.get_history
data:
  installation_id: gustav-palsson
  date: "2026-10-12"
response_variable: wattr_history
```

Use a date within the current 30-day window. The response contains timestamped 15-minute intervals for grid imports/exports, house use (excluding the car when separately measured), and battery charging/discharging in kWh. The API includes source availability, per-field measurement coverage/quality and any recoverable coarse energy across long gaps. Short measured power integration and counter deltas are identified separately. Battery energy is never derived from SoC changes. Denmark's daylight-saving days contain 92 or 100 intervals; ordinary days contain 96.

Missing or future readings remain `null`; a recorded zero is `0`. A partial daily total is an observed lower bound: check `totals.FIELD.complete` and `coverage_seconds` before treating it as a complete day's consumption. Energy in `coarse_energy` has known endpoints but cannot be allocated accurately to 15-minute intervals; it is separate from the interval sums. Do not add it blindly to a daily total if its endpoints cross that day's boundary.

This read action returns data for your charts/migration tooling. It does **not** backdate HA state history, import statistics or overwrite SolarAssistant totals. Preserving existing records requires an explicit migration in your HA setup that imports only missing timestamps and keeps the cumulative baseline. The integration itself writes no past Recorder data. Thirty-day access does not mean thirty days of observations exist; consult `available_from` and `available_through` in the response.

Battery charge/discharge sensors show measured energy for today, with the same Danish midnight reset as other daily totals. Voltage and temperature remain unknown if Wattr has no measured reading. PV entities still appear only for installations with PV.
