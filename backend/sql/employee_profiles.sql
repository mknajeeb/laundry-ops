USE laundryapp;

CREATE TABLE IF NOT EXISTS employee_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(120) NOT NULL,
    employment_type VARCHAR(30) NOT NULL DEFAULT 'WASHPRO_W2',
    address_line1 VARCHAR(255) NULL,
    address_line2 VARCHAR(255) NULL,
    city VARCHAR(100) NULL,
    state VARCHAR(50) NULL,
    zip_code VARCHAR(20) NULL,
    tax_id_type VARCHAR(10) NULL,
    tax_id_value VARCHAR(30) NULL,
    pay_rate DECIMAL(10,2) NULL DEFAULT 0,
    overtime_rate DECIMAL(10,2) NULL DEFAULT 0,
    spread_of_time_rate DECIMAL(10,2) NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    UNIQUE KEY uq_employee_profiles_emp_id (employee_id),
    INDEX idx_employee_profiles_name (last_name, first_name),
    INDEX idx_employee_profiles_type (employment_type)
);

-- Allowed employment_type values:
-- WASHPRO_W2, WASHPRO_1099, WASHMATE_1099
-- Allowed tax_id_type values:
-- SSN, ITIN
