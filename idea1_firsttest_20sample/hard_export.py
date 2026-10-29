"""Export candidate V/S inputs and private evidence without invoking a model."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from hard_scenarios import derive_answer


RULES = [
    "本题机制仅适用于当前已校准的模拟器资产、位置和观察窗口；机器人之外没有未记录的主动操作。",
    "开启的咖啡机只接收Mug；空Mug放入后可获得咖啡，已有水的Mug不会因此被替换成咖啡。机器外的另一杯不会被远程注液。",
    "拿起容器时，它当时实际承载的内容物可随动；已移到外部台面的物体不因过去的承载关系而随动。物体移动不自动表示内部承载关系解除。",
    "炉头由其实际连接的旋钮控制，不能直接开关炉头。只有处于该实例已校准作用位置的容器受对应热源影响；不把所有邻近容器一律变热。",
    "微波炉必须关门才能启动，启动后不能开门；当前位于炉内的土豆可受热并变熟，位于已校准外部位置的土豆不因旧炉内关系而受热。",
    "土豆真实熟化后自然冷却不会撤销已经成立的熟度；再次加热已熟土豆时，温度可以改变而熟度仍保持true。",
]


class NativeMeasurementUnavailable(RuntimeError):
    """Missing truth is an unpublishable measurement, not a Gold unknown."""


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def public_roles(ctx):
    wanted = {"H01": ("A", "B", "M"), "H02": ("P", "Q", "X"),
              "H03": ("KA", "KB", "BA", "BB", "X", "Y"),
              "H04": ("P", "B", "X"), "H05": ("Microwave", "Z")}
    roles = list(wanted[ctx.group_id])
    if getattr(ctx, "h01_natural", False):
        roles.append("Faucet")
    return [a for a in roles if a in ctx.roles]


def _objects(ctx):
    initial = {o["objectId"]: o for o in ctx.initial_metadata.get("objects", [])}
    return [{"alias": a, "object_type": initial.get(ctx.roles[a], {}).get("objectType", "unknown")}
            for a in public_roles(ctx)]


def _location_labels(ctx):
    objects = {o["objectId"]: o for o in ctx.initial_metadata.get("objects", [])}
    return list(ctx.waypoints) + [a for a in public_roles(ctx)
                                 if objects.get(ctx.roles[a], {}).get("receptacle") is True] + ["unknown"]


def _location_definitions(ctx):
    names = {"A_park": "咖啡机外A杯的初始停放台面", "B_park": "咖啡机外B杯的初始停放台面",
             "left": "两盘初态的左侧停放区", "right": "两盘初态的右侧停放区",
             "apple_staging": "两盘之外的苹果暂存台面", "plate_buffer": "交换空盘用的外部周转位",
             "buffer": "炉头之外的容器周转台面", "BA": "炉头BA的位置", "BB": "炉头BB的位置",
             "h04_external": "外盘之外的移出物品停放台面", "cooling_C": "微波炉外部的自然冷却位置C",
             "final_E": "已经校准为不受本次微波炉启动加热的炉外位置E"}
    return {name: names.get(name, name) for name in ctx.waypoints}


def _question_rows(ctx):
    return [{**q, "fact_id": f"{q['subject']}.{q['predicate']}"} for q in ctx.questions]


def _state_before(ctx):
    result = []
    # This is the explicitly stronger S protocol. No full native objects or
    # coordinates are exposed; only the task's current semantic predicates.
    predicates = ("liquid", "temperature", "isCooked", "isToggled", "location")
    native = {o["objectId"]: o for o in ctx.before_target.get("objects", [])}
    for alias in public_roles(ctx):
        obj = native.get(ctx.roles[alias], {})
        for predicate in predicates:
            capability = {"liquid": "canFillWithLiquid", "isCooked": "cookable", "isToggled": "toggleable"}.get(predicate)
            if capability and obj.get(capability) is not True:
                continue
            if predicate == "location" and not any(q["subject"] == alias and q["predicate"] == "location"
                                                    for q in ctx.questions):
                continue
            value = derive_answer({"subject": alias, "predicate": predicate}, ctx.before_target, ctx)
            if value is not None:
                result.append({"subject": alias, "predicate": predicate, "value": value})
        memberships = [a for a in public_roles(ctx)
                       if ctx.roles[a] in (obj.get("parentReceptacles") or [])]
        if memberships:
            result.append({"subject": alias, "predicate": "known_container_memberships",
                           "value": memberships,
                           "note": "可能包含祖先；不声称这是唯一直接承载边。"})
    return result


def _event_public(ctx):
    return {k: ctx.target_event[k] for k in ("action", "subject", "destination", "success")
            if k in ctx.target_event and ctx.target_event[k] is not None}


def request_text(model_input):
    return (
        "请只根据本条完整公开输入回答，不访问模拟器metadata或隐藏答案。"
        "下面的JSON是全部待发送内容，所有历史、初态说明、规则、事件信息和问题均须保留。"
        "初态像素框只指定物体身份，不提供后续状态。相同capture_group_index的互补视角来自同一步。"
        "请返回一个以fact_id为键的JSON对象；布尔题使用true/false，未知使用字符串unknown。\n\n"
        + json.dumps(model_input, ensure_ascii=False, indent=2)
    )


def _copy_model_frames(trace, root):
    frames, hashes = [], []
    for row in trace.model_frames():
        source = (Path(trace.directory) / row["path"]).resolve()
        source.relative_to(Path(trace.directory).resolve())
        digest = sha_file(source)
        relative = f"data/media/{digest}.png"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        if sha_file(target) != digest:
            raise RuntimeError("Public image copy hash mismatch")
        frames.append({**row, "path": relative})
        hashes.append(digest)
    return frames, hashes


def write_audit_timeline(ctx, trace, case):
    runs = [{"path": r["path"], "stage": r["phase_label"],
             **{k: r[k] for k in ("view_id", "run_length", "duplicate_count", "start_step", "end_step")}}
            for r in trace.auditor_frames]
    boundaries = json.loads((Path(trace.directory) / "boundaries.json").read_text(encoding="utf-8"))
    write_json(Path(trace.directory) / "review_timeline.json", {
        "sample_id": case.case_id, "title": case.title, "frames": runs,
        "capture_groups": [{k: v for k, v in group.items() if k != "_signature"}
                           for group in getattr(trace, "_capture_groups", [])],
        "capture_group_count": len(getattr(trace, "_capture_groups", [])),
        "boundaries": [{**r, "step_index": r["global_step"]} for r in boundaries],
        "steps": ([{"采集检查": ctx.capture_diagnostics}] if getattr(ctx, "capture_diagnostics", None) else []) + trace.events,
        "checks": ctx.checks,
        "checkpoints": copy.deepcopy(getattr(ctx, "h01_checkpoints", [])),
        "public_frame_map": [{"frame_index": i, "start_step": frame["start_step"],
                               "end_step": frame["end_step"], "step_numbers": frame.get("step_numbers", [])}
                              for i, frame in enumerate(trace.model_frames(), 1)]
                             if getattr(ctx, "h01_natural", False) else [],
        "note": "完整私有轨迹，含准备、失败与原生参数，不属于模型输入。",
    })


def export_case(ctx, trace, root, case):
    root = Path(root)
    if ctx.target_event.get("success") is not True:
        raise RuntimeError("Cannot publish a question whose target event failed")
    frames, media_hashes = _copy_model_frames(trace, root)
    if not frames:
        raise RuntimeError("Visual candidate has no public frames")
    questions = _question_rows(ctx)
    if not questions:
        raise RuntimeError("Candidate has no formal questions")
    gold_targets = []
    for question in questions:
        answer = derive_answer(question, ctx.after_target, ctx, before=ctx.before_target)
        if answer is None:
            ctx.measurement_issues = [{"fact_id": question["fact_id"], "status": "native_truth_unavailable"}]
            raise NativeMeasurementUnavailable(f"Native truth unavailable for {question['fact_id']}; do not turn missing measurement into Gold unknown")
        gold_targets.append({"fact_id": question["fact_id"],
                             "expected_answer": answer})
    anchors = []
    for anchor in getattr(ctx, "initial_identity_regions", []):
        # Public identity regions must point to the first-person agent image
        # from the synchronized group in which the region was measured.
        if anchor.get("view_id", "agent") != "agent":
            continue
        group_index = anchor.get("initial_capture_group_index")
        matching = next((i + 1 for i, f in enumerate(frames)
                         if f["view_id"] == "agent" and
                         (group_index is None and f["start_step"] <= anchor.get("global_step", -1) <= f["end_step"]
                          or group_index is not None and f["start_step"] <= group_index <= f["end_step"])), None)
        if matching is not None:
            anchors.append({"alias": anchor["alias"], "view_id": "agent",
                            **({"anchor_kind": anchor["anchor_kind"]} if anchor.get("anchor_kind") else {}),
                            "pixel_bbox": anchor["pixel_bbox"],
                            "initial_frame_index": matching,
                            "initial_capture_group_index": frames[matching - 1]["capture_group_index"]})
    # Distinct aliases must be grounded in the public initial images. The
    # anchor is a pixel region from those images, not native/world metadata.
    if set(public_roles(ctx)) - {a["alias"] for a in anchors}:
        raise RuntimeError("Initial public identity anchors do not cover the task roles")
    # Public indices begin at the public history, so hidden calibration length
    # cannot reveal the variant. Full global indices remain in private traces.
    origin = min(frame["start_step"] for frame in frames)
    for index, frame in enumerate(frames, 1):
        frame["start_step"] -= origin
        frame["end_step"] -= origin
        frame["capture_group_index"] = index
        if "step_numbers" in frame:
            frame["step_numbers"] = [step - origin for step in frame["step_numbers"]]
    for anchor in anchors:
        anchor["initial_capture_group_index"] = anchor["initial_frame_index"]
    result = []
    for protocol, mode in (("hard-selective-V/v1", "V"), ("hard-selective-S/v1", "S")):
        sample_id = f"{case.case_id}_{mode}"
        mi = {
            "protocol": protocol,
            "protocol_note": ("视觉历史+统一机制规则；没有准确的逐步文字转录或完整事件前状态。"
                              if mode == "V" else "准确事件前状态+准确目标事件+统一规则；有意不提供图像或历史。"),
            "objects": _objects(ctx),
            "location_answer_labels": _location_labels(ctx),
            "location_definitions": _location_definitions(ctx),
            "initial_state_declarations": copy.deepcopy(ctx.public_declarations) if mode == "V" else [],
            "initial_identity_regions": anchors if mode == "V" else [],
            "history": [{"stage": "ordered_visual_history", "source": "按frames中顺序查看；重复数不是秒数。"}]
                       if mode == "V" else [],
            "state_before_event": _state_before(ctx) if mode == "S" else [],
            "rules": list(RULES),
            "event": _event_public(ctx) if mode == "S" else {"source": "最后一个目标事件视觉片段"},
            "frames": frames if mode == "V" else [], "questions": questions,
        }
        record_path = root / "data" / "input" / f"{sample_id}.json"
        if record_path.exists():
            raise FileExistsError(f"Refusing to replace public input: {record_path}")
        write_json(record_path, {"sample_id": sample_id, "model_input": mi})
        write_json(root / "prepared_requests" / f"{sample_id}.json", {
            "schema": "hard-request/v1", "status": "prepared_not_sent", "protocol": protocol,
            "model_input_sha256": sha_file(record_path), "media_sha256": media_hashes if mode == "V" else [],
            "model_input": mi, "request_text": request_text(mi),
            "audit_timeline_path": f"audit_traces/{case.case_id}/review_timeline.json",
        })
        write_json(root / "hidden_gold" / f"{sample_id}.json", {
            "sample_id": sample_id, "construction_status": "simulator_recorded_candidate",
            "review_status": "pending_human_review", "query_targets": gold_targets,
            "before_metadata": ctx.before_target, "after_metadata": ctx.after_target,
            "actual_target_event": ctx.target_event,
            "gold_source": "actual native before/after only; no expected design table",
            "position_change_threshold_m": 0.02,
        })
        result.append(sample_id)
    return result
