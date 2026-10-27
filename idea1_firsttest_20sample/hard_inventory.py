"""Static inventory gates for the conditional hard-history groups.

The helpers inspect native metadata only. They never create, clone, or mutate
simulator objects, and they deliberately report missing requirements instead
of treating an unavailable group as a failed mechanism.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


_REQUIREMENTS: dict[str, tuple[dict[str, Any], ...]] = {
    "H01": (
        {"object_type": "Mug", "min_count": 2, "capabilities": ("canFillWithLiquid",)},
        {"object_type": "CoffeeMachine", "min_count": 1, "capabilities": ()},
    ),
    "H02": (
        {"object_type": "Plate", "min_count": 2, "capabilities": ("pickupable", "receptacle")},
        {"object_type": "Apple", "min_count": 1, "capabilities": ("pickupable",)},
    ),
    "H03": (
        {"object_type": "StoveKnob", "min_count": 2, "capabilities": ("toggleable",)},
        {"object_type": "StoveBurner", "min_count": 2, "capabilities": ()},
        {"object_type": "Kettle", "min_count": 1, "capabilities": ("pickupable",)},
        {"object_type": "Pot", "min_count": 1, "capabilities": ("pickupable",)},
    ),
    "H04": (
        {"object_type": "Plate", "min_count": 1, "capabilities": ("pickupable", "receptacle")},
        {"object_type": "Bowl", "min_count": 1, "capabilities": ("pickupable", "receptacle")},
        {"object_type": "Apple", "min_count": 1, "capabilities": ("pickupable",)},
    ),
    "H05": (
        {"object_type": "Potato", "min_count": 1, "capabilities": ("pickupable", "cookable")},
        {"object_type": "Microwave", "min_count": 1, "capabilities": ("toggleable", "openable", "receptacle")},
    ),
}


def inventory_requirements(group_id: str) -> list[dict[str, Any]]:
    """Return serializable per-group native inventory requirements."""
    try:
        requirements = _REQUIREMENTS[group_id]
    except KeyError as exc:
        raise ValueError(f"Unknown hard group {group_id!r}; expected one of {sorted(_REQUIREMENTS)}") from exc
    return [{**row, "capabilities": list(row["capabilities"])} for row in requirements]


def check_inventory(group_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Check distinct native object instances and required capability flags."""
    objects = metadata.get("objects", []) if isinstance(metadata, dict) else []
    objects = [row for row in objects if isinstance(row, dict)] if isinstance(objects, list) else []
    counts = Counter(str(row.get("objectType")) for row in objects if row.get("objectType"))
    missing = []
    for requirement in inventory_requirements(group_id):
        object_type = requirement["object_type"]
        eligible_ids = {row.get("objectId") for row in objects
                        if row.get("objectType") == object_type and row.get("objectId")
                        and all(row.get(capability) is True for capability in requirement["capabilities"])}
        count = len(eligible_ids)
        if count < requirement["min_count"]:
            missing.append({**requirement, "available_count": count,
                            "native_type_count": counts.get(object_type, 0)})
    return {"satisfied": not missing, "missing": missing,
            "counts": dict(sorted(counts.items()))}
