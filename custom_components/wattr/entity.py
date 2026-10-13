"""Stable device identity and dynamic discovery shared by both platforms."""

import math
from collections.abc import Callable

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import parse_datetime

from .const import DOMAIN


def numeric(value):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def timestamp(value):
    return parse_datetime(value) if isinstance(value, str) else None


def subjects(coordinator):
    for site in (coordinator.data or {}).get("installations", []):
        yield site, "installation", site["id"]
        for car in site.get("cars") or []:
            if isinstance(car, dict) and isinstance(car.get("id"), str):
                yield site, "car", car["id"]
        if isinstance(site.get("charger"), dict):
            yield site, "charger", site["id"]


class WattrEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, site_id, kind, subject_id, key):
        super().__init__(coordinator)
        self.site_id, self.kind, self.subject_id = site_id, kind, subject_id
        device_id = f"{coordinator.account_id}:{site_id}:{kind}:{subject_id}"
        self._attr_unique_id = f"{device_id}:{key}"
        site = coordinator.installation(site_id)
        subject = self.subject
        name = subject.get("name") if kind == "car" else site.get("name")
        if kind == "charger":
            name = f"{name} charger"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=name or "Wattr",
            manufacturer="Wattr",
            model={
                "installation": "Energy installation",
                "car": "Connected car",
                "charger": "Connected charger",
            }[kind],
            configuration_url="https://wattr.dk/portal/settings",
        )
        if kind != "installation":
            self._attr_device_info["via_device"] = (
                DOMAIN,
                f"{coordinator.account_id}:{site_id}:installation:{site_id}",
            )

    @property
    def subject(self):
        site = self.coordinator.installation(self.site_id)
        if site is None:
            return None
        if self.kind == "car":
            return next(
                (c for c in site.get("cars") or [] if c.get("id") == self.subject_id),
                None,
            )
        return site.get("charger") if self.kind == "charger" else site

    @property
    def available(self):
        return super().available and self.subject is not None

    @property
    def extra_state_attributes(self):
        subject = self.subject or {}
        return {"read_at": subject["read_at"]} if subject.get("read_at") else None


def discover(coordinator, entry, async_add_entities, factory: Callable):
    known = set()

    def update():
        entities = []
        for site, kind, subject_id in subjects(coordinator):
            for entity in factory(coordinator, site, kind, subject_id):
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    entities.append(entity)
        if entities:
            async_add_entities(entities)

    update()
    entry.async_on_unload(coordinator.async_add_listener(update))
