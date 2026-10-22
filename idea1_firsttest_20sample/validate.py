"""Validate exported AI2-THOR cases against the design and observed metadata.

This reports completeness, event execution, intended-condition contrasts and
observed A/B change-pattern differences. It never substitutes expected checks
from the spec for simulator results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / "specs.json"

# Hints select which recorded initial metadata should evidence each contrast.
# They do not encode the expected value or the expected post-event outcome.
CONTRAST_HINTS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "M01": (("Potato", ("parentReceptacles",)),),
    "M02": (("Potato", ("isCooked",)),),
    "M03": (("Bowl", ("isDirty",)),),
    "M04": (("Cup", ("parentReceptacles",)),),
    "S05": (("Kettle", ("parentReceptacles",)),),
    "S06": (("Kettle", ("parentReceptacles",)),),
    "W08": (("Faucet", ("isToggled",)),),
    "W09": (("Faucet", ("isToggled",)),),
    "W10": (("Faucet", ("isToggled",)),),
    "W11": (("Faucet", ("isToggled",)),),
    "W12": (("ShowerHead", ("isToggled",)),),
    "C13": (("CoffeeMachine", ("isToggled",)),),
    "C14": (("Mug", ("isFilledWithLiquid", "fillLiquid")),),
    "C15": (("Mug", ("parentReceptacles", "position")),),
    "T16": (("Toaster", ("isToggled",)),),
    "T17": (("BreadSliced", ("parentReceptacles",)),),
    "T18": (("BreadSliced", ("isCooked",)),),
    "B19": (("Laptop", ("isToggled",)),),
    "P20": (("Apple", ("parentReceptacles",)),),
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _object_map(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    objects = metadata.get("objects", [])
    result: dict[str, Mapping[str, Any]] = {}
    if isinstance(objects, Mapping):
        for key, value in objects.items():
            if isinstance(value, Mapping):
                result[str(value.get("objectId", key))] = value
    elif isinstance(objects, list):
        for value in objects:
            if isinstance(value, Mapping):
                object_id = value.get("objectId", value.get("id"))
                if object_id is not None:
                    result[str(object_id)] = value
    return result


def _role_matches(object_id: str, obj: Mapping[str, Any], role: str) -> bool:
    object_type = str(obj.get("objectType", ""))
    # IDs commonly include the type; objectType is the preferred signal.
    return role.lower() in object_type.lower() or role.lower() in object_id.lower()


def _fact_map(hidden: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(f.get("subject")), str(f.get("predicate"))): f
        for f in hidden.get("actual_facts_diff", [])
        if isinstance(f, Mapping)
    }


def _m03_dirty_fact(hidden: Mapping[str, Any]) -> Mapping[str, Any] | None:
    facts = _fact_map(hidden)
    extra = hidden.get("extra", {}) if isinstance(hidden.get("extra"), Mapping) else {}
    roles = extra.get("role_bindings", {}) if isinstance(extra.get("role_bindings"), Mapping) else {}
    subject = roles.get("Bowl_1")
    if subject is None:
        for alias, object_id in roles.items():
            if "bowl" in str(alias).lower():
                subject = object_id
                break
    if subject is not None and (str(subject), "isDirty") in facts:
        return facts[(str(subject), "isDirty")]
    metadata = _object_map(hidden.get("before_metadata", {}))
    candidates = [object_id for object_id, obj in metadata.items() if _role_matches(object_id, obj, "Bowl")]
    if len(candidates) == 1:
        return facts.get((candidates[0], "isDirty"))
    return None


def _contrast_values(hidden: Mapping[str, Any], pair_id: str) -> list[dict[str, Any]]:
    hints = CONTRAST_HINTS.get(pair_id, ())
    objects = _object_map(hidden.get("before_metadata", {}))
    found: list[dict[str, Any]] = []
    for role, predicates in hints:
        matching = [(object_id, obj) for object_id, obj in objects.items() if _role_matches(object_id, obj, role)]
        if len(matching) != 1:
            continue
        object_id, obj = matching[0]
        for predicate in predicates:
            if predicate in obj:
                found.append({"subject": object_id, "predicate": predicate, "value": obj[predicate]})
    # Caller-supplied evidence supports unusual scenes and duplicate object types.
    evidence = hidden.get("extra", {}).get("contrast_evidence") if isinstance(hidden.get("extra"), Mapping) else None
    if isinstance(evidence, Mapping):
        evidence = [evidence]
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, Mapping) and "subject_id" in item and "predicate" in item and "value" in item:
                found.append({"subject": str(item["subject_id"]), "predicate": str(item["predicate"]), "value": item["value"]})
    # Deduplicate exact subject/predicate pairs, preferring explicit evidence.
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in found:
        dedup[(item["subject"], item["predicate"])] = item
    return list(dedup.values())


def _action_success(hidden: Mapping[str, Any]) -> bool | None:
    evaluated = hidden.get("evaluated_action")
    if isinstance(evaluated, Mapping) and isinstance(evaluated.get("lastActionSuccess"), bool):
        return evaluated["lastActionSuccess"]
    log = hidden.get("action_log")
    entries = log if isinstance(log, list) else [log]
    for entry in reversed(entries):
        if isinstance(entry, Mapping):
            if isinstance(entry.get("lastActionSuccess"), bool):
                return entry["lastActionSuccess"]
            result = entry.get("event")
            if isinstance(result, Mapping) and isinstance(result.get("lastActionSuccess"), bool):
                return result["lastActionSuccess"]
    return None


def _selected_fact_keys(hidden: Mapping[str, Any]) -> set[str]:
    extra = hidden.get("extra", {})
    if not isinstance(extra, Mapping):
        return set()
    raw = extra.get("selected_pair_fact_keys", extra.get("pair_target_fact_keys", []))
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, Mapping):
        raw = list(raw.keys())
    return {str(value) for value in (raw or [])}


def _ids_from_event(event: Mapping[str, Any]) -> list[str]:
    kwargs = event.get("kwargs", {})
    if not isinstance(kwargs, Mapping):
        return []
    result = []
    for key in ("objectId", "targetObjectId", "receptacleObjectId", "destination"):
        raw = kwargs.get(key)
        if isinstance(raw, (list, tuple)):
            result.extend(str(x) for x in raw)
        elif raw is not None:
            result.append(str(raw))
    return sorted(result)


def _event_kwargs(event: Mapping[str, Any]) -> Mapping[str, Any]:
    kwargs = event.get("kwargs", {})
    return kwargs if isinstance(kwargs, Mapping) else {}


def _public_path_issues(value: Any, base: Path) -> list[str]:
    issues: list[str] = []
    if isinstance(value, Mapping):
        for child in value.values():
            issues.extend(_public_path_issues(child, base))
    elif isinstance(value, (list, tuple)):
        for child in value:
            issues.extend(_public_path_issues(child, base))
    elif isinstance(value, str):
        normalized = value.replace("\\", "/").lower()
        if any(part.startswith(".") for part in normalized.split("/")) or "hidden_gold" in normalized or "/hidden/" in normalized or normalized.startswith("hidden/"):
            issues.append(value)
        if "/media/" in normalized or normalized.startswith("data/media/"):
            candidate = (base / value).resolve()
            try:
                candidate.relative_to(base.resolve())
            except ValueError:
                issues.append(value)
            else:
                if not candidate.is_file():
                    issues.append(value)
    return issues


def _matching_review_samples(root: Path, review_record: Any) -> set[str]:
    if (not isinstance(review_record, Mapping) or review_record.get("review_record_version") != 1
            or not isinstance(review_record.get("samples"), Mapping) or not str(review_record.get("reviewer", "")).strip()):
        return set()
    try:
        from review import _root_fingerprint, _sample_ids
        current_ids = _sample_ids(root)
        current_root_hash, current_hashes = _root_fingerprint(root, current_ids)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return set()
    review_samples = review_record["samples"]
    if current_root_hash != review_record.get("root_fingerprint") or set(review_samples) != set(current_ids):
        return set()
    return {
        sample_id for sample_id in current_ids
        if isinstance(review_samples[sample_id], Mapping)
        and review_samples[sample_id].get("sample_fingerprint") == current_hashes[sample_id]
        and review_samples[sample_id].get("approved") is True
        and review_samples[sample_id].get("visual_evidence_confirmed") is True
        and review_samples[sample_id].get("initial_controls_confirmed") is True
        and review_samples[sample_id].get("knowledge_protocol_confirmed") is True
    }


def _normalize_fact_key(key: str, facts_a: Mapping[tuple[str, str], Any], facts_b: Mapping[tuple[str, str], Any]) -> tuple[str, str] | None:
    if "." in key:
        subject, predicate = key.rsplit(".", 1)
    elif ":" in key:
        subject, predicate = key.rsplit(":", 1)
    else:
        return None
    candidate = (subject, predicate)
    return candidate if candidate in facts_a and candidate in facts_b else None


def _pair_result(pair: Mapping[str, Any], a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> dict[str, Any]:
    pair_id = str(pair["pair_id"])
    if a is None or b is None:
        return {
            "pair_id": pair_id,
            "strict_minimal_pair": bool(pair.get("strict_minimal_pair")),
            "status": "fail",
            "reason": "missing_variant_record",
            "contrast_status": "inconclusive",
            "actual_flip_status": "inconclusive",
            "observed_flip_facts": [],
        }

    contrast_a = _contrast_values(a, pair_id)
    contrast_b = _contrast_values(b, pair_id)
    by_key_a = {(x["subject"], x["predicate"]): x["value"] for x in contrast_a}
    by_key_b = {(x["subject"], x["predicate"]): x["value"] for x in contrast_b}
    shared_contrasts = sorted(set(by_key_a) & set(by_key_b))
    contrast_differences = [
        {"subject": subject, "predicate": predicate, "A": by_key_a[(subject, predicate)], "B": by_key_b[(subject, predicate)]}
        for subject, predicate in shared_contrasts
        if by_key_a[(subject, predicate)] != by_key_b[(subject, predicate)]
    ]
    if contrast_differences:
        contrast_status = "pass"
    elif shared_contrasts:
        contrast_status = "fail"
    else:
        contrast_status = "inconclusive"

    facts_a = _fact_map(a)
    facts_b = _fact_map(b)
    shared_facts = sorted(set(facts_a) & set(facts_b))
    observed_flips = [
        {"fact_id": f"{subject}.{predicate}", "A_changed": facts_a[(subject, predicate)].get("changed"), "B_changed": facts_b[(subject, predicate)].get("changed")}
        for subject, predicate in shared_facts
        if isinstance(facts_a[(subject, predicate)].get("changed"), bool)
        and isinstance(facts_b[(subject, predicate)].get("changed"), bool)
        and facts_a[(subject, predicate)].get("changed") != facts_b[(subject, predicate)].get("changed")
    ]
    selected_keys = _selected_fact_keys(a) | _selected_fact_keys(b)
    selected_map = {key: _normalize_fact_key(key, facts_a, facts_b) for key in selected_keys}
    selected = [key for key, mapped in selected_map.items() if mapped]
    selected_flip_ids = {entry["fact_id"] for entry in observed_flips}
    if selected:
        selected_ids = {f"{subject}.{predicate}" for mapped in selected_map.values() if mapped for subject, predicate in [mapped]}
        actual_flip_status = "pass" if selected_ids & selected_flip_ids else "fail"
    else:
        actual_flip_status = "inconclusive"

    action_a = a.get("action_name")
    action_b = b.get("action_name")
    targets_a = sorted(a.get("action_targets", []))
    targets_b = sorted(b.get("action_targets", []))
    strict = bool(pair.get("strict_minimal_pair"))
    if not strict:
        event_match_status = "not_required_non_strict_pair"
    elif action_a is None or action_b is None or not targets_a or not targets_b:
        event_match_status = "inconclusive"
    else:
        event_match_status = "pass" if action_a == action_b and targets_a == targets_b else "fail"

    # The evaluated event must be explicit and agree on kind/target except for
    # the two intentional target-binding/destination contrasts.
    event_a, event_b = a.get("evaluated_action"), b.get("evaluated_action")
    event_kind_status = "inconclusive"
    if isinstance(event_a, Mapping) and isinstance(event_b, Mapping):
        kind_ok = event_a.get("action") == event_b.get("action")
        targets_event_a = _ids_from_event(event_a)
        targets_event_b = _ids_from_event(event_b)
        kwargs_a, kwargs_b = _event_kwargs(event_a), _event_kwargs(event_b)
        if pair_id == "S07":
            target_ok = bool(kwargs_a.get("objectId") and kwargs_b.get("objectId")) and kwargs_a.get("objectId") != kwargs_b.get("objectId")
        elif pair_id == "C15":
            from event_bindings import destination_contrast
            target_ok = destination_contrast(a, b, event_a, event_b)
        else:
            target_ok = bool(targets_event_a and targets_event_b) and targets_event_a == targets_event_b
        event_kind_status = "pass" if kind_ok and target_ok else "fail"
    event_binding_differs = bool(isinstance(event_a, Mapping) and isinstance(event_b, Mapping) and _ids_from_event(event_a) != _ids_from_event(event_b))
    if pair_id in {"S07", "C15"} and event_kind_status == "pass" and event_binding_differs:
        contrast_status = "pass"

    extra_a = a.get("extra", {}) if isinstance(a.get("extra"), Mapping) else {}
    extra_b = b.get("extra", {}) if isinstance(b.get("extra"), Mapping) else {}
    roles_a, roles_b = extra_a.get("role_bindings"), extra_b.get("role_bindings")
    roles_match = isinstance(roles_a, Mapping) and isinstance(roles_b, Mapping) and roles_a.keys() == roles_b.keys()
    if roles_match:
        roles_match = all(str(roles_a[k]) == str(roles_b[k]) for k in roles_a)
    scene_a, scene_b = a.get("scene_name"), b.get("scene_name")
    scene_status = "pass" if scene_a and scene_a == scene_b else ("fail" if scene_a and scene_b and scene_a != scene_b else "inconclusive")

    special_preservation = pair_id == "M03"
    selected_required = not special_preservation
    if selected_required and not selected:
        actual_flip_status = "fail"
    preservation_status = "not_required"
    if special_preservation:
        bowl_a = _m03_dirty_fact(a)
        bowl_b = _m03_dirty_fact(b)
        preservation_status = "pass" if bowl_a and bowl_b and bowl_a.get("changed") is False and bowl_b.get("changed") is False and bowl_a.get("before") != bowl_b.get("before") else "fail"

    position_differences = []
    if roles_match:
        before_a, before_b = _object_map(a.get("before_metadata", {})), _object_map(b.get("before_metadata", {}))
        for alias in sorted(roles_a):
            object_id = str(roles_a[alias])
            oa, ob = before_a.get(object_id, {}), before_b.get(object_id, {})
            pa, pb = oa.get("position"), ob.get("position")
            if isinstance(pa, Mapping) and isinstance(pb, Mapping):
                try:
                    distance = sum((float(pa[k]) - float(pb[k])) ** 2 for k in ("x", "y", "z")) ** 0.5
                except (KeyError, TypeError, ValueError):
                    continue
                if distance > 0.01:
                    position_differences.append({"role": str(alias), "object_id": object_id, "distance_m": distance})

    success_a, success_b = _action_success(a), _action_success(b)
    action_status = "fail" if success_a is False or success_b is False else (
        "pass" if success_a is True and success_b is True else "inconclusive"
    )
    failures = []
    if action_status == "fail":
        failures.append("one_or_both_evaluated_actions_failed")
    if strict and event_match_status == "fail":
        failures.append("strict_pair_event_or_target_mismatch")
    if contrast_status == "fail":
        failures.append("contrast_field_was_observed_but_did_not_differ")
    if event_kind_status == "fail":
        failures.append("evaluated_action_kind_or_target_mismatch")
    if selected_required and actual_flip_status == "fail" and not special_preservation:
        failures.append("selected_mechanism_target_did_not_flip")
    if special_preservation and preservation_status == "fail":
        failures.append("M03_dirty_value_not_preserved_in_both_variants")
    if scene_status == "fail" or not roles_match:
        failures.append("scene_or_role_bindings_mismatch")
    for side, record in (("A", a), ("B", b)):
        ex = record.get("extra", {}) if isinstance(record.get("extra"), Mapping) else {}
        obs = ex.get("observation_audit", {}) if isinstance(ex.get("observation_audit"), Mapping) else {}
        if not obs.get("event_target_visible") or not obs.get("required_frames_present"):
            failures.append(f"{side}_observation_evidence_incomplete")
        if not record.get("before_metadata") or not record.get("after_metadata"):
            failures.append(f"{side}_metadata_missing")
        if not isinstance(record.get("_public_model_input"), Mapping) or not record["_public_model_input"].get("questions"):
            failures.append(f"{side}_query_missing")
        checks = ex.get("scenario_checks", [])
        if not isinstance(checks, list) or not checks or any(not isinstance(c, Mapping) or c.get("passed") is not True for c in checks):
            failures.append(f"{side}_scenario_check_failed_or_missing")
    status = "fail" if failures else (
        "pass" if action_status == "pass" and event_match_status in {"pass", "not_required_non_strict_pair"} and event_kind_status == "pass" and contrast_status == "pass" and (actual_flip_status == "pass" or special_preservation) and scene_status == "pass" and (not special_preservation or preservation_status == "pass") and (not position_differences or (extra_a.get("initial_control_audited") and extra_b.get("initial_control_audited"))) else "inconclusive"
    )
    return {
        "pair_id": pair_id,
        "strict_minimal_pair": strict,
        "status": status,
        "failures": failures,
        "action_success": {"A": success_a, "B": success_b, "status": action_status},
        "event_match_status": event_match_status,
        "evaluated_event_status": event_kind_status,
        "event_binding_differs": event_binding_differs,
        "scene_role_status": scene_status,
        "role_bindings_match": roles_match,
        "contrast_key": pair.get("contrast_key"),
        "contrast_status": contrast_status,
        "observed_initial_contrast_differences": contrast_differences,
        "actual_flip_status": actual_flip_status,
        "preservation_status": preservation_status,
        "tracked_role_position_differences": position_differences,
        "position_review_status": "audited" if position_differences and extra_a.get("initial_control_audited") and extra_b.get("initial_control_audited") else ("review_required" if position_differences else "matched_or_unavailable"),
        "initial_control_audited": bool(extra_a.get("initial_control_audited")) and bool(extra_b.get("initial_control_audited")),
        "selected_pair_fact_keys": sorted(selected),
        "observed_flip_facts": observed_flips,
    }


def _reviewed_fact_readiness(record: dict, reviewed_fact_ids: set[str]) -> dict:
    """Resolve readiness in a working copy, never rewrite native Gold values."""
    result = dict(record)
    facts = []
    for original in record.get("actual_facts_diff", []):
        fact = dict(original)
        if fact.get("fact_id") in reviewed_fact_ids and fact.get("knowability") == "not_assessed":
            fact["knowability"] = "knowable"
            fact["knowability_review_basis"] = "hash_bound_per_question_evidence_review"
        facts.append(fact)
    result["actual_facts_diff"] = facts
    return result


def validate(root: str | Path, pair_ids: list[str] | None = None) -> dict[str, Any]:
    """Return a JSON-serializable dataset validation report for ``root``."""
    root_path = Path(root)
    spec = _read_json(root_path / "specs.json") if (root_path / "specs.json").exists() else _read_json(SPEC_PATH)
    pairs = spec.get("pairs", [])
    if pair_ids:
        wanted = set(pair_ids)
        known = {str(p.get("pair_id")) for p in pairs}
        unknown = sorted(wanted - known)
        pairs = [p for p in pairs if p.get("pair_id") in wanted]
    else:
        unknown = []
    expected_ids = {f"{pair['pair_id']}_{variant}" for pair in pairs for variant in ("A", "B")}
    all_spec_ids = {f"{pair['pair_id']}_{variant}" for pair in spec.get("pairs", []) for variant in ("A", "B")}
    input_dir = root_path / "data" / "input"
    hidden_dir = root_path / "hidden_gold"
    input_files = {p.stem: p for p in input_dir.glob("*.json")} if input_dir.exists() else {}
    hidden_files = {p.stem: p for p in hidden_dir.glob("*.json")} if hidden_dir.exists() else {}
    available_ids = set(input_files) & set(hidden_files)
    missing = sorted(expected_ids - available_ids)
    unexpected = sorted((set(input_files) | set(hidden_files)) - all_spec_ids)
    records: dict[str, dict[str, Any]] = {}
    public_leaks: list[str] = []
    sample_errors: list[dict[str, str]] = []
    sample_errors.extend({"sample_id": "", "error": f"unknown_requested_pair_id:{pair_id}"} for pair_id in unknown)
    review_record = None
    review_path = root_path / "review_records.json"
    if review_path.is_file():
        try:
            review_record = _read_json(review_path)
        except (OSError, json.JSONDecodeError):
            sample_errors.append({"sample_id": "", "error": "invalid_review_records_json"})
    valid_review_samples = _matching_review_samples(root_path, review_record)
    evidence_status, evidence_errors, reviewed_facts = "missing", [], {}
    evidence_path = root_path / "evidence_review.json"
    if evidence_path.is_file():
        try:
            from evidence_workflow import check_review
            evidence_result = check_review(root_path, evidence_path)
            evidence_status = evidence_result["status"]
            evidence_errors = evidence_result.get("errors", [])
            if evidence_status == "approved":
                for sample in _read_json(evidence_path)["samples"]:
                    reviewed_facts[sample["sample_id"]] = {q["fact_id"] for q in sample["questions"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            evidence_status, evidence_errors = "blocked", [str(exc)]
    scan_ids = available_ids & expected_ids if pair_ids else available_ids
    for sample_id in sorted(scan_ids):
        try:
            public = _read_json(input_files[sample_id])
            hidden = _read_json(hidden_files[sample_id])
        except (OSError, json.JSONDecodeError) as exc:
            sample_errors.append({"sample_id": sample_id, "error": str(exc)})
            continue
        if public.get("sample_id") != sample_id or hidden.get("sample_id") != sample_id:
            sample_errors.append({"sample_id": sample_id, "error": "filename_sample_id_mismatch"})
        if public.get("pair_id") != hidden.get("pair_id") or public.get("variant") != hidden.get("variant"):
            sample_errors.append({"sample_id": sample_id, "error": "public_hidden_identity_mismatch"})
        # Inspect only the public subtree; only key names are checked, never text questions.
        model_input = public.get("model_input")
        from exporter import _scan_for_public_leaks  # local sibling; same standalone folder
        paths = _scan_for_public_leaks(model_input)
        public_leaks.extend(f"{sample_id}:{path}" for path in paths)
        path_issues = _public_path_issues(model_input, root_path)
        public_leaks.extend(f"{sample_id}:invalid_or_hidden_path:{path}" for path in path_issues)
        if isinstance(model_input, Mapping) and not model_input.get("frames"):
            sample_errors.append({"sample_id": sample_id, "error": "public_media_frames_missing"})
        records[sample_id] = _reviewed_fact_readiness(hidden, reviewed_facts.get(sample_id, set()))
        if isinstance(public, Mapping):
            records[sample_id]["_public_model_input"] = public.get("model_input")
        if sample_id in valid_review_samples:
            current_extra = records[sample_id].get("extra", {})
            records[sample_id]["extra"] = dict(current_extra) if isinstance(current_extra, Mapping) else {}
            records[sample_id]["extra"].update({"initial_control_audited": True, "review_audited": True})

    pair_reports = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        pair_reports.append(_pair_result(pair, records.get(f"{pair_id}_A"), records.get(f"{pair_id}_B")))

    failed_pairs = [p["pair_id"] for p in pair_reports if p["status"] == "fail"]
    inconclusive_pairs = [p["pair_id"] for p in pair_reports if p["status"] == "inconclusive"]
    if missing or unexpected or sample_errors or public_leaks or failed_pairs:
        overall = "fail"
    elif inconclusive_pairs:
        overall = "inconclusive"
    else:
        reviewed = evidence_status == "approved" and all(f"{p['pair_id']}_A" in valid_review_samples and f"{p['pair_id']}_B" in valid_review_samples for p in pairs)
        knowable = all(
            all(f.get("knowability") == "knowable" for f in records.get(f"{p['pair_id']}_{v}", {}).get("actual_facts_diff", []) if f.get("fact_id") in _selected_fact_keys(records.get(f"{p['pair_id']}_{v}", {})))
            for p in pairs for v in ("A", "B")
        )
        overall = "pass" if reviewed and knowable else "pending_review"
    if isinstance(review_record, Mapping):
        review_record_status = "valid" if valid_review_samples and len(valid_review_samples) == len(review_record.get("samples", {})) else "stale_or_incomplete"
    else:
        review_record_status = "stale_or_incomplete" if review_record is not None else "missing"
    return {
        "dataset_id": spec.get("dataset_id"),
        "status": overall,
        "validation_level": "simulator_validated" if overall in {"pass", "pending_review"} else "pending_or_failed",
        "benchmark_ready": overall == "pass",
        "review_record_status": review_record_status,
        "question_evidence_review_status": evidence_status,
        "question_evidence_review_errors": evidence_errors,
        "not_ready_reasons": (["per_question_evidence_review_missing_or_blocked"] if evidence_status != "approved" else []) + (["matching_human_review_record_missing_or_stale"] if overall == "pending_review" and review_record_status != "valid" else []) + (["selected_target_not_knowable"] if overall == "pending_review" and not all(all(f.get("knowability") == "knowable" for f in records.get(f"{p['pair_id']}_{v}", {}).get("actual_facts_diff", []) if f.get("fact_id") in _selected_fact_keys(records.get(f"{p['pair_id']}_{v}", {}))) for p in pairs for v in ("A", "B")) else []),
        "expected_sample_count": len(expected_ids),
        "available_public_sample_count": len(input_files),
        "available_hidden_sample_count": len(hidden_files),
        "complete_pair_count": sum(1 for p in pair_reports if f"{p['pair_id']}_A" in available_ids and f"{p['pair_id']}_B" in available_ids),
        "missing_sample_ids": missing,
        "unexpected_sample_ids": unexpected,
        "sample_errors": sample_errors,
        "public_hidden_key_leaks": public_leaks,
        "pair_reports": pair_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Export root containing data/input and hidden_gold")
    parser.add_argument("--strict", action="store_true", help="Exit 0 only when selected pairs pass all simulator checks")
    parser.add_argument("--pairs", nargs="*", help="Validate only these pair IDs (for example pilot pairs)")
    args = parser.parse_args()
    pair_ids = [part.strip() for item in (args.pairs or []) for part in item.split(",") if part.strip()]
    report = validate(args.root, pair_ids or None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and report["status"] != "pass":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

