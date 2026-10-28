"""Read an existing ZIP into a compact stdout report; no simulator or writes.

Use system python3. This file imports no project module and writes no file.
It reads metadata, logs, requests and ZIP sizes, never images or model weights.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import zipfile


def read_report(path):
    with zipfile.ZipFile(path) as archive:
        def read(name):
            return json.loads(archive.read("dataset/" + name))

        summary = read("generation_summary.json")
        survey = read("inventory_survey.json")
        report = {"schema": "hard-existing-zip-audit/v1", "source_zip": str(path),
                  "source_bytes": path.stat().st_size,
                  "scope": "read-only program/state audit; no visual approval or model run",
                  "summary": summary, "inventory_scenes": [], "native_cases": []}
        for scene in survey.get("scenes", []):
            row = {"scene": scene.get("scene"), "groups": {}}
            for group, preparation in (scene.get("native_inventory_preparation") or {}).items():
                types = {}
                for kind, state in preparation.get("types", {}).items():
                    attempts = state.get("attempts", [])
                    types[kind] = {"before_count": state.get("before_count"),
                                   "after_count": state.get("after_count"),
                                   "complete": state.get("complete"),
                                   "attempt_count": len(attempts),
                                   "error_first_lines": dict(collections.Counter(
                                       a.get("record", {}).get("errorMessage", "").split("\n")[0]
                                       for a in attempts)),
                                   "nonfailure_attempts": [a for a in attempts
                                                            if a.get("status") != "native_action_failed"],
                                   "capability_checks": state.get("capability_checks"),
                                   "relation_check": state.get("relation_check")}
                row["groups"][group] = {"status": preparation.get("status"), "types": types,
                                          "native_action": preparation.get("native_action")}
            report["inventory_scenes"].append(row)
        for name in archive.namelist():
            if not name.startswith("dataset/audit_traces/") or not name.endswith("/native_result.json"):
                continue
            raw = archive.read(name)
            native = json.loads(raw)
            case = name.split("/")[2]
            item = {"case_id": case, "native_result_sha256": hashlib.sha256(raw).hexdigest(),
                    "measurement_issues": native.get("measurement_issues"),
                    "failed_checks": [c.get("name") for c in native.get("checks", []) if not c.get("passed")],
                    "target": {k: native.get("target_event", {}).get(k) for k in
                               ("action", "subject", "native_action_success", "postcondition_verified")},
                    "last_navigation": native.get("navigation_attempts", [])[-1:],
                    "states": {}}
            for label in ("before_target", "after_target"):
                by_id = {o["objectId"]: o for o in native.get(label, {}).get("objects", [])}
                item["states"][label] = {role: {key: by_id.get(oid, {}).get(key) for key in
                    ("position", "temperature", "isCooked", "isToggled", "isOpen",
                     "parentReceptacles", "receptacleObjectIds", "isPickedUp")}
                    for role, oid in native.get("roles", {}).items()}
            # Explain the last failed approach using the last recorded native
            # metadata. This is geometry evidence, not proof of a visible image.
            steps_name = "dataset/audit_traces/" + case + "/steps.jsonl"
            if item["last_navigation"] and item["last_navigation"][0].get("status") == "failed":
                last_step = json.loads(archive.read(steps_name).decode("utf-8").splitlines()[-1])
                meta_name = "dataset/audit_traces/" + case + "/" + last_step["metadata_gzip"]
                metadata = json.loads(gzip.decompress(archive.read(meta_name)))
                target_id = item["last_navigation"][0]["object_id"]
                target = next((o for o in metadata["objects"] if o["objectId"] == target_id), {})
                box = target.get("axisAlignedBoundingBox") or {}
                bounds_distance = None
                if box.get("center") and box.get("size"):
                    position = metadata["agent"]["position"]
                    bounds_distance = math.hypot(*(max(0., abs(position[k] - box["center"][k])
                                                       - box["size"][k] / 2) for k in ("x", "z")))
                item["last_approach_metadata"] = {"global_step": last_step["global_step"],
                    "agent": metadata["agent"], "native_pivot_distance": target.get("distance"),
                    "metadata_visible": target.get("visible"),
                    "metadata_interactable": target.get("isInteractable"),
                    "horizontal_distance_to_bounds": bounds_distance}
            report["native_cases"].append(item)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(read_report(args.zip), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
