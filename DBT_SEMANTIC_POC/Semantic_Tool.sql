-- ============================================================================
-- PHASE 1: SEMANTIC VIEW SUBMISSION TOOL -- SCHEMA AND TABLES
-- Location: TASTY_BYTES_DB.SEMANTIC_TOOL
-- ============================================================================
-- Two categories of table here:
--   1. BUILDER tables -- the live, editable working copy the visual builder
--      reads/writes as users add and delete items. Not versioned themselves.
--   2. WORKFLOW tables -- proposals, immutable version snapshots (SCD Type 2),
--      and an append-only deployment audit log.
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE TASTY_BYTES_WH;
USE DATABASE TASTY_BYTES_DB;

CREATE SCHEMA IF NOT EXISTS TASTY_BYTES_DB.SEMANTIC_TOOL
  COMMENT = 'Application and workflow state for the semantic view submission tool';

USE SCHEMA TASTY_BYTES_DB.SEMANTIC_TOOL;


-- ----------------------------------------------------------------------------
-- WORKFLOW TABLE 1: proposals
-- One row per semantic view proposal. Holds current status plus the mutable
-- "what is live right now" deployment pointers.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_proposals (
    proposal_id             VARCHAR(36)   NOT NULL,
    view_name               VARCHAR(255)  NOT NULL,
    description             VARCHAR,
    owner                   VARCHAR(255)  NOT NULL
        COMMENT 'Business user who created this. Never changes.',
    status                  VARCHAR(20)   NOT NULL DEFAULT 'DRAFT'
        COMMENT 'DRAFT | SUBMITTED | NEEDS_REVISION | VALIDATED | CLOSED',
    closed_reason           VARCHAR(20)
        COMMENT 'REJECTED | WITHDRAWN -- only meaningful when status = CLOSED',
    current_version_number  NUMBER(10,0)  NOT NULL DEFAULT 1,
    is_update_to_existing   BOOLEAN       NOT NULL DEFAULT FALSE,
    existing_view_reference VARCHAR(500)
        COMMENT 'Fully qualified name of the live view being updated, if applicable',
    target_database         VARCHAR(255)  NOT NULL
        COMMENT 'Database the semantic view will be built in',
    target_schema_dev       VARCHAR(255)  NOT NULL DEFAULT 'DEV',
    target_schema_prod      VARCHAR(255)  NOT NULL DEFAULT 'PROD',
    deployed_dev_version    NUMBER(10,0)
        COMMENT 'Which version is currently live in dev. NULL = never deployed there.',
    deployed_prod_version   NUMBER(10,0)
        COMMENT 'Which version is currently live in prod. NULL = never deployed there.',
    created_at              TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_at              TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_proposals PRIMARY KEY (proposal_id)
)
COMMENT = 'One row per semantic view proposal, with current status and live deployment pointers';


