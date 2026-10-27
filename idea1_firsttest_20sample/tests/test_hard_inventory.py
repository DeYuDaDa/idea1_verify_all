"""Pure metadata checks for conditional hard-group inventory gates."""
from hard_inventory import check_inventory, inventory_requirements


def test_requirements_are_static_distinct_instance_and_capability_gates():
    requirements = inventory_requirements("H01")
    assert requirements[0] == {
        "object_type": "Mug", "min_count": 2,
        "capabilities": ["canFillWithLiquid"],
    }
    one_mug = {"objects": [
        {"objectId": "Mug|1", "objectType": "Mug", "canFillWithLiquid": True},
        {"objectId": "Mug|1", "objectType": "Mug", "canFillWithLiquid": True},
        {"objectId": "CoffeeMachine|1", "objectType": "CoffeeMachine"},
    ]}
    result = check_inventory("H01", one_mug)
    assert result["satisfied"] is False
    assert result["missing"][0]["available_count"] == 1
    assert result["missing"][0]["native_type_count"] == 2


def test_missing_capability_is_separate_from_raw_type_count():
    result = check_inventory("H02", {"objects": [
        {"objectId": "Plate|1", "objectType": "Plate", "pickupable": True},
        {"objectId": "Plate|2", "objectType": "Plate", "pickupable": True, "receptacle": True},
        {"objectId": "Apple|1", "objectType": "Apple", "pickupable": True},
    ]})
    assert result["satisfied"] is False
    assert result["missing"] == [{
        "object_type": "Plate", "min_count": 2,
        "capabilities": ["pickupable", "receptacle"],
        "available_count": 1, "native_type_count": 2,
    }]


def test_unknown_group_is_rejected_and_no_metadata_is_mutated():
    metadata = {"objects": [{"objectId": "Potato|1", "objectType": "Potato"}]}
    before = repr(metadata)
    result = check_inventory("H05", metadata)
    assert result["satisfied"] is False
    assert metadata["objects"][0]["objectId"] == "Potato|1"
    assert repr(metadata) == before
    try:
        inventory_requirements("H99")
    except ValueError as exc:
        assert "Unknown hard group" in str(exc)
    else:
        raise AssertionError("unknown group must not be silently accepted")
