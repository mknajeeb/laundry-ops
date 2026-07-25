-- Additive manager-edit lock for WF Review / Edit Bag.
-- Safe to run repeatedly. ensure_shift_monitor_day_tables also applies this.

ALTER TABLE rinse_shift_monitor_day_bags
  ADD COLUMN manager_edit_version INT NOT NULL DEFAULT 0;
