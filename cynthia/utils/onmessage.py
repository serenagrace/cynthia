from pathlib import Path
import pickle

ONMESSAGE = {}


class OnMessage:
    async def default_condition(self, client, message):
        return True

    async def default_action(self, client, message):
        if self.logger is not None:
            self.logger.log_message(message)

    def __init__(
        self, logger=None, condition=None, action=None, channel=None, guild=None
    ):
        self.logger = logger
        self.channel = channel
        self.guild = guild
        self.condition = self.default_condition
        if condition is not None:
            self.condition = condition
        self.action = self.default_action
        if action is not None:
            self.action = action

    async def call(self, client, message):
        if self.channel is not None and message.channel.id != self.channel:
            return
        if self.guild is not None and message.guild.id != self.guild:
            return
        if await self.condition(client, message):
            await self.action(client, message)


def load_onmessage(path: Path):
    onmessage_path = path / "onmessage.pkl"
    if onmessage_path.exists() and onmessage_path.is_file():
        try:
            with open(onmessage_path, "rb") as f:
                _onmessage = pickle.load(f)
                for key, value in _onmessage.items():
                    if key not in ONMESSAGE.keys():
                        ONMESSAGE[key] = value
        except Exception as e:
            print(f"Error loading onmessage data: {e}")


def save_onmessage(drive_path: Path):
    onmessage_path = drive_path / "onmessage.pkl"
    pickle_data = None
    try:
        import dill

        dill.detect.trace(True)
        dill.detect.badobjects(ONMESSAGE)
        dill.detect.errors(ONMESSAGE)
        dill.dumps(ONMESSAGE)
        pickle_data = pickle.dumps(ONMESSAGE)
    except Exception as e:
        print(f"Error pickling onmessage data: {e}")
    else:
        with open(onmessage_path, "wb") as f:
            f.write(pickle_data)
