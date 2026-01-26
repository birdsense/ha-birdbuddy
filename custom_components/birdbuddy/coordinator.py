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

# GraphQL introspection query to discover FeedItemNewPostcard fields
INTROSPECT_NEW_POSTCARD_QUERY = """
query IntrospectNewPostcard {
    __type(name: "FeedItemNewPostcard") {
        name
        fields {
            name
            type {
                name
                kind
                ofType {
                    name
                    kind
                }
            }
        }
    }
}
"""

# GraphQL introspection query to discover MediaImageSize enum values
INTROSPECT_MEDIA_IMAGE_SIZE_QUERY = """
query IntrospectMediaImageSize {
    __type(name: "MediaImageSize") {
        name
        enumValues {
            name
        }
    }
}
"""

# Custom GraphQL query to get postcards with medias
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
                        mediaSpeciesAssignedName {
                            name
                        }
                        sightingReportPreview {
                            species {
                                name
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
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=POLLING_INTERVAL,
        )

    async def _fetch_feed_with_postcard_media(self) -> dict:
        """Fetch feed with postcard media using custom GraphQL query.

        Returns a dict mapping feed item ID to its media data.
        """
        media_map = {}

        # First, introspect the schema to see what fields are available
        try:
            LOGGER.warning("Introspecting FeedItemNewPostcard schema...")
            schema_result = await self.client._make_request(
                query=INTROSPECT_NEW_POSTCARD_QUERY,
            )
            if schema_result and "__type" in schema_result:
                fields = schema_result["__type"].get("fields", [])
                field_names = [f["name"] for f in fields]
                LOGGER.warning("FeedItemNewPostcard has fields: %s", field_names)
        except Exception as exc:
            LOGGER.warning("Schema introspection failed: %s", exc)

        # Introspect MediaImageSize enum to see valid values
        try:
            enum_result = await self.client._make_request(
                query=INTROSPECT_MEDIA_IMAGE_SIZE_QUERY,
            )
            if enum_result and "__type" in enum_result:
                enum_values = enum_result["__type"].get("enumValues", [])
                value_names = [v["name"] for v in enum_values]
                LOGGER.warning("MediaImageSize enum values: %s", value_names)
        except Exception as exc:
            LOGGER.warning("MediaImageSize introspection failed: %s", exc)

        # Now try to fetch feed with media fields
        try:
            LOGGER.warning("Fetching feed with all fields via custom query")
            result = await self.client._make_request(
                query=FEED_WITH_MEDIAS_QUERY,
            )
            LOGGER.warning("Custom feed query result: %s", result)

            if result and "me" in result and "feed" in result["me"]:
                edges = result["me"]["feed"].get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    item_id = node.get("id")
                    if not item_id:
                        continue

                    # Extract media and species info
                    if node.get("medias"):
                        item_data = {"medias": node["medias"]}
                        # Also get species name if available
                        if node.get("mediaSpeciesAssignedName"):
                            item_data["speciesName"] = node["mediaSpeciesAssignedName"].get("name")
                        if node.get("sightingReportPreview") and node["sightingReportPreview"].get("species"):
                            item_data["species"] = node["sightingReportPreview"]["species"]
                        media_map[item_id] = item_data
                        LOGGER.warning("Found %d medias for %s (species: %s)",
                                      len(node["medias"]), item_id,
                                      item_data.get("speciesName", "unknown"))

            LOGGER.warning("Media map has %d items with media", len(media_map))
        except Exception as exc:
            LOGGER.warning("Failed to fetch feed with media: %s", exc)

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
            LOGGER.warning("_process_feed: No feed items to process")
            return

        new_postcard_ids = new_postcard_ids or set()
        LOGGER.warning("_process_feed: Processing %d feed items, %d are truly new postcards",
                      len(feed), len(new_postcard_ids))

        # Fetch media data using our custom query (pybirdbuddy misses this)
        postcard_media_map = await self._fetch_feed_with_postcard_media()

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

            # For NewPostcard items without media, try to fetch media
            if item_type == "FeedItemNewPostcard" and not has_medias:
                # First check if our custom query got media for this item
                if item_id in postcard_media_map:
                    postcard_data = postcard_media_map[item_id]
                    medias = []
                    if postcard_data.get("coverMedia"):
                        cover = postcard_data["coverMedia"]
                        medias.append({
                            "id": cover.get("id"),
                            "contentUrl": cover.get("contentUrl"),
                            "thumbnailUrl": cover.get("thumbnailUrl"),
                            "__typename": "MediaImage",
                        })
                    if postcard_data.get("medias"):
                        for media in postcard_data["medias"]:
                            medias.append({
                                "id": media.get("id"),
                                "contentUrl": media.get("contentUrl"),
                                "thumbnailUrl": media.get("thumbnailUrl"),
                                "__typename": "MediaImage",
                            })
                    if medias:
                        item_data["medias"] = medias
                        LOGGER.warning("Got %d medias from custom postcard query", len(medias))

                # If custom query didn't get media and it's truly new, try sighting API
                if not item_data.get("medias") and item_id in new_postcard_ids:
                    LOGGER.warning("Trying sighting_from_postcard for: %s", item_id)
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
                                LOGGER.warning("Added %d medias from sighting", len(medias))

                            # Auto-collect the postcard
                            try:
                                collected = await self.client.finish_postcard(
                                    feed_item_id=item_id,
                                    sighting_result=sighting,
                                )
                                LOGGER.warning("Auto-collected postcard %s: %s", item_id, collected)
                            except Exception as collect_exc:
                                LOGGER.warning("Failed to auto-collect %s: %s", item_id, collect_exc)
                    except Exception as exc:
                        LOGGER.warning("sighting_from_postcard failed for %s: %s", item_id, exc)

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
        LOGGER.warning("=== FORCE REFRESH START ===")
        try:
            LOGGER.warning("Calling client.refresh()...")
            await self.client.refresh()
            LOGGER.warning("client.refresh() completed")

            # Get truly uncollected postcards - process these directly!
            LOGGER.warning("Calling client.new_postcards()...")
            new_postcards = await self.client.new_postcards()
            LOGGER.warning("new_postcards() returned %d items", len(new_postcards) if new_postcards else 0)

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
