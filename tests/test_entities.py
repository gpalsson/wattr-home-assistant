from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.wattr.binary_sensor import factory as binary_factory
from custom_components.wattr.diagnostics import async_get_config_entry_diagnostics
from custom_components.wattr.entity import discover
from custom_components.wattr.sensor import factory


def coordinator(snapshot):
    c = SimpleNamespace(
        data=snapshot,
        account_id="test-account",
        last_update_success=True,
        async_add_listener=Mock(return_value=lambda: None),
    )
    c.installation = lambda id: next(
        (s for s in c.data["installations"] if s["id"] == id), None
    )
    return c


def sensors(snapshot, kind="installation", id="test-home"):
    c = coordinator(snapshot)
    return c, {
        s.entity_description.key: s
        for s in factory(c, snapshot["installations"][0], kind, id)
    }


def test_measurements_units_unknown_zero_sign(snapshot):
    c, s = sensors(snapshot)
    assert s["battery_power"].native_value == -0.8
    assert s["battery_power"].native_unit_of_measurement == "kW"
    assert s["battery_soc"].native_value == 50.5
    assert s["solar_power"].native_value is None
    assert s["import_kwh"].native_value == 0
    assert s["savings_dkk"].native_value == -1.2
    assert s["battery_power"].available
    c.last_update_success = False
    assert not s["battery_power"].available


def test_source_timestamp_does_not_discard_stored_values(snapshot):
    snapshot["installations"][0]["read_at"] = "2020-01-01T00:00:00Z"
    _, s = sensors(snapshot)
    assert s["battery_soc"].native_value == 50.5
    assert s["battery_soc"].extra_state_attributes["read_at"].startswith("2020")


def test_plan_is_bounded_with_no_control_entities(snapshot):
    snapshot["installations"][0]["plan"]["intervals"] *= 500
    _, s = sensors(snapshot)
    assert len(s["plan"].extra_state_attributes["intervals"]) == 400
    assert s["plan"].native_value.tzinfo is not None
    assert not any("control" in key for key in s)


def test_daily_reset_uses_danish_midnight(snapshot):
    _, s = sensors(snapshot)
    assert s["import_kwh"].last_reset.isoformat() == "2026-10-13T00:00:00+02:00"
    assert s["battery_soc"].last_reset is None
    snapshot["installations"][0]["today"]["date"] = "2026-10-25"
    assert s["import_kwh"].last_reset.isoformat() == "2026-10-25T00:00:00+02:00"


def test_no_assumed_solar_and_removed_ownership_unavailable(snapshot):
    snapshot["installations"][0]["has_solar"] = False
    c, s = sensors(snapshot)
    assert "solar_power" not in s
    c.data = {"installations": []}
    assert not s["battery_soc"].available
    assert s["battery_soc"].native_value is None


@pytest.mark.parametrize("value", [True, "90", float("nan"), float("inf"), -1, 101])
def test_bad_soc_is_unknown(snapshot, value):
    snapshot["installations"][0]["battery_soc_percent"] = value
    _, s = sensors(snapshot)
    assert s["battery_soc"].native_value is None


def test_car_status_unknown_preserved_and_ids_stable(snapshot):
    c, s = sensors(snapshot, "car", "test-car")
    assert s["car_soc"].native_value == 88.7
    unique = s["car_soc"].unique_id
    snapshot["installations"][0]["cars"][0]["name"] = "New name"
    _, renamed = sensors(snapshot, "car", "test-car")
    assert renamed["car_soc"].unique_id == unique
    binary = {
        e.entity_description.key: e
        for e in binary_factory(c, snapshot["installations"][0], "car", "test-car")
    }
    assert binary["plugged_in"].is_on is True
    snapshot["installations"][0]["cars"][0]["plugged_in"] = None
    assert binary["plugged_in"].is_on is None


def test_dynamic_discovery_only_adds_new_entities(snapshot):
    c = coordinator(snapshot)
    entry = SimpleNamespace(async_on_unload=Mock())
    added = []
    discover(c, entry, lambda entities: added.extend(entities), factory)
    count = len(added)
    callback = c.async_add_listener.call_args.args[0]
    callback()
    assert len(added) == count
    snapshot["installations"][0]["cars"].append({"id": "new-car", "name": "Second"})
    callback()
    assert len(added) == count + 2
    assert len({e.unique_id for e in added}) == len(added)


async def test_diagnostics_never_expose_tokens_or_measurements(snapshot):
    c = coordinator(snapshot)
    result = await async_get_config_entry_diagnostics(
        None, SimpleNamespace(runtime_data=c, data={"refresh_token": "secret"})
    )
    assert set(result) == {
        "integration_version",
        "api_version",
        "last_update_success",
        "installation_count",
    }
    assert result["installation_count"] == 1


def test_battery_energy_voltage_temperature_are_measured(snapshot):
    site = snapshot["installations"][0]
    site.update(battery_voltage_v=52.4, battery_temperature_c=24.5)
    site["today"].update(
        battery_charge_kwh=12.3,
        battery_discharge_kwh=8.7,
        battery_energy_quality={"charge": {"complete": False, "coverage_seconds": 900}},
    )
    _, s = sensors(snapshot)
    assert s["battery_voltage"].native_value == 52.4
    assert s["battery_voltage"].native_unit_of_measurement == "V"
    assert s["battery_temperature"].native_value == 24.5
    assert s["battery_charge_kwh"].native_value == 12.3
    assert s["battery_charge_kwh"].last_reset is not None
    assert (
        s["battery_charge_kwh"].extra_state_attributes["measurement_quality"][
            "complete"
        ]
        is False
    )
    assert s["battery_discharge_kwh"].native_value == 8.7
    del site["today"]["battery_charge_kwh"]
    assert s["battery_charge_kwh"].native_value is None
