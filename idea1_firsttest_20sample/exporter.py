"""Export one executed AI2-THOR case into separate public and hidden records.

This module records observed simulator metadata. It deliberately does not turn
the design spec's expected checks into model gold labels.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


SPEC_PATH = Path(__file__).with_name("specs.json")
FACT_FIELDS: dict[str, tuple[str, ...]] = {
    "temperature": ("temperature", "ObjectTemperature"),
    "isCooked": ("isCooked",),
    "isDirty": ("isDirty",),
    "isFilledWithLiquid": ("isFilledWithLiquid",),
    "fillLiquid": ("fillLiquid",),
    "isToggled": ("isToggled",),
    "isBroken": ("isBroken",),
    "isOpen": ("isOpen",),
    "isPickedUp": ("isPickedUp",),
    "mass": ("mass",),
    "position": ("position",),
    "parentReceptacles": ("parentReceptacles",),
    "controlledObjects": ("controlledObjects",),
    "capabilities": ("capabilities",),
}

# These are direct effects of the named action itself. Other facts are only
# classified as indirect when the caller supplies a verified mechanism rule.
ACTION_DIRECT_FIELDS: dict[str, set[str]] = {
    "ToggleObjectOn": {"isToggled"},
    "ToggleObjectOff": {"isToggled"},
    "OpenObject": {"isOpen"},
    "CloseObject": {"isOpen"},
    "BreakObject": {"isBroken"},
    "PickupObject": {"isPickedUp", "position"},
    "PutObject": {"position", "parentReceptacles"},
    "FillObjectWithLiquid": {"isFilledWithLiquid", "fillLiquid"},
}

_FORBIDDEN_PUBLIC_KEYS = {
    "after", "aftermetadata", "afterstate", "actualafter", "finalstate",
    "groundtruth", "gold", "hiddengold", "poststate", "simulatormetadata",
    "truth", "truestate", "targetlabels",
}
_CAPABILITY_FIELDS = {
    "isCooked": "cookable", "isDirty": "dirtyable",
    "isFilledWithLiquid": "canFillWithLiquid", "fillLiquid": "canFillWithLiquid",
    "isToggled": "toggleable", "isBroken": "breakable", "isOpen": "openable",
}


def _jsonable(value: Any) -> Any:
    """Convert common simulator/numeric values into stable JSON values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (Path, date, datetime)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = [_jsonable(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False)) if isinstance(value, set) else items
    # numpy scalars and similar scalar wrappers expose item().
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except (TypeError, ValueError):
            pass
    # Preserve opaque values as text rather than silently dropping evidence.
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _object_map(metadata: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    objects = metadata.get("objects", [])
    result: dict[str, Mapping[str, Any]] = {}
    if isinstance(objects, Mapping):
        iterable = objects.items()
        for key, obj in iterable:
            if isinstance(obj, Mapping):
                object_id = str(obj.get("objectId", key))
                result[object_id] = obj
        return result
    if isinstance(objects, Iterable) and not isinstance(objects, (str, bytes)):
        for obj in objects:
            if not isinstance(obj, Mapping):
                continue
            object_id = obj.get("objectId", obj.get("id"))
            if object_id is not None:
                result[str(object_id)] = obj
    return result


def _ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    if isinstance(values, Mapping):
        return [str(values.get("objectId", values.get("id", values)))]
    try:
        return [str(v.get("objectId", v.get("id"))) if isinstance(v, Mapping) else str(v) for v in values]
    except TypeError:
        return [str(values)]


def _canonical_value(obj: Mapping[str, Any], aliases: tuple[str, ...]) -> tuple[bool, Any, str | None]:
    for key in aliases:
        if key in obj:
            return True, _jsonable(obj[key]), key
    return False, None, None


def _fact_value(present: bool, value: Any) -> dict[str, Any]:
    # Missing properties are not false; the property may not apply to this object.
    return {"state": "value", "value": value} if present else {"state": "not_applicable"}


def _position_close(a: Any, b: Any) -> bool:
    if not isinstance(a, Mapping) or not isinstance(b, Mapping) or not all(k in a and k in b for k in ("x", "y", "z")):
        return a == b
    try:
        return math.sqrt(sum((float(a[k]) - float(b[k])) ** 2 for k in ("x", "y", "z"))) <= 0.01
    except (TypeError, ValueError):
        return a == b


def _field_overrides(extra: Mapping[str, Any], key: str) -> dict[str, set[str]]:
    raw = extra.get(key, {})
    result: dict[str, set[str]] = {}
    if isinstance(raw, Mapping):
        for subject, fields in raw.items():
            if isinstance(fields, str):
                fields = [fields]
            result[str(subject)] = {str(f) for f in (fields or [])}
    elif isinstance(raw, list):
        # A field-name list applies only to the explicitly supplied direct subjects.
        result["*"] = {str(f) for f in raw}
    return result


def _fact_key_set(extra: Mapping[str, Any], key: str) -> set[str]:
    raw = extra.get(key, [])
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, Mapping):
        raw = list(raw.keys())
    return {str(v) for v in (raw or [])}


