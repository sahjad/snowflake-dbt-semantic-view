-- ============================================================================
-- PHASE 1 VALIDATION: the queries the apps will actually run, plus a
-- full lifecycle test using throwaway data.
-- Run this AFTER phase1_semantic_tool_schema.sql
-- ============================================================================

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE TASTY_BYTES_WH;
USE SCHEMA TASTY_BYTES_DB.SEMANTIC_TOOL;


-- ============================================================================
-- PART A: THE FOUR QUERIES THAT DRIVE THE APP UIs
-- These are the exact filters behind each screen we designed.
-- ============================================================================

-- A1. Business user's "My submissions" list
--     (scoped to one owner; shows status, current version, deployment state)
CREATE OR REPLACE VIEW vw_my_submissions AS
SELECT
    p.proposal_id,
    p.view_name,
    p.owner,
    p.status,
    p.closed_reason,
    p.current_version_number,
    p.deployed_dev_version,
    p.deployed_prod_version,
    v.validator,
    v.review_notes,
    p.updated_at
FROM svt_proposals p
LEFT JOIN svt_versions v
    ON p.proposal_id = v.proposal_id
   AND v.is_current = TRUE;

-- A2. Engineer's "Review queue" -- everything awaiting a decision
CREATE OR REPLACE VIEW vw_review_queue AS
SELECT
    p.proposal_id,
    p.view_name,
    p.owner,
    p.current_version_number,
    p.is_update_to_existing,
    v.yaml_content,
    v.modified_by,
    v.review_notes,
    p.updated_at
FROM svt_proposals p
JOIN svt_versions v
    ON p.proposal_id = v.proposal_id
   AND v.is_current = TRUE
WHERE p.status = 'SUBMITTED';

-- A3. Engineer's "Validated, not deployed"
--     Catches BOTH cases: never deployed anywhere, AND deployed but on an
--     older version than what is now validated (per environment).
CREATE OR REPLACE VIEW vw_validated_not_deployed AS
SELECT
    p.proposal_id,
    p.view_name,
    p.owner,
    p.current_version_number,
    p.deployed_dev_version,
    p.deployed_prod_version,
    CASE
        WHEN p.deployed_dev_version IS NULL THEN 'Never deployed'
        WHEN p.deployed_dev_version < p.current_version_number THEN 'Outdated'
        ELSE 'Current'
    END AS dev_state,
    CASE
        WHEN p.deployed_prod_version IS NULL THEN 'Never deployed'
        WHEN p.deployed_prod_version < p.current_version_number THEN 'Outdated'
        ELSE 'Current'
    END AS prod_state,
    v.validator,
    v.validated_at
FROM svt_proposals p
JOIN svt_versions v
    ON p.proposal_id = v.proposal_id
   AND v.is_current = TRUE
WHERE p.status = 'VALIDATED'
  AND v.validator IS NOT NULL
  AND (
        p.deployed_dev_version  IS NULL OR p.deployed_dev_version  < p.current_version_number
     OR p.deployed_prod_version IS NULL OR p.deployed_prod_version < p.current_version_number
      );

-- A4. Engineer's "Deployed" -- anything live anywhere, with history count
CREATE OR REPLACE VIEW vw_deployed AS
SELECT
    p.proposal_id,
    p.view_name,
    p.owner,
    p.current_version_number,
    p.deployed_dev_version,
    p.deployed_prod_version,
    (SELECT COUNT(*) FROM svt_deployment_log d WHERE d.proposal_id = p.proposal_id)
        AS total_deploy_events
FROM svt_proposals p
WHERE p.deployed_dev_version IS NOT NULL
   OR p.deployed_prod_version IS NOT NULL;


-- ============================================================================
-- PART B: LIFECYCLE TEST -- walks a proposal through every state transition
-- and asserts the UI views return the right thing at each step.
-- Uses a clearly-named throwaway proposal, cleaned up at the end.
-- ============================================================================

-- B1. Create a DRAFT
INSERT INTO svt_proposals
    (proposal_id, view_name, owner, status, current_version_number, target_database)
