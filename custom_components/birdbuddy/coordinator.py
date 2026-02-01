"""Data Update coordinator for Bird Buddy."""

from __future__ import annotations

from datetime import timedelta

from birdbuddy.client import BirdBuddy
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

    def _get_processed_item_ids(self) -> set[str]:
        """Get set of previously processed item IDs from config entry data."""
        return set(self.config_entry.data.get(CONF_LAST_FEED_ITEM_IDS, []))

    def _save_processed_item_ids(self, item_ids: set[str]) -> None:
        """Save processed item IDs to config entry data."""
        # Update config entry data with new item IDs
        new_data = dict(self.config_entry.data)
        new_data[CONF_LAST_FEED_ITEM_IDS] = list(item_ids)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

    async def _process_feed_from_custom_query(self) -> None:
        """Process feed items directly from custom query - the only reliable source of media."""
        # Get previously processed item IDs
        processed_ids = self._get_processed_item_ids()

        # Fetch feed with media using our custom query
        result = None
        try:
            result = await self.client._make_request(query=FEED_WITH_MEDIAS_QUERY)
        except Exception as exc:
            LOGGER.warning("Custom query failed: %s", exc)
            return

        if not result or "me" not in result or "feed" not in result["me"]:
            LOGGER.warning("Custom query returned invalid structure")
            return

        edges = result["me"]["feed"].get("edges", [])
        LOGGER.warning("FEED: Processing %d edges from custom query", len(edges))

        new_ids = set()

        for edge in edges:
            node = edge.get("node", {})
            if not node:
                continue

            item_id = node.get("id")
            item_type = node.get("__typename", "unknown")
            created_at = node.get("createdAt")
            medias = node.get("medias", [])

            if not item_id:
                continue

            new_ids.add(item_id)

            # Skip if already processed
            if item_id in processed_ids:
                continue

            # Get media URLs directly from the query result
            media_count = len(medias)

            # Debug: log what's in the medias
            if medias:
                LOGGER.warning("MEDIA_KEYS for %s: %s", item_id, list(medias[0].keys()))
                LOGGER.warning("FIRST_MEDIA for %s: %s", item_id, medias[0])

            best_media = medias[-1] if medias else None
            media_url = best_media.get("contentUrl") if best_media else None
            thumbnail_url = best_media.get("thumbnailUrl") if best_media else None

            all_media_urls = [m.get("contentUrl") for m in medias if m.get("contentUrl")]
            all_thumbnail_urls = [m.get("thumbnailUrl") for m in medias if m.get("thumbnailUrl")]

            event_data = {
                "item_id": item_id,
                "type": item_type,
                "created_at": created_at,
                "media_url": media_url,
                "thumbnail_url": thumbnail_url,
                "media_count": media_count,
                "has_media": media_count > 0,
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

            # Process feed directly from custom query - bypasses pybirdbuddy limitations
            await self._process_feed_from_custom_query()

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
            await self.client.refresh()
            await self._process_feed_from_custom_query()
            self.last_update_timestamp = dt_util.now()
        except Exception as exc:
            LOGGER.error("Force refresh failed: %s", exc)
