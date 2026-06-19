-- Batch document mode: payment_receipt vs official_paystub (idempotent).
SET @db := DATABASE();

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'document_mode');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN document_mode VARCHAR(32) NULL', 'SELECT ''skip document_mode'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
