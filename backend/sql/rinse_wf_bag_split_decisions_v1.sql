-- Canonical WF Split manager decisions (survive day rebuild).
CREATE TABLE IF NOT EXISTS rinse_wf_bag_split_decisions (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  shift_date_et DATE NOT NULL,
  bag_id VARCHAR(64) NOT NULL,
  decision VARCHAR(32) NOT NULL,
  note TEXT NULL,
  decided_by_user_id INT NULL,
  decided_by_display_name VARCHAR(255) NULL,
  decided_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wf_split_decision (organization_id, shift_date_et, bag_id),
  KEY idx_wf_split_decision_day (organization_id, shift_date_et, decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