def _matches_fact_key(subject: str, predicate: str, configured: set[str]) -> bool:
    return f"{subject}.{predicate}" in configured or f"{subject}:{predicate}" in configured


def _classify_directness(
    subject: str,
    predicate: str,
    action_name: str,
    action_targets: set[str],
    direct_subjects: set[str],
    extra: Mapping[str, Any],
    changed: bool | None,
) -> tuple[str, str]:
    if changed is False:
        return "unaffected", "metadata_equal_before_after"
    if changed is None:
        return "unclassified", "comparison_unavailable"

    direct_keys = _fact_key_set(extra, "direct_fact_keys")
    direct_fields = _field_overrides(extra, "direct_fields")
    if _matches_fact_key(subject, predicate, direct_keys):
        return "direct", "explicit_direct_fact_key"
    if predicate in direct_fields.get(subject, set()) or predicate in direct_fields.get("*", set()):
        return "direct", "explicit_direct_field"
    target_scope = action_targets | direct_subjects
    if subject in target_scope and predicate in ACTION_DIRECT_FIELDS.get(action_name, set()):
        return "direct", f"primary_field_for_{action_name}"

    indirect_keys = _fact_key_set(extra, "indirect_fact_keys")
    indirect_fields = _field_overrides(extra, "indirect_fields")
    if _matches_fact_key(subject, predicate, indirect_keys):
        return "indirect", "explicit_mechanism_supported_fact_key"
    if predicate in indirect_fields.get(subject, set()) or predicate in indirect_fields.get("*", set()):
        return "indirect", "explicit_mechanism_supported_field"
    return "unclassified", "no_verified_mechanism_mapping"


def _knowability(subject: str, predicate: str, extra: Mapping[str, Any]) -> str:
    raw = extra.get("knowability", {})
    if isinstance(raw, Mapping):
        val = raw.get(f"{subject}.{predicate}", raw.get(subject, "not_assessed"))
        if isinstance(val, Mapping):
            val = val.get(predicate, "not_assessed")
        if val in {"knowable", "unknown", "not_applicable", "not_assessed"}:
            return str(val)
    return "not_assessed"


def _scan_for_public_leaks(value: Any, path: str = "model_input") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in _FORBIDDEN_PUBLIC_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_scan_for_public_leaks(child, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_scan_for_public_leaks(child, f"{path}[{index}]"))
    return found


def _action_name(action_log: Any, fallback: Any) -> str:
    if isinstance(action_log, Mapping):
        return str(action_log.get("action", action_log.get("lastAction", fallback or "")))
    if isinstance(action_log, list):
        for entry in reversed(action_log):
            if isinstance(entry, Mapping):
                action = entry.get("action", entry.get("lastAction"))
                if action:
                    return str(action)
    return str(fallback or "")


def _action_targets(action_log: Any, fallback_target: Any) -> set[str]:
    targets: set[str] = set(_ids(fallback_target))
    entries = action_log if isinstance(action_log, list) else [action_log]
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        for key in ("objectId", "target", "targetObjectId", "object_id"):
            targets.update(_ids(entry.get(key)))
        for key in ("action", "lastAction"):
            params = entry.get(key)
            if isinstance(params, Mapping):
                targets.update(_ids(params.get("objectId")))
        kwargs = entry.get("kwargs")
        if isinstance(kwargs, Mapping):
            targets.update(_ids(kwargs.get("objectId")))
            targets.update(_ids(kwargs.get("receptacleObjectId", kwargs.get("destination"))))
    return targets


