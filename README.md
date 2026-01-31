# Bird Buddy Home Assistant Integration (Feed-Only Version)

**This is a stripped-down version of the original Bird Buddy integration that focuses solely on feed monitoring and event triggering.**

## 🔥 Key Features

- ✅ **Feed monitoring**: Fetches Bird Buddy feed (configurable 1-20 min interval)
- ✅ **Direct media access**: Gets image URLs directly without needing Bird Buddy app
- ✅ **Smart image selection**: Automatically picks sharpest image from burst mode
- ✅ **Duplicate prevention**: Persistent storage prevents processing the same items twice
- ✅ **Event triggering**: Fires `birdbuddy_new_feed_item` events with media URLs
- ✅ **Minimal footprint**: Basic status entities only, no complex device management

## 🎯 What This Version Does

This integration focuses on one thing: **getting bird photos and triggering events automatically**.

When a bird visits your feeder, it fires a Home Assistant event containing:
- Direct image URLs (no need to open Bird Buddy app!)
- Automatic selection of the sharpest image from burst mode
- All burst images available for advanced use
- Item metadata (ID, type, timestamp)

You can then use these events in automations to:
- Send notifications with bird photos
- Download images automatically
- Process with local AI for species identification
- Trigger other integrations

## 🚫 What This Version Doesn't Do

- ❌ No device entities or controls (no feeder management)
- ❌ No media browser integration  
- ❌ No postcard collection services
- ❌ No firmware update handling
- ❌ No battery/signal/full device sensors (only basic feed status)

## Installation

### With HACS

1. Open HACS Settings and add this repository as a Custom Repository
2. Use **Integration** as the category
3. Click `Install`
4. Restart Home Assistant
5. Continue to Setup

### Manual

Copy the `birdbuddy` directory from `custom_components` in this repository,
and place inside your Home Assistant Core installation's `custom_components` directory.

## Setup

1. Install this integration
2. Navigate to **Settings** → **Devices & Services**
3. Click **+ Add Integration**
4. Search for `Bird Buddy`
5. Enter your Bird Buddy email and password
6. The integration will start monitoring your feed immediately

> **Note**: If your BirdBuddy account was created using SSO (Google, Facebook, etc), you'll need to create a password-based account or use the member account workaround described in the original documentation.

## Basic Status Entities

The integration provides 3 minimal entities to monitor status:

### **Feed Status** Sensor
- Shows "OK (X items processed)" or "Error"
- Attributes: last update time, total processed items, update interval
- Entity ID: `sensor.bird_buddy_feed_feed_status`

### **Last Sync** Sensor  
- Timestamp of last successful feed synchronization
- Device Class: Timestamp (can be used directly in automations)
- Entity ID: `sensor.bird_buddy_feed_last_sync`

### **Connection** Binary Sensor
- Shows online/offline status of the integration
- Device Class: Connectivity
- Entity ID: `binary_sensor.bird_buddy_feed_connection`

These entities provide quick verification that the integration is working and processing feed data correctly.

**Note**: The integration does NOT collect or process postcards - it only monitors the feed for new items and triggers events. All postcard processing must be handled manually through the Bird Buddy app or custom automations using the event data.

## Events

### `birdbuddy_new_feed_item`

This event is fired for **every new feed item**, regardless of type.

**Event Data Structure:**
```yaml
event_data:
  item_id: "7f9e310f-53ce-4f94-ab6b-460c5c93d78f"
  type: "FeedItemNewPostcard"
  created_at: "2026-01-24T07:27:38.416Z"

  # Easy access to best media (last image from burst = sharpest)
  has_media: true
  media_count: 4
  media_url: "https://media.app-api-graphql..."      # Best quality image URL
  thumbnail_url: "https://media.app-api-graphql..."  # Thumbnail of best image

  # All media for advanced use (index 0 = first/blurry, index -1 = last/sharp)
  all_media_urls: ["https://...", "https://...", ...]
  all_thumbnail_urls: ["https://...", "https://...", ...]
```

