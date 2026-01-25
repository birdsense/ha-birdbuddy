"""The Bird Buddy integration."""

from __future__ import annotations

from birdbuddy.client import BirdBuddy

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    DOMAIN,
    LOGGER,
    CONF_RESET_FEED_STORAGE,
)
from .coordinator import BirdBuddyDataUpdateCoordinator

# Minimal platforms for feed-only integration
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

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
    LOGGER.info("Setting up Bird Buddy coordinator for user: %s", entry.data[CONF_EMAIL])
    await coordinator.async_config_entry_first_refresh()
    LOGGER.info("Bird Buddy coordinator setup completed")

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    ):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


# Device removal not needed for feed-only integration


def _setup_services(hass: HomeAssistant) -> bool:
    """Register services for feed-only integration"""
    
    async def handle_reset_feed_storage(service: ServiceCall) -> None:
        """Reset feed storage to process all items again."""
        LOGGER.info("Reset feed storage service called")
        for coordinator in hass.data[DOMAIN].values():
            coordinator._reset_feed_storage()
        LOGGER.info("Feed storage reset - all items will be processed again")

    hass.services.async_register(
        DOMAIN,
        "reset_feed_storage",
        handle_reset_feed_storage,
        schema=vol.Schema({}),
    )
    
    async def handle_refresh_feed(service: ServiceCall) -> None:
        """Manually trigger feed refresh."""
        LOGGER.warning("=== REFRESH FEED SERVICE CALLED ===")
        coordinators = list(hass.data[DOMAIN].values())
        LOGGER.warning("Found %d coordinators", len(coordinators))

        if not coordinators:
            LOGGER.error("No Bird Buddy coordinators found! Is the integration properly configured?")
            return

        for coordinator in coordinators:
            LOGGER.warning("Calling force_refresh_now on coordinator...")
            await coordinator.force_refresh_now()
        LOGGER.warning("=== REFRESH FEED SERVICE COMPLETED ===")

    hass.services.async_register(
        DOMAIN,
        "refresh_feed",
        handle_refresh_feed,
        schema=vol.Schema({}),
    )
    LOGGER.info("Bird Buddy services registered successfully")
    return True
