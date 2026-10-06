USE ROLE ACCOUNTADMIN;

-- Required to associate/run system DMFs at all
GRANT DATABASE ROLE SNOWFLAKE.DATA_METRIC_USER TO ROLE ACCOUNTADMIN;

-- Required to query the results afterward -- granting to both roles that
-- will need to read it (yourself, and NEO4J_LINEAGE_ROLE for the graph enrichment later)
GRANT APPLICATION ROLE SNOWFLAKE.DATA_QUALITY_MONITORING_VIEWER TO ROLE ACCOUNTADMIN;
GRANT APPLICATION ROLE SNOWFLAKE.DATA_QUALITY_MONITORING_VIEWER TO ROLE NEO4J_LINEAGE_ROLE;

USE DATABASE TASTY_BYTES_DB;
USE SCHEMA DEV;


ALTER TABLE dim_menu                      SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_truck                     SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_location                  SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_customer_loyalty          SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_franchise                 SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_date                      SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE dim_menu_item_health_metrics  SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE bridge_menu_item_ingredient   SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE fct_order_header              SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';
ALTER TABLE fct_order_detail              SET DATA_METRIC_SCHEDULE = 'USING CRON 0 * * * * UTC';



-- ============================================================
-- dim_menu
-- ============================================================
ALTER TABLE dim_menu ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_menu ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (menu_item_id);
ALTER TABLE dim_menu ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (menu_item_id);

-- ============================================================
-- dim_truck
-- ============================================================
ALTER TABLE dim_truck ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_truck ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (truck_id);
ALTER TABLE dim_truck ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (truck_id);

-- ============================================================
-- dim_location
-- ============================================================
ALTER TABLE dim_location ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_location ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (location_id);
ALTER TABLE dim_location ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (location_id);

-- ============================================================
-- dim_customer_loyalty
-- ============================================================
ALTER TABLE dim_customer_loyalty ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_customer_loyalty ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (customer_id);
ALTER TABLE dim_customer_loyalty ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (customer_id);

-- ============================================================
-- dim_franchise -- DUPLICATE_COUNT here specifically validates the
-- QUALIFY dedup in stg_franchise.sql actually worked; should report 0
-- ============================================================
ALTER TABLE dim_franchise ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_franchise ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (franchise_id);
ALTER TABLE dim_franchise ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (franchise_id);

-- ============================================================
-- dim_date -- static calendar spine, no FRESHNESS check needed
-- ============================================================
ALTER TABLE dim_date ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_date ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (date_day);
ALTER TABLE dim_date ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (date_day);

-- ============================================================
-- dim_menu_item_health_metrics
-- ============================================================
ALTER TABLE dim_menu_item_health_metrics ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE dim_menu_item_health_metrics ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (menu_item_id);
ALTER TABLE dim_menu_item_health_metrics ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (menu_item_id);

-- ============================================================
-- bridge_menu_item_ingredient -- composite key, checking both columns
-- individually rather than guessing multi-column DUPLICATE_COUNT semantics
-- ============================================================
ALTER TABLE bridge_menu_item_ingredient ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE bridge_menu_item_ingredient ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (menu_item_id);
ALTER TABLE bridge_menu_item_ingredient ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (ingredient_name);

-- ============================================================
-- fct_order_header
-- ============================================================
ALTER TABLE fct_order_header ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE fct_order_header ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (order_id);
ALTER TABLE fct_order_header ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (order_id);
ALTER TABLE fct_order_header ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (customer_id);
ALTER TABLE fct_order_header ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.FRESHNESS ON (order_date);

-- ============================================================
-- fct_order_detail
-- ============================================================
ALTER TABLE fct_order_detail ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.ROW_COUNT ON ();
ALTER TABLE fct_order_detail ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (order_detail_id);
ALTER TABLE fct_order_detail ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.DUPLICATE_COUNT ON (order_detail_id);
ALTER TABLE fct_order_detail ADD DATA METRIC FUNCTION SNOWFLAKE.CORE.NULL_COUNT ON (customer_id);




SELECT SYSDATE();


-- Check DMFs Applied
SELECT 'DIM_MENU' AS tbl, * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_MENU', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_TRUCK', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_TRUCK', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_LOCATION', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_LOCATION', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_CUSTOMER_LOYALTY', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_CUSTOMER_LOYALTY', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_FRANCHISE', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_FRANCHISE', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_DATE', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_DATE', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'DIM_MENU_ITEM_HEALTH_METRICS', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.DIM_MENU_ITEM_HEALTH_METRICS', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'BRIDGE_MENU_ITEM_INGREDIENT', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.BRIDGE_MENU_ITEM_INGREDIENT', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'FCT_ORDER_HEADER', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.FCT_ORDER_HEADER', REF_ENTITY_DOMAIN => 'TABLE'))
UNION ALL
SELECT 'FCT_ORDER_DETAIL', * FROM TABLE(INFORMATION_SCHEMA.DATA_METRIC_FUNCTION_REFERENCES(REF_ENTITY_NAME => 'TASTY_BYTES_DB.DEV.FCT_ORDER_DETAIL', REF_ENTITY_DOMAIN => 'TABLE'));


-- Test DMF
SELECT table_name, metric_name, value, measurement_time
FROM SNOWFLAKE.LOCAL.DATA_QUALITY_MONITORING_RESULTS
WHERE table_database = 'TASTY_BYTES_DB' AND table_schema = 'DEV'
ORDER BY measurement_time DESC;



ALTER TABLE dim_menu                      SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_truck                     SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_location                  SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_customer_loyalty          SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_franchise                 SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_date                      SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE dim_menu_item_health_metrics  SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE bridge_menu_item_ingredient   SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE fct_order_header              SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';
ALTER TABLE fct_order_detail              SET DATA_METRIC_SCHEDULE = 'USING CRON 0 6 * * * UTC';



