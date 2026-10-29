import time

# Replace with your Discord application's Client ID.
# Find it in Developer Portal > Your Application > General Information.
# Upload matching asset keys under Developer Portal > Your Application >
# Rich Presence > Art Assets.
CLIENT_ID = "1370896076856496210"
CYNTHIA_HOSTNAME = "serenegrace.io"
CYNTHIA_PROTOCOL = "https://"
API_URL = f"{CYNTHIA_PROTOCOL}{CYNTHIA_HOSTNAME}/api/user_status"
FEED_URL = f"{CYNTHIA_PROTOCOL}{CYNTHIA_HOSTNAME}/video_feed"


def corrected_start(data):
    """Presence start (epoch ms) shifted forward by time the hunt was not running."""
    timestamps = data.get("timestamps") or {}
    start = timestamps.get("start", None)
    if start is None:
        return None
    return start + timestamps.get("correction", 0)


def build_presence(data):
    """Keyword arguments for RPC.update, or None when there is nothing to show.

    The activity type is returned as a string; main() maps it to ActivityType.
    """
    if not data or not data.get("name"):
        return None
    return {
        "activity_type": data.get("type", "playing"),
        "name": data["name"],
        "state": data.get("state", None),
        "state_url": FEED_URL,
        "details": data.get("details", None),
        "large_image": (data.get("assets") or {}).get("large_image", None),
        "large_url": FEED_URL,
        "start": corrected_start(data),
    }


def main():
    import requests
    from pypresence import Presence
    from pypresence.types import ActivityType

    RPC = Presence(CLIENT_ID)  # Initialize the client
    RPC.connect()  # Connect to the Discord desktop client

    print("Rich Presence is active! Press Ctrl+C to exit.")

    activity_types = {
        "playing": ActivityType.PLAYING,
        "listening": ActivityType.LISTENING,
        "watching": ActivityType.WATCHING,
        "competing": ActivityType.COMPETING,
    }
    data = None
    # Keep the program running so the presence stays active
    while True:
        count = 5
        new_data = None
        try:
            new_data = requests.get(API_URL).json()
            # Update your presence
            if new_data is not None:
                if new_data != data:
                    data = new_data
                    count = 0
                if not count:
                    count = 4
                    presence = build_presence(data)
                    if presence is not None:
                        presence["activity_type"] = activity_types[
                            presence["activity_type"]
                        ]
                        RPC.update(**presence)
                else:
                    count -= 1
        except:
            pass
        time.sleep(3)


if __name__ == "__main__":
    main()
