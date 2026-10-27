"""Bounded native inventory survey; no asset spawning and no inferred counts."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from hard_inventory import check_inventory
from runtime import ControllerSession


def scene_candidates(selected, limit=30):
    preferred = [case.scene for case in selected]
    return list(dict.fromkeys(preferred + [f"FloorPlan{i}" for i in range(1, 31)]))[:limit]


def survey_scenes(selected, root, config, launch, *, scene_limit=30):
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
            row = {"scene": scene, "checks": {}}
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
                for group in groups:
                    check = check_inventory(group, metadata)
                    row["checks"][group] = check
                    if check["satisfied"] and group not in report["assignments"]:
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
