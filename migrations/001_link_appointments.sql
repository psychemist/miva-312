ALTER TABLE tbl_appointment
    ADD COLUMN user_id BIGINT UNSIGNED NULL AFTER reference,
    ADD KEY ix_appointment_user (user_id),
    ADD CONSTRAINT fk_appointment_user FOREIGN KEY (user_id)
        REFERENCES tbl_user(id) ON DELETE SET NULL
