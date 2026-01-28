#!/usr/bin/env python3
"""Test script to verify polling interval configuration."""

import sys
import os

# Add the custom_components directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'custom_components'))

from birdbuddy.const import (
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    MAX_POLLING_INTERVAL,
)

def test_constants():
    """Test that constants are properly defined."""
    print("Testing polling interval constants...")
    
    assert CONF_POLLING_INTERVAL == "polling_interval"
    assert DEFAULT_POLLING_INTERVAL == 10
    assert MIN_POLLING_INTERVAL == 1
    assert MAX_POLLING_INTERVAL == 20
    
    print("✅ Constants test passed!")

def test_coordinator_initialization():
    """Test coordinator initialization with different polling intervals."""
    print("\nTesting coordinator initialization...")
    
    from unittest.mock import MagicMock
    from birdbuddy.coordinator import BirdBuddyDataUpdateCoordinator
    from datetime import timedelta
    
    # Mock HomeAssistant and ConfigEntry
    mock_hass = MagicMock()
    mock_client = MagicMock()
    
    # Test 1: Default polling interval
    mock_entry = MagicMock()
    mock_entry.options = {}
    mock_entry.data = {}
    
    coordinator = BirdBuddyDataUpdateCoordinator(mock_hass, mock_client, mock_entry)
    assert coordinator.update_interval == timedelta(minutes=10)
    print("✅ Default polling interval (10 minutes) works")
    
    # Test 2: Custom polling interval from options
    mock_entry.options = {CONF_POLLING_INTERVAL: 5}
    coordinator = BirdBuddyDataUpdateCoordinator(mock_hass, mock_client, mock_entry)
    assert coordinator.update_interval == timedelta(minutes=5)
    print("✅ Custom polling interval from options (5 minutes) works")
    
    # Test 3: Custom polling interval from data
    mock_entry.options = {}
    mock_entry.data = {CONF_POLLING_INTERVAL: 15}
    coordinator = BirdBuddyDataUpdateCoordinator(mock_hass, mock_client, mock_entry)
    assert coordinator.update_interval == timedelta(minutes=15)
    print("✅ Custom polling interval from data (15 minutes) works")
    
    # Test 4: Options take precedence over data
    mock_entry.options = {CONF_POLLING_INTERVAL: 3}
    mock_entry.data = {CONF_POLLING_INTERVAL: 12}
    coordinator = BirdBuddyDataUpdateCoordinator(mock_hass, mock_client, mock_entry)
    assert coordinator.update_interval == timedelta(minutes=3)
    print("✅ Options take precedence over data")
    
    print("✅ Coordinator initialization test passed!")

def test_options_flow_schema():
    """Test options flow schema validation."""
    print("\nTesting options flow schema...")
    
    import voluptuous as vol
    
    # This is the schema from our options flow
    schema = vol.Schema({
        vol.Required(
            CONF_POLLING_INTERVAL,
            default=DEFAULT_POLLING_INTERVAL
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_POLLING_INTERVAL, max=MAX_POLLING_INTERVAL)
        )
    })
    
    # Test valid values
    valid_values = [1, 5, 10, 15, 20]
    for value in valid_values:
        result = schema({CONF_POLLING_INTERVAL: value})
        assert result[CONF_POLLING_INTERVAL] == value
    print("✅ Valid polling intervals accepted")
    
    # Test invalid values
    invalid_values = [0, 21, -1, 100]
    for value in invalid_values:
        try:
            schema({CONF_POLLING_INTERVAL: value})
            assert False, f"Should have failed for value {value}"
        except vol.Invalid:
            pass  # Expected
    print("✅ Invalid polling intervals rejected")
    
    # Test default value
    result = schema({})
    assert result[CONF_POLLING_INTERVAL] == DEFAULT_POLLING_INTERVAL
    print("✅ Default polling interval used when not specified")
    
    print("✅ Options flow schema test passed!")

if __name__ == "__main__":
    try:
        test_constants()
        test_coordinator_initialization()
        test_options_flow_schema()
        print("\n🎉 All tests passed! Polling interval configuration is working correctly.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)