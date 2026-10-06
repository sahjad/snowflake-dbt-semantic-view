-- ============================================================================
-- BOOTSTRAP: Neo4j Lineage Explorer, from zero, in a new Snowflake account.
--
-- ASSUMES: TASTY_BYTES_DB already exists, with the DEV/RAW schemas, Gold
-- tables, Silver views, and semantic views already built (that's a
-- separate setup process -- the dbt project + Semantic_Tool.sql).
--
-- MANUAL STEPS THAT CANNOT BE SCRIPTED (do these BEFORE running this file):
--   1. Install "Neo4j Graph Analytics for Snowflake" from the Snowflake
--      Marketplace (Admin/ACCOUNTADMIN only, via Snowsight UI).
--   2. A compute pool for it to use -- SYSTEM_COMPUTE_POOL_CPU is used
--      below; create your own if that's not available in the new account.
--
-- Run top to bottom as ACCOUNTADMIN (or an equivalently privileged role).
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- ----------------------------------------------------------------------------
-- SECTION 1: Core infrastructure -- warehouse, database, role.
-- ----------------------------------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS NEO4J_LINEAGE_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

CREATE DATABASE IF NOT EXISTS NEO4J_LINEAGE_DB;

CREATE ROLE IF NOT EXISTS NEO4J_LINEAGE_ROLE;

-- Confirmed username from this project -- verify it matches the new
-- account if different.
GRANT ROLE NEO4J_LINEAGE_ROLE TO USER SAHJAD;

GRANT OWNERSHIP ON DATABASE NEO4J_LINEAGE_DB TO ROLE NEO4J_LINEAGE_ROLE;
GRANT USAGE, OPERATE ON WAREHOUSE NEO4J_LINEAGE_WH TO ROLE NEO4J_LINEAGE_ROLE;

-- ----------------------------------------------------------------------------
-- SECTION 2: Grants needed on the schema itself -- each CREATE <object
-- type> privilege is separate in Snowflake, even for a role that owns
-- the whole database (confirmed the hard way, multiple times, this
-- session).
-- ----------------------------------------------------------------------------
-- Confirmed via live testing: the auto-created PUBLIC schema stays owned
-- by whoever ran CREATE DATABASE (ACCOUNTADMIN here) even after the
-- DATABASE's own ownership transfers to NEO4J_LINEAGE_ROLE -- that
-- transfer doesn't cascade to the schema inside it. The CREATE <object>
-- grants below are each separate from basic USAGE, which is why
-- deploying the Streamlit app (which needs USAGE specifically, to run
-- "as" this role) failed without this line.
GRANT USAGE ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;
GRANT CREATE TABLE ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;
GRANT CREATE VIEW ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;
GRANT CREATE TASK ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;
GRANT CREATE PROCEDURE ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;
GRANT CREATE STREAMLIT ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO ROLE NEO4J_LINEAGE_ROLE;

-- ----------------------------------------------------------------------------
-- SECTION 3: Account-level privileges for lineage + data quality access.
-- ----------------------------------------------------------------------------
GRANT RESOLVE ALL ON ACCOUNT TO ROLE NEO4J_LINEAGE_ROLE;
GRANT VIEW LINEAGE ON ACCOUNT TO ROLE NEO4J_LINEAGE_ROLE;
GRANT DATABASE ROLE SNOWFLAKE.DATA_METRIC_USER TO ROLE NEO4J_LINEAGE_ROLE;
GRANT APPLICATION ROLE SNOWFLAKE.DATA_QUALITY_MONITORING_VIEWER TO ROLE NEO4J_LINEAGE_ROLE;

-- Needed specifically for RELATIONSHIPS_VW's Silver->Raw lineage block,
-- which reads SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES -- confirmed
-- the hard way (broke the whole app) when ownership shifted without it.
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE NEO4J_LINEAGE_ROLE;

-- Neo4j Graph Analytics app roles -- names may differ slightly depending
-- on the exact app version installed; check SHOW APPLICATION ROLES IN
-- APPLICATION NEO4J_GRAPH_ANALYTICS if these don't match.
GRANT APPLICATION ROLE NEO4J_GRAPH_ANALYTICS.APP_ADMIN TO ROLE NEO4J_LINEAGE_ROLE;
GRANT APPLICATION ROLE NEO4J_GRAPH_ANALYTICS.APP_USER TO ROLE NEO4J_LINEAGE_ROLE;
GRANT USAGE ON COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU TO ROLE NEO4J_LINEAGE_ROLE;

-- ----------------------------------------------------------------------------
-- SECTION 4: Access to the existing TASTY_BYTES_DB content. Assumes the
-- standard DEV/RAW schema layout and the 3 known semantic views -- adjust
-- names/counts if the new account's build differs.
-- ----------------------------------------------------------------------------
GRANT USAGE ON DATABASE TASTY_BYTES_DB TO ROLE NEO4J_LINEAGE_ROLE;
GRANT USAGE ON SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
GRANT USAGE ON SCHEMA TASTY_BYTES_DB.RAW TO ROLE NEO4J_LINEAGE_ROLE;

