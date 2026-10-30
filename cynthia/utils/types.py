"""
Miscellaneous type utilites.
"""


def force_obj_is_list(obj, dict_method="items") -> list:
    """
    Force object into list form
    """
    if obj is None:
        return []
    if isinstance(obj, dict):
        return list(getattr(obj, dict_method)())
    if type(obj) not in (tuple, list):
        return [obj]
    return obj


def force_obj_is_dict(obj) -> dict:
    """
    Force object into dict form
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if type(obj) in (tuple, list):
        return {i: v for i, v in enumerate(obj)}
    return {0: obj}
