import logging
from pathlib import Path
import importlib
import multiprocessing

from .daemon import Daemon
from cynthia.utils.namespace import Namespace

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class DMan:

    def __init__(self):
        self.__modules = list()
        self.__loaded_modules = list()
        self.__loaded_daemons = Namespace()
        self.__previously_loaded_modules = list()
        self.load_daemons()

    def load_daemons(self):
        importlib.invalidate_caches()
        self.clear_daemons()

        self.__directory = Path(__file__).parent
        self.__modules = [
            module.stem
            for module in Path(__file__).parent.glob("*.py")
            if module.stem not in ["__init__", "dman", "daemon"]
        ]
        logger.debug(
            f"{len(self.modules)} daemon modules found in {self.daemon_directory}."
        )
        errors = []
        for module in self.modules:
            logger.debug(f"Loading daemons from module: {module} ...")
            daemons_module = None
            try:
                if module in self.__previously_loaded_modules:
                    daemons_module = importlib.reload_module(
                        "." + module, "cynthia.daemons"
                    )
                else:
                    daemons_module = importlib.import_module(
                        "." + module, "cynthia.daemons"
                    )
                self.__loaded_modules.append(module)
            except (ImportError, FileNotFoundError, ValueError, KeyError) as e:
                error = (
                    f" ERR.\n\tFailed to load daemon from module: {module}\n"
                    + f"\tError: {e}"
                )
                logger.error(error)
                errors += error
            if daemons_module is not None:
                public_objects = filter(
                    lambda key: not key.startswith("__"), dir(daemons_module)
                )
                daemons = filter(
                    lambda obj: isinstance(obj, type) and issubclass(obj, Daemon),
                    [getattr(daemons_module, key) for key in public_objects],
                )
                for daemon in daemons:
                    if daemon.__name__ in self.__loaded_daemons:
                        logger.warn(f'Duplicate daemon with name "{daemon.__name__}".')
                    self.__loaded_daemons[daemon.__name__] = daemon
                logger.debug("Done")
            else:
                logger.error(f" ERR.\n\tNo daemon found in module: {module}")
        return len(self.loaded_daemons), errors

    def clear_daemons(self):
        self.__previously_loaded_modules = getattr(self, "__loaded_modules", list())
        self.__loaded_modules = list()
        self.__loaded_daemons = Namespace()

        # TODO: Trigger Daemon __onexit__

    @property
    def modules(self):
        return self.__modules

    @property
    def loaded_modules(self):
        return self.__loaded_modules

    @property
    def daemon_directory(self):
        return self.__directory

    @property
    def loaded_daemons(self):
        return self.__loaded_daemons

    @property
    def daemons(self):
        return self.__loaded_daemons
