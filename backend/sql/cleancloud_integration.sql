USE laundryapp;

CREATE TABLE IF NOT EXISTS cleancloud_webhook_events (
  id INT AUTO_INCREMENT PRIMARY KEY,
  event_id VARCHAR(120) NULL,
  event_type VARCHAR(80) NULL,
  payload_json LONGTEXT NOT NULL,
  process_status VARCHAR(20) NOT NULL DEFAULT 'RECEIVED',
  error_message VARCHAR(500) NULL,
  received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at DATETIME NULL,
  updated_at DATETIME NULL,
  UNIQUE KEY ux_cleancloud_event_id (event_id),
  INDEX idx_cleancloud_event_type (event_type),
  INDEX idx_cleancloud_received_at (received_at)
);

CREATE TABLE IF NOT EXISTS cleancloud_customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cleancloud_customer_id VARCHAR(120) NOT NULL,
  first_name VARCHAR(120) NULL,
  last_name VARCHAR(120) NULL,
  full_name VARCHAR(255) NULL,
  phone VARCHAR(60) NULL,
  email VARCHAR(255) NULL,
  status VARCHAR(60) NULL,
  address_line1 VARCHAR(255) NULL,
  address_line2 VARCHAR(255) NULL,
  city VARCHAR(120) NULL,
  state VARCHAR(120) NULL,
  postal_code VARCHAR(40) NULL,
  country VARCHAR(120) NULL,
  raw_json LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,
  last_seen_at DATETIME NULL,
  UNIQUE KEY ux_cleancloud_customer_id (cleancloud_customer_id),
  INDEX idx_cleancloud_customer_name (full_name),
  INDEX idx_cleancloud_customer_phone (phone),
  INDEX idx_cleancloud_customer_email (email)
);

CREATE TABLE IF NOT EXISTS cleancloud_orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cleancloud_order_id VARCHAR(120) NOT NULL,
  cleancloud_customer_id VARCHAR(120) NULL,
  order_status VARCHAR(80) NULL,
  payment_status VARCHAR(80) NULL,
  service_type VARCHAR(120) NULL,
  pickup_date DATETIME NULL,
  delivery_date DATETIME NULL,
  total_amount DECIMAL(10,2) NULL,
  currency VARCHAR(10) NULL,
  cleaned_by VARCHAR(150) NULL,
  picked_up_by VARCHAR(150) NULL,
  delivered_by VARCHAR(150) NULL,
  ticket_number VARCHAR(120) NULL,
  raw_json LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,
  last_seen_at DATETIME NULL,
  UNIQUE KEY ux_cleancloud_order_id (cleancloud_order_id),
  INDEX idx_cleancloud_order_status (order_status),
  INDEX idx_cleancloud_order_customer (cleancloud_customer_id),
  INDEX idx_cleancloud_order_delivery (delivery_date)
);
