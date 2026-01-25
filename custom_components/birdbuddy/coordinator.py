"""Data Update coordinator for Bird Buddy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
            LOGGER.warning("_process_feed: No feed items to process")
            return

        LOGGER.warning("_process_feed: Processing %d feed items", len(feed))

        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        LOGGER.warning("_process_feed: Already processed %d items: %s", len(processed_ids), list(processed_ids)[:5])
        new_ids = set()

        for item in feed:
            # Handle both FeedNode objects and strings
            if isinstance(item, str):
                item_id = item
                item_type = "unknown"
                created_at = None
                item_data = {"id": item}
            else:
                # Assume FeedNode object
                item_id = item.get("id") if hasattr(item, 'get') and item else None
                item_type = item.get("__typename") if hasattr(item, 'get') and item else "unknown"
                created_at = item.get("createdAt") if hasattr(item, 'get') and item else None
                item_data = dict(item.data) if hasattr(item, 'data') and item else {"id": item_id}

            if not item_id:
                continue

            new_ids.add(item_id)

            # Skip if already processed
            if item_id in processed_ids:
                LOGGER.warning("Skipping already processed: %s", item_id)
                continue

            LOGGER.warning("NEW feed item: %s (type: %s)", item_id, item_type)

            # For NewPostcard items without media, try to fetch sighting data
            has_medias = item_data.get("medias") and len(item_data.get("medias", [])) > 0

            if item_type == "FeedItemNewPostcard" and not has_medias:
                LOGGER.info("Fetching sighting data for recent postcard: %s", item_id)
                try:
                    sighting = await self.client.sighting_from_postcard(item_id)
                    if sighting:
                        # Extract media info from sighting
                        medias = []
                        for media in sighting.medias:
                            medias.append({
                                "id": media.id,
                                "contentUrl": media.content_url,
                                "thumbnailUrl": media.thumbnail_url,
                                "__typename": "MediaImage" if not media.is_video else "MediaVideo",
                            })
                        if medias:
                            item_data["medias"] = medias
                            LOGGER.info("Added %d medias from sighting", len(medias))

                        # Also add species info from sighting report if available
                        if sighting.report:
                            report = sighting.report
                            if hasattr(report, 'sightings') and report.sightings:
                                species_list = []
                                for s in report.sightings:
                                    if hasattr(s, 'species') and s.species:
                                        species_list.append({
                                            "name": s.species.get("name", "Unknown"),
                                            "id": s.species.get("id"),
                                        })
                                if species_list:
                                    item_data["species"] = species_list
                except Exception as exc:
                    LOGGER.debug("Failed to fetch sighting for %s: %s", item_id, exc)

            # Fire event with complete feed item data
            event_data = {
                "item_id": item_id,
                "item_data": item_data,
                "created_at": created_at,
                "type": item_type,
            }
            LOGGER.warning("FIRING EVENT %s for item %s", EVENT_NEW_FEED_ITEM, item_id)
            LOGGER.warning("Event data keys: %s, has medias: %s", list(event_data.get("item_data", {}).keys()), "medias" in event_data.get("item_data", {}))

            self.hass.bus.fire(
                event_type=EVENT_NEW_FEED_ITEM,
                event_data=event_data,
                origin=EventOrigin.remote,
            )
            LOGGER.warning("Event fired successfully for %s", item_id)

        # Save all item IDs we've now seen
        all_seen_ids = processed_ids.union(new_ids)
        self._save_processed_item_ids(all_seen_ids)
        new_items_count = len(new_ids - processed_ids)
        if new_items_count > 0:
            LOGGER.info("Processed %d new feed items", new_items_count)

    async def _async_update_data(self) -> BirdBuddy:
        """Fetch latest feed data."""
        LOGGER.info("Bird Buddy coordinator update started")
        try:
            await self.client.refresh()

            # Use refresh_feed with explicit timestamp to get recent items
            # The regular feed() method doesn't return the newest postcards
            since_time = datetime.now(timezone.utc) - timedelta(hours=24)
            feed = await self.client.refresh_feed(since=since_time)
            LOGGER.info("Feed fetched: %d items (since %s)", len(feed) if feed else 0, since_time.isoformat())

            if not feed:
                LOGGER.info("No new feed items since last check")

            await self._process_feed(feed)

            # Update timestamp for successful operations
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            # Don't mark entities unavailable for temporary API errors (502, 503, etc)
            error_str = str(exc)
            if "502" in error_str or "503" in error_str or "504" in error_str:
                LOGGER.warning("Bird Buddy API temporarily unavailable: %s", exc)
                # Return existing client data without raising - entities stay available
                return self.client
            LOGGER.error("Failed to fetch Bird Buddy feed: %s", exc)
            raise UpdateFailed(f"Error fetching feed: {exc}") from exc

        return self.client

    def _reset_feed_storage(self) -> None:
        """Reset the feed storage to process all items again."""
        # Clear stored item IDs
        old_count = len(self.config_entry.data.get(CONF_LAST_FEED_ITEM_IDS, []))
        new_data = dict(self.config_entry.data)
        new_data[CONF_LAST_FEED_ITEM_IDS] = []
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        LOGGER.warning("Feed storage reset - cleared %d items, all will be processed as new", old_count)

    async def force_refresh_now(self) -> None:
        """Force immediate feed refresh and processing."""
        LOGGER.warning("Force refresh triggered - processing feed immediately")
        try:
            await self.client.refresh()

            # Use refresh_feed with explicit timestamp to get recent items
            since_time = datetime.now(timezone.utc) - timedelta(hours=24)
            feed = await self.client.refresh_feed(since=since_time)
            LOGGER.warning("Force refresh fetched: %d items (since %s)", len(feed) if feed else 0, since_time.isoformat())

            # Log each item for debugging
            if feed:
                for item in feed:
                    item_id = item.get("id") if hasattr(item, 'get') else "unknown"
                    item_type = item.get("__typename") if hasattr(item, 'get') else "unknown"
                    LOGGER.warning("Feed item: %s (%s)", item_id, item_type)

            await self._process_feed(feed)

            # Update timestamp
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
