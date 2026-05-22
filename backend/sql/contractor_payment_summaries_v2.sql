-- Extend contractor payment summaries for universal invoice/receipt + YTD/1099 tracking.
-- Applied at runtime via ensure_contractor_payment_summaries_table(); run manually if needed.

ALTER TABLE contractor_payment_summaries MODIFY user_id INT NULL;

ALTER TABLE contractor_payment_summaries
  ADD COLUMN IF NOT EXISTS contractor_type VARCHAR(32) NOT NULL DEFAULT 'regular',
  ADD COLUMN IF NOT EXISTS worker_name_snapshot VARCHAR(255) NULL,
  ADD COLUMN IF NOT EXISTS worker_phone_snapshot VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS worker_email_snapshot VARCHAR(255) NULL,
  ADD COLUMN IF NOT EXISTS work_performed TEXT NULL,
  ADD COLUMN IF NOT EXISTS total_amount_due DECIMAL(10,2) NULL,
  ADD COLUMN IF NOT EXISTS amount_paid DECIMAL(10,2) NULL,
  ADD COLUMN IF NOT EXISTS payment_date DATE NULL,
  ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'paid',
  ADD COLUMN IF NOT EXISTS source_type VARCHAR(32) NOT NULL DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS source_clock_batch_id INT NULL,
  ADD COLUMN IF NOT EXISTS signed_document_record_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
