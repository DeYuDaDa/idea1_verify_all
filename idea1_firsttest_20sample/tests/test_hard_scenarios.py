"""Pure symbolic checks for the hard-case catalog and metadata label rules."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from hard_scenarios import cases, derive_answer, _sample_observation_window, _calibrate_forward


def test_catalog_has_twenty_ordered_case_ids_and_group_contracts():
    rows = cases()
    assert len(rows) == 20
    assert [row.case_id for row in rows] == [f"H{group:02d}-{variant}"
                                             for group in range(1, 6)
                                             for variant in range(1, 5)]
    assert [row.group_id for row in rows[::4]] == [f"H{i:02d}" for i in range(1, 6)]
    assert all(row.scene and row.family and row.title and callable(row.run) for row in rows)
    assert rows[4].scene == "FloorPlan6"
    assert rows[8].scene == "FloorPlan2"


def test_calibration_native_move_removes_object_from_nested_machine_before_restoring_surface():
    from copy import deepcopy
    from unittest.mock import patch
    import hard_scenarios

    class _CalibrationContext:
        roles = {"A": "Mug|A", "M": "CoffeeMachine|1"}
        waypoints = {"A_park": {"objectId": "CounterTop|1"}}

        def __init__(self):
            self.objects = [
                {"objectId": "Mug|A", "parentReceptacles": ["CounterTop|1"]},
                {"objectId": "CoffeeMachine|1", "parentReceptacles": ["CounterTop|1"],
                 "receptacleObjectIds": []},
                {"objectId": "CounterTop|1", "receptacleObjectIds": ["CoffeeMachine|1"]},
            ]
            self.moves = []
            self.checks = []
            self.session = self

        def snapshot(self):
            return {"objects": deepcopy(self.objects)}

        def obj(self, object_id):
            return next(row for row in self.objects if row["objectId"] == object_id)

        def mark_setup_stage(self, label, *, kind):
            self.setup_stage = (label, kind)

        def check(self, label, passed, evidence):
            self.checks.append((label, passed, evidence))

    ctx = _CalibrationContext()

    def native_move(context, role, slot):
        context.moves.append((role, slot))
        mug = context.obj("Mug|A")
        machine = context.obj("CoffeeMachine|1")
        if slot == "M":
            mug["parentReceptacles"] = ["CoffeeMachine|1", "CounterTop|1"]
            machine["receptacleObjectIds"] = ["Mug|A"]
        else:
            mug["parentReceptacles"] = ["CounterTop|1"]
            machine["receptacleObjectIds"] = []
        return {"lastActionSuccess": True}

    with patch.object(hard_scenarios, "_move", side_effect=native_move):
        _calibrate_forward(ctx, "A", "A_park", "M")

    assert ctx.moves == [("A", "M"), ("A", "A_park")]
    assert "CoffeeMachine|1" not in ctx.obj("Mug|A")["parentReceptacles"]
    assert "Mug|A" not in ctx.obj("CoffeeMachine|1")["receptacleObjectIds"]
    assert ctx.checks[-1][0] == "calibration_restore_A_A_park"
    assert ctx.checks[-1][1] is True
    assert ctx.checks[-1][2]["old_destination_cleared"] is True
    assert ctx.checks[-1][2]["before"]["objects"][0]["parentReceptacles"] == ["CounterTop|1"]
    assert ctx.checks[-1][2]["after_forward_placement"]["objects"][0]["parentReceptacles"] == [
        "CoffeeMachine|1", "CounterTop|1"]
    assert ctx.checks[-1][2]["after_restore"]["objects"][0]["parentReceptacles"] == ["CounterTop|1"]


def test_public_transfer_shows_the_same_placed_object_before_leaving_its_phase():
    from types import SimpleNamespace
    from unittest.mock import patch
    import hard_scenarios
    for public in (False, True):
        calls = []
        ctx = SimpleNamespace(roles={"Z": "same-potato"}, history_started=public,
                              navigate_to=lambda oid, why: calls.append(("show", oid)),
                              trace=SimpleNamespace(capture_current=lambda label: calls.append(("capture", label))))
        with patch.object(hard_scenarios, "_move", side_effect=lambda *args: calls.append(("move", args[2]))):
            hard_scenarios._native_transfer(ctx, "Z", "final_E")
        assert calls[0] == ("move", "final_E")
        if public:
            assert calls[1] == ("show", "same-potato") and calls[2][0] == "capture"
        else:
            assert len(calls) == 1


class _Context:
    roles = {"A": "Mug|A", "M": "CoffeeMachine|1", "Z": "Potato|1"}
    waypoints = {"CoffeeMachine": "CoffeeMachine|1", "inside": "Microwave|1"}
    before_target = {
        "objects": [
            {"objectId": "Mug|A", "position": {"x": 0.0, "y": 0.8, "z": 0.0}},
            {"objectId": "Potato|1", "position": {"x": 0.0, "y": 0.8, "z": 0.0}},
        ]
    }


def test_answers_require_actual_native_fields_and_use_small_position_tolerance():
    ctx = _Context()
    records = [
        {"objectId": "Mug|A", "isFilledWithLiquid": False, "fillLiquid": None,
         "position": {"x": 0.01, "y": 0.8, "z": 0.0}, "parentReceptacles": ["CoffeeMachine|1"]},
        {"objectId": "Potato|1", "isCooked": True, "temperature": "Hot",
         "position": {"x": 0.04, "y": 0.8, "z": 0.0}, "parentReceptacles": ["Microwave|1"]},
    ]
    metadata = {"objects": records}
    assert derive_answer({"subject": "A", "predicate": "liquid"}, metadata, ctx) == "Empty"
    assert derive_answer({"subject": "A", "predicate": "location"}, metadata, ctx) == "M"
    assert derive_answer({"subject": "A", "predicate": "world_position_changed"}, metadata, ctx) is False
    assert derive_answer({"subject": "Z", "predicate": "world_position_changed"}, metadata, ctx) is True
    assert derive_answer({"subject": "Z", "predicate": "isCooked"}, metadata, ctx) is True
    assert derive_answer({"subject": "Z", "predicate": "temperature"}, metadata, ctx) == "Hot"


def test_missing_or_inapplicable_metadata_stays_unknown():
    ctx = _Context()
    metadata = {"objects": [{"objectId": "Potato|1", "isCooked": False,
                             "position": {"x": 0.0, "y": 0.8, "z": 0.0}}]}
    assert derive_answer({"subject": "Z", "predicate": "temperature"}, metadata, ctx) is None
    assert derive_answer({"subject": "Z", "predicate": "location"}, metadata, ctx) is None
    assert derive_answer({"subject": "A", "predicate": "liquid"}, metadata, ctx) is None
    assert derive_answer({"subject": "Z", "predicate": "world_position_changed"}, metadata, ctx) is False


def test_location_uses_native_ancestry_and_rejects_ambiguous_unrelated_parents():
    class _LocationContext:
        roles = {"A": "Mug|A", "M": "CoffeeMachine|1", "P": "Plate|1"}
        waypoints = {"park": {"objectId": "CounterTop|1"},
                     "unrelated": {"objectId": "SideTable|1"}}
        before_target = {}

    ctx = _LocationContext()
    nested = {"objects": [
        {"objectId": "Mug|A", "parentReceptacles": ["CoffeeMachine|1", "CounterTop|1"]},
        {"objectId": "CoffeeMachine|1", "parentReceptacles": ["CounterTop|1"],
         "receptacleObjectIds": ["Mug|A"]},
        {"objectId": "CounterTop|1", "parentReceptacles": None, "receptacleObjectIds": ["CoffeeMachine|1"]},
    ]}
    assert derive_answer({"subject": "A", "predicate": "location"}, nested, ctx) == "M"

    ambiguous = {"objects": [
        {"objectId": "Mug|A", "parentReceptacles": ["Plate|1", "SideTable|1"]},
        {"objectId": "Plate|1"},
        {"objectId": "SideTable|1"},
    ]}
    assert derive_answer({"subject": "A", "predicate": "location"}, ambiguous, ctx) is None


def test_observation_pass_zero_is_immediate_and_offsets_are_cumulative():
    class _FakeSession:
        def __init__(self, owner):
            self.owner = owner

        def snapshot(self):
            return {"objects": [{"objectId": "Potato|1", "pass": self.owner.pass_count}]}

    class _FakeContext:
        roles = {"Z": "Potato|1"}

        def __init__(self):
            self.pass_count = 0
            self.steps = []
            self.phases = []
            self.session = _FakeSession(self)

        def obj(self, role):
            return self.session.snapshot()["objects"][0]

        def phase(self, label, *, public=True, kind="history"):
            self.phases.append((label, self.pass_count, public, kind))

        def step(self, action):
            assert action == "Pass"
            self.pass_count += 1
            self.steps.append(action)

    ctx = _FakeContext()
    rows, total = _sample_observation_window(ctx, (0, 1, 4, 12))
    assert [row["pass"] for row in rows] == [0, 1, 4, 12]
    assert [row["metadata"]["Z"]["pass"] for row in rows] == [0, 1, 4, 12]
    assert total == 12 and len(ctx.steps) == 12
    assert all(kind == "observation" and public for _, _, public, kind in ctx.phases)
    assert ctx.phases[0][1] == 0


def test_public_queries_do_not_embed_planned_gold_and_no_cooking_shortcut_is_used():
    source = Path(__file__).parents[1].joinpath("hard_scenarios.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "expected_gold" not in source.lower()
    assert "CookObject" not in source
    assert "SetObjectPoses" not in source
    # H05 cooks through the appliance and its native toggle, never a state setter.
    assert "_h05_cook_history_native" in source
    assert 'set_toggle(ctx.roles["Microwave"], True)' in source
    assert "native_move_" in source
    uncooked = source[source.index('H05 uncooked history: place Potato inside'):source.index('H05 place at final inside/outside position and close appliance')]
    assert 'set_open(ctx.roles["Microwave"], False)' in uncooked
    assert 'for _ in range(4):\n            ctx.step("Pass")' in uncooked
    assert 'set_open(ctx.roles["Microwave"], True)' in uncooked
    assert 'set_toggle(ctx.roles["Microwave"], True)' not in uncooked
    assert 'isCooked") is False' in uncooked and '_temperature(ctx.obj("Z")) == "RoomTemp"' in uncooked


def load_tests(loader, tests, pattern):
    # These dependency-free functions also run under the server's existing
    # unittest entrypoint; do not silently report a zero-test success.
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items()
                              if name.startswith("test_") and callable(value))

