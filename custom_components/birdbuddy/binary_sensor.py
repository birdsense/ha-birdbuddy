"""Binary sensors for Bird Buddy feed-only integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, BINARY_SENSOR_CONNECTION
from .coordinator import BirdBuddyDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up binary sensors from a config entry."""
    coordinator: BirdBuddyDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([
        BirdBuddyConnectionSensor(coordinator, entry),
    ])


class BirdBuddyConnectionSensor(BinarySensorEntity, CoordinatorEntity):
    """Binary sensor showing Bird Buddy connection status."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BirdBuddyDataUpdateCoordinator, entry: ConfigEntry) -> None:
        """Initialize connection sensor."""
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{BINARY_SENSOR_CONNECTION}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Bird Buddy Feed",
            manufacturer="Bird Buddy, Inc.",
        )

    @property
    def is_on(self) -> bool:
        """Return True if connected and last update was successful."""
        return self.coordinator.last_update_success

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return True  # Always available to show connection status