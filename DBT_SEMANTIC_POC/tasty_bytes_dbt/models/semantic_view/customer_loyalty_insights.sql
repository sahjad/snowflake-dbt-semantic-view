{{ config(materialized='semantic_view_yaml') }}
name: CUSTOMER_LOYALTY_INSIGHTS
description: Understand loyalty programme performance -- spend, order volume, and
  average basket size across cities and customer segments.
tables:
- name: ORDER_ITEMS
  base_table:
    database: TASTY_BYTES_DB
    schema: DEV
    table: FCT_ORDER_DETAIL
  description: Individual line items -- one row per product sold
  primary_key:
    columns:
    - ORDER_DETAIL_ID
  facts:
  - name: line_total_fact
    expr: LINE_TOTAL
    data_type: NUMBER(38,4)
  - name: quantity_fact
    expr: QUANTITY
    data_type: NUMBER(5,0)
  - name: order_id_fact
    expr: ORDER_ID
    data_type: NUMBER(38,0)
  metrics:
  - name: total_spend
    expr: SUM(ORDER_ITEMS.line_total_fact)
  - name: total_orders
    expr: COUNT(DISTINCT ORDER_ITEMS.order_id_fact)
  - name: average_basket_value
    expr: SUM(ORDER_ITEMS.line_total_fact) / COUNT(DISTINCT ORDER_ITEMS.order_id_fact)
- name: CUSTOMERS
  base_table:
    database: TASTY_BYTES_DB
    schema: DEV
    table: DIM_CUSTOMER_LOYALTY
  description: Loyalty programme members
  primary_key:
    columns:
    - CUSTOMER_ID
  dimensions:
  - name: customer_name
    expr: FIRST_NAME
    data_type: VARCHAR(16777216)
  - name: customer_home_city
    expr: CITY
    data_type: VARCHAR(16777216)
    synonyms:
    - home city
    - residence
  - name: favourite_brand
    expr: FAVOURITE_BRAND
    data_type: VARCHAR(16777216)
    synonyms:
    - preferred brand
- name: LOCATIONS
  base_table:
    database: TASTY_BYTES_DB
    schema: DEV
    table: DIM_LOCATION
  description: Where the order was placed
  primary_key:
    columns:
    - LOCATION_ID
  dimensions:
  - name: order_city
    expr: CITY
    data_type: VARCHAR(16777216)
    synonyms:
    - where sold
    - point of sale
  - name: order_region
    expr: REGION
    data_type: VARCHAR(16777216)
    synonyms:
    - territory
relationships:
- name: order_items_to_locations
  left_table: ORDER_ITEMS
  right_table: LOCATIONS
  relationship_columns:
  - left_column: LOCATION_ID
    right_column: LOCATION_ID
  relationship_type: many_to_one
- name: order_items_to_customers
  left_table: ORDER_ITEMS
  right_table: CUSTOMERS
  relationship_columns:
  - left_column: CUSTOMER_ID
    right_column: CUSTOMER_ID
  relationship_type: many_to_one
verified_queries:
  - name: spend_by_order_city
    question: "What is our total loyalty spend by city?"
    sql: "SELECT LOCATIONS.order_city, SUM(ORDER_ITEMS.line_total_fact) AS total_spend FROM ORDER_ITEMS JOIN LOCATIONS ON ORDER_ITEMS.location_id = LOCATIONS.location_id GROUP BY LOCATIONS.order_city ORDER BY total_spend DESC"
