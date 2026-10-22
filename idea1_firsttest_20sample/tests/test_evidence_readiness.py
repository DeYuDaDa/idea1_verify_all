import unittest

from validate import _reviewed_fact_readiness


class EvidenceReadinessTests(unittest.TestCase):
    def test_review_resolves_only_matching_unassessed_facts_without_changing_gold(self):
        original = {"actual_facts_diff": [
            {"fact_id": "a", "knowability": "not_assessed", "after": {"value": True}},
            {"fact_id": "b", "knowability": "unknown", "after": {"value": False}},
            {"fact_id": "c", "knowability": "not_assessed"},
        ]}
        reviewed = _reviewed_fact_readiness(original, {"a", "b"})
        self.assertEqual(reviewed["actual_facts_diff"][0]["knowability"], "knowable")
        self.assertEqual(reviewed["actual_facts_diff"][1]["knowability"], "unknown")
        self.assertEqual(reviewed["actual_facts_diff"][2]["knowability"], "not_assessed")
        self.assertEqual(original["actual_facts_diff"][0]["knowability"], "not_assessed")
        self.assertEqual(reviewed["actual_facts_diff"][0]["after"], {"value": True})


if __name__ == "__main__":
    unittest.main()
