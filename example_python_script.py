# Python script to download Bird Buddy images
# Save this as: /config/python_scripts/birdbuddy_downloader.py

import requests
import os

def save_birdbuddy_image(url, filename, item_id):
    """Download and save Bird Buddy image."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'wb') as f:
            f.write(response.content)
        
        logger.info(f"Downloaded Bird Buddy image {item_id} to {filename}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to download Bird Buddy image {item_id}: {e}")
        return False