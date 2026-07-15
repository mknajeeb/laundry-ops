"""Tests for bag-level discrete-event Shift Capacity Planner."""

from backend.shift_capacity_des import apply_des_action, parse_des_inputs, run_bag_des_simulation


def _base(**overrides):
    payload = {
        "engine": "bag_des",
        "start_time": "7:00 AM",
        "target_time": "12:00 PM",
        "bag_count": 16,
        "avg_lbs_per_bag": 20,
        "batch_size": 8,
        "batch_limit_mode": "whichever_first",
        "washer_count": 2,
        "dryer_count": 2,
        "washer_capacity_lb": 80,
        "dryer_capacity_lb": 80,
        "wash_cycle_min": 30,
        "dry_cycle_min": 40,
        "weigh_min_per_bag": 1,
        "sort_min_per_bag": 4,
        "load_washer_min": 2,
        "unload_transfer_min": 3,
        "load_dryer_min": 2,
        "unload_dryer_min": 0,
        "fold_rate_mode": "lbs_per_hour",
        "fold_lbs_per_hour": 40,
        "employees": [
            {"id": "W1", "name": "Weigher 1", "primary_role": "weigher", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {"id": "H1", "name": "Washer 1", "primary_role": "washer", "start_time": "7:00 AM", "end_time": "3:00 PM"},
            {
                "id": "F1",
                "name": "Folder 1",
                "primary_role": "folder",
                "start_time": "7:00 AM",
                "end_time": "3:00 PM",
                "fold_lbs_per_hour": 35,
            },
            {
                "id": "F2",
                "name": "Folder 2",
                "primary_role": "folder",
                "start_time": "8:00 AM",
                "end_time": "3:00 PM",
                "fold_lbs_per_hour": 40,
            },
        ],
    }
    payload.update(overrides)
    return payload


class TestBatchCapacity:
    def test_pound_capacity_limits_batch_before_bag_count(self):
        # 8-bag limit but 80 lb capacity / 20 lb bags => 4 bags
        result = run_bag_des_simulation(_base(batch_size=8, washer_capacity_lb=80, avg_lbs_per_bag=20, bag_count=12))
        batches = result["ready_to_fold_by_batch"]
        assert batches
        assert batches[0]["bags"] == 4
        assert batches[0]["pounds"] <= 80 + 1e-6

    def test_bag_limit_reached_before_pounds(self):
        result = run_bag_des_simulation(
            _base(batch_size=3, washer_capacity_lb=500, avg_lbs_per_bag=10, bag_count=9)
        )
        assert result["ready_to_fold_by_batch"][0]["bags"] == 3


class TestRoleSharing:
    def test_weigher_and_washer_same_person_no_overlap(self):
        payload = _base(
            weigher_washer_same=True,
            employees=[
                {
                    "id": "E1",
                    "name": "Employee 1",
                    "primary_role": "weigher",
                    "secondary_roles": ["washer"],
                    "start_time": "7:00 AM",
                    "end_time": "3:00 PM",
                },
                {"id": "S1", "name": "Sorter 1", "primary_role": "sorter", "start_time": "7:00 AM"},
                {
                    "id": "F1",
                    "name": "Folder 1",
                    "primary_role": "folder",
                    "start_time": "7:00 AM",
                    "fold_lbs_per_hour": 40,
                },
            ],
            bag_count=6,
            washer_count=1,
            dryer_count=1,
        )
        result = run_bag_des_simulation(payload)
        assert result["simulation_valid"] is True
        # Named assignment present
        for row in result["bag_rows"]:
            assert row["weighed_by"]
            assert row["washer_loaded_by"]


class TestFolderEntry:
    def test_folder_two_starts_later(self):
        result = run_bag_des_simulation(_base(bag_count=8))
        folded_by = {r["folded_by"] for r in result["bag_rows"]}
        assert "Folder 1" in folded_by
        # Folder 2 starts 8:00; some bags should still be assignable after that
        assert result["summary"]["bags_ready_by_target"] >= 1


class TestWeightsAndOrders:
    def test_uneven_bag_weights(self):
        result = run_bag_des_simulation(
            _base(
                bag_count=4,
                bag_weights=[18.2, 21.6, 17.9, 22.0],
                batch_size=8,
                washer_capacity_lb=80,
            )
        )
        weights = [r["weight"] for r in result["bag_rows"]]
        assert weights == [18.2, 21.6, 17.9, 22.0]

    def test_order_identity_preserved(self):
        result = run_bag_des_simulation(
            {
                **_base(bag_count=3),
                "orders": [
                    {
                        "order_number": "10482",
                        "bag_count": 3,
                        "weights": [18.2, 21.6, 17.9],
                        "two_washer": True,
                    }
                ],
            }
        )
        assert all(r["order"] == "10482" for r in result["bag_rows"])
        assert len(result["bag_rows"]) == 3


class TestHandlingDelays:
    def test_loading_and_transfer_delay_ready_time(self):
        fast = run_bag_des_simulation(
            _base(bag_count=4, batch_size=4, load_washer_min=1, unload_transfer_min=1, load_dryer_min=1)
        )
        slow = run_bag_des_simulation(
            _base(bag_count=4, batch_size=4, load_washer_min=10, unload_transfer_min=10, load_dryer_min=10)
        )
        assert slow["ready_to_fold_by_batch"][0]["ready_to_fold_min"] > fast["ready_to_fold_by_batch"][0][
            "ready_to_fold_min"
        ]


class TestStaffingInjection:
    def test_add_washer_mid_shift_action(self):
        base = _base(bag_count=12)
        before = run_bag_des_simulation(base)
        patched = apply_des_action(
            base,
            {
                "staffing_event": {
                    "type": "add_employee",
                    "name": "Washer 2",
                    "primary_role": "washer",
                    "start_time": "8:30 AM",
                }
            },
        )
        after = run_bag_des_simulation(patched)
        assert any(e["name"] == "Washer 2" for e in after["employees"])
        assert after["summary"]["final_completion_time"] is not None
        assert before["summary"]["bags_ready_by_target"] >= 0


class TestAvailabilityAndReady:
    def test_ready_counts_monotonic_30min(self):
        result = run_bag_des_simulation(_base(bag_count=16))
        ready = [r["bags_ready"] for r in result["availability_30min"]]
        folded = [r["bags_folded"] for r in result["availability_30min"]]
        assert ready == sorted(ready)
        assert folded == sorted(folded)
        assert result["ready_to_fold_by_batch"][-1]["cumulative_bags_ready"] == 16

    def test_no_resource_overlap(self):
        result = run_bag_des_simulation(_base(bag_count=20, washer_count=2, dryer_count=2))
        assert result["simulation_valid"] is True
        assert result["overlap_errors"] == []


class TestParse:
    def test_defaults_employees(self):
        inp = parse_des_inputs({"bag_count": 10, "start_time": "7:00 AM", "target_time": "12:00 PM"})
        assert inp.employees
        assert inp.washer_capacity_lb == 80


class TestSplitOrders:
    def test_two_washer_order_uses_multiple_washers(self):
        result = run_bag_des_simulation(
            {
                **_base(bag_count=4, washer_count=2, dryer_count=2, batch_size=8, washer_capacity_lb=200),
                "orders": [
                    {
                        "order_number": "10482",
                        "bag_count": 4,
                        "weights": [20, 20, 20, 20],
                        "two_washer": True,
                    }
                ],
            }
        )
        washers = {r["washer"] for r in result["bag_rows"]}
        assert len(washers) >= 2

    def test_two_dryer_order_uses_multiple_dryers(self):
        result = run_bag_des_simulation(
            {
                **_base(bag_count=4, washer_count=2, dryer_count=2, batch_size=8, washer_capacity_lb=200),
                "orders": [
                    {
                        "order_number": "10483",
                        "bag_count": 4,
                        "weights": [20, 20, 20, 20],
                        "two_dryer": True,
                    }
                ],
            }
        )
        dryers = {r["dryer"] for r in result["bag_rows"]}
        assert len(dryers) >= 2
