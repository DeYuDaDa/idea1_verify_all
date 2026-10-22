"""Resolve source and destination for an evaluated AI2-THOR PutObject event.

AI2-THOR's native ``PutObject`` call puts the held object into ``kwargs.objectId``;
the source is the sole object in the pre-event agent inventory. A legacy fixture
format is also accepted when it explicitly stores the source in ``objectId`` and
the destination in ``receptacleObjectId``. For that fixture format, an available
inventory must agree with the explicit source. If inventory is absent, the two
explicit legacy fields are sufficient. We intentionally do not infer a source
from action-target aliases or scene gold metadata.
"""

from collections.abc import Mapping
from typing import Any


def _object_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _inventory_ids(record: Mapping[str, Any]) -> tuple[bool, list[str] | None]:
    """Return whether inventory is present and its unambiguous object IDs."""
    before = record.get("before_metadata")
    if not isinstance(before, Mapping):
        return False, None

    if "inventoryObjects" in before:
        inventory = before.get("inventoryObjects")
    else:
        agent = before.get("agent")
        if not isinstance(agent, Mapping) or "inventoryObjects" not in agent:
            return False, None
        inventory = agent.get("inventoryObjects")

    if not isinstance(inventory, (list, tuple)):
        return True, None
    ids: list[str] = []
    for item in inventory:
        if not isinstance(item, Mapping):
            return True, None
        item_id = _object_id(item.get("objectId"))
        if item_id is None:
            return True, None
        ids.append(item_id)
    return True, ids


def put_binding(record: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return ``(held_source_id, destination_id)`` for a valid PutObject.

    The native form requires exactly one pre-event inventory object and treats
    ``kwargs.objectId`` as the destination. The legacy fixture form has an
    explicit ``kwargs.receptacleObjectId`` destination and treats
    ``kwargs.objectId`` as the source; if inventory is recorded, it must contain
    exactly that source. Invalid, ambiguous, missing, or self-targeting bindings
    return ``None``.
    """
    if not isinstance(record, Mapping) or not isinstance(event, Mapping):
        return None
    if event.get("action") != "PutObject":
        return None
    kwargs = event.get("kwargs")
    if not isinstance(kwargs, Mapping):
        return None

    inventory_present, inventory_ids = _inventory_ids(record)
    object_arg = _object_id(kwargs.get("objectId"))
    legacy_destination = _object_id(kwargs.get("receptacleObjectId"))

    if legacy_destination is not None:
        # Legacy fixture encoding: objectId names the source, the separate
        # receptacleObjectId names the destination.
        source = object_arg
        destination = legacy_destination
        if source is None:
            return None
        if inventory_present:
            if inventory_ids is None or len(inventory_ids) != 1 or inventory_ids[0] != source:
                return None
    else:
        # Native AI2-THOR encoding: objectId names the destination; the held
        # source can only be read from the pre-event inventory.
        if not inventory_present or inventory_ids is None or len(inventory_ids) != 1:
            return None
        source = inventory_ids[0]
        destination = object_arg

    if destination is None or source == destination:
        return None
    return source, destination


def destination_contrast(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    event_a: Mapping[str, Any],
    event_b: Mapping[str, Any],
) -> bool:
    """Return true only when both PutObject calls move the same source to
    different destinations.
    """
    binding_a = put_binding(a, event_a)
    binding_b = put_binding(b, event_b)
    return bool(
        binding_a is not None
        and binding_b is not None
        and binding_a[0] == binding_b[0]
        and binding_a[1] != binding_b[1]
    )
