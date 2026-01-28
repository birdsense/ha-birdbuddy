"""Constants for the Bird Buddy integration."""

from datetime import timedelta
import logging

DOMAIN = "birdbuddy"
LOGGER = logging.getLogger(__package__)
MANUFACTURER = "Bird Buddy, Inc."

# Polling interval configuration
CONF_POLLING_INTERVAL = "polling_interval"
DEFAULT_POLLING_INTERVAL = 10  # minutes
MIN_POLLING_INTERVAL = 1       # minutes
MAX_POLLING_INTERVAL = 20      # minutes

# Default polling interval (used as fallback).
POLLING_INTERVAL = timedelta(minutes=DEFAULT_POLLING_INTERVAL)

# Events
EVENT_NEW_FEED_ITEM = f"{DOMAIN}_new_feed_item"

# Config entry keys
CONF_LAST_FEED_ITEM_IDS = "last_feed_item_ids"
CONF_RESET_FEED_STORAGE = "reset_feed_storage"

# Sensor types
SENSOR_FEED_STATUS = "feed_status"
SENSOR_LAST_SYNC = "last_sync"

# Binary sensor types
BINARY_SENSOR_CONNECTION = "connection"
