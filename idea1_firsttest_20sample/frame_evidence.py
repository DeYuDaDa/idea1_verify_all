"""Private capture diagnostics; object detection never certifies state readability.

This module reads a completed event only. It never moves the agent, advances
physics, changes a held object, or creates model-visible annotations.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any


def describe_frame(event: Any, metadata: Mapping, roles: Mapping[str, str], *,
                   stage: str, relative_path: str, png_sha256: str,
                   capture_action_index: int) -> dict:
    from interactions import Interactions

    frame = getattr(event, "frame", None)
    shape = getattr(frame, "shape", ())
    height, width = (int(shape[0]), int(shape[1])) if len(shape) >= 2 else (0, 0)
    objects = {obj.get("objectId"): obj for obj in metadata.get("objects", [])}
    detections = getattr(event, "instance_detections2D", None)
    masks = getattr(event, "instance_masks", None)
    entries = {}
    for alias, object_id in roles.items():
        obj = objects.get(object_id, {})
        bbox = None
        if isinstance(detections, Mapping):
            try:
                bbox = Interactions._bbox_from_detection(detections[object_id])
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        mask_pixels = None
        if isinstance(masks, Mapping):
            try:
                mask = masks[object_id]
                mask_pixels = len(mask.nonzero()[0])
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                pass
        area = None if bbox is None or not width or not height else (
            bbox["width"] * bbox["height"] / (width * height)
        )
        entries[alias] = {
            "object_id": object_id,
            "asset_id": obj.get("assetId"),
            "metadata_visible": obj.get("visible"),
            "bbox_xywh": bbox,
            "bbox_area_fraction": area,
            "mask_pixels": mask_pixels,
            "mask_area_fraction": mask_pixels / (width * height) if mask_pixels is not None and width and height else None,
            "camera_sanity_bbox": Interactions._rendered_target_bbox(
                SimpleNamespace(event=event, metadata=metadata), object_id
            ),
            "state_readability": "not_assessed",
            # Native fields belong in the private audit, never the prompt.
            "native_state": {key: copy.deepcopy(obj[key]) for key in (
                "position", "parentReceptacles", "isPickedUp", "isToggled", "isBroken",
                "isOpen", "isCooked", "isDirty", "isFilledWithLiquid", "fillLiquid",
                "temperature", "ObjectTemperature",
            ) if key in obj},
        }
    return {
        "stage": stage, "relative_rgb_path": relative_path, "png_sha256": png_sha256,
        "width": width, "height": height, "capture_action_index": capture_action_index,
        "last_action": metadata.get("lastAction"),
        "last_action_success": metadata.get("lastActionSuccess"),
        "camera_position": copy.deepcopy(metadata.get("cameraPosition")),
        "agent": copy.deepcopy(metadata.get("agent", {})),
        "inventory": copy.deepcopy(metadata.get("inventoryObjects", [])),
        "roles": entries,
        "semantics": "bbox/mask is object-presence evidence, not state-readability approval",
    }
