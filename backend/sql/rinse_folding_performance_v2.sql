-- Phase 3: exception review + scoring columns on rinse_folding_performance
ALTER TABLE rinse_folding_performance
  ADD COLUMN scoring_status VARCHAR(24) NULL AFTER status,
  ADD COLUMN included_in_scoring TINYINT(1) NOT NULL DEFAULT 0 AFTER scoring_status,
  ADD COLUMN reviewed_at DATETIME NULL AFTER included_in_scoring,
  ADD COLUMN reviewed_by_user_id INT NULL AFTER reviewed_at,
  ADD COLUMN exception_review_note TEXT NULL AFTER reviewed_by_user_id;
