UNSPECIFIED = object()

from cynthia.utils.types import force_obj_is_list


class Namespace:
    def __init__(self, _dict=None):

        if _dict is None:
            _dict = {}

        self._nspace_dict = {}
        for k, v in _dict.items():
            self._nspace_dict[k] = v

    def __setattr__(self, attr, val):
        if attr in ("_nspace_dict", "__dict__", "keys", "items", "values"):
            super().__setattr__(attr, val)
        elif attr in self.__dict__:
            raise KeyError(
                f"Specified key `{attr}` reserved by python or underlying class."
            )
        else:
            self._nspace_dict[attr] = val

    def __getattribute__(self, attr):
        if attr in (
            "_nspace_dict",
            "__dict__",
            "keys",
            "items",
            "values",
            "get",
            "set",
        ):
            return super().__getattribute__(attr)
        elif attr in self.__dict__:
            return super().__getattribute__(attr)
        if attr not in self._nspace_dict.keys():
            raise KeyError()
        return self._nspace_dict[attr]

    def get(self, attr, default):
        return self._nspace_dict.get(attr, default)

    def set(self, attr, val):
        self._nspace_dict[attr] = val

    def append(self, attr, val):
        self._nspace_dict[attr] = force_obj_is_list(self._nspace_dict.get(attr, None))
        self._nspace_dict[attr].append(val)

    def items(self):
        return self._nspace_dict.items()

    def values(self):
        return self._nspace_dict.values()

    def keys(self):
        return self._nspace_dict.keys()
