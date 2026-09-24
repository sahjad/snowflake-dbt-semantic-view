SHOW GRANTS TO ROLE ACCOUNTADMIN;

USE WAREHOUSE TASTY_BYTES_WH;

SELECT MIN(order_ts) AS earliest_order, MAX(order_ts) AS latest_order
FROM TASTY_BYTES_DB.raw.order_header;



SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.stg_order_header;   -- should be well under 248M
SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.stg_order_detail;   -- full 673M, unfiltered at this layer
SELECT MIN(order_ts), MAX(order_ts) FROM TASTY_BYTES_DB.dev.stg_order_header;  -- should show >= 2020-11-01


SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.fct_order_detail;
SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.dim_menu;
SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.dim_truck;
SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.dim_location;
SELECT COUNT(*) FROM TASTY_BYTES_DB.dev.dim_customer_loyalty;
SELECT SUM(line_total) AS total_revenue FROM TASTY_BYTES_DB.dev.fct_order_detail;


SELECT table_name, table_type
FROM TASTY_BYTES_DB.INFORMATION_SCHEMA.TABLES
WHERE table_schema = 'DEV'
ORDER BY table_type, table_name;


USE DATABASE TASTY_BYTES_DB;
USE SCHEMA dev;

CREATE OR REPLACE NETWORK RULE dbt_network_rule
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = (
    'hub.getdbt.com',
    'codeload.github.com'
  );

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION dbt_ext_access
  ALLOWED_NETWORK_RULES = (dbt_network_rule)
  ENABLED = TRUE;


SHOW SEMANTIC VIEWS IN SCHEMA TASTY_BYTES_DB.dev;

SELECT truck_brand_name, AGG(total_revenue) AS revenue
FROM TASTY_BYTES_DB.dev.tasty_bytes_semantic_view
GROUP BY truck_brand_name
ORDER BY revenue DESC;


DESCRIBE SEMANTIC VIEW TASTY_BYTES_DB.dev.tasty_bytes_semantic_view;


SELECT SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('TASTY_BYTES_DB.DEV.TASTY_BYTES_SEMANTIC_VIEW');


SELECT order_channel, COUNT(order_detail_id_fact) AS line_item_count
FROM TASTY_BYTES_DB.dev.tasty_bytes_semantic_view
GROUP BY order_channel
ORDER BY line_item_count DESC;


SELECT order_channel, COUNT(*) 
FROM TASTY_BYTES_DB.raw.order_header 
GROUP BY order_channel;


SELECT item_category, location_city, AGG(total_revenue) AS revenue
FROM TASTY_BYTES_DB.dev.tasty_bytes_semantic_view
GROUP BY item_category, location_city
ORDER BY revenue DESC;



-- Matches its YTD 2022 vs YTD 2021 comparison
SELECT 
    m.truck_brand_name,
    SUM(CASE WHEN f.order_ts BETWEEN '2022-01-01' AND '2022-11-01' THEN f.line_total ELSE 0 END) AS ytd_2022,
    SUM(CASE WHEN f.order_ts BETWEEN '2021-01-01' AND '2021-11-01' THEN f.line_total ELSE 0 END) AS prior_ytd_2021
FROM TASTY_BYTES_DB.dev.fct_order_detail f
JOIN TASTY_BYTES_DB.dev.dim_menu m ON f.menu_item_id = m.menu_item_id
WHERE m.truck_brand_name IN ('Kitakata Ramen Bar', 'Nani''s Kitchen', 'Cheeky Greek', 'Smoky BBQ', 'Le Coin des Crêpes')
GROUP BY m.truck_brand_name
ORDER BY ytd_2022 DESC;

-- Matches its "30-day rolling average" (Oct 3 -- Nov 1, 2022)
SELECT 
    m.truck_brand_name,
    SUM(f.line_total) / 30.0 AS avg_daily_revenue_last_30_days
FROM TASTY_BYTES_DB.dev.fct_order_detail f
JOIN TASTY_BYTES_DB.dev.dim_menu m ON f.menu_item_id = m.menu_item_id
WHERE f.order_ts BETWEEN '2022-10-03' AND '2022-11-01'
  AND m.truck_brand_name IN ('Kitakata Ramen Bar', 'Nani''s Kitchen', 'Cheeky Greek', 'Smoky BBQ', 'Le Coin des Crêpes')
GROUP BY m.truck_brand_name
ORDER BY avg_daily_revenue_last_30_days DESC;

SHOW SEMANTIC VIEWS IN SCHEMA TASTY_BYTES_DB.dev;

SELECT dim_menu.truck_brand_name, AGG(fct_order_detail.total_revenue) AS total_revenue
FROM TASTY_BYTES_DB.dev.tasty_bytes_truck_menu_yaml_demo
GROUP BY dim_menu.truck_brand_name;



SELECT CURRENT_USER();

LIST @TASTY_BYTES_DB.SEMANTIC_TOOL.TMP_WS_WRITE;



GRANT WRITE ON WORKSPACE "USER$<their_own_username>".PUBLIC."snowflake-dbt-semantic-view" TO ROLE <their_active_role>;
GRANT WRITE ON WORKSPACE "USER$SAHJAD".PUBLIC."snowflake-dbt-semantic-view" TO ROLE ACCOUNTADMIN;


CREATE DBT PROJECT TASTY_BYTES_DB.SEMANTIC_TOOL.tasty_bytes_dbt_deploy
FROM 'snow://workspace/"USER$SAHJAD".PUBLIC."snowflake-dbt-semantic-view"/versions/live/DBT_SEMANTIC_POC/tasty_bytes_dbt';




EXECUTE DBT PROJECT TASTY_BYTES_DB.SEMANTIC_TOOL.tasty_bytes_dbt_deploy
  ARGS = 'run --target dev --select models/semantic_view/customer_loyalty_insights.sql';