-- Optional: table is auto-created on first async Rinse import.
-- Run manually if your DBA prefers migrations before deploy.

CREATE TABLE IF NOT EXISTS rinse_import_jobs (
    id CHAR(36) NOT NULL PRIMARY KEY,
    organization_id INT NOT NULL,
    user_id INT NOT NULL,
    batch_date DATE NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'queued',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    progress_note VARCHAR(512) NULL,
    result_json LONGTEXT NULL,
    error_summary VARCHAR(4000) NULL,
    http_status INT NULL,
    exit_code INT NULL,
    stdout_tail MEDIUMTEXT NULL,
    stderr_tail MEDIUMTEXT NULL,
    INDEX idx_rinse_job_org_created (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
