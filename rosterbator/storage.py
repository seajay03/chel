from __future__ import annotations

"""Persistence layer for games and practice lobbies."""

import json
import pathlib
from typing import Dict, List

STORAGE_FILE = pathlib.Path(__file__).with_name("storage.json")


def load_storage() -> Dict[str, List]:
    """Load storage from :data:`STORAGE_FILE`.

    Returns a mapping with ``games`` and ``practices`` lists.
    """

    if STORAGE_FILE.exists():
        with STORAGE_FILE.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    else:
        data = {"games": [], "practices": []}
    return data


def save_storage(data: Dict[str, List]) -> None:
    """Persist *data* to :data:`STORAGE_FILE`."""

    with STORAGE_FILE.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
