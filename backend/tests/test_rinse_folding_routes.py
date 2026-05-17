"""Folding performance API registration smoke tests."""

from __future__ import annotations

import unittest


class TestFoldingRoutesRegistered(unittest.TestCase):
    def test_folding_endpoints_registered(self):
        from backend.app import app

        rules = {r.rule for r in app.url_map.iter_rules()}
        self.assertIn("/rinse/bags/<bag_id>/recompute-folding", rules)
        self.assertIn("/rinse/folding/recompute", rules)
        self.assertIn("/rinse/folding/exceptions", rules)
        self.assertIn("/rinse/folding/stats/daily", rules)
        self.assertIn("/rinse/folding/benchmarks", rules)


if __name__ == "__main__":
    unittest.main()
