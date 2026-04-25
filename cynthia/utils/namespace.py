UNSPECIFIED = object()

from cynthia.utils.types import force_obj_is_list

INFRA_MEMBERS = (
    "_nspace_dict",
    "__dict__",
    "keys",
    "items",
    "values",
    "get",
    "set",
    "dict",
    "len",
    "append",
    "__setitem__",
    "__getitem__",
    "__contains__",
)


class Namespace:

    def __init__(self, _dict=None):

        if _dict is None:
            _dict = {}

        self._nspace_dict = {}
        for k, v in _dict.items():
            if isinstance(k, str):
                k = k.replace(" ", "_")
            self._nspace_dict[k] = v

    def __setattr__(self, attr, val):
        if attr in INFRA_MEMBERS:
            super().__setattr__(attr, val)
        elif attr in self.__dict__:
            raise KeyError(
                f"Specified key `{attr}` reserved by python or underlying class."
            )
        else:
            self._nspace_dict[attr] = val

    def __getattribute__(self, attr):
        if attr in INFRA_MEMBERS:
            return super().__getattribute__(attr)
        elif attr in self.__dict__:
            return super().__getattribute__(attr)
        if attr not in self._nspace_dict.keys():
            print(f"Namespace key `{attr}` not found.")
            raise KeyError(f"Specified key `{attr}` not found in namespace.")
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

    def dict(self):
        return self._nspace_dict

    def __setitem__(self, key, value):
        self._nspace_dict[key] = value

    def __getitem__(self, key):
        if key not in self._nspace_dict:
            print(f"Namespace key `{key}` not found.")
            raise KeyError("Specified key `{key}` not found in namespace.")
        return self._nspace_dict[key]

    def __contains__(self, key):
        return key in self._nspace_dict

    def __len__(self):
        return len(self._nspace_dict.keys())