VALUES
    ('test-001', 'ZZ_TEST_VIEW', 'test_business_user', 'DRAFT', 1, 'TASTY_BYTES_DB');

INSERT INTO svt_versions
    (version_id, proposal_id, version_number, yaml_content, modified_by, is_current)
VALUES
    ('test-v1', 'test-001', 1, 'name: ZZ_TEST_VIEW', 'test_business_user', TRUE);

-- Add a builder item, to confirm cascade-delete dependency checking works
INSERT INTO svt_builder_tables
    (item_id, proposal_id, table_alias, physical_database, physical_schema, physical_table, primary_key_cols)
VALUES
    ('test-bt1', 'test-001', 'FCT_TEST', 'TASTY_BYTES_DB', 'DEV', 'FCT_ORDER_DETAIL', 'ORDER_DETAIL_ID');

INSERT INTO svt_builder_facts
    (item_id, proposal_id, table_alias, fact_name, expr)
VALUES
    ('test-bf1', 'test-001', 'FCT_TEST', 'amount_fact', 'line_total');

-- CHECK 1: draft should NOT appear in the review queue
SELECT 'CHECK 1 -- draft not in review queue' AS check_name,
       IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS result
FROM vw_review_queue WHERE proposal_id = 'test-001';


-- B2. Submit it
UPDATE svt_proposals
   SET status = 'SUBMITTED', updated_at = CURRENT_TIMESTAMP()
 WHERE proposal_id = 'test-001';

-- CHECK 2: now it SHOULD appear in the review queue
SELECT 'CHECK 2 -- submitted appears in review queue' AS check_name,
       IFF(COUNT(*) = 1, 'PASS', 'FAIL') AS result
FROM vw_review_queue WHERE proposal_id = 'test-001';


-- B3. Engineer sends it back with notes
UPDATE svt_proposals SET status = 'NEEDS_REVISION' WHERE proposal_id = 'test-001';
UPDATE svt_versions
   SET review_notes = 'Please add a description to the amount_fact.'
 WHERE proposal_id = 'test-001' AND is_current = TRUE;

-- CHECK 3: out of the queue again, and notes visible to the business user
SELECT 'CHECK 3 -- sent back leaves queue, notes visible' AS check_name,
       IFF(
         (SELECT COUNT(*) FROM vw_review_queue WHERE proposal_id = 'test-001') = 0
         AND (SELECT review_notes FROM vw_my_submissions WHERE proposal_id = 'test-001') IS NOT NULL,
         'PASS', 'FAIL') AS result;


-- B4. Resubmit, then engineer validates v1
UPDATE svt_proposals SET status = 'SUBMITTED'  WHERE proposal_id = 'test-001';
UPDATE svt_proposals SET status = 'VALIDATED'  WHERE proposal_id = 'test-001';
UPDATE svt_versions
   SET validator = 'test_engineer', validated_at = CURRENT_TIMESTAMP()
 WHERE proposal_id = 'test-001' AND is_current = TRUE;

-- CHECK 4: validated + never deployed => shows in "validated, not deployed"
SELECT 'CHECK 4 -- validated appears as not-yet-deployed' AS check_name,
       IFF(COUNT(*) = 1, 'PASS', 'FAIL') AS result
FROM vw_validated_not_deployed WHERE proposal_id = 'test-001';


-- B5. Deploy v1 to DEV only (prod deliberately left behind)
UPDATE svt_proposals SET deployed_dev_version = 1 WHERE proposal_id = 'test-001';
INSERT INTO svt_deployment_log
    (log_id, proposal_id, version_number, environment, deployed_by)
VALUES
    ('test-d1', 'test-001', 1, 'DEV', 'test_engineer');

-- CHECK 5: appears in "deployed", AND still in "validated, not deployed"
--          (because prod is still empty) -- the dual-appearance case we designed for
SELECT 'CHECK 5 -- dev-only deploy appears in BOTH lists' AS check_name,
       IFF(
         (SELECT COUNT(*) FROM vw_deployed WHERE proposal_id = 'test-001') = 1
         AND (SELECT COUNT(*) FROM vw_validated_not_deployed WHERE proposal_id = 'test-001') = 1,
         'PASS', 'FAIL') AS result;