def _build_facts(
    before_metadata: Mapping[str, Any],
    after_metadata: Mapping[str, Any],
    tracked_ids: list[str],
    action_name: str,
    action_targets: set[str],
    direct_subjects: set[str],
    extra: Mapping[str, Any],
) -> list[dict[str, Any]]:
    before_objects = _object_map(before_metadata)
    after_objects = _object_map(after_metadata)
    subjects = tracked_ids or sorted(set(before_objects) | set(after_objects))
    facts: list[dict[str, Any]] = []
    for subject in subjects:
        before_obj = before_objects.get(subject, {})
        after_obj = after_objects.get(subject, {})
        for predicate, aliases in FACT_FIELDS.items():
            before_present, before_value, before_source = _canonical_value(before_obj, aliases)
            after_present, after_value, after_source = _canonical_value(after_obj, aliases)
            if not _capability_applies(subject, predicate, before_obj, after_obj, extra):
                before_present = after_present = False
                before_value = after_value = None
            if predicate == "fillLiquid":
                if before_obj.get("isFilledWithLiquid") is False and before_value in (None, ""):
                    before_value = None
                if after_obj.get("isFilledWithLiquid") is False and after_value in (None, ""):
                    after_value = None
            if not before_present and not after_present:
                changed = None
                comparison = "not_applicable"
            elif before_present != after_present:
                changed = None
                comparison = "not_comparable_field_missing_on_one_side"
            else:
                if predicate == "parentReceptacles" and isinstance(before_value, list) and isinstance(after_value, list):
                    before_value, after_value = sorted(before_value), sorted(after_value)
                changed = (not _position_close(before_value, after_value)) if predicate == "position" else before_value != after_value
                comparison = "different" if changed else "equal"
            directness, classification_reason = _classify_directness(
                subject, predicate, action_name, action_targets, direct_subjects, extra, changed
            )
            capability = _CAPABILITY_FIELDS.get(predicate)
            capability_assessed = bool(capability and capability in after_obj)
            facts.append({
                "fact_id": f"{subject}.{predicate}",
                "subject": subject,
                "predicate": predicate,
                "before": _fact_value(before_present, before_value),
                "after": _fact_value(after_present, after_value),
                "before_source_field": before_source,
                "after_source_field": after_source,
                "changed": changed,
                "comparison_status": comparison,
                "directness": directness,
                "classification_reason": classification_reason,
                "knowability": _knowability(subject, predicate, extra),
                "verification_status": "not_verified_candidate",
                "assessed": capability_assessed if capability else True,
                "capability_field": capability,
                "evidence": [
                    {"source_type": "simulator_metadata", "visibility": "hidden_gold", "snapshot": "before", "field_path": f"objects[{subject}].{before_source}" if before_source else None},
                    {"source_type": "simulator_metadata", "visibility": "hidden_gold", "snapshot": "after", "field_path": f"objects[{subject}].{after_source}" if after_source else None},
                    {"source_type": "event_action_log", "visibility": "hidden_gold", "record_id": "action_log"},
                ] + _extra_fact_evidence(extra, subject, predicate),
            })
    return facts


def _extra_fact_evidence(extra: Mapping[str, Any], subject: str, predicate: str) -> list[Any]:
    raw = extra.get("fact_evidence", {})
    if isinstance(raw, Mapping):
        values = raw.get(f"{subject}.{predicate}", [])
        return list(values) if isinstance(values, (list, tuple)) else ([values] if values else [])
    return []


def _capability_applies(
    subject: str, predicate: str, before_obj: Mapping[str, Any], after_obj: Mapping[str, Any], extra: Mapping[str, Any]
) -> bool:
    capability = _CAPABILITY_FIELDS.get(predicate)
    if not capability:
        return True
    status = after_obj.get(capability, before_obj.get(capability))
    if status is not False:
        return True
    # Stove burners can expose isToggled as a state controlled by a mapped
    # knob even when their own toggleable capability is false.
    if predicate == "isToggled":
        indirect = _field_overrides(extra, "indirect_fields")
        return predicate in indirect.get(subject, set()) or predicate in indirect.get("*", set())
    return False


