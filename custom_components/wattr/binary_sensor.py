"""Car/charger status; never turn an unknown status into disconnected."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .entity import WattrEntity, discover


class WattrBinarySensor(WattrEntity, BinarySensorEntity):
    def __init__(self, coordinator, site_id, kind, subject_id, key):
        super().__init__(coordinator, site_id, kind, subject_id, key)
        self.entity_description = BinarySensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=BinarySensorDeviceClass.PLUG if key == "plugged_in" else None,
        )

    @property
    def is_on(self):
        value = (self.subject or {}).get(self.entity_description.key)
        return value if isinstance(value, bool) else None


def factory(coordinator, site, kind, subject_id):
    if kind in ("car", "charger"):
        for key in ("plugged_in", "charging"):
            yield WattrBinarySensor(coordinator, site["id"], kind, subject_id, key)


async def async_setup_entry(hass, entry, async_add_entities):
    discover(entry.runtime_data, entry, async_add_entities, factory)