-- B6. Deploy v1 to PROD as well -- now fully current
UPDATE svt_proposals SET deployed_prod_version = 1 WHERE proposal_id = 'test-001';
INSERT INTO svt_deployment_log
    (log_id, proposal_id, version_number, environment, deployed_by)
VALUES
    ('test-d2', 'test-001', 1, 'PROD', 'test_engineer');

-- CHECK 6: fully deployed => drops OUT of "validated, not deployed"
SELECT 'CHECK 6 -- fully deployed leaves the pending list' AS check_name,
       IFF(COUNT(*) = 0, 'PASS', 'FAIL') AS result
FROM vw_validated_not_deployed WHERE proposal_id = 'test-001';


-- B7. Business user edits the validated view => creates v2 (SCD2 in action)
UPDATE svt_versions SET is_current = FALSE
 WHERE proposal_id = 'test-001' AND version_number = 1;

INSERT INTO svt_versions
    (version_id, proposal_id, version_number, yaml_content, modified_by, is_current)
VALUES
    ('test-v2', 'test-001', 2, 'name: ZZ_TEST_VIEW', 'test_business_user', TRUE);

UPDATE svt_proposals
   SET current_version_number = 2, status = 'SUBMITTED'
 WHERE proposal_id = 'test-001';

-- CHECK 7: exactly one current version, v1 history preserved with its validator
SELECT 'CHECK 7 -- SCD2: one current row, v1 history intact' AS check_name,
       IFF(
         (SELECT COUNT(*) FROM svt_versions WHERE proposal_id = 'test-001' AND is_current = TRUE) = 1
         AND (SELECT validator FROM svt_versions WHERE proposal_id = 'test-001' AND version_number = 1) = 'test_engineer'
         AND (SELECT COUNT(*) FROM svt_versions WHERE proposal_id = 'test-001') = 2,
         'PASS', 'FAIL') AS result;

-- CHECK 8: v1 still shown as live in both envs even though v2 exists
--          (deployment pointers must NOT auto-advance on new version)
SELECT 'CHECK 8 -- deployment pointers still on v1, not v2' AS check_name,
       IFF(deployed_dev_version = 1 AND deployed_prod_version = 1 AND current_version_number = 2,
           'PASS', 'FAIL') AS result
FROM svt_proposals WHERE proposal_id = 'test-001';


-- B9. Engineer validates v2 and deploys to DEV -- rollback capability check
UPDATE svt_proposals SET status = 'VALIDATED' WHERE proposal_id = 'test-001';
UPDATE svt_versions SET validator = 'test_engineer', validated_at = CURRENT_TIMESTAMP()
 WHERE proposal_id = 'test-001' AND version_number = 2;
UPDATE svt_proposals SET deployed_dev_version = 2 WHERE proposal_id = 'test-001';
INSERT INTO svt_deployment_log
    (log_id, proposal_id, version_number, environment, deployed_by)
VALUES ('test-d3', 'test-001', 2, 'DEV', 'test_engineer');

-- CHECK 9: dev on v2, prod still on v1 -- environments genuinely independent
SELECT 'CHECK 9 -- dev v2 / prod v1 simultaneously' AS check_name,
       IFF(deployed_dev_version = 2 AND deployed_prod_version = 1, 'PASS', 'FAIL') AS result
FROM svt_proposals WHERE proposal_id = 'test-001';

-- CHECK 10: full deployment audit trail survives -- 3 events logged
SELECT 'CHECK 10 -- deployment log has full history' AS check_name,
       IFF(COUNT(*) = 3, 'PASS', 'FAIL') AS result
FROM svt_deployment_log WHERE proposal_id = 'test-001';


-- B11. Cascade-delete dependency check: what depends on builder table FCT_TEST?
SELECT 'CHECK 11 -- cascade warning finds dependent items' AS check_name,
       IFF(COUNT(*) = 1, 'PASS', 'FAIL') AS result
