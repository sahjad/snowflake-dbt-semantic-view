USE ROLE ACCOUNTADMIN;

-- Suspend the tasks first -- a cheap precaution, avoids any edge case
-- with an active scheduled task mid-run during the drop.
ALTER TASK NEO4J_LINEAGE_DB.PUBLIC.REFRESH_PK_FK_METADATA_TASK SUSPEND;
ALTER TASK NEO4J_LINEAGE_DB.PUBLIC.REFRESH_GOLD_SILVER_LINEAGE_TASK SUSPEND;
ALTER TASK NEO4J_LINEAGE_DB.PUBLIC.REFRESH_LISTING_MAP_TASK SUSPEND;

-- This one statement removes the database, every object inside it
-- (tables, views, procedures, tasks), AND the deployed Streamlit app.
DROP DATABASE NEO4J_LINEAGE_DB;

-- Removes the role itself.
DROP ROLE NEO4J_LINEAGE_ROLE;