"""Default environment, bot configuration, context, and permission values."""


class Defaults:
    """Container for default configuration and permission mappings."""

    env = {
        "DISCORD_BOT_TOKEN": None,
        "OTP_SECRET": None,
        "DRIVE_PATH": None,
        "ELGATO_USB_ID": None,
        "SYNC_GUILD_ID": None,
        "STATUS_HOSTS": None,
    }
    config = {
        "silent": False,
        "debug": False,
        "owner": None,
        # restart the looping macro 5s after an encounter
        "encounter_reset": True,
        # systemd units checked by the /status command
        "status_services": ["cynthia.service"],
    }
    context = {}
    perms = {
        "privileged": [],
        "nxbt": [],
        "drive": [],
        "owners": [],
        "admins": [],
        "allowed_commands": [],
    }
