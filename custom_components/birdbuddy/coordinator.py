"""Data Update coordinator for Bird Buddy."""

from __future__ import annotations

from datetime import datetime

from birdbuddy.client import BirdBuddy
from birdbuddy.feed import FeedNode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import EventOrigin, HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, EVENT_NEW_FEED_ITEM, LOGGER, POLLING_INTERVAL, CONF_LAST_FEED_ITEM_IDS


class BirdBuddyDataUpdateCoordinator(DataUpdateCoordinator[BirdBuddy]):
    """Class to coordinate fetching BirdBuddy feed data."""

    config_entry: ConfigEntry
    client: BirdBuddy

    def __init__(
        self,
        hass: HomeAssistant,
        client: BirdBuddy,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the BirdBuddy data coordinator."""
        self.client = client
        self.first_update = True
        self.last_update_timestamp = None
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=POLLING_INTERVAL,
        )

    def _get_processed_item_ids(self) -> set[str]:
        """Get set of previously processed item IDs from config entry data."""
        return set(self.config_entry.data.get(CONF_LAST_FEED_ITEM_IDS, []))

    def _save_processed_item_ids(self, item_ids: set[str]) -> None:
        """Save processed item IDs to config entry data."""
        # Update config entry data with new item IDs
        new_data = dict(self.config_entry.data)
        new_data[CONF_LAST_FEED_ITEM_IDS] = list(item_ids)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

    async def _process_feed(self, feed: list[FeedNode]) -> None:
        """Process new feed items and emit events."""
        if not feed:
            return

        LOGGER.debug("Found %d feed items", len(feed))
        
        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        new_ids = set()

        for item in feed:
            item_id = item.get("id")
            if not item_id:
                continue

            new_ids.add(item_id)
            
            # Skip if already processed
            if item_id in processed_ids:
                continue

            LOGGER.info("New feed item: %s (type: %s)", item_id, item.get("__typename"))
            
            # Fire event with complete feed item data
            self.hass.bus.fire(
                event_type=EVENT_NEW_FEED_ITEM,
                event_data={
                    "item_id": item_id,
                    "item_data": item.data,
                    "created_at": item.get("createdAt"),
                    "type": item.get("__typename"),
                },
                origin=EventOrigin.remote,
            )

        # Save all item IDs we've now seen
        all_seen_ids = processed_ids.union(new_ids)
        self._save_processed_item_ids(all_seen_ids)

    async def _async_update_data(self) -> BirdBuddy:
        """Fetch latest feed data."""
        try:
            await self.client.refresh()

            # Skip processing the Feed on the first update. This works around a minor issue
            # where the `automation` integration is not loaded yet by the time we make our first
            # update call. If we proceed, we might emit feed items while there are
            # no automations listening.
            if not self.first_update:
                feed = await self.client.refresh_feed()
                await self._process_feed(feed)
            else:
                LOGGER.info("First update completed - next update will process feed items")
            
            # Update timestamp for successful operations
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Failed to fetch Bird Buddy feed: %s", exc)
            raise UpdateFailed(f"Error fetching feed: {exc}") from exc

        self.first_update = False
        return self.client
