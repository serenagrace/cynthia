"""Default environment, bot configuration, context, and permission values."""


class Defaults:
    """Container for default configuration and permission mappings."""

    env = {"DISCORD_BOT_TOKEN": None, "OTP_SECRET": None}
    config = {
        "silent": False,
        "debug": False,
        "owner": None,
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
