{{ config(materialized='semantic_view_yaml') }}
name: TASTY_BYTES_TRUCK_MENU_YAML_DEMO
description: >
  Minimal example demonstrating semantic view creation via YAML through
  dbt (SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML), instead of the SQL DDL
  path used by tasty_bytes_semantic_view and
  tasty_bytes_profitability_semantic_view.

tables:
  - name: FCT_ORDER_DETAIL
    base_table:
      database: {{ ref('fct_order_detail').database }}
      schema: {{ ref('fct_order_detail').schema }}
      table: {{ ref('fct_order_detail').identifier }}
    primary_key:
      columns:
        - ORDER_DETAIL_ID
    facts:
      - name: LINE_TOTAL_FACT
        expr: line_total
      - name: QUANTITY_FACT
        expr: quantity
    metrics:
      - name: TOTAL_REVENUE
        expr: SUM(line_total)
      - name: TOTAL_QUANTITY_SOLD
        expr: SUM(quantity)

  - name: DIM_MENU
    base_table:
      database: {{ ref('dim_menu').database }}
      schema: {{ ref('dim_menu').schema }}
      table: {{ ref('dim_menu').identifier }}
    primary_key:
      columns:
        - MENU_ITEM_ID
    dimensions:
      - name: TRUCK_BRAND_NAME
        expr: truck_brand_name
      - name: ITEM_CATEGORY
        expr: item_category

relationships:
  - name: ORDER_DETAIL_TO_MENU
    left_table: FCT_ORDER_DETAIL
    right_table: DIM_MENU
    relationship_columns:
      - left_column: MENU_ITEM_ID
        right_column: MENU_ITEM_ID