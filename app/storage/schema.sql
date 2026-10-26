-- 医药研发知识助手 SQLite schema
-- 设计原则：任务、证据、claim、评审、快照、审计全链路可追溯；
-- 所有 ACL 字段在检索层过滤，不允许先取后遮。

PRAGMA foreign_keys = ON;

-- ============================================================
-- 项目与成员（演示级 ACL；生产接 SSO/项目系统）
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_members (
    project_id   TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (project_id, user_id)
);

-- ============================================================
-- 文档与切块
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    source_type   TEXT NOT NULL,
    source_id     TEXT,
    title         TEXT NOT NULL,
    source_url    TEXT,
    license       TEXT,
    published_at  TEXT,
    acl_scope     TEXT NOT NULL DEFAULT 'public',
    content_hash  TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    ingested_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_acl_scope ON documents(acl_scope);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id         TEXT PRIMARY KEY,
    doc_id           TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    parent_id        TEXT,
    text             TEXT NOT NULL,
    parent_text      TEXT NOT NULL DEFAULT '',
    section_path     TEXT,
    page_number      INTEGER,
    figure           TEXT,
    table_ref        TEXT,
    entity_ids_json  TEXT NOT NULL DEFAULT '[]',
    species          TEXT,
    sample           TEXT,
    method           TEXT,
    stance_hint      TEXT NOT NULL DEFAULT 'unknown',
    result_polarity  TEXT NOT NULL DEFAULT 'unknown',
    acl_scope        TEXT NOT NULL DEFAULT 'public',
    token_count      INTEGER,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_acl_scope ON chunks(acl_scope);
CREATE INDEX IF NOT EXISTS idx_chunks_species ON chunks(species);

-- ============================================================
-- 研究任务与图执行事件
-- ============================================================
CREATE TABLE IF NOT EXISTS research_tasks (
    task_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    question     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'planned',
    plan_json    TEXT NOT NULL DEFAULT '{}',
    result_json  TEXT NOT NULL DEFAULT '{}',
    report_md    TEXT NOT NULL DEFAULT '',
    trace_id     TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    snapshot_id  TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON research_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON research_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON research_tasks(status);

CREATE TABLE IF NOT EXISTS task_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    node         TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);

-- ============================================================
-- 证据、claim、评审、快照
-- ============================================================
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    chunk_id        TEXT,
    quote           TEXT NOT NULL,
    locator_json    TEXT NOT NULL DEFAULT '{}',
    entity_ids_json TEXT NOT NULL DEFAULT '[]',
    species         TEXT,
    sample          TEXT,
    method          TEXT,
    stance          TEXT NOT NULL DEFAULT 'unknown',
    level           TEXT NOT NULL DEFAULT 'unknown',
    acl_scope       TEXT NOT NULL DEFAULT 'public',
    scores_json     TEXT NOT NULL DEFAULT '{}',
    retrieved_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tool_call_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_type, source_id);

CREATE TABLE IF NOT EXISTS claims (
    claim_id             TEXT PRIMARY KEY,
    task_id              TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    text                 TEXT NOT NULL,
    stance               TEXT NOT NULL,
    level                TEXT NOT NULL DEFAULT 'unknown',
    support_ids_json     TEXT NOT NULL DEFAULT '[]',
    contradict_ids_json  TEXT NOT NULL DEFAULT '[]',
    confidence           REAL NOT NULL DEFAULT 0,
    caveats_json         TEXT NOT NULL DEFAULT '[]',
    verified             INTEGER NOT NULL DEFAULT 0,
    verify_detail_json   TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_claims_task ON claims(task_id);

CREATE TABLE IF NOT EXISTS reviews (
    review_id    TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    reviewer_id  TEXT NOT NULL,
    claim_id     TEXT,
    action       TEXT NOT NULL,
    comment      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id        TEXT PRIMARY KEY,
    task_id            TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    version            INTEGER NOT NULL DEFAULT 1,
    manifest_json      TEXT NOT NULL DEFAULT '{}',
    model_versions_json TEXT NOT NULL DEFAULT '{}',
    prompt_version     TEXT NOT NULL DEFAULT '',
    graph_version      TEXT NOT NULL DEFAULT '',
    tool_calls_json    TEXT NOT NULL DEFAULT '[]',
    evidence_ids_json  TEXT NOT NULL DEFAULT '[]',
    content_hash       TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_task ON snapshots(task_id);

-- ============================================================
-- 工具调用、审计、索引清单、LLM 缓存
-- ============================================================
CREATE TABLE IF NOT EXISTS tool_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT NOT NULL REFERENCES research_tasks(task_id) ON DELETE CASCADE,
    tool_name      TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_hash    TEXT NOT NULL DEFAULT '',
    dataset_version TEXT,
    status         TEXT NOT NULL DEFAULT 'ok',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT,
    project_id  TEXT,
    action      TEXT NOT NULL,
    resource    TEXT,
    allowed     INTEGER NOT NULL DEFAULT 0,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id);

CREATE TABLE IF NOT EXISTS index_manifest (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    collection       TEXT NOT NULL,
    embedding_model  TEXT NOT NULL,
    embedding_dim    INTEGER NOT NULL,
    chunker_version  TEXT NOT NULL DEFAULT '',
    document_count   INTEGER NOT NULL DEFAULT 0,
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    manifest_json    TEXT NOT NULL DEFAULT '{}',
    built_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_index_manifest_collection
    ON index_manifest(collection, built_at);

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash   TEXT PRIMARY KEY,
    model         TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
