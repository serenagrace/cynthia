import re


class Snowflake:
    def __init__(self, *, flake_type: str = None, uid: str = None, euid: str = None):
        if bool(flake_type) ^ bool(uid):
            raise ValueError("Flake_type or uid must be provided together.")
        if flake_type and euid:
            raise ValueError(
                "Snowflakes must be initialized either with flake_type and uid or with euid, not both."
            )
        if flake_type:
            flake_type = flake_type.lower().strip()
            FLAKE_TYPES = ("user", "guild", "channel", "role")
            if not any(flake_type.startswith(ft) for ft in FLAKE_TYPES):
                if flake_type not in FLAKE_TYPES:
                    raise ValueError(
                        f"Invalid flake_type: {flake_type}. Must be one of {FLAKE_TYPES}."
                    )
            self.flake_type = flake_type.lower().strip()[0]
            self.uid = uid
            self.euid = f"{flake_type[0]}:{uid}"
        else:
            if not re.match(r"^[a-z]:[a-zA-Z0-9]+$", euid):
                raise ValueError(
                    "Invalid euid format. Must be in the format 'type:uid'."
                )
            flake_type, uid = euid.split(":")
            self.flake_type = flake_type.lower().strip()[0]
            self.uid = uid
            self.euid = euid

    def __str__(self):
        return self.euid

    def __repr__(self):
        return f"Snowflake(type='{self.flake_type}', uid='{self.uid}')"


class GuildFlake(Snowflake):
    def __init__(self, uid: str):
        if ":" in uid:
            uid = uid.split(":")[1]
        super().__init__(flake_type="guild", uid=uid)


class UserFlake(Snowflake):
    def __init__(self, uid: str):
        if ":" in uid:
            uid = uid.split(":")[1]
        super().__init__(flake_type="user", uid=uid)


class RoleFlake(Snowflake):
    def __init__(self, uid: str):
        if ":" in uid:
            uid = uid.split(":")[1]
        super().__init__(flake_type="role", uid=uid)


class ChannelFlake(Snowflake):
    def __init__(self, uid: str):
        if ":" in uid:
            uid = uid.split(":")[1]
        super().__init__(flake_type="channel", uid=uid)


class PermFlake:
    def __init__(self, *, flake_type: str = None, uid: str, allow: bool = None):
        if not flake_type:
            if ":" not in uid:
                raise ValueError(
                    "Invalid uid format. Must be in the format 'type:uid'."
                )
            flake_type, uid = uid.split(":")
        if allow is None:
            if any(flake_type.startswith(pchar) for pchar in ("+", "-")):
                allow = flake_type[0] == "+"
                flake_type = flake_type[1:]
            elif any(uid.startswith(pchar) for pchar in ("+", "-")):
                allow = uid[0] == "+"
                uid = uid[1:]
        self._snowflake = Snowflake(flake_type=flake_type, uid=uid)
        self.flake_type = self._snowflake.flake_type
        self.uid = self._snowflake.uid
        self.euid = self._snowflake.euid
        self.allow = allow

    def __str__(self):
        prefix = "+" if self.allow else "-"
        return str(prefix) + str(self._snowflake)

    def __repr__(self):
        return (
            f"PermFlake(type='{self.flake_type}', uid='{self.uid}', allow={self.allow})"
        )
