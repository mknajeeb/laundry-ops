-- Scheduled / server Rinse scrape run history (ACA job, manual CLI).
-- Table is also auto-created on first orchestrator run.

CREATE TABLE IF NOT EXISTS rinse_scrape_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    tenant_slug VARCHAR(64) NULL,
    rinse_vendor VARCHAR(16) NULL,
    run_type VARCHAR(16) NOT NULL DEFAULT 'scheduled',
    status VARCHAR(24) NOT NULL DEFAULT 'running',
    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    duration_seconds INT NULL,
    portal_csv_path VARCHAR(1024) NULL,
    scan_events_csv_path VARCHAR(1024) NULL,
    scan_events_events_path VARCHAR(1024) NULL,
    portal_rows_count INT NULL,
    scan_events_count INT NULL,
    imported_batch_id INT NULL,
    error_message TEXT NULL,
    log_path VARCHAR(1024) NULL,
    result_json LONGTEXT NULL,
    INDEX idx_rsr_org_started (organization_id, started_at DESC),
    INDEX idx_rsr_org_status (organization_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
