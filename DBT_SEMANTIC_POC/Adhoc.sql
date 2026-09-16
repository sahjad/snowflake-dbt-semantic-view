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