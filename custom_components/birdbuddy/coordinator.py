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

    async def _process_feed(self, feed: list) -> None:
        """Process new feed items and emit events."""
        if not feed:
            LOGGER.info("No feed items found")
            return

        LOGGER.info("Processing %d feed items", len(feed))
        
        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        LOGGER.info("Already processed %d items", len(processed_ids))
        new_ids = set()

        for item in feed:
            # Handle both FeedNode objects and strings
            if isinstance(item, str):
                item_id = item
                item_type = "unknown"
                created_at = None
                item_data = {"id": item}
                LOGGER.info("Processing string item: %s", item_id)
            else:
                # Assume FeedNode object
                item_id = item.get("id") if hasattr(item, 'get') and item else None
                item_type = item.get("__typename") if hasattr(item, 'get') and item else "unknown"
                created_at = item.get("createdAt") if hasattr(item, 'get') and item else None
                item_data = item.data if hasattr(item, 'data') and item else {"id": item_id}
            
            if not item_id:
                continue

            new_ids.add(item_id)
            
            # Skip if already processed
            if item_id in processed_ids:
                continue

            LOGGER.info("New feed item: %s (type: %s)", item_id, item_type)
            
            # Fire event with complete feed item data
            event_data = {
                "item_id": item_id,
                "item_data": item_data,
                "created_at": created_at,
                "type": item_type,
            }
            LOGGER.info("Firing event %s with data: %s", EVENT_NEW_FEED_ITEM, event_data)
            
            self.hass.bus.fire(
                event_type=EVENT_NEW_FEED_ITEM,
                event_data=event_data,
                origin=EventOrigin.remote,
            )

        # Save all item IDs we've now seen
        all_seen_ids = processed_ids.union(new_ids)
        self._save_processed_item_ids(all_seen_ids)
        new_items_count = len(new_ids - processed_ids)
        LOGGER.info("Processed %d new items, %d total items tracked", 
                   new_items_count, len(all_seen_ids))
        
        if new_items_count == 0:
            LOGGER.info("No new feed items found to emit events for")

    async def _async_update_data(self) -> BirdBuddy:
        """Fetch latest feed data."""
        try:
            await self.client.refresh()

            # Always process the feed using feed() to get ALL items without internal cache
            feed = await self.client.feed()
            LOGGER.info("Feed fetched: %d items", len(feed) if feed else 0)
            
            # Debug: log all feed items
            if feed:
                for i, item in enumerate(feed):
                    if isinstance(item, str):
                        LOGGER.info("Feed item %d: ID=%s, Type=string", i+1, item)
                    else:
                        LOGGER.info("Feed item %d: ID=%s, Type=%s, Created=%s", 
                                   i+1, item.get("id") if hasattr(item, 'get') else "unknown", 
                                   item.get("__typename") if hasattr(item, 'get') else "unknown", 
                                   item.get("createdAt") if hasattr(item, 'get') else "unknown")
            else:
                LOGGER.warning("No feed items returned from Bird Buddy API")
            
            await self._process_feed(feed)
            
            # Update timestamp for successful operations
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Failed to fetch Bird Buddy feed: %s", exc)
            raise UpdateFailed(f"Error fetching feed: {exc}") from exc


        return self.client

    def _reset_feed_storage(self) -> None:
        """Reset the feed storage to process all items again."""
        # Clear stored item IDs
        new_data = dict(self.config_entry.data)
        new_data[CONF_LAST_FEED_ITEM_IDS] = []
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        

        
        LOGGER.info("Feed storage reset - all items will be processed as new")

    async def force_refresh_now(self) -> None:
        """Force immediate feed refresh and processing."""
        LOGGER.info("Force refresh triggered - processing feed immediately")
        try:
            await self.client.refresh()
            feed = await self.client.feed()
            LOGGER.info("Force refresh fetched: %d items", len(feed) if feed else 0)
            
            if feed:
                for i, item in enumerate(feed):
                    if isinstance(item, str):
                        LOGGER.info("Force refresh item %d: ID=%s, Type=string", i+1, item)
                    else:
                        LOGGER.info("Force refresh item %d: ID=%s, Type=%s, Created=%s", 
                                           i+1, item.get("id") if hasattr(item, 'get') else "unknown", 
                                           item.get("__typename") if hasattr(item, 'get') else "unknown", 
                                           item.get("createdAt") if hasattr(item, 'get') else "unknown")
            
            # Process feed regardless of first_update flag
            await self._process_feed(feed)
            
            # Update timestamp
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