GRANT SELECT ON ALL TABLES IN SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON ALL VIEWS IN SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA TASTY_BYTES_DB.RAW TO ROLE NEO4J_LINEAGE_ROLE;
-- Also cover anything created AFTER this point, going forward:
GRANT SELECT ON FUTURE TABLES IN SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA TASTY_BYTES_DB.RAW TO ROLE NEO4J_LINEAGE_ROLE;

-- Semantic views need individual grants (confirmed no bulk/ALL form
-- exists for this object type) -- but FUTURE does work, confirmed
-- earlier this project:
GRANT SELECT ON FUTURE SEMANTIC VIEWS IN SCHEMA TASTY_BYTES_DB.DEV TO ROLE NEO4J_LINEAGE_ROLE;
-- FUTURE only covers views created AFTER the grant above -- these three
-- already exist, so they need explicit grants too. Update this list if
-- the new account's semantic views differ.
GRANT SELECT ON SEMANTIC VIEW TASTY_BYTES_DB.DEV.TASTY_BYTES_SEMANTIC_VIEW TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON SEMANTIC VIEW TASTY_BYTES_DB.DEV.TASTY_BYTES_PROFITABILITY_SEMANTIC_VIEW TO ROLE NEO4J_LINEAGE_ROLE;
GRANT SELECT ON SEMANTIC VIEW TASTY_BYTES_DB.DEV.CUSTOMER_LOYALTY_INSIGHTS TO ROLE NEO4J_LINEAGE_ROLE;

-- ----------------------------------------------------------------------------
-- From here on, switch to the role that should own everything else.
-- ----------------------------------------------------------------------------
USE ROLE NEO4J_LINEAGE_ROLE;
USE WAREHOUSE NEO4J_LINEAGE_WH;
USE DATABASE NEO4J_LINEAGE_DB;
USE SCHEMA PUBLIC;

-- ----------------------------------------------------------------------------
-- SECTION 5: PK/FK metadata snapshots -- SHOW PRIMARY KEYS/SHOW IMPORTED
-- KEYS can't be embedded in a view, so these are captured into real
-- tables, refreshed daily.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
  SHOW PRIMARY KEYS IN SCHEMA TASTY_BYTES_DB.DEV;
  CREATE OR REPLACE TABLE NEO4J_LINEAGE_DB.PUBLIC.PK_METADATA AS
  SELECT "database_name" AS DATABASE_NAME, "schema_name" AS SCHEMA_NAME,
         "table_name" AS TABLE_NAME, "column_name" AS COLUMN_NAME,
         "key_sequence" AS KEY_SEQUENCE, "constraint_name" AS CONSTRAINT_NAME
  FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

  SHOW IMPORTED KEYS IN SCHEMA TASTY_BYTES_DB.DEV;
  CREATE OR REPLACE TABLE NEO4J_LINEAGE_DB.PUBLIC.FK_METADATA AS
  SELECT "fk_database_name" AS FK_DATABASE_NAME, "fk_schema_name" AS FK_SCHEMA_NAME,
         "fk_table_name" AS FK_TABLE_NAME, "fk_column_name" AS FK_COLUMN_NAME,
         "pk_database_name" AS PK_DATABASE_NAME, "pk_schema_name" AS PK_SCHEMA_NAME,
         "pk_table_name" AS PK_TABLE_NAME, "pk_column_name" AS PK_COLUMN_NAME,
         "fk_name" AS FK_NAME, "pk_name" AS PK_NAME
  FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

  RETURN 'PK/FK metadata refreshed at ' || CURRENT_TIMESTAMP()::VARCHAR;
END;
$$;

CALL NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA();

CREATE OR REPLACE TASK NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA_TASK
  WAREHOUSE = NEO4J_LINEAGE_WH
  SCHEDULE = 'USING CRON 0 7 * * * UTC'
AS
  CALL NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA();

ALTER TASK NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA_TASK RESUME;

-- ----------------------------------------------------------------------------
-- SECTION 6: NODES_VW, RELATIONSHIPS_VW, and the listing/lineage
-- automation that feeds them.
--
-- >>> At this point, run FINAL_listing_automation.sql in full <<<
-- >>> (skip its grant section at the top -- already covered above) <<<
-- >>> Then run FINAL_table_lineage_automation.sql in full         <<<
-- >>> (same -- skip its grants section, already covered above)    <<<
-- ----------------------------------------------------------------------------

-- ----------------------------------------------------------------------------
-- SECTION 7: Thin projection views the Neo4j Graph Analytics algorithms
-- (WCC/PageRank/Louvain) read from -- numeric IDs only, no VARCHAR
-- columns, since the algorithm engine can't handle mixed types.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW NEO4J_LINEAGE_DB.PUBLIC.GRAPH_NODES_VW AS
SELECT NODEID::BIGINT AS NODEID FROM NEO4J_LINEAGE_DB.PUBLIC.NODES_VW;

