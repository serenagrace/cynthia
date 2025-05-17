UNSPECIFIED = object()


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
        if attr in ("_nspace_dict", "__dict__", "keys", "items", "values", "get"):
            return super().__getattribute__(attr)
        elif attr in self.__dict__:
            return super().__getattribute__(attr)
        if attr not in self._nspace_dict.keys():
            raise KeyError()
        return self._nspace_dict[attr]

    def get(self, attr, default):
        return self._nspace_dict.get(attr, default)

    def items(self):
        return self._nspace_dict.items()

    def values(self):
        return self._nspace_dict.values()

    def keys(self):
        return self._nspace_dict.keys()
