-- Supply Product Master (Phase A)
-- Laundry process products + effective-dated package pricing.
-- Intentionally separate from inventory_items (warehouse stock/count/order domain).

CREATE TABLE IF NOT EXISTS supply_products (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  product_code VARCHAR(64) NULL,
  supply_type VARCHAR(40) NOT NULL,
  brand VARCHAR(100) NOT NULL,
  product_name VARCHAR(150) NOT NULL,
  vendor VARCHAR(150) NULL,
  form VARCHAR(20) NOT NULL DEFAULT 'LIQUID',
  package_qty DECIMAL(12,4) NOT NULL,
  package_unit VARCHAR(20) NOT NULL DEFAULT 'oz',
  average_dose DECIMAL(12,4) NOT NULL,
  dose_unit VARCHAR(20) NOT NULL DEFAULT 'oz',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  legacy_report_key VARCHAR(64) NULL,
  inventory_item_id INT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_supply_prod_org_legacy (organization_id, legacy_report_key),
  UNIQUE KEY uq_supply_prod_org_code (organization_id, product_code),
  KEY idx_supply_prod_org_type (organization_id, supply_type, is_active),
  KEY idx_supply_prod_org_active (organization_id, is_active, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supply_product_prices (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL,
  product_id INT NOT NULL,
  purchase_price_per_package DECIMAL(12,4) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE NULL,
  notes VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_spp_org_product (organization_id, product_id),
  KEY idx_spp_product_dates (product_id, effective_from, effective_to),
  CONSTRAINT fk_spp_product
    FOREIGN KEY (product_id) REFERENCES supply_products(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
