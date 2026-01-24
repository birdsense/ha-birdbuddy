"""Sensors for Bird Buddy feed-only integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_FEED_STATUS, SENSOR_LAST_SYNC
from .coordinator import BirdBuddyDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: BirdBuddyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([
        BirdBuddyFeedStatusSensor(coordinator, entry),
        BirdBuddyLastSyncSensor(coordinator, entry),
    ])


class BirdBuddyFeedStatusSensor(SensorEntity, CoordinatorEntity):
    """Sensor showing Bird Buddy feed status."""

    _attr_has_entity_name = True
    _attr_translation_key = "feed_status"

    def __init__(self, coordinator: BirdBuddyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize feed status sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_FEED_STATUS}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Bird Buddy Feed",
            manufacturer="Bird Buddy, Inc.",
        )

    @property
    def native_value(self) -> str:
        """Return feed status."""
        if self.coordinator.last_update_success:
            processed_count = len(self.coordinator._get_processed_item_ids())
            return f"OK ({processed_count} items processed)"
        return "Error"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return {
            "last_update": self.coordinator.data.last_refresh if self.coordinator.data else None,
            "total_items_processed": len(self.coordinator._get_processed_item_ids()),
            "update_interval_minutes": 10,
        }


class BirdBuddyLastSyncSensor(SensorEntity, CoordinatorEntity):
    """Sensor showing last sync timestamp."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: BirdBuddyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize last sync sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_LAST_SYNC}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Bird Buddy Feed",
            manufacturer="Bird Buddy, Inc.",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return last successful sync timestamp."""
        if self.coordinator.last_update_success and self.coordinator.data:
            return self.coordinator.data.last_refresh
        return None

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None