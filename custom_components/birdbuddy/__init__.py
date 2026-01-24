"""The Bird Buddy integration."""

from __future__ import annotations

from birdbuddy.client import BirdBuddy

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    LOGGER,
)
from .coordinator import BirdBuddyDataUpdateCoordinator

# No platforms needed for feed-only integration

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Setup the integration"""
    # This will register the services even if there's no ConfigEntry yet...
    _setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up Bird Buddy from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    client = BirdBuddy(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    client.language_code = hass.config.language
    coordinator = BirdBuddyDataUpdateCoordinator(hass, client, entry)

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()

    # No platforms to set up

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload a config entry."""
    # No platforms to unload
    unload_ok = True
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


# Device removal not needed for feed-only integration


def _setup_services(hass: HomeAssistant) -> bool:
    """No services needed for feed-only integration"""
    return True
