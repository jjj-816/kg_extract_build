CREATE TABLE IF NOT EXISTS audit_document (
    document_id CHAR(36) PRIMARY KEY,
    original_filename VARCHAR(512) NOT NULL,
    file_type VARCHAR(16) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    original_path TEXT NOT NULL,
    converted_path TEXT NULL,
    parse_status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_audit_document_hash (content_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_document_block (
    block_id VARCHAR(80) PRIMARY KEY,
    document_id CHAR(36) NOT NULL,
    ordinal INT UNSIGNED NOT NULL,
    block_type VARCHAR(32) NOT NULL,
    section_path JSON NULL,
    source_locator VARCHAR(512) NOT NULL,
    raw_text LONGTEXT NOT NULL,
    normalized_text LONGTEXT NOT NULL,
    table_json JSON NULL,
    image_refs_json JSON NULL,
    parse_status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_audit_block_document_ordinal (document_id, ordinal),
    CONSTRAINT fk_audit_block_document FOREIGN KEY (document_id)
        REFERENCES audit_document(document_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_run (
    run_id CHAR(36) PRIMARY KEY,
    document_id CHAR(36) NOT NULL,
    status VARCHAR(32) NOT NULL,
    project_name VARCHAR(512) NULL,
    audit_year INT UNSIGNED NULL,
    work_purpose TEXT NULL,
    task_library_id VARCHAR(255) NOT NULL,
    task_library_version VARCHAR(64) NOT NULL,
    task_library_hash CHAR(64) NOT NULL,
    binding_version VARCHAR(128) NOT NULL,
    config_snapshot JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_run_document FOREIGN KEY (document_id)
        REFERENCES audit_document(document_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_run_work_type (
    run_id CHAR(36) NOT NULL,
    work_type VARCHAR(255) NOT NULL,
    PRIMARY KEY (run_id, work_type),
    CONSTRAINT fk_audit_work_type_run FOREIGN KEY (run_id)
        REFERENCES audit_run(run_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_task_execution (
    execution_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    task_snapshot JSON NOT NULL,
    route VARCHAR(64) NOT NULL,
    execution_status VARCHAR(32) NOT NULL,
    result_status VARCHAR(32) NULL,
    failure_reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_audit_execution_run_task (run_id, task_id),
    CONSTRAINT fk_audit_execution_run FOREIGN KEY (run_id)
        REFERENCES audit_run(run_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_declared_norm (
    declared_norm_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    raw_reference_text TEXT NOT NULL,
    normalized_code VARCHAR(255) NULL,
    family_id CHAR(36) NULL,
    version_id CHAR(36) NULL,
    source_block_id VARCHAR(80) NULL,
    coverage_status VARCHAR(32) NOT NULL,
    year_status VARCHAR(32) NULL,
    is_supplementary TINYINT(1) NOT NULL DEFAULT 0,
    human_confirmation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_declared_norm_run FOREIGN KEY (run_id)
        REFERENCES audit_run(run_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_declared_norm_block FOREIGN KEY (source_block_id)
        REFERENCES audit_document_block(block_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_task_evidence (
    task_evidence_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    execution_id BIGINT UNSIGNED NOT NULL,
    evidence_role VARCHAR(32) NOT NULL,
    external_evidence_id VARCHAR(255) NULL,
    document_block_id VARCHAR(80) NULL,
    evidence_snapshot JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_audit_task_evidence_execution (execution_id),
    CONSTRAINT fk_audit_task_evidence_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_task_evidence_block FOREIGN KEY (document_block_id)
        REFERENCES audit_document_block(block_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_retrieval_candidate (
    candidate_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    execution_id BIGINT UNSIGNED NOT NULL,
    retrieval_type VARCHAR(32) NOT NULL,
    query_text TEXT NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    rank_no INT UNSIGNED NOT NULL,
    score DOUBLE NULL,
    graph_path_json JSON NULL,
    selected_for_model TINYINT(1) NOT NULL DEFAULT 0,
    source_version_json JSON NULL,
    evidence_snapshot JSON NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_audit_candidate_execution (execution_id, retrieval_type, rank_no),
    CONSTRAINT fk_audit_candidate_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_applicability_result (
    applicability_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    execution_id BIGINT UNSIGNED NOT NULL,
    clause_id BIGINT UNSIGNED NOT NULL,
    version_id CHAR(36) NOT NULL,
    status VARCHAR(32) NOT NULL,
    condition_evidence_json JSON NOT NULL,
    missing_conditions_json JSON NOT NULL,
    reason TEXT NOT NULL,
    llm_call_id CHAR(36) NULL,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_applicability_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_llm_call (
    llm_call_id CHAR(36) PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    execution_id BIGINT UNSIGNED NULL,
    stage VARCHAR(64) NOT NULL,
    provider_id VARCHAR(64) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    parameters_json JSON NOT NULL,
    prompt_version VARCHAR(128) NOT NULL,
    prompt_hash CHAR(64) NOT NULL,
    request_payload LONGTEXT NOT NULL,
    raw_response LONGTEXT NULL,
    parsed_response JSON NULL,
    validation_errors_json JSON NULL,
    correction_attempt INT UNSIGNED NOT NULL DEFAULT 0,
    latency_ms INT UNSIGNED NULL,
    token_usage_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_llm_call_run FOREIGN KEY (run_id)
        REFERENCES audit_run(run_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_llm_call_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_issue (
    issue_id CHAR(36) PRIMARY KEY,
    execution_id BIGINT UNSIGNED NOT NULL,
    issue_category VARCHAR(64) NOT NULL,
    summary TEXT NOT NULL,
    affected_scope TEXT NULL,
    suggestion TEXT NULL,
    machine_status VARCHAR(32) NOT NULL,
    human_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_issue_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_human_review (
    review_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    issue_id CHAR(36) NULL,
    execution_id BIGINT UNSIGNED NULL,
    action_type VARCHAR(64) NOT NULL,
    before_value JSON NULL,
    after_value JSON NULL,
    reviewer_name VARCHAR(255) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT fk_audit_review_issue FOREIGN KEY (issue_id)
        REFERENCES audit_issue(issue_id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_review_execution FOREIGN KEY (execution_id)
        REFERENCES audit_task_execution(execution_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_report (
    report_id CHAR(36) PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    report_status VARCHAR(32) NOT NULL,
    report_version INT UNSIGNED NOT NULL,
    result_json JSON NOT NULL,
    docx_path TEXT NULL,
    generated_by VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_audit_report_run_version (run_id, report_version),
    CONSTRAINT fk_audit_report_run FOREIGN KEY (run_id)
        REFERENCES audit_run(run_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
