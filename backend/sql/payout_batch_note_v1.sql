-- Batch-level paystub note (idempotent).
SET @db := DATABASE();

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'batch_note');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN batch_note TEXT NULL', 'SELECT ''skip batch_note'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
