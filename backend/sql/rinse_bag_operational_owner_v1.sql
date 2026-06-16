-- Canonical operational owner per Rinse bag_id (WashPro vs VeeWash isolation).
-- One row per bag_id globally; assigned on first legitimate ingest or audit backfill.

CREATE TABLE IF NOT EXISTS rinse_bag_operational_owner (
  bag_id VARCHAR(64) NOT NULL PRIMARY KEY,
  owner_organization_id INT NOT NULL,
  owner_rinse_vendor VARCHAR(16) NOT NULL,
  assigned_at DATETIME NOT NULL,
  assignment_source VARCHAR(32) NOT NULL,
  locked TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_rboo_owner_org (owner_organization_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
