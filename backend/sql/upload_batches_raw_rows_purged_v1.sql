-- Option C retention: keep upload_batches header; mark when heavy child rows were purged.
ALTER TABLE upload_batches
  ADD COLUMN raw_rows_purged_at DATETIME NULL,
  ADD COLUMN purged_summary_json TEXT NULL;