def _query_targets(model_input: Any, extra: Mapping[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(model_input, Mapping):
        return []
    roles = extra.get("role_bindings", {})
    roles = roles if isinstance(roles, Mapping) else {}
    aliases_by_id = {str(object_id): str(alias) for alias, object_id in roles.items()}
    fact_map = {(f["subject"], f["predicate"]): f for f in facts}
    targets = []
    for question in model_input.get("questions", []) or []:
        if not isinstance(question, Mapping):
            continue
        fact_id = str(question.get("fact_id", ""))
        if "." in fact_id:
            subject, predicate = fact_id.rsplit(".", 1)
        else:
            alias, predicate = str(question.get("subject", "")), str(question.get("predicate", ""))
            subject = str(roles.get(alias, alias))
        fact = fact_map.get((subject, predicate))
        if not fact:
            continue
        if fact.get("knowability") == "unknown":
            answer = "unknown"
        elif fact.get("knowability") == "not_applicable":
            answer = "not_applicable"
        elif fact.get("after", {}).get("state") == "not_applicable":
            answer = "not_applicable"
        elif predicate == "position" and question.get("answer_mode") == "change_status":
            answer = "changed" if fact.get("changed") is True else ("preserved" if fact.get("changed") is False else "unknown")
        elif predicate == "parentReceptacles":
            raw_ids = fact.get("after", {}).get("value") or []
            answer = sorted(aliases_by_id[object_id] for object_id in raw_ids if object_id in aliases_by_id)
        else:
            answer = fact.get("after", {}).get("value")
            if predicate == "fillLiquid" and answer in (None, ""):
                answer = None
        targets.append({"fact_id": fact_id or f"{subject}.{predicate}", "expected_answer": answer})
    return targets


def _load_spec() -> dict[str, Any]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def export_case(
    root: str | Path,
    pair_id: str,
    variant: str,
    model_input: Any,
    before_metadata: Mapping[str, Any],
    after_metadata: Mapping[str, Any],
    direct_subject_ids: Any,
    tracked_object_ids: Any,
    action_log: Any,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one executed case and return its record paths.

    ``extra`` may provide ``direct_fields``/``direct_fact_keys``,
    ``indirect_fields``/``indirect_fact_keys``, ``knowability``, and optional
    ``selected_pair_fact_keys`` / ``contrast_evidence`` for pair validation.
    Field maps take the form ``{"ObjectId": ["predicate"]}``; a list applies
    only to explicitly supplied direct subjects. ``model_input`` is copied as
    public data after a recursive scan for hidden/final-state keys.
    """
    variant = variant.upper()
    if variant not in {"A", "B"}:
        raise ValueError("variant must be 'A' or 'B'")
    spec = _load_spec()
    pair = next((p for p in spec["pairs"] if p["pair_id"] == pair_id), None)
    if pair is None:
        raise KeyError(f"Unknown pair_id: {pair_id}")
    if not isinstance(before_metadata, Mapping) or not isinstance(after_metadata, Mapping):
        raise TypeError("before_metadata and after_metadata must be THORevent.metadata mappings")
    extra = dict(extra or {})
    leak_paths = _scan_for_public_leaks(model_input)
    if leak_paths:
        raise ValueError("model_input contains hidden/final-state key(s): " + ", ".join(leak_paths))

    evaluated = extra.get("evaluated_action")
    action_log = extra.get("event_records", action_log)
    evaluated_event = dict(evaluated) if isinstance(evaluated, Mapping) else None
    action_name = str(evaluated_event.get("action", "")) if evaluated_event is not None else _action_name(action_log, pair.get("event", {}).get("action"))
    fallback_target = pair.get("event", {}).get("target")
    if isinstance(fallback_target, Mapping):
        fallback_target = fallback_target.get(variant)
    targets = _action_targets(action_log, fallback_target)
    if evaluated_event is not None:
        targets.update(_action_targets({"kwargs": evaluated_event.get("kwargs", {})}, None))
    direct_subjects = set(_ids(direct_subject_ids))
    tracked_ids = _ids(tracked_object_ids)
    facts = _build_facts(
        before_metadata, after_metadata, tracked_ids, action_name, targets,
        direct_subjects, extra,
    )
    query_targets = _query_targets(model_input, extra, facts)
    sample_id = f"{pair_id}_{variant}"
    public_record = {
        "sample_id": sample_id,
        "pair_id": pair_id,
        "variant": variant,
        "model_input": _jsonable(model_input),
    }
    hidden_record = {
        "sample_id": sample_id,
        "pair_id": pair_id,
        "variant": variant,
        "scene_name": before_metadata.get("sceneName") or (model_input.get("scene") if isinstance(model_input, Mapping) else None),
        "design_status": "design_expectations_not_used_as_gold",
        "execution_status": "recorded",
        "construction_status": extra.get("construction_status", "simulator_recorded_candidate"),
        "action_name": action_name,
        "action_targets": sorted(targets),
        "direct_subject_ids": sorted(direct_subjects),
        "tracked_object_ids": tracked_ids,
        "before_metadata": _jsonable(before_metadata),
        "after_metadata": _jsonable(after_metadata),
        "action_log": _jsonable(action_log),
        "evaluated_action": _jsonable(evaluated_event),
        "actual_facts_diff": facts,
        "query_targets": query_targets,
        "extra": _jsonable(extra),
    }
    root_path = Path(root)
    input_path = root_path / "data" / "input" / f"{sample_id}.json"
    hidden_path = root_path / "hidden_gold" / f"{sample_id}.json"
    _write_json(input_path, public_record)
    _write_json(hidden_path, hidden_record)
    return {"sample_id": sample_id, "input_path": str(input_path), "hidden_gold_path": str(hidden_path), "fact_count": len(facts)}

