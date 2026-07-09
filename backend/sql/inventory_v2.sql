-- Inventory v2 — weekly stock checks, ordering, and settings.
-- Run against laundryapp after backup. Runtime ensure in inventory_module.py.
--
-- Migrates legacy inventory_items, inventory_counts, bag_sales in place.
-- New tables: categories, vendors, stock_checks, orders, adjustments.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS inventory_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL DEFAULT 1,
  name VARCHAR(100) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_inv_cat_org_name (organization_id, name),
  INDEX idx_inv_cat_org_sort (organization_id, is_active, sort_order)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_vendors (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL DEFAULT 1,
  name VARCHAR(150) NOT NULL,
  phone VARCHAR(50) NULL,
  email VARCHAR(150) NULL,
  payment_method VARCHAR(80) NULL,
  notes VARCHAR(500) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_inv_vendor_org_name (organization_id, name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_stock_checks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL DEFAULT 1,
  checked_by_user_id INT NULL,
  checked_by_name VARCHAR(150) NOT NULL,
  check_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  submitted_at DATETIME NULL,
  INDEX idx_inv_sc_org_date (organization_id, check_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_stock_check_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stock_check_id INT NOT NULL,
  item_id INT NOT NULL,
  counted_qty DECIMAL(10,2) NULL,
  previous_on_hand DECIMAL(10,2) NOT NULL DEFAULT 0,
  note VARCHAR(255) NULL,
  INDEX idx_inv_scl_check (stock_check_id),
  CONSTRAINT fk_inv_scl_check FOREIGN KEY (stock_check_id)
    REFERENCES inventory_stock_checks(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL DEFAULT 1,
  vendor_id INT NULL,
  vendor_name VARCHAR(150) NULL,
  order_date DATE NULL,
  expected_date DATE NULL,
  received_date DATE NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  tax DECIMAL(12,2) NOT NULL DEFAULT 0,
  shipping_charge DECIMAL(12,2) NOT NULL DEFAULT 0,
  additional_charge DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount DECIMAL(12,2) NOT NULL DEFAULT 0,
  grand_total DECIMAL(12,2) NOT NULL DEFAULT 0,
  ordered_by_user_id INT NULL,
  ordered_by_name VARCHAR(150) NULL,
  received_by_user_id INT NULL,
  received_by_name VARCHAR(150) NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_inv_ord_org_status (organization_id, status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_order_lines (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  item_id INT NOT NULL,
  qty_ordered DECIMAL(10,2) NOT NULL DEFAULT 0,
  qty_received DECIMAL(10,2) NOT NULL DEFAULT 0,
  unit_cost DECIMAL(12,4) NOT NULL DEFAULT 0,
  line_total DECIMAL(12,2) NOT NULL DEFAULT 0,
  notes VARCHAR(255) NULL,
  CONSTRAINT fk_inv_ol_order FOREIGN KEY (order_id)
    REFERENCES inventory_orders(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS inventory_adjustments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organization_id INT NOT NULL DEFAULT 1,
  item_id INT NOT NULL,
  adjustment_type VARCHAR(30) NOT NULL,
  qty_change DECIMAL(10,2) NOT NULL,
  reason VARCHAR(255) NULL,
  reference_type VARCHAR(30) NULL,
  reference_id INT NULL,
  created_by_user_id INT NULL,
  created_by_name VARCHAR(150) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Legacy inventory_items extended at runtime via ensure_inventory_tables().
