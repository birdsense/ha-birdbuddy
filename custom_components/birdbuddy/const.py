"""Constants for the Bird Buddy integration."""

from datetime import timedelta
import logging

DOMAIN = "birdbuddy"
LOGGER = logging.getLogger(__package__)
MANUFACTURER = "Bird Buddy, Inc."

# Default polling interval.
POLLING_INTERVAL = timedelta(minutes=10)

# Events
EVENT_NEW_FEED_ITEM = f"{DOMAIN}_new_feed_item"

# Config entry keys
CONF_LAST_FEED_ITEM_IDS = "last_feed_item_ids"
