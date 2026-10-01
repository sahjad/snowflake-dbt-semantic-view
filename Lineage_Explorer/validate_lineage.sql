/* ============================================================================
   Validate Snowflake metadata and native lineage before running the app.
   Change the object names below to objects that exist in your account.
   ============================================================================ */

USE ROLE LINEAGE_APP_ROLE;
USE WAREHOUSE LINEAGE_APP_WH;

-- 1. Confirm the target database and schemas are visible.
SHOW DATABASES LIKE 'TASTY_BYTES_DB';
SHOW SCHEMAS IN DATABASE TASTY_BYTES_DB;

-- 2. Confirm table-like objects and semantic views are visible.
SHOW TABLES IN DATABASE TASTY_BYTES_DB;
SHOW VIEWS IN DATABASE TASTY_BYTES_DB;
SHOW SEMANTIC VIEWS IN DATABASE TASTY_BYTES_DB;

-- 3. Validate upstream lineage for a known object.
SELECT
    DISTANCE,
    SOURCE_OBJECT_DATABASE,
    SOURCE_OBJECT_SCHEMA,
    SOURCE_OBJECT_NAME,
    SOURCE_OBJECT_DOMAIN,
    SOURCE_DETAILS:dataset_type::VARCHAR AS SOURCE_DATASET_TYPE,
    TARGET_OBJECT_DATABASE,
    TARGET_OBJECT_SCHEMA,
    TARGET_OBJECT_NAME,
    TARGET_OBJECT_DOMAIN,
    TARGET_DETAILS:dataset_type::VARCHAR AS TARGET_DATASET_TYPE,
    PROCESS
FROM TABLE(
    SNOWFLAKE.CORE.GET_LINEAGE(
        object_name   => 'TASTY_BYTES_DB.DEV.FCT_ORDER_DETAIL',
        object_domain => 'TABLE',
        direction     => 'UPSTREAM',
        max_distance  => 3
    )
)
ORDER BY DISTANCE, SOURCE_OBJECT_NAME, TARGET_OBJECT_NAME;

-- 4. Validate downstream lineage as well.
SELECT
    DISTANCE,
    SOURCE_OBJECT_DATABASE,
    SOURCE_OBJECT_SCHEMA,
    SOURCE_OBJECT_NAME,
    SOURCE_OBJECT_DOMAIN,
    TARGET_OBJECT_DATABASE,
    TARGET_OBJECT_SCHEMA,
    TARGET_OBJECT_NAME,
    TARGET_OBJECT_DOMAIN,
    PROCESS
FROM TABLE(
    SNOWFLAKE.CORE.GET_LINEAGE(
        object_name   => 'TASTY_BYTES_DB.DEV.FCT_ORDER_DETAIL',
        object_domain => 'TABLE',
        direction     => 'DOWNSTREAM',
        max_distance  => 3
    )
)
ORDER BY DISTANCE, SOURCE_OBJECT_NAME, TARGET_OBJECT_NAME;

-- 5. Optional semantic-view metadata check. Replace the name before running.
-- SELECT *
-- FROM TASTY_BYTES_DB.INFORMATION_SCHEMA.SEMANTIC_TABLES
-- WHERE SEMANTIC_VIEW_SCHEMA = 'DEV'
--   AND SEMANTIC_VIEW_NAME = 'YOUR_SEMANTIC_VIEW_NAME';
