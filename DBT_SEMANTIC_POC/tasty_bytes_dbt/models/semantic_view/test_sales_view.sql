{{ config(materialized='semantic_view_yaml') }}
name: TEST_SALES_VIEW
tables:
- name: FCT_ORDER_DETAIL
  base_table:
    database: TASTY_BYTES_DB
    schema: DEV
    table: FCT_ORDER_DETAIL
  primary_key:
    columns:
    - ORDER_DETAIL_ID
  facts:
  - name: line_total_fact
    expr: LINE_TOTAL
    data_type: NUMBER(38,4)
  metrics:
  - name: total_revenue
    expr: SUM(FCT_ORDER_DETAIL.line_total_fact)
- name: DIM_MENU
  base_table:
    database: TASTY_BYTES_DB
    schema: DEV
    table: DIM_MENU
  primary_key:
    columns:
    - MENU_ITEM_ID
  dimensions:
  - name: truck_brand_name
    expr: TRUCK_BRAND_NAME
    data_type: VARCHAR(16777216)
relationships:
- name: fct_order_detail_to_dim_menu
  left_table: FCT_ORDER_DETAIL
  right_table: DIM_MENU
  relationship_columns:
  - left_column: MENU_ITEM_ID
    right_column: MENU_ITEM_ID
  relationship_type: many_to_one
verified_queries:
  - name: revenue_by_truck_brand
    question: "What is our total revenue by truck brand?"
    sql: "SELECT DIM_MENU.truck_brand_name, SUM(FCT_ORDER_DETAIL.line_total_fact) AS total_revenue FROM FCT_ORDER_DETAIL JOIN DIM_MENU ON FCT_ORDER_DETAIL.menu_item_id = DIM_MENU.menu_item_id GROUP BY DIM_MENU.truck_brand_name ORDER BY total_revenue DESC"