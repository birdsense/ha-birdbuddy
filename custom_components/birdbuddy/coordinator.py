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

    async def _process_feed(self, feed: list, new_postcard_ids: set[str] = None) -> None:
        """Process new feed items and emit events.

        Args:
            feed: List of feed items to process
            new_postcard_ids: Set of IDs from new_postcards() that are truly uncollected
        """
        if not feed:
            LOGGER.warning("_process_feed: No feed items to process")
            return

        new_postcard_ids = new_postcard_ids or set()
        LOGGER.warning("_process_feed: Processing %d feed items, %d are truly new postcards",
                      len(feed), len(new_postcard_ids))

        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        LOGGER.warning("_process_feed: Already processed %d items", len(processed_ids))
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

            LOGGER.warning("NEW feed item: %s (type: %s)", item_id, item_type)

            # Check if we already have media from the feed data (CollectedPostcard has media)
            has_medias = item_data.get("medias") and len(item_data.get("medias", [])) > 0

            if has_medias:
                LOGGER.warning("Item %s already has %d medias from feed",
                              item_id, len(item_data.get("medias", [])))

            # For NewPostcard items without media, try to fetch sighting data
            # But ONLY if it's in the new_postcard_ids set (truly uncollected)
            if item_type == "FeedItemNewPostcard" and not has_medias:
                if item_id in new_postcard_ids:
                    LOGGER.warning("Fetching sighting for truly new postcard: %s", item_id)
                    try:
                        # Pass the FeedNode object instead of just the ID
                        sighting = await self.client.sighting_from_postcard(item)
                        LOGGER.warning("Sighting result for %s: %s", item_id, sighting)
                        if sighting:
                            # Extract media info from sighting
                            medias = []
                            LOGGER.warning("Sighting has %d medias",
                                          len(sighting.medias) if sighting.medias else 0)
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

                            # Auto-collect the postcard so user doesn't need to open the app
                            try:
                                collected = await self.client.finish_postcard(
                                    feed_item_id=item_id,
                                    sighting_report=sighting,
                                )
                                LOGGER.warning("Auto-collected postcard %s: %s", item_id, collected)
                            except Exception as collect_exc:
                                LOGGER.warning("Failed to auto-collect %s: %s", item_id, collect_exc)
                    except Exception as exc:
                        LOGGER.warning("FAILED to fetch sighting for %s: %s", item_id, exc)
                else:
                    LOGGER.warning("Postcard %s already collected in app (not in new_postcards)", item_id)

            # Fire event with complete feed item data
            event_data = {
                "item_id": item_id,
                "item_data": item_data,
                "created_at": created_at,
                "type": item_type,
            }

            has_medias_now = "medias" in item_data and len(item_data.get("medias", [])) > 0
            LOGGER.warning("FIRING EVENT for %s - type: %s, has_medias: %s",
                          item_id, item_type, has_medias_now)

            self.hass.bus.fire(
                event_type=EVENT_NEW_FEED_ITEM,
                event_data=event_data,
                origin=EventOrigin.remote,
            )

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

            # Get truly uncollected postcards (these work with sighting_from_postcard)
            new_postcards = await self.client.new_postcards()
            new_postcard_ids = set()
            for pc in new_postcards:
                pc_id = pc.get("id") if hasattr(pc, 'get') else None
                if pc_id:
                    new_postcard_ids.add(pc_id)
            LOGGER.info("Found %d truly new postcards", len(new_postcard_ids))

            # Use refresh_feed with explicit timestamp to get all recent items
            # This includes both new AND collected postcards
            since_time = datetime.now(timezone.utc) - timedelta(hours=24)
            feed = await self.client.refresh_feed(since=since_time)
            LOGGER.info("Feed fetched: %d items (since %s)", len(feed) if feed else 0, since_time.isoformat())

            if not feed:
                LOGGER.info("No new feed items since last check")

            await self._process_feed(feed, new_postcard_ids)

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

            # Get truly uncollected postcards - process these directly!
            new_postcards = await self.client.new_postcards()
            LOGGER.warning("Found %d new postcards from new_postcards()", len(new_postcards))

            # Log detailed info about each new postcard
            for pc in new_postcards:
                pc_id = pc.get("id") if hasattr(pc, 'get') else "unknown"
                pc_data = dict(pc.data) if hasattr(pc, 'data') else {}
                LOGGER.warning("New postcard %s - all data keys: %s", pc_id, list(pc_data.keys()))
                LOGGER.warning("New postcard %s - full data: %s", pc_id, pc_data)

            # Process new_postcards directly (they are the source of truth)
            new_postcard_ids = set()
            new_postcard_map = {}
            for pc in new_postcards:
                pc_id = pc.get("id") if hasattr(pc, 'get') else None
                if pc_id:
                    new_postcard_ids.add(pc_id)
                    new_postcard_map[pc_id] = pc  # Keep reference to FeedNode

            # Also get refresh_feed for collected postcards (these have media)
            since_time = datetime.now(timezone.utc) - timedelta(hours=24)
            feed = await self.client.refresh_feed(since=since_time)
            LOGGER.warning("refresh_feed returned: %d items", len(feed) if feed else 0)

            # Combine: use new_postcards as primary, add any collected from feed
            combined_feed = list(new_postcards)  # Start with new postcards
            feed_ids = set(pc.get("id") if hasattr(pc, 'get') else None for pc in new_postcards)

            # Add items from refresh_feed that aren't already included
            if feed:
                for item in feed:
                    item_id = item.get("id") if hasattr(item, 'get') else None
                    if item_id and item_id not in feed_ids:
                        combined_feed.append(item)
                        feed_ids.add(item_id)

            LOGGER.warning("Combined feed: %d total items", len(combined_feed))
            await self._process_feed(combined_feed, new_postcard_ids)

            # Update timestamp
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
