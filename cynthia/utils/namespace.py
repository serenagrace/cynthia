"""Mapping wrapper that exposes string keys through attribute access."""

from cynthia.utils.types import force_obj_is_list

UNSPECIFIED = object()

INFRA_MEMBERS = (
    "_nspace_dict",
    "__dict__",
    "__repr__",
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
    "__delitem__",
    "__contains__",
    "__iter__",
    "__len__",
)


class Namespace:
    """Store mapping entries with attribute and item access."""

    def __init__(self, _dict=None):
        """Initialize the namespace from an optional mapping."""
        if _dict is None:
            _dict = {}

        self._nspace_dict = {}
        for k, v in _dict.items():
            if isinstance(k, str):
                k = k.replace(" ", "_")
            self._nspace_dict[k] = v

    def __repr__(self):
        """Return a constructor-like representation of the namespace."""
        type_name = type(self).__name__
        arg_strings = []
        for name, value in self.items():
            arg_strings.append("%s=%s" % (name, value))
        return "%s(%s)" % (type_name, ", ".join(arg_strings))

    def __setattr__(self, attr, val):
        """Set an attribute as a mapping key unless reserved by the class."""
        if attr in INFRA_MEMBERS:
            super().__setattr__(attr, val)
        elif attr in self.__dict__:
            raise KeyError(
                f"Specified key `{attr}` reserved by python or underlying class."
            )
        else:
            self._nspace_dict[attr] = val

    def __getattribute__(self, attr):
        """Resolve infrastructure attributes or look up a namespace key."""
        if attr in INFRA_MEMBERS:
            return super().__getattribute__(attr)
        elif attr in self.__dict__:
            return super().__getattribute__(attr)
        if attr not in self._nspace_dict.keys():
            print(f"Namespace key `{attr}` not found.")
            raise KeyError(f"Specified key `{attr}` not found in namespace.")
        return self._nspace_dict[attr]

    def get(self, attr, default):
        """Return a key's value or the supplied default."""
        return self._nspace_dict.get(attr, default)

    def set(self, attr, val):
        """Set a key's value."""
        self._nspace_dict[attr] = val

    def append(self, attr, val):
        """Append a value to a key's list, creating that list when needed."""
        self._nspace_dict[attr] = force_obj_is_list(self._nspace_dict.get(attr, None))
        self._nspace_dict[attr].append(val)

    def items(self):
        """Return the namespace's key-value pairs."""
        return self._nspace_dict.items()

    def values(self):
        """Return the namespace's values."""
        return self._nspace_dict.values()

    def keys(self):
        """Return the namespace's keys."""
        return self._nspace_dict.keys()

    def dict(self):
        """Return the backing mapping."""
        return self._nspace_dict

    def __setitem__(self, key, value):
        """Set a mapping item."""
        self._nspace_dict[key] = value

    def __getitem__(self, key):
        """Return a mapping item or raise KeyError when the key is absent."""
        if key not in self._nspace_dict:
            print(f"Namespace key `{key}` not found.")
            raise KeyError("Specified key `{key}` not found in namespace.")
        return self._nspace_dict[key]

    def __contains__(self, key):
        """Return whether a key exists in the namespace."""
        return key in self._nspace_dict

    def __len__(self):
        """Return the number of keys in the namespace."""
        return len(self._nspace_dict.keys())

    def __delitem__(self, key):
        """Delete a mapping item."""
        del self._nspace_dict[key]
