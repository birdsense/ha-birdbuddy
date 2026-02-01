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

from .const import (
    DOMAIN,
    EVENT_NEW_FEED_ITEM,
    LOGGER,
    POLLING_INTERVAL,
    CONF_LAST_FEED_ITEM_IDS,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
)

# Custom GraphQL query to get postcards with medias
# pybirdbuddy doesn't request the medias field, but it exists!
# FeedItemNewPostcard HAS a medias field, pybirdbuddy just doesn't request it!
# Media is an interface - all fields must be queried via inline fragments
# contentUrl requires size argument (MediaImageSize enum)
FEED_WITH_MEDIAS_QUERY = """
query GetFeedWithMedias {
    me {
        feed(first: 50) {
            edges {
                node {
                    ... on FeedItemNewPostcard {
                        id
                        createdAt
                        __typename
                        medias {
                            ... on MediaImage {
                                id
                                thumbnailUrl
                                contentUrl(size: ORIGINAL)
                            }
                            ... on MediaVideo {
                                id
                                thumbnailUrl
                            }
                        }
                    }
                    ... on FeedItemCollectedPostcard {
                        id
                        createdAt
                        __typename
                        medias {
                            ... on MediaImage {
                                id
                                thumbnailUrl
                                contentUrl(size: ORIGINAL)
                            }
                            ... on MediaVideo {
                                id
                                thumbnailUrl
                            }
                        }
                    }
                }
            }
        }
    }
}
"""


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
        
        # Get polling interval from config entry options, with fallback to defaults
        polling_minutes = (
            entry.options.get(CONF_POLLING_INTERVAL)
            or entry.data.get(CONF_POLLING_INTERVAL)
            or DEFAULT_POLLING_INTERVAL
        )
        
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=polling_minutes),
        )

    async def _fetch_feed_with_postcard_media(self, max_retries: int = 3) -> dict:
        """Fetch feed with postcard media using custom GraphQL query.

        Returns a dict mapping feed item ID to its media data.
        Retries on temporary errors (502, 503, 504).
        """
        import asyncio
        media_map = {}

        for attempt in range(max_retries):
            try:
                result = await self.client._make_request(
                    query=FEED_WITH_MEDIAS_QUERY,
                )

                # Debug: log raw result structure
                if result:
                    LOGGER.warning("CUSTOM_QUERY raw keys: %s", list(result.keys()))
                    if "me" in result:
                        LOGGER.warning("CUSTOM_QUERY me keys: %s", list(result["me"].keys()) if result["me"] else "None")
                    if "errors" in result:
                        LOGGER.warning("CUSTOM_QUERY errors: %s", result["errors"])
                else:
                    LOGGER.warning("CUSTOM_QUERY returned None/empty")

                if result and "me" in result and "feed" in result["me"]:
                    edges = result["me"]["feed"].get("edges", [])
                    LOGGER.warning("CUSTOM_QUERY: %d edges in feed", len(edges))

                    # Debug first few edges
                    for i, edge in enumerate(edges[:3]):
                        node = edge.get("node", {})
                        LOGGER.warning("CUSTOM_QUERY edge %d: typename=%s, id=%s, medias=%s",
                                       i, node.get("__typename"), node.get("id"),
                                       len(node.get("medias", [])) if node.get("medias") else "None")

                    for edge in edges:
                        node = edge.get("node", {})
                        item_id = node.get("id")
                        if not item_id:
                            continue

                        medias = node.get("medias", [])
                        if medias:
                            media_map[item_id] = {"medias": medias}

                    LOGGER.warning("CUSTOM_QUERY: media_map has %d items with media", len(media_map))
                    return media_map  # Success, return immediately

            except Exception as exc:
                error_str = str(exc)
                is_temporary = any(code in error_str for code in ["502", "503", "504"])

                if is_temporary and attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    LOGGER.warning("Temporary API error (attempt %d/%d), retrying in %ds: %s",
                                  attempt + 1, max_retries, wait_time, exc)
                    await asyncio.sleep(wait_time)
                else:
                    LOGGER.warning("CUSTOM_QUERY failed: %s", exc)
                    break

        return media_map

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
            LOGGER.debug("_process_feed: No feed items to process")
            return

        new_postcard_ids = new_postcard_ids or set()
        LOGGER.warning("PROCESS_FEED: %d feed items, %d truly new postcards",
                       len(feed), len(new_postcard_ids))

        # Fetch media data using our custom query (pybirdbuddy misses this)
        postcard_media_map = await self._fetch_feed_with_postcard_media()

        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()
        LOGGER.warning("PROCESS_FEED: %d already processed, media_map has %d",
                       len(processed_ids), len(postcard_media_map))
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

            LOGGER.warning("PROCESS_FEED: NEW item %s (type: %s), in_media_map: %s",
                          item_id, item_type, item_id in postcard_media_map)

            # Check if we already have media from the feed data
            has_medias = item_data.get("medias") and len(item_data.get("medias", [])) > 0

            # For items without media, fetch from our custom query
            # This works for both NewPostcard and CollectedPostcard
            if not has_medias and item_id in postcard_media_map:
                postcard_data = postcard_media_map[item_id]
                if postcard_data.get("medias"):
                    item_data["medias"] = postcard_data["medias"]
                    has_medias = True
                    LOGGER.warning("PROCESS_FEED: Got %d medias from custom query for %s",
                                   len(postcard_data["medias"]), item_id)

            if not has_medias:
                LOGGER.warning("No medias found for %s (in media_map: %s)",
                              item_id, item_id in postcard_media_map)

                # If custom query didn't get media and it's truly new, try sighting API
                if not item_data.get("medias") and item_id in new_postcard_ids:
                    LOGGER.debug("Trying sighting_from_postcard for: %s", item_id)
                    try:
                        sighting = await self.client.sighting_from_postcard(item)
                        if sighting:
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
                                LOGGER.debug("Added %d medias from sighting", len(medias))

                            # Auto-collect the postcard
                            try:
                                collected = await self.client.finish_postcard(
                                    feed_item_id=item_id,
                                    sighting_result=sighting,
                                )
                                LOGGER.debug("Auto-collected postcard %s: %s", item_id, collected)
                            except Exception as collect_exc:
                                LOGGER.debug("Failed to auto-collect %s: %s", item_id, collect_exc)
                    except Exception as exc:
                        LOGGER.debug("sighting_from_postcard failed for %s: %s", item_id, exc)

            # Build event data with easy-to-use media fields
            medias = item_data.get("medias", [])
            media_count = len(medias)

            # Pick the best image (last one is usually sharpest in burst mode)
            best_media = medias[-1] if medias else None
            media_url = best_media.get("contentUrl") if best_media else None
            thumbnail_url = best_media.get("thumbnailUrl") if best_media else None

            # Also collect all media URLs for flexibility
            all_media_urls = [m.get("contentUrl") for m in medias if m.get("contentUrl")]
            all_thumbnail_urls = [m.get("thumbnailUrl") for m in medias if m.get("thumbnailUrl")]

            event_data = {
                "item_id": item_id,
                "type": item_type,
                "created_at": created_at,
                # Easy access to best media (last image is usually sharpest)
                "media_url": media_url,
                "thumbnail_url": thumbnail_url,
                # Metadata
                "media_count": media_count,
                "has_media": media_count > 0,
                # All media for advanced use (index 0 = first/blurry, index -1 = last/sharp)
                "all_media_urls": all_media_urls,
                "all_thumbnail_urls": all_thumbnail_urls,
            }

            LOGGER.warning("FIRING_EVENT: %s, media_url=%s, count=%d",
                          item_id, media_url[:50] if media_url else "None", media_count)

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
                LOGGER.debug("Bird Buddy API temporarily unavailable: %s", exc)
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
        LOGGER.debug("Feed storage reset - cleared %d items, all will be processed as new", old_count)

    async def force_refresh_now(self) -> None:
        """Force immediate feed refresh and processing."""
        LOGGER.debug("=== FORCE REFRESH START ===")
        try:
            LOGGER.debug("Calling client.refresh()...")
            await self.client.refresh()
            LOGGER.debug("client.refresh() completed")

            # Get truly uncollected postcards - process these directly!
            LOGGER.debug("Calling client.new_postcards()...")
            new_postcards = await self.client.new_postcards()
            LOGGER.debug("new_postcards() returned %d items", len(new_postcards) if new_postcards else 0)

            # Log detailed info about each new postcard
            for pc in new_postcards:
                pc_id = pc.get("id") if hasattr(pc, 'get') else "unknown"
                pc_data = dict(pc.data) if hasattr(pc, 'data') else {}
                LOGGER.debug("New postcard %s - all data keys: %s", pc_id, list(pc_data.keys()))
                LOGGER.debug("New postcard %s - full data: %s", pc_id, pc_data)

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
            LOGGER.debug("refresh_feed returned: %d items", len(feed) if feed else 0)

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

            LOGGER.debug("Combined feed: %d total items", len(combined_feed))
            await self._process_feed(combined_feed, new_postcard_ids)

            # Update timestamp
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
