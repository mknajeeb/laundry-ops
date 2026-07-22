-- Step-1 manager corrections audit (also created via ensure_step1_correction_table).
CREATE TABLE IF NOT EXISTS rinse_step1_corrections (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    bag_id VARCHAR(32) NOT NULL,
    action VARCHAR(64) NOT NULL,
    reason_code VARCHAR(64) NULL,
    reason_text VARCHAR(512) NOT NULL,
    previous_values JSON NULL,
    new_values JSON NULL,
    actor_user_id INT NULL,
    actor_display_name VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_step1_corr_org_bag (organization_id, bag_id),
    INDEX idx_step1_corr_created (organization_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
