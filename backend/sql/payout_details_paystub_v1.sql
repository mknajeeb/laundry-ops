-- Payout details, accountant payment confirmation, paystub workflow (idempotent).
SET @db := DATABASE();

-- payout_batches: accountant confirm + admin finalize timestamps
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'accountant_payment_confirmed_at');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN accountant_payment_confirmed_at DATETIME NULL', 'SELECT ''skip accountant_payment_confirmed_at'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'accountant_payment_confirmed_by');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN accountant_payment_confirmed_by INT NULL', 'SELECT ''skip accountant_payment_confirmed_by'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'payout_details_finalized_at');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN payout_details_finalized_at DATETIME NULL', 'SELECT ''skip payout_details_finalized_at'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'payout_details_finalized_by');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN payout_details_finalized_by INT NULL', 'SELECT ''skip payout_details_finalized_by'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batches' AND COLUMN_NAME = 'payout_details_audit_json');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batches ADD COLUMN payout_details_audit_json JSON NULL', 'SELECT ''skip payout_details_audit_json'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- payout_batch_lines: flexible deduction / payment / settlement blob
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'payout_batch_lines' AND COLUMN_NAME = 'payout_details_json');
SET @sql := IF(@c = 0, 'ALTER TABLE payout_batch_lines ADD COLUMN payout_details_json JSON NULL', 'SELECT ''skip payout_details_json'' AS _note');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
