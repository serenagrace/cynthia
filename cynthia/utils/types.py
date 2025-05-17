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
