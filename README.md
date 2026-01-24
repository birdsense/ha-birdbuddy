# Bird Buddy Home Assistant Integration (Feed-Only Version)

**This is a stripped-down version of the original Bird Buddy integration that focuses solely on feed monitoring and event triggering.**

## 🔥 Key Features

- ✅ **Feed monitoring**: Fetches Bird Buddy feed every 10 minutes
- ✅ **Duplicate prevention**: Persistent storage prevents processing the same items twice
- ✅ **Event triggering**: Fires `birdbuddy_new_feed_item` events for new feed items
- ✅ **Minimal footprint**: No sensors, devices, or complex entities
- ✅ **Reliable**: Avoids postcard processing issues that affect the full integration

## 🎯 What This Version Does

This stripped integration focuses on one thing: **getting feed data and triggering events**. 

When a new item appears in your Bird Buddy feed, it fires a Home Assistant event containing:
- Item ID and type (e.g., `FeedItemNewPostcard`, `FeedItemCollectedPostcard`)
- Creation timestamp
- Complete feed item data (including media URLs, species info, etc.)

You can then use these events in automations to:
- Send notifications
- Download images/videos
- Trigger other integrations
- Process data however you want

## 🚫 What This Version Doesn't Do

- ❌ No sensor entities (battery, signal, etc.)
- ❌ No device entities or controls
- ❌ No media browser integration
- ❌ No postcard collection services
- ❌ No firmware update handling

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

## Events

### `birdbuddy_new_feed_item`

This event is fired for **every new feed item**, regardless of type.

**Event Data Structure:**
```json
{
  "item_id": "7f9e310f-53ce-4f94-ab6b-460c5c93d78f",
  "item_data": { /* complete feed item data */ },
  "created_at": "2026-01-24T07:27:38.416Z",
  "type": "FeedItemNewPostcard"
}
```

**Common Item Types:**
- `FeedItemNewPostcard`: New postcard waiting to be processed
- `FeedItemCollectedPostcard`: Postcard that has been collected
- `FeedItemFeederInvitationAccepted`: Feeder invitation accepted
- `FeedItemSpeciesUnlocked`: New species unlocked

## Example Automations

### Basic Notification

```yaml
automation:
  - alias: "Bird Buddy - New Feed Item"
    description: "Notifies when new Bird Buddy feed item is detected"
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    action:
      - service: notify.notify
        data:
          message: "New Bird Buddy feed item: {{ trigger.event.data.item_id }} ({{ trigger.event.data.type }})"
          title: "Bird Buddy Feed Update"
      - service: logbook.log
        data:
          name: "Bird Buddy Feed"
          message: "Item {{ trigger.event.data.item_id }}: {{ trigger.event.data.type }} at {{ trigger.event.data.created_at }}"
```

### Download New Postcard Images

```yaml
automation:
  - alias: "Bird Buddy - Download Postcard Images"
    description: "Downloads images from new postcards"
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.type == 'FeedItemNewPostcard' }}"
    action:
      - service: downloader.download_file
        data:
          url: "{{ trigger.event.data.item_data.medias[0].contentUrl }}"
          filename: "/config/www/birdbuddy/{{ trigger.event.data.item_id }}.jpg"
          overwrite: true
```

### Process Specific Bird Types

```yaml
automation:
  - alias: "Bird Buddy - Special Bird Detected"
    description: "Special handling for specific bird species"
    trigger:
      - platform: event
        event_type: birdbuddy_new_feed_item
    condition:
      - condition: template
        value_template: >-
          {{ trigger.event.data.type == 'FeedItemCollectedPostcard' 
             and 'Great Tit' in (trigger.event.data.item_data.species | map(attribute='name') | list) }}
    action:
      - service: notify.mobile_app
        data:
          message: "Great Tit detected! Check your Bird Buddy app."
          title: "Special Bird Alert"
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
| Sensor Entities | ✅ | ❌ |
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