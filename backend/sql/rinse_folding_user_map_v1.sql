-- Map Rinse folding assigned_user_name to internal users.id for clock-hour productivity.
CREATE TABLE IF NOT EXISTS rinse_folding_user_map (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organization_id INT NOT NULL,
    rinse_user_name VARCHAR(255) NOT NULL,
    user_id INT NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rfum_org_name (organization_id, rinse_user_name),
    KEY idx_rfum_user (organization_id, user_id),
    CONSTRAINT fk_rfum_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
