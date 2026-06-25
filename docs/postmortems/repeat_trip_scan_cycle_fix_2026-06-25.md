# Repeat-Trip Scan Cycle Fix — Postmortem (2026-06-25)

**Commits:** `21afbd5`, `8ac53fa`, `9ebcee2`  
**Verification:** `python3 -m backend.scripts.verify_repeat_trip_fixes`

---

## Problem

- Repeat-trip bags were incorrectly treated as a single lifecycle.
- Sorting sessions could span multiple customer/vendor cycles (e.g. Francis 194h on `DJMFG1YEH7`).
- Previously completed bags re-entering service were classified as stale and excluded from today's workload (e.g. `73NBRCJBHJ`, `86CK96LI6E`, `DJMFG1YEH7` on 2026-06-25).

## Root Cause

- Lifecycle anchoring used an earlier vendor cycle instead of the current one.
- Sort end detection did not always stop at wash handoff or vendor cycle reset.
- Workload baseline did not recognize a same-day `sent-to-vendor` as a new lifecycle.

## Fixes

- Latest `sent-to-vendor` becomes lifecycle anchor (`lifecycle_anchor` in `rinse_bag_stage_bounds.py`).
- Sorting session capped at:
  - wash handoff,
  - split-load,
  - create-issue,
  - cross-employee transition,
  - vendor cycle reset.
- Same-day `sent-to-vendor` opens a fresh workload cycle (`_classify_baseline_seed_bag`).
- Repeat-trip completions count toward today's workload (`bags_completed_today` loop).
- Stale bucket ignores bags with same-day lifecycle reset (`_load_completed_before_day_start_still_present`).

## Regression Tests

### Repeat-trip sorting

| Test | File |
|------|------|
| `TestRepeatTripSortingCycleBoundaries::test_DJMFG1YEH7_latest_vendor_cycle_only_on_selected_day` | `backend/tests/test_sorting_chronology.py` |
| `TestRepeatTripSortingCycleBoundaries::test_sorting_end_capped_at_wash_handoff_not_later_cycle` | `backend/tests/test_sorting_chronology.py` |
| `test_86CK96LI6E_cross_employee_weight_not_sort_start` | `backend/tests/test_sorting_chronology.py` |
| `test_COXWJMCCPH_ready_washer_does_not_extend_sort_end` | `backend/tests/test_sorting_chronology.py` |
| `test_697BP084AA_ignores_jennifer_add_photos_after_wash_before_create_issue` | `backend/tests/test_sorting_chronology.py` |
| `test_D6E0SRN9QV_ignores_jennifer_add_photos_after_wash_setup` | `backend/tests/test_sorting_chronology.py` |
| `test_1VMV2DUPUW_ignores_jennifer_add_photos_after_create_issue` | `backend/tests/test_sorting_chronology.py` |
| `test_COXWJMCCPH_ignores_jennifer_add_photos_after_ready_washer` | `backend/tests/test_sorting_chronology.py` |

### Repeat-trip workload

| Test | File |
|------|------|
| `TestCrossDayCompletionAttribution::test_baseline_seed_resend_today_opens_new_cycle` | `backend/tests/test_rinse_at_vendor_module.py` |
| `TestCrossDayCompletionAttribution::test_bags_completed_today_includes_repeat_trip_resend_completion` | `backend/tests/test_rinse_at_vendor_module.py` |
| `test_resend_same_day_resets_completion_anchor` | `backend/tests/test_rinse_at_vendor_module.py` |

### Stale bucket

| Test | File |
|------|------|
| `TestCrossDayCompletionAttribution::test_still_present_skips_bags_with_same_day_sent_to_vendor_reset` | `backend/tests/test_rinse_at_vendor_module.py` |
| `TestCrossDayCompletionAttribution::test_clean_baseline_excludes_completed_before_day_start_from_workload` | `backend/tests/test_rinse_at_vendor_module.py` |

### Lifecycle anchor

| Test | File |
|------|------|
| `TestRepeatTripSortingCycleBoundaries::test_lifecycle_anchor_uses_latest_sent_to_vendor` | `backend/tests/test_sorting_chronology.py` |
| `test_resend_same_day_resets_completion_anchor` | `backend/tests/test_rinse_at_vendor_module.py` |

### Wash handoff

| Test | File |
|------|------|
| `test_BZABOG8NPP_wash_handoff_add_photos_credits_weigh_operator` | `backend/tests/test_sorting_chronology.py` |
| `TestRepeatTripSortingCycleBoundaries::test_sorting_end_capped_at_wash_handoff_not_later_cycle` | `backend/tests/test_sorting_chronology.py` |
| `TestSortingSessionEnd::test_ready_washer_does_not_extend_sorting` | `backend/tests/test_sorting_session.py` |
| `TestSortingSessionEnd::test_different_user_ready_washer_not_used` | `backend/tests/test_sorting_session.py` |
| `TestSortingSessionEnd::test_split_load_then_create_issue` | `backend/tests/test_sorting_session.py` |

Run the focused suite:

```bash
python3 -m pytest \
  backend/tests/test_sorting_chronology.py::TestRepeatTripSortingCycleBoundaries \
  backend/tests/test_rinse_at_vendor_module.py::TestCrossDayCompletionAttribution \
  -q
```

## Lessons Learned

Engineering rules going forward:

1. **Every customer pickup starts a new lifecycle.**
2. **Scan history must always be interpreted in lifecycle context.**
3. **Read-time aggregation must never merge events across lifecycles.**
4. **Every production bug must receive a permanent regression test before closure.**