CREATE OR REPLACE VIEW NEO4J_LINEAGE_DB.PUBLIC.GRAPH_RELS_VW AS
SELECT SOURCENODEID::BIGINT AS SOURCENODEID, TARGETNODEID::BIGINT AS TARGETNODEID
FROM NEO4J_LINEAGE_DB.PUBLIC.RELATIONSHIPS_VW;

-- ----------------------------------------------------------------------------
-- SECTION 8 (OPTIONAL): Neo4j Graph Analytics application support --
-- only needed if you want the WCC/PageRank/Louvain algorithm buttons to
-- actually work. Currently NOT required: SHOW_GRAPH_ALGORITHMS is False
-- in the deployed app, so these buttons are hidden entirely today.
--
-- Requires the "Neo4j Graph Analytics for Snowflake" app already
-- installed from the Marketplace (the manual step noted at the top of
-- this file) -- these GRANT ... TO APPLICATION statements will fail
-- with an "object does not exist" error otherwise.
--
-- Skip this whole section unless/until you re-enable those buttons.
-- ----------------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;

-- Let the application itself (not your role) see and read the data it
-- needs to build a graph from.
GRANT USAGE ON DATABASE TASTY_BYTES_DB TO APPLICATION Neo4j_Graph_Analytics;
GRANT USAGE ON SCHEMA TASTY_BYTES_DB.DEV TO APPLICATION Neo4j_Graph_Analytics;
GRANT USAGE ON DATABASE NEO4J_LINEAGE_DB TO APPLICATION Neo4j_Graph_Analytics;
GRANT USAGE ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO APPLICATION Neo4j_Graph_Analytics;
GRANT SELECT ON ALL TABLES IN SCHEMA TASTY_BYTES_DB.DEV TO APPLICATION Neo4j_Graph_Analytics;
GRANT SELECT ON ALL VIEWS IN SCHEMA TASTY_BYTES_DB.DEV TO APPLICATION Neo4j_Graph_Analytics;

-- Let the application write its own computed result tables
-- (RESULT_WCC_LINEAGE_COMPONENTS, etc.) back into our schema.
GRANT CREATE TABLE ON SCHEMA NEO4J_LINEAGE_DB.PUBLIC TO APPLICATION Neo4j_Graph_Analytics;

-- A database role wrapping FUTURE grants, specifically because dbt
-- rebuilds every Gold table via CREATE OR REPLACE on each run -- a
-- plain one-time GRANT SELECT ON ALL TABLES wouldn't survive that, so
-- this keeps the application seeing rebuilt tables automatically.
CREATE DATABASE ROLE IF NOT EXISTS TASTY_BYTES_DB.NEO4J_READ_ROLE;
GRANT SELECT ON FUTURE TABLES IN SCHEMA TASTY_BYTES_DB.DEV TO DATABASE ROLE TASTY_BYTES_DB.NEO4J_READ_ROLE;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA TASTY_BYTES_DB.DEV TO DATABASE ROLE TASTY_BYTES_DB.NEO4J_READ_ROLE;
GRANT DATABASE ROLE TASTY_BYTES_DB.NEO4J_READ_ROLE TO APPLICATION Neo4j_Graph_Analytics;

-- Consumer-side: let NEO4J_LINEAGE_ROLE actually call the app's
-- procedures and see its own result tables.
GRANT APPLICATION ROLE Neo4j_Graph_Analytics.app_user TO ROLE NEO4J_LINEAGE_ROLE;
GRANT APPLICATION ROLE Neo4j_Graph_Analytics.app_admin TO ROLE NEO4J_LINEAGE_ROLE;

-- Optional verification -- confirms the app can see a compute pool to
-- run on.
USE ROLE NEO4J_LINEAGE_ROLE;
USE WAREHOUSE NEO4J_LINEAGE_WH;
CALL Neo4j_Graph_Analytics.graph.show_available_compute_pools();

-- ============================================================================
-- MANUAL STEPS REMAINING (cannot be scripted in SQL):
--
-- 1. Deploy the Streamlit app itself: open a Workspace connected to the
--    project's Git repo (or upload streamlit_app.py directly), then use
--    Snowsight's "Deploy app" flow -- Owner role: NEO4J_LINEAGE_ROLE,
--    Query warehouse: NEO4J_LINEAGE_WH, App location:
--    NEO4J_LINEAGE_DB.PUBLIC.
--
-- 2. If you want the WCC/PageRank/Louvain algorithm buttons to have
--    results ready (optional -- SHOW_GRAPH_ALGORITHMS is currently False
--    in the app anyway), click "Run WCC" / "Run PageRank" / "Run
--    Louvain" once inside the deployed app -- these write their own
--    RESULT_* tables automatically, nothing to pre-create.
-- ============================================================================