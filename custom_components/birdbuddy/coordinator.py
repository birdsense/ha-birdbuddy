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
            LOGGER.warning("No feed items found")
            return

        LOGGER.warning("Processing %d feed items", len(feed))

        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        LOGGER.warning("Already processed %d items", len(processed_ids))
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
                continue

            LOGGER.warning("New feed item: %s (type: %s)", item_id, item_type)

            # For NewPostcard items without media, fetch the full sighting data
            # Only try for recent postcards (< 2 hours old) to avoid API errors
            has_medias = item_data.get("medias") and len(item_data.get("medias", [])) > 0
            is_recent = False
            if created_at:
                try:
                    # Parse ISO timestamp and check if recent
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    age = datetime.now(timezone.utc) - created_dt
                    is_recent = age < timedelta(hours=2)
                    LOGGER.warning("Postcard age: %s, is_recent: %s", age, is_recent)
                except (ValueError, TypeError):
                    is_recent = False

            if item_type == "FeedItemNewPostcard" and not has_medias and is_recent:
                LOGGER.warning("Fetching sighting data for recent postcard: %s", item_id)
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
                            LOGGER.warning("Added %d medias from sighting", len(medias))

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
                    LOGGER.warning("Failed to fetch sighting for %s: %s", item_id, exc)

            # Fire event with complete feed item data
            event_data = {
                "item_id": item_id,
                "item_data": item_data,
                "created_at": created_at,
                "type": item_type,
            }
            LOGGER.warning("Firing event %s with data: %s", EVENT_NEW_FEED_ITEM, event_data)

            self.hass.bus.fire(
                event_type=EVENT_NEW_FEED_ITEM,
                event_data=event_data,
                origin=EventOrigin.remote,
            )

        # Save all item IDs we've now seen
        all_seen_ids = processed_ids.union(new_ids)
        self._save_processed_item_ids(all_seen_ids)
        new_items_count = len(new_ids - processed_ids)
        LOGGER.warning("Processed %d new items, %d total items tracked",
                       new_items_count, len(all_seen_ids))

        if new_items_count == 0:
            LOGGER.warning("No new feed items found to emit events for")

    async def _async_update_data(self) -> BirdBuddy:
        """Fetch latest feed data."""
        LOGGER.info("Bird Buddy coordinator update started")
        try:
            await self.client.refresh()

            # Fetch feed items using feed() - get 50 items to ensure recent ones are included
            # feed() returns a Feed object, we need to access .nodes to get the list
            feed_response = await self.client.feed(first=50)
            feed = list(feed_response.nodes) if feed_response else []
            LOGGER.warning("Feed fetched: %d items", len(feed))

            if not feed:
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
        LOGGER.warning("Force refresh triggered - processing feed immediately")
        try:
            await self.client.refresh()

            # Try refresh_feed with a recent timestamp to bypass caching
            try:
                since_time = datetime.now(timezone.utc) - timedelta(hours=24)
                LOGGER.warning("Trying refresh_feed(since=%s)", since_time.isoformat())
                recent_feed = await self.client.refresh_feed(since=since_time)
                LOGGER.warning("refresh_feed(since=24h ago) returned: %d items", len(recent_feed) if recent_feed else 0)
                if recent_feed:
                    for i, item in enumerate(recent_feed):
                        item_id = item.get("id") if hasattr(item, 'get') else "unknown"
                        item_type = item.get("__typename") if hasattr(item, 'get') else "unknown"
                        item_created = item.get("createdAt") if hasattr(item, 'get') else "unknown"
                        LOGGER.warning("RecentFeed %d: ID=%s, Type=%s, Created=%s", i+1, item_id, item_type, item_created)
            except Exception as exc:
                LOGGER.warning("refresh_feed(since=...) failed: %s", exc)

            # Also try new_postcards() to see if recent items appear there
            try:
                new_postcards = await self.client.new_postcards()
                LOGGER.warning("new_postcards() returned: %d items", len(new_postcards) if new_postcards else 0)
                if new_postcards:
                    for i, pc in enumerate(new_postcards):
                        pc_id = pc.get("id") if hasattr(pc, 'get') else "unknown"
                        pc_created = pc.get("createdAt") if hasattr(pc, 'get') else "unknown"
                        LOGGER.warning("NewPostcard %d: ID=%s, Created=%s", i+1, pc_id, pc_created)
            except Exception as exc:
                LOGGER.warning("new_postcards() failed: %s", exc)

            # Fetch more items (50 instead of default 20) to ensure we get recent ones
            feed_response = await self.client.feed(first=50)
            feed = list(feed_response.nodes) if feed_response else []
            LOGGER.warning("Force refresh fetched: %d items", len(feed))

            if feed:
                for i, item in enumerate(feed):
                    if isinstance(item, str):
                        LOGGER.warning("Item %d: ID=%s, Type=string", i+1, item)
                    else:
                        item_type = item.get("__typename") if hasattr(item, 'get') else "unknown"
                        item_id = item.get("id") if hasattr(item, 'get') else "unknown"
                        created = item.get("createdAt") if hasattr(item, 'get') else "unknown"
                        # Check for medias in item data
                        has_medias = False
                        if hasattr(item, 'data') and item.data:
                            medias = item.data.get("medias", [])
                            has_medias = len(medias) > 0 if medias else False
                        LOGGER.warning("Item %d: ID=%s, Type=%s, Created=%s, HasMedias=%s",
                                       i+1, item_id, item_type, created, has_medias)
            
            await self._process_feed(feed)
            
            # Update timestamp
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
