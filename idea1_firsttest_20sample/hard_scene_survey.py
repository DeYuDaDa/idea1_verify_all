"""Bounded native survey, with auditable H01/H02 additions before public history."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from hard_inventory import check_inventory
from hard_inventory_prepare import ensure_native_inventory
from runtime import ControllerSession


def scene_candidates(selected, limit=30):
    preferred = [case.scene for case in selected]
    return list(dict.fromkeys(preferred + [f"FloorPlan{i}" for i in range(1, 31)]))[:limit]


def check_layout_inventory(group, metadata):
    """Check independent surfaces used by the existing native placement story.

    Four coordinates on one CounterTop are not four PutObject destinations.
    This gate establishes only inventory availability, not reachability.
    """
    minimum = {"H01": 2, "H02": 4}.get(group, 0)
    ids = sorted({o["objectId"] for o in metadata.get("objects", [])
                  if o.get("objectType") in {"CounterTop", "DiningTable", "KitchenIsland"}
                  and o.get("receptacle") is True and o.get("objectId")
                  and isinstance(o.get("position"), dict)})
    return {"satisfied": len(ids) >= minimum, "required_distinct_surfaces": minimum,
            "available_distinct_surfaces": len(ids), "surface_ids": ids,
            "scope": "layout inventory only; placement and navigation remain unverified"}


def survey_scenes(selected, root, config, launch, *, scene_limit=30, seed=17):
    root = Path(root)
    folder = root / "inventory_survey"
    folder.mkdir(parents=True, exist_ok=True)
    groups = list(dict.fromkeys(case.group_id for case in selected))
    report = {"schema": "hard-inventory-survey/v1", "assignments": {}, "scenes": [],
              "scope": "native object counts/capabilities only; not a placement or visual approval",
              "model_called": False, "scene_limit": scene_limit}
    controller = None
    try:
        for scene in scene_candidates(selected, scene_limit):
            row = {"scene": scene, "checks": {}, "layout_checks": {}}
            report["scenes"].append(row)
            try:
                if controller is None:
                    controller = ControllerSession(scene=scene, platform=config.get("platform", "CloudRendering"),
                        width=config.get("width", 640), height=config.get("height", 480), **launch)
                else:
                    controller.reset(scene)
                metadata = controller.snapshot()
                relative = f"inventory_survey/{scene}.json.gz"
                with gzip.open(root / relative, "wt", encoding="utf-8") as stream:
                    json.dump(metadata, stream, ensure_ascii=False)
                row["metadata_path"] = relative
                additions_needed = [group for group in groups if group in {"H01", "H02"}
                                    and group not in report["assignments"]
                                    and check_layout_inventory(group, metadata)["satisfied"]
                                    and not check_inventory(group, metadata)["satisfied"]]
                if additions_needed:
                    row["native_inventory_preparation"] = {
                        group: ensure_native_inventory(controller, [group], seed=seed, history_started=False)
                        for group in additions_needed}
                    metadata = controller.snapshot()
                    augmented = f"inventory_survey/{scene}_after_native_additions.json.gz"
                    with gzip.open(root / augmented, "wt", encoding="utf-8") as stream:
                        json.dump(metadata, stream, ensure_ascii=False)
                    row["prepared_metadata_path"] = augmented
                for group in groups:
                    check = check_inventory(group, metadata)
                    row["checks"][group] = check
                    layout = check_layout_inventory(group, metadata)
                    row["layout_checks"][group] = layout
                    native_ready = (group not in additions_needed or
                                    row["native_inventory_preparation"][group].get("status")
                                    in {"already_sufficient", "added_and_verified"})
                    if check["satisfied"] and layout["satisfied"] and native_ready and group not in report["assignments"]:
                        report["assignments"][group] = scene
                row["status"] = "inventory_recorded"
                print(f"[inventory] {scene}: assignments={report['assignments']}", flush=True)
                if len(report["assignments"]) == len(groups):
                    break
            except Exception as exc:
                row.update(status="native_inventory_error", error=f"{type(exc).__name__}: {exc}")
                report["fatal_error"] = row["error"]
                break
    finally:
        if controller is not None:
            try:
                controller.stop()
            except Exception as exc:
                report["stop_error"] = str(exc)
        report["unassigned_groups"] = [g for g in groups if g not in report["assignments"]]
        (root / "inventory_survey.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
