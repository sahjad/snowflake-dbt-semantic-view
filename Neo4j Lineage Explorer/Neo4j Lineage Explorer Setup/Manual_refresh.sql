-- ============================================================================
-- DEMO QUICK REFERENCE: manually trigger either refresh instantly,
-- instead of waiting for the 7am UTC scheduled task.
--
-- Run as NEO4J_LINEAGE_ROLE. Each one takes a few seconds, not instant --
-- GET_LINEAGE calls and SHOW GRANTS TO SHARE both involve real work, not
-- just a cache flip.
-- ============================================================================

USE ROLE NEO4J_LINEAGE_ROLE;
USE WAREHOUSE NEO4J_LINEAGE_WH;

-- ----------------------------------------------------------------------------
-- Just added/changed a LISTING (new listing published, or a semantic
-- view added to/removed from an existing one's share)?
-- ----------------------------------------------------------------------------
CALL NEO4J_LINEAGE_DB.PUBLIC.REFRESH_LISTING_SEMANTIC_VIEW_MAP();

-- Confirm it picked up the change:
SELECT * FROM NEO4J_LINEAGE_DB.PUBLIC.LISTING_SEMANTIC_VIEW_MAP;

-- ----------------------------------------------------------------------------
-- Just added/changed a GOLD TABLE (new dbt model, or an existing one's
-- Staging source changed)?
-- ----------------------------------------------------------------------------
CALL NEO4J_LINEAGE_DB.PUBLIC.REFRESH_GOLD_SILVER_LINEAGE_SNAPSHOT();

-- Confirm it picked up the change:
SELECT * FROM NEO4J_LINEAGE_DB.PUBLIC.GOLD_SILVER_DEPENDS_ON_SNAPSHOT ORDER BY TARGET_OBJECT_NAME;

-- ----------------------------------------------------------------------------
-- Changed something structural (new Gold table that needs a grant, or a
-- PK/FK constraint changed)? Also worth refreshing, same idea:
-- ----------------------------------------------------------------------------
-- New table needs this FIRST, or neither refresh above will see it at all:
-- GRANT SELECT ON TABLE TASTY_BYTES_DB.DEV.<new_table_name> TO ROLE NEO4J_LINEAGE_ROLE;

CALL NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA();

-- ----------------------------------------------------------------------------
-- After any of the above -- the app itself will pick up the new data
-- automatically on its NEXT query (NODES_VW/RELATIONSHIPS_VW read these
-- tables live). If Streamlit's own caching makes it feel stale, just
-- rerun the app (or wait out its cache TTL) -- no need to redeploy
-- anything.
-- ----------------------------------------------------------------------------