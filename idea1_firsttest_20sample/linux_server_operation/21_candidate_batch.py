"""Bookkeeping for a new generation cohort; this helper never starts a model or Unity."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def check(project, data_root):
    manifests = sorted((data_root / "camera_probe").glob("*/manifest.json"))
    if not manifests:
        raise ValueError("No camera probe manifest; run step 16 first")
    latest = manifests[-1]
    record = read(latest)
    expected = {("FloorPlan5", "CoffeeMachine"), ("FloorPlan201", "Laptop"), ("FloorPlan9", "Microwave")}
    cases = record.get("cases", [])
    if record.get("status") != "passed" or len(cases) != 3:
        raise ValueError(f"Latest camera probe has not passed: {latest}")
    if {(c.get("scene"), c.get("objectType")) for c in cases} != expected or not all(
            c.get("status") == "passed" and c.get("validated_look", {}).get("pass") is True for c in cases):
        raise ValueError("Camera result lacks the three rendered target checks")
    for name in ("runtime.py", "interactions.py", "camera_probe.py"):
        digest = hashlib.sha256((project / name).read_bytes()).hexdigest()
        if record.get("source_sha256", {}).get(name) != digest:
            raise ValueError(f"Camera result is from different/unknown code: {name}; rerun step 16")
    if shutil.disk_usage(data_root).free < 5 * 1024**3:
        raise ValueError("Require 5 GiB free on data disk before this generation batch")
    print(f"Current rendered camera checks passed: {latest}", flush=True)


def prepare(args):
    from generator import ALL_PAIRS
    pairs = args.pairs.split(",")
    if not pairs or len(set(pairs)) != len(pairs) or set(pairs) - set(ALL_PAIRS):
        raise ValueError("Unknown or duplicate requested pairs")
    config = read(args.project / "config.json")
    # Use previously informative rooms first; these are search priorities, not Gold.
    priorities = {"coffee": ["FloorPlan5"], "microwave": ["FloorPlan9"],
                  "breakage": ["FloorPlan201"], "carrying": ["FloorPlan5", "FloorPlan3"],
                  "toaster": ["FloorPlan10"], "stove": ["FloorPlan9", "FloorPlan7"]}
    for family, preferred in priorities.items():
        original = config["scene_candidates"][family]
        config["scene_candidates"][family] = preferred + [scene for scene in original if scene not in preferred]
    run = args.output / "_run"
    write(run / "config.json", config)
    names = ("generator.py", "runtime.py", "interactions.py", "exporter.py", "validate.py", "specs.json")
    hashes = {}
    for name in names:
        source = args.project / name
        target = run / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(source.read_bytes())
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    write(run / "plan.json", {"created_utc": datetime.now(timezone.utc).isoformat(),
                              "pairs": pairs, "max_scenes_per_family": args.max_scenes,
                              "seeds": args.seeds, "source_sha256": hashes,
                              "new_output_root": str(args.output), "reviewed": False})


def collect(args):
    from review import create_template
    from validate import validate
    plan = read(args.output / "_run" / "plan.json")
    available = sorted(p.stem for p in (args.output / "pair_receipts").glob("*.json"))
    report = validate(args.output, plan["pairs"])
    write(args.output / "_run" / "validation_report.json", report)
    write(args.output / "_run" / "execution_result.json", {
        "generation_exit_status": args.generation_status, "candidate_pairs": available,
        "requested_pairs": plan["pairs"], "candidate_records": len(available) * 2,
        "formal_evaluation_ready": False,
    })
    review_path = args.data_root / f"review_form_{args.output.name}.json"
    if available:
        create_template(args.output, review_path)
    # Reuse selected-attempt collection, without importing unrelated old batch logs.
    location = args.project / "linux_server_operation" / "14_collect_pilot_evidence.py"
    spec = importlib.util.spec_from_file_location("scope_evidence_collector", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = args.data_root / "pilot_evidence" / args.output.name
    evidence.mkdir(parents=True, exist_ok=False)
    collector = module.Collector(args.output, args.data_root, evidence)
    for relative in ("generation_summary.json", "specs.json"):
        collector.add(args.output / relative, f"exports/{relative}", "current batch", required=True)
    for path in sorted((args.output / "_run").rglob("*")):
        if path.is_file():
            collector.add(path, "exports/_run/" + path.relative_to(args.output / "_run").as_posix(), "current batch provenance")
    collector.add(args.log, f"logs/{args.log.name}", "this generation stage log", required=True)
    if review_path.is_file():
        collector.add(review_path, "review/" + review_path.name, "unapproved review template")
    module.collect_successes(collector)
    module.collect_attempts(collector)
    module.write_manifest(collector)
    archive = evidence.with_suffix(".zip")
    module.archive_directory(evidence, archive)
    print(json.dumps({"export_root": str(args.output), "candidate_pairs": available,
                      "missing_requested_pairs": sorted(set(plan["pairs"]) - set(available)),
                      "review_template": str(review_path) if available else None,
                      "evidence_zip": str(archive), "not_a_model_evaluation": True}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "prepare", "collect"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pairs")
    parser.add_argument("--max-scenes", type=int)
    parser.add_argument("--seeds")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--generation-status", type=int)
    args = parser.parse_args()
    # Generator and review imports resolve to the repository, never bundle code.
    import sys
    sys.path.insert(0, str(args.project.resolve()))
    if args.mode == "check":
        check(args.project, args.data_root)
    elif args.mode == "prepare":
        prepare(args)
    else:
        collect(args)


if __name__ == "__main__":
    main()