-- ----------------------------------------------------------------------------
-- WORKFLOW TABLE 2: versions (SCD Type 2)
-- One row per version. Once a version is validated its yaml_content is frozen;
-- any later edit inserts a new row rather than updating this one.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_versions (
    version_id      VARCHAR(36)   NOT NULL,
    proposal_id     VARCHAR(36)   NOT NULL,
    version_number  NUMBER(10,0)  NOT NULL,
    yaml_content    VARCHAR       NOT NULL
        COMMENT 'The generated semantic view YAML for this version',
    modified_by     VARCHAR(255)  NOT NULL
        COMMENT 'Business user or engineer -- whoever last edited this version',
    validator       VARCHAR(255)
        COMMENT 'Engineer who validated this specific version. NULL = not yet validated.',
    validated_at    TIMESTAMP_NTZ,
    review_notes    VARCHAR
        COMMENT 'Engineer comments: why sent back, why rejected, or what was changed',
    is_current      BOOLEAN       NOT NULL DEFAULT TRUE
        COMMENT 'TRUE for only the latest version of a given proposal',
    created_at      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_versions PRIMARY KEY (version_id),
    CONSTRAINT fk_svt_versions_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'SCD Type 2 version history -- immutable snapshots of each proposal version';


-- ----------------------------------------------------------------------------
-- WORKFLOW TABLE 3: deployment_log (append-only)
-- One row per deploy action. Never updated or deleted -- full audit trail,
-- including rollbacks (deploying an older version again is just another row).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_deployment_log (
    log_id          VARCHAR(36)   NOT NULL,
    proposal_id     VARCHAR(36)   NOT NULL,
    version_number  NUMBER(10,0)  NOT NULL,
    environment     VARCHAR(10)   NOT NULL
        COMMENT 'DEV | PROD -- one row per environment, even if deployed together',
    deployed_by     VARCHAR(255)  NOT NULL,
    deployed_at     TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    deploy_notes    VARCHAR,
    CONSTRAINT pk_svt_deployment_log PRIMARY KEY (log_id),
    CONSTRAINT fk_svt_deployment_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Append-only audit log of every deployment action across all environments';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 1: builder_tables
-- Logical tables selected in the visual builder. Deleting a row here should
-- cascade-warn about dependent facts/dimensions/relationships in the UI.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_tables (
    item_id           VARCHAR(36)   NOT NULL,
    proposal_id       VARCHAR(36)   NOT NULL,
    table_alias       VARCHAR(255)  NOT NULL
        COMMENT 'Logical name used inside the semantic view',
    physical_database VARCHAR(255)  NOT NULL,
    physical_schema   VARCHAR(255)  NOT NULL,
    physical_table    VARCHAR(255)  NOT NULL,
    primary_key_cols  VARCHAR
        COMMENT 'Comma-separated list of primary key column names',
    description       VARCHAR,
    created_at        TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_tables PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_tables_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: logical tables in the proposal being edited';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 2: builder_dimensions
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_dimensions (
    item_id        VARCHAR(36)   NOT NULL,
    proposal_id    VARCHAR(36)   NOT NULL,
    table_alias    VARCHAR(255)  NOT NULL
        COMMENT 'Which logical table this dimension belongs to',
    dimension_name VARCHAR(255)  NOT NULL
        COMMENT 'Declared semantic name -- what verified queries must reference',
    expr           VARCHAR(255)  NOT NULL
        COMMENT 'Underlying physical column',
    data_type      VARCHAR(100),
    description    VARCHAR,
    synonyms       VARCHAR
        COMMENT 'Comma-separated alternate business terms, aids Cortex Analyst',
    created_at     TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_dimensions PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_dimensions_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: dimensions in the proposal being edited';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 3: builder_facts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_facts (
    item_id     VARCHAR(36)   NOT NULL,
    proposal_id VARCHAR(36)   NOT NULL,
    table_alias VARCHAR(255)  NOT NULL,
    fact_name   VARCHAR(255)  NOT NULL
        COMMENT 'Declared semantic name. Convention: _fact suffix avoids cross-table ambiguity.',
    expr        VARCHAR(255)  NOT NULL
        COMMENT 'Underlying physical column',
    data_type   VARCHAR(100),
    description VARCHAR,
    created_at  TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_facts PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_facts_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: facts in the proposal being edited';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 4: builder_metrics
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_metrics (
    item_id      VARCHAR(36)   NOT NULL,
    proposal_id  VARCHAR(36)   NOT NULL,
    table_alias  VARCHAR(255)  NOT NULL,
    metric_name  VARCHAR(255)  NOT NULL,
    agg_function VARCHAR(50)
        COMMENT 'SUM | AVG | COUNT | COUNT DISTINCT | MIN | MAX -- NULL if custom expression',
    target_fact  VARCHAR(255)
        COMMENT 'Which declared fact is being aggregated. NULL if custom expression.',
    expr         VARCHAR       NOT NULL
        COMMENT 'Final metric expression, either built from agg+fact or typed custom',
    description  VARCHAR,
    created_at   TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_metrics PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_metrics_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: metrics in the proposal being edited';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 5: builder_relationships
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_relationships (
    item_id           VARCHAR(36)   NOT NULL,
    proposal_id       VARCHAR(36)   NOT NULL,
    relationship_name VARCHAR(255)  NOT NULL,
    left_table        VARCHAR(255)  NOT NULL
        COMMENT 'Child table -- the many side, typically the fact table',
    right_table       VARCHAR(255)  NOT NULL
        COMMENT 'Parent table -- the one side, typically a dimension',
    left_column       VARCHAR(255)  NOT NULL
        COMMENT 'Foreign key column on the left table',
    right_column      VARCHAR(255)  NOT NULL
        COMMENT 'Primary key column on the right table',
    relationship_type VARCHAR(50)   NOT NULL DEFAULT 'many_to_one',
    created_at        TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_relationships PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_relationships_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: relationships in the proposal being edited';


-- ----------------------------------------------------------------------------
-- BUILDER TABLE 6: builder_verified_queries
-- Optional, but worth capturing here so the generator can produce syntactically
-- correct verified queries automatically -- avoiding the three rules that
-- caused real errors earlier: no AGG(), reference logical tables not the
-- semantic view name, and use declared names not raw physical columns.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS svt_builder_verified_queries (
    item_id     VARCHAR(36)   NOT NULL,
    proposal_id VARCHAR(36)   NOT NULL,
    query_name  VARCHAR(255)  NOT NULL,
    question    VARCHAR       NOT NULL
        COMMENT 'Natural language question a business user would actually ask',
    sql_text    VARCHAR       NOT NULL
        COMMENT 'Standard SQL against logical tables. No AGG(); use declared names.',
    created_at  TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_svt_builder_vq PRIMARY KEY (item_id),
    CONSTRAINT fk_svt_builder_vq_proposal FOREIGN KEY (proposal_id)
        REFERENCES svt_proposals (proposal_id)
)
COMMENT = 'Builder working copy: verified queries in the proposal being edited';


-- ============================================================================
-- VERIFICATION
-- ============================================================================
SHOW TABLES IN SCHEMA TASTY_BYTES_DB.SEMANTIC_TOOL;

SELECT table_name, comment
FROM TASTY_BYTES_DB.INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'SEMANTIC_TOOL'
ORDER BY table_name;