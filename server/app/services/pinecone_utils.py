from __future__ import annotations

from typing import Any, Iterable, Set


def extract_index_names(response: object) -> Set[str]:
    """
    Normalizes the different return shapes from pinecone.list_indexes() into a set of names.
    """
    names: Set[str] = set()

    if response is None:
        return names

    if hasattr(response, "names"):
        try:
            iterable = response.names()
            for item in iterable:
                if item:
                    names.add(str(item))
            return names
        except TypeError:
            pass

    iterable: Iterable[Any] | None
    if hasattr(response, "indexes"):
        iterable = getattr(response, "indexes")
    elif isinstance(response, dict) and "indexes" in response:
        iterable = response["indexes"]
    elif isinstance(response, (list, tuple, set)):
        iterable = response
    else:
        iterable = None

    if iterable is None:
        return names

    for item in iterable:
        if not item:
            continue
        if isinstance(item, str):
            names.add(item)
            continue
        name = getattr(item, "name", None)
        if name:
            names.add(str(name))
            continue
        if isinstance(item, dict):
            dict_name = item.get("name")
            if dict_name:
                names.add(str(dict_name))

    return names

