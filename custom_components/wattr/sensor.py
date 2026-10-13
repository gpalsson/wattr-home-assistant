"""Measurements and plans only; no controls."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower

from .entity import WattrEntity, discover, numeric, timestamp


@dataclass(frozen=True, kw_only=True)
class Description(SensorEntityDescription):
    path: tuple[str, ...]
    kind: str = "installation"
    requires: str | None = None


def desc(
    key,
    path=None,
    *,
    kind="installation",
    requires=None,
    unit=None,
    device_class=None,
    state_class=None,
):
    return Description(
        key=key,
        translation_key=key,
        path=tuple((path or key).split(".")),
        kind=kind,
        requires=requires,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
    )


DESCRIPTIONS = [
    desc(
        "battery_soc",
        "battery_soc_percent",
        requires="has_inverter",
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    *[
        desc(
            k,
            k + "_kw",
            requires=r,
            unit=UnitOfPower.KILO_WATT,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
        )
        for k, r in [
            ("battery_power", "has_inverter"),
            ("house_power", "has_inverter"),
            ("grid_power", "has_inverter"),
            ("solar_power", "has_solar"),
        ]
    ],
    desc("inverter_status", requires="has_inverter"),
    desc("read_at", device_class=SensorDeviceClass.TIMESTAMP),
    desc(
        "plan",
        "plan.built_at",
        requires="has_inverter",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    *[
        desc(
            k,
            "today." + k,
            requires="has_solar" if k == "solar_kwh" else None,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL,
        )
        for k in ["import_kwh", "export_kwh", "house_kwh", "car_kwh", "solar_kwh"]
    ],
    *[
        desc(
            k,
            "today." + k,
            unit="DKK",
            device_class=SensorDeviceClass.MONETARY,
            state_class=SensorStateClass.TOTAL,
        )
        for k in ["import_cost_dkk", "export_income_dkk", "savings_dkk"]
    ],
    *[
        desc(
            k,
            "today." + k,
            unit=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
        )
        for k in ["planned_import_kwh", "planned_export_kwh"]
    ],
    *[
        desc(k, "today." + k, unit="DKK", device_class=SensorDeviceClass.MONETARY)
        for k in ["planned_import_cost_dkk", "planned_export_income_dkk"]
    ],
    desc(
        "car_soc",
        "soc_percent",
        kind="car",
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    desc(
        "car_read_at", "read_at", kind="car", device_class=SensorDeviceClass.TIMESTAMP
    ),
    desc(
        "charger_power",
        "power_kw",
        kind="charger",
        unit=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    desc(
        "charge_plan_start",
        "plan_start",
        kind="charger",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    desc(
        "charge_plan_end",
        "plan_end",
        kind="charger",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    desc(
        "charge_plan_cost",
        "plan_cost_dkk",
        kind="charger",
        unit="DKK",
        device_class=SensorDeviceClass.MONETARY,
    ),
    desc(
        "charge_plan_energy",
        "plan_energy_kwh",
        kind="charger",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
    ),
]


class WattrSensor(WattrEntity, SensorEntity):
    def __init__(self, coordinator, site_id, kind, subject_id, description):
        super().__init__(coordinator, site_id, kind, subject_id, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        value = self.subject
        for key in self.entity_description.path:
            value = value.get(key) if isinstance(value, dict) else None
        if self.device_class == SensorDeviceClass.TIMESTAMP:
            return timestamp(value)
        if self.native_unit_of_measurement:
            result = numeric(value)
            if (
                self.native_unit_of_measurement == PERCENTAGE
                and result is not None
                and not 0 <= result <= 100
            ):
                return None
            return result
        return value if isinstance(value, str) else None

    @property
    def last_reset(self):
        if self.state_class != SensorStateClass.TOTAL:
            return None
        date = (self.subject or {}).get("today", {}).get("date")
        try:
            return (
                datetime.fromisoformat(date).replace(
                    tzinfo=ZoneInfo("Europe/Copenhagen")
                )
                if date
                else None
            )
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "plan":
            plan = (self.subject or {}).get("plan") or {}
            return {"intervals": (plan.get("intervals") or [])[:400]}
        return super().extra_state_attributes


def factory(coordinator, site, kind, subject_id):
    for description in DESCRIPTIONS:
        if description.kind == kind and (
            not description.requires or site.get(description.requires)
        ):
            yield WattrSensor(coordinator, site["id"], kind, subject_id, description)


async def async_setup_entry(hass, entry, async_add_entities):
    discover(entry.runtime_data, entry, async_add_entities, factory)