FROM svt_builder_facts
WHERE proposal_id = 'test-001' AND table_alias = 'FCT_TEST';


-- ============================================================================
-- PART C: CLEANUP -- remove all test data (children first, FK order)
-- ============================================================================
DELETE FROM svt_builder_facts        WHERE proposal_id = 'test-001';
DELETE FROM svt_builder_tables       WHERE proposal_id = 'test-001';
DELETE FROM svt_deployment_log       WHERE proposal_id = 'test-001';
DELETE FROM svt_versions             WHERE proposal_id = 'test-001';
DELETE FROM svt_proposals            WHERE proposal_id = 'test-001';

SELECT 'CLEANUP -- all test rows removed' AS check_name,
       IFF((SELECT COUNT(*) FROM svt_proposals WHERE proposal_id = 'test-001') = 0,
           'PASS', 'FAIL') AS result;


SELECT COUNT(*) AS should_be_zero FROM svt_proposals WHERE proposal_id = 'test-001';


DROP VIEW IF EXISTS vw_my_submissions;
DROP VIEW IF EXISTS vw_review_queue;
DROP VIEW IF EXISTS vw_validated_not_deployed;
DROP VIEW IF EXISTS vw_deployed;

TRUNCATE TABLE IF EXISTS svt_builder_verified_queries;
TRUNCATE TABLE IF EXISTS svt_builder_relationships;
TRUNCATE TABLE IF EXISTS svt_builder_metrics;
TRUNCATE TABLE IF EXISTS svt_builder_facts;
TRUNCATE TABLE IF EXISTS svt_builder_dimensions;
TRUNCATE TABLE IF EXISTS svt_builder_tables;
TRUNCATE TABLE IF EXISTS svt_deployment_log;
TRUNCATE TABLE IF EXISTS svt_versions;
TRUNCATE TABLE IF EXISTS svt_proposals;


SELECT 'svt_proposals'                AS table_name, COUNT(*) AS row_count FROM svt_proposals
UNION ALL SELECT 'svt_versions',                     COUNT(*) FROM svt_versions
UNION ALL SELECT 'svt_deployment_log',               COUNT(*) FROM svt_deployment_log
UNION ALL SELECT 'svt_builder_tables',               COUNT(*) FROM svt_builder_tables
UNION ALL SELECT 'svt_builder_dimensions',           COUNT(*) FROM svt_builder_dimensions
UNION ALL SELECT 'svt_builder_facts',                COUNT(*) FROM svt_builder_facts
UNION ALL SELECT 'svt_builder_metrics',              COUNT(*) FROM svt_builder_metrics
UNION ALL SELECT 'svt_builder_relationships',        COUNT(*) FROM svt_builder_relationships
UNION ALL SELECT 'svt_builder_verified_queries',     COUNT(*) FROM svt_builder_verified_queries
ORDER BY table_name;


SELECT proposal_id, view_name, owner, status
FROM TASTY_BYTES_DB.SEMANTIC_TOOL.svt_proposals;


UPDATE TASTY_BYTES_DB.SEMANTIC_TOOL.svt_proposals
SET owner = 'SAHJAD'
WHERE owner LIKE 'STPLATSTREAMLIT%';



-- DROP CUSTOMER LOYALTY INSIGHTS

DROP SEMANTIC VIEW IF EXISTS TASTY_BYTES_DB.dev.customer_loyalty_insights;
-- only if you also deployed to prod during testing:
DROP SEMANTIC VIEW IF EXISTS TASTY_BYTES_DB.prod.customer_loyalty_insights;


USE SCHEMA TASTY_BYTES_DB.SEMANTIC_TOOL;

DELETE FROM svt_builder_verified_queries WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_builder_relationships WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_builder_metrics WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_builder_facts WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_builder_dimensions WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_builder_tables WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_deployment_log WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_versions WHERE proposal_id IN
    (SELECT proposal_id FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS');
DELETE FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS';


SELECT * FROM svt_proposals WHERE view_name = 'CUSTOMER_LOYALTY_INSIGHTS';
-- should return 0 rows

select * from svt_deployment_log;

