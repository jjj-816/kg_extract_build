CREATE TABLE IF NOT EXISTS kg_experiment_run (
    run_id CHAR(36) PRIMARY KEY,
    run_name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    deletion_state VARCHAR(32) NOT NULL DEFAULT 'active',
    code_commit VARCHAR(64) NULL,
    config_snapshot JSON NULL,
    schema_snapshot JSON NULL,
    error_message TEXT NULL,
    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    INDEX idx_kg_run_status_started (status, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_document (
    document_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    file_name VARCHAR(512) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    content LONGTEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_message TEXT NULL,
    started_at DATETIME(6) NOT NULL,
    finished_at DATETIME(6) NULL,
    UNIQUE KEY uk_kg_document_run_file (run_id, file_name),
    INDEX idx_kg_document_status (run_id, status),
    CONSTRAINT fk_kg_document_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_document_chunk (
    chunk_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    chunk_type VARCHAR(64) NOT NULL,
    chunk_index INT UNSIGNED NOT NULL,
    start_offset INT NULL,
    end_offset INT NULL,
    content_hash CHAR(64) NOT NULL,
    content LONGTEXT NOT NULL,
    milvus_id BIGINT UNSIGNED NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_kg_chunk_doc_type_index (document_id, chunk_type, chunk_index),
    INDEX idx_kg_chunk_run_type (run_id, chunk_type),
    CONSTRAINT fk_kg_chunk_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_chunk_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_llm_call (
    llm_call_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NULL,
    chunk_id BIGINT UNSIGNED NULL,
    stage VARCHAR(64) NOT NULL,
    entity_name VARCHAR(512) NULL,
    model_name VARCHAR(255) NOT NULL,
    prompt LONGTEXT NOT NULL,
    raw_response LONGTEXT NULL,
    parsed_result JSON NULL,
    metadata_json JSON NULL,
    latency_ms INT UNSIGNED NULL,
    success TINYINT(1) NOT NULL,
    error_message TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_llm_run_stage (run_id, stage),
    INDEX idx_kg_llm_document (document_id),
    CONSTRAINT fk_kg_llm_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_llm_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_llm_chunk FOREIGN KEY (chunk_id)
        REFERENCES kg_document_chunk(chunk_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_entity (
    entity_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    stage VARCHAR(32) NOT NULL,
    entity_name VARCHAR(512) NOT NULL,
    entity_type VARCHAR(255) NOT NULL,
    standard_name VARCHAR(512) NULL,
    aliases JSON NULL,
    source_type VARCHAR(32) NULL,
    metadata_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_entity_run_stage (run_id, stage),
    INDEX idx_kg_entity_name (entity_name(191)),
    CONSTRAINT fk_kg_entity_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_entity_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_retrieval_result (
    retrieval_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    entity_name VARCHAR(512) NOT NULL,
    query_alias VARCHAR(512) NOT NULL,
    chunk_id BIGINT UNSIGNED NULL,
    sentence LONGTEXT NOT NULL,
    similarity_score DOUBLE NULL,
    hit_rank INT UNSIGNED NOT NULL,
    match_type VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_retrieval_entity (run_id, entity_name(191)),
    CONSTRAINT fk_kg_retrieval_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_retrieval_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_retrieval_chunk FOREIGN KEY (chunk_id)
        REFERENCES kg_document_chunk(chunk_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_triplet (
    triplet_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    source_llm_call_id BIGINT UNSIGNED NULL,
    stage VARCHAR(32) NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    entity_name VARCHAR(512) NULL,
    head VARCHAR(512) NOT NULL,
    head_type VARCHAR(255) NOT NULL,
    relation_name VARCHAR(255) NOT NULL,
    tail VARCHAR(512) NOT NULL,
    tail_type VARCHAR(255) NOT NULL,
    is_valid TINYINT(1) NOT NULL,
    validation_reason TEXT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_triplet_run_stage (run_id, stage),
    INDEX idx_kg_triplet_relation (relation_name),
    CONSTRAINT fk_kg_triplet_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_triplet_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_triplet_llm FOREIGN KEY (source_llm_call_id)
        REFERENCES kg_llm_call(llm_call_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_evaluation_run (
    evaluation_id CHAR(36) PRIMARY KEY,
    run_id CHAR(36) NOT NULL,
    gold_path VARCHAR(1024) NOT NULL,
    gold_hash CHAR(64) NOT NULL,
    metric_config_json JSON NULL,
    summary_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_eval_run_gold (run_id, gold_hash),
    CONSTRAINT fk_kg_eval_run FOREIGN KEY (run_id)
        REFERENCES kg_experiment_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_triplet_evidence (
    triplet_id BIGINT UNSIGNED NOT NULL,
    retrieval_id BIGINT UNSIGNED NOT NULL,
    evidence_order INT UNSIGNED NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'model_selected',
    PRIMARY KEY (triplet_id, retrieval_id),
    INDEX idx_kg_triplet_evidence_retrieval (retrieval_id),
    CONSTRAINT fk_kg_triplet_evidence_triplet FOREIGN KEY (triplet_id)
        REFERENCES kg_triplet(triplet_id) ON DELETE CASCADE,
    CONSTRAINT fk_kg_triplet_evidence_retrieval FOREIGN KEY (retrieval_id)
        REFERENCES kg_retrieval_result(retrieval_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_evaluation_metric (
    metric_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evaluation_id CHAR(36) NOT NULL,
    scope_type VARCHAR(32) NOT NULL,
    scope_name VARCHAR(512) NOT NULL,
    metric_name VARCHAR(128) NOT NULL,
    metric_value DOUBLE NOT NULL,
    numerator DOUBLE NULL,
    denominator DOUBLE NULL,
    details_json JSON NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_eval_metric_scope (evaluation_id, scope_type, metric_name),
    CONSTRAINT fk_kg_eval_metric_run FOREIGN KEY (evaluation_id)
        REFERENCES kg_evaluation_run(evaluation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_evaluation_entity_alignment (
    alignment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    evaluation_id CHAR(36) NOT NULL,
    document_name VARCHAR(512) NOT NULL,
    entity_name VARCHAR(512) NOT NULL,
    entity_type VARCHAR(255) NOT NULL,
    canonical_id VARCHAR(255) NULL,
    canonical_name VARCHAR(512) NULL,
    canonical_type VARCHAR(255) NULL,
    match_status VARCHAR(64) NOT NULL,
    candidate_count INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_eval_alignment_eval (evaluation_id, match_status),
    CONSTRAINT fk_kg_eval_alignment_run FOREIGN KEY (evaluation_id)
        REFERENCES kg_evaluation_run(evaluation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_family (
    family_id CHAR(36) PRIMARY KEY,
    canonical_name VARCHAR(512) NOT NULL,
    standard_code_base VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_kg_normative_family_identity (canonical_name, standard_code_base)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_version (
    version_id CHAR(36) PRIMARY KEY,
    family_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    display_name VARCHAR(512) NOT NULL,
    standard_code VARCHAR(255) NULL,
    version_year INT UNSIGNED NOT NULL,
    publication_year INT UNSIGNED NULL,
    effective_year INT UNSIGNED NULL,
    invalid_year INT UNSIGNED NULL,
    status VARCHAR(32) NOT NULL,
    supersedes_version_id CHAR(36) NULL,
    metadata_confirmed TINYINT(1) NOT NULL DEFAULT 0,
    metadata_hash CHAR(64) NOT NULL,
    confirmed_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    INDEX idx_kg_normative_version_family_year (family_id, effective_year, invalid_year),
    CONSTRAINT fk_kg_normative_version_family FOREIGN KEY (family_id)
        REFERENCES kg_normative_family(family_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_version_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_version_supersedes FOREIGN KEY (supersedes_version_id)
        REFERENCES kg_normative_version(version_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_clause_set (
    clause_set_id CHAR(36) PRIMARY KEY,
    version_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    source_content_hash CHAR(64) NOT NULL,
    parser_version VARCHAR(128) NOT NULL,
    parser_config_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    published_at DATETIME(6) NULL,
    INDEX idx_kg_normative_clause_set_version (version_id, status),
    CONSTRAINT fk_kg_normative_clause_set_version FOREIGN KEY (version_id)
        REFERENCES kg_normative_version(version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_clause_set_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_clause (
    clause_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    clause_set_id CHAR(36) NOT NULL,
    version_id CHAR(36) NOT NULL,
    document_id BIGINT UNSIGNED NOT NULL,
    clause_number VARCHAR(128) NULL,
    hierarchy_path JSON NULL,
    clause_title VARCHAR(1024) NULL,
    raw_text LONGTEXT NOT NULL,
    normalized_text LONGTEXT NOT NULL,
    start_offset INT NOT NULL,
    end_offset INT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    parse_status VARCHAR(32) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    INDEX idx_kg_normative_clause_set (clause_set_id, clause_number),
    CONSTRAINT fk_kg_normative_clause_set FOREIGN KEY (clause_set_id)
        REFERENCES kg_normative_clause_set(clause_set_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_clause_version FOREIGN KEY (version_id)
        REFERENCES kg_normative_version(version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_clause_document FOREIGN KEY (document_id)
        REFERENCES kg_document(document_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_index (
    index_id CHAR(36) PRIMARY KEY,
    version_id CHAR(36) NOT NULL,
    clause_set_id CHAR(36) NOT NULL,
    collection_name VARCHAR(255) NOT NULL,
    embedding_model_key VARCHAR(255) NOT NULL,
    embedding_model_revision VARCHAR(255) NOT NULL,
    embedding_dimension INT UNSIGNED NOT NULL,
    encoder_profile_json JSON NOT NULL,
    encoder_profile_hash CHAR(64) NOT NULL,
    metric_type VARCHAR(32) NOT NULL,
    milvus_index_params_json JSON NULL,
    milvus_search_params_json JSON NULL,
    chunker_version VARCHAR(128) NOT NULL,
    chunk_config_json JSON NOT NULL,
    index_fingerprint CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    enabled_for_audit TINYINT(1) NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    built_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_kg_normative_index_fingerprint (index_fingerprint),
    INDEX idx_kg_normative_index_version (version_id, status),
    CONSTRAINT fk_kg_normative_index_version FOREIGN KEY (version_id)
        REFERENCES kg_normative_version(version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_index_clause_set FOREIGN KEY (clause_set_id)
        REFERENCES kg_normative_clause_set(clause_set_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_index_segment (
    segment_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    index_id CHAR(36) NOT NULL,
    clause_id BIGINT UNSIGNED NOT NULL,
    segment_index INT UNSIGNED NOT NULL,
    embedding_text LONGTEXT NOT NULL,
    token_count INT UNSIGNED NULL,
    text_hash CHAR(64) NOT NULL,
    milvus_vector_id VARCHAR(128) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_kg_normative_segment_index_order (index_id, clause_id, segment_index),
    UNIQUE KEY uk_kg_normative_segment_vector (index_id, milvus_vector_id),
    CONSTRAINT fk_kg_normative_segment_index FOREIGN KEY (index_id)
        REFERENCES kg_normative_index(index_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_segment_clause FOREIGN KEY (clause_id)
        REFERENCES kg_normative_clause(clause_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_index_release (
    release_id CHAR(36) PRIMARY KEY,
    release_name VARCHAR(255) NOT NULL,
    collection_name VARCHAR(255) NOT NULL,
    embedding_model_key VARCHAR(255) NOT NULL,
    embedding_model_revision VARCHAR(255) NOT NULL,
    encoder_profile_hash CHAR(64) NOT NULL,
    release_fingerprint CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    published_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL,
    UNIQUE KEY uk_kg_normative_release_fingerprint (release_fingerprint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kg_normative_index_release_member (
    release_id CHAR(36) NOT NULL,
    index_id CHAR(36) NOT NULL,
    version_id CHAR(36) NOT NULL,
    clause_set_id CHAR(36) NOT NULL,
    included_at DATETIME(6) NOT NULL,
    PRIMARY KEY (release_id, index_id),
    CONSTRAINT fk_kg_normative_release_member_release FOREIGN KEY (release_id)
        REFERENCES kg_normative_index_release(release_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_release_member_index FOREIGN KEY (index_id)
        REFERENCES kg_normative_index(index_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_release_member_version FOREIGN KEY (version_id)
        REFERENCES kg_normative_version(version_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kg_normative_release_member_clause_set FOREIGN KEY (clause_set_id)
        REFERENCES kg_normative_clause_set(clause_set_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
