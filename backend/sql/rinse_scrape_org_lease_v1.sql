-- Per-org fencing token for scheduled Rinse sync.
-- Late writers from a fenced generation must not confirm/import/project.
CREATE TABLE IF NOT EXISTS rinse_scrape_org_lease (
    organization_id INT NOT NULL PRIMARY KEY,
    generation BIGINT NOT NULL DEFAULT 0,
    owner_run_id BIGINT NULL,
    owner_execution_name VARCHAR(256) NULL,
    owner_pid INT NULL,
    heartbeat_at DATETIME(6) NULL,
    last_progress_at DATETIME(6) NULL,
    current_stage VARCHAR(64) NULL,
    fenced_at DATETIME(6) NULL,
    fence_reason VARCHAR(255) NULL,
    updated_at DATETIME(6) NOT NULL,
    INDEX idx_rs_lease_owner_run (owner_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
