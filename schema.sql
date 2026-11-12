-- Run this inside your selected MySQL database (for example, pawkin).
-- Password stores a salted Werkzeug scrypt hash, never a plaintext password.
CREATE TABLE IF NOT EXISTS tbl_user (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tbl_appointment (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference VARCHAR(15) NOT NULL,
    owner_name VARCHAR(100) NOT NULL,
    email VARCHAR(254) NOT NULL,
    phone VARCHAR(30) NOT NULL,
    pet_name VARCHAR(80) NOT NULL,
    species VARCHAR(20) NOT NULL,
    service VARCHAR(30) NOT NULL,
    preferred_date DATE NOT NULL,
    preferred_time TIME NOT NULL,
    notes VARCHAR(1000) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_appointment_reference (reference),
    KEY ix_appointment_date (preferred_date, preferred_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