**Common Item Types:**
- `FeedItemNewPostcard`: New postcard detected (contains images from bird visit)
- `FeedItemCollectedPostcard`: Postcard already collected in Bird Buddy app
- `FeedItemFeederInvitationAccepted`: Feeder invitation accepted
- `FeedItemSpeciesUnlocked`: New species unlocked

**Media Note**: Bird Buddy captures multiple images in burst mode. The first image is often blurry while later ones are sharper. The `media_url` field automatically selects the last (sharpest) image. Use `all_media_urls` if you want to access all images.

## Example Automations

### Basic Notification with Image

```yaml
automation:
  - alias: "Bird Buddy - New Bird Notification"
    description: "Sends notification with bird image when detected"
    mode: parallel
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.has_media }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Vogel gespot!"
          message: "{{ trigger.event.data.media_count }} foto's gemaakt"
          data:
            image: "{{ trigger.event.data.media_url }}"
```

### Download Best Image

```yaml
automation:
  - alias: "Bird Buddy - Download Images"
    description: "Downloads the sharpest image from each bird visit"
    mode: parallel
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.has_media }}"
    action:
      - service: downloader.download_file
        data:
          url: "{{ trigger.event.data.media_url }}"
          filename: "/config/www/birdbuddy/{{ trigger.event.data.item_id }}.jpg"
          overwrite: true
```

### Download All Images from Burst

```yaml
automation:
  - alias: "Bird Buddy - Download All Burst Images"
    description: "Downloads all images from burst mode"
    mode: parallel
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.has_media }}"
    action:
      - repeat:
          count: "{{ trigger.event.data.media_count }}"
          sequence:
            - service: downloader.download_file
              data:
                url: "{{ trigger.event.data.all_media_urls[repeat.index - 1] }}"
                filename: "/config/www/birdbuddy/{{ trigger.event.data.item_id }}_{{ repeat.index }}.jpg"
```

### Log All Bird Visits

```yaml
automation:
  - alias: "Bird Buddy - Log Visit"
    description: "Logs all bird visits to logbook"
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    action:
      - service: logbook.log
        data:
          name: "Bird Buddy"
          message: >-
            {{ trigger.event.data.type }} -
            {{ trigger.event.data.media_count }} photos
            {% if trigger.event.data.has_media %}({{ trigger.event.data.media_url }}){% endif %}
```

## Feed Storage & Deduplication

The integration maintains a persistent list of processed item IDs in your Home Assistant configuration. This ensures:

- No duplicate events for the same feed item
- Survives Home Assistant restarts
- Handles connection issues gracefully
- Prevents event flooding during reconnections

## Troubleshooting

**No events being triggered?**
1. Check the Home Assistant logs for any errors
2. Verify your Bird Buddy credentials are correct
3. Ensure you have recent activity in your Bird Buddy feed
4. Check that the integration is running (look for it in Settings → Devices & Services)

**Events stopped working after restart?**
The integration maintains feed state across restarts, so you shouldn't see duplicate events. If no new events appear, check if there are actually new items in your Bird Buddy feed.

## Difference from Original Integration

| Feature | Original Integration | This Feed-Only Version |
|---------|---------------------|------------------------|
| Feed Monitoring | ✅ | ✅ |
| Event Triggering | ✅ (postcard only) | ✅ (all feed items) |
| Sensor Entities | ✅ (full device sensors) | ✅ (basic status only) |
| Device Controls | ✅ | ❌ |
| Media Browser | ✅ | ❌ |
| Postcard Services | ✅ | ❌ |
| Complexity | High | Low |
| Failure Points | Many | Minimal |

## Contributing

This is a simplified fork focused on reliability. For feature requests or issues related to the full Bird Buddy integration, please refer to the original repository.

---

**Original integration**: [jhansche/ha-birdbuddy](https://github.com/jhansche/ha-birdbuddy)  
**Library**: [pybirdbuddy](https://github.com/jhansche/pybirdbuddy)