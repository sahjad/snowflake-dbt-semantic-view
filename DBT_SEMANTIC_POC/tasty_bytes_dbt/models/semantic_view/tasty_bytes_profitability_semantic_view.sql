{{ config(materialized='semantic_view') }}

TABLES (
    fct_order_detail     AS {{ ref('fct_order_detail') }}     PRIMARY KEY (order_detail_id),
    dim_menu             AS {{ ref('dim_menu') }}             PRIMARY KEY (menu_item_id),
    dim_truck            AS {{ ref('dim_truck') }}            PRIMARY KEY (truck_id),
    dim_location         AS {{ ref('dim_location') }}         PRIMARY KEY (location_id),
    dim_customer_loyalty AS {{ ref('dim_customer_loyalty') }} PRIMARY KEY (customer_id)
)

RELATIONSHIPS (
    order_detail_to_menu     AS fct_order_detail (menu_item_id) REFERENCES dim_menu (menu_item_id),
    order_detail_to_truck    AS fct_order_detail (truck_id)     REFERENCES dim_truck (truck_id),
    order_detail_to_location AS fct_order_detail (location_id)  REFERENCES dim_location (location_id),
    order_detail_to_customer AS fct_order_detail (customer_id)  REFERENCES dim_customer_loyalty (customer_id)
)

FACTS (
    fct_order_detail.order_detail_id_fact AS order_detail_id,
    fct_order_detail.quantity_fact        AS quantity,
    fct_order_detail.unit_price_fact      AS unit_price,
    fct_order_detail.line_total_fact      AS line_total,

    -- New: catalog-level cost/price, exposed as facts so ad-hoc questions
    -- like "average cost of goods for Snacks" work without a formal metric
    dim_menu.cost_of_goods_fact           AS cost_of_goods_usd,
    dim_menu.list_price_fact              AS sale_price_usd
)

DIMENSIONS (
    fct_order_detail.order_ts          AS order_ts,

    dim_menu.menu_type                 AS menu_type,
    dim_menu.truck_brand_name          AS truck_brand_name,
    dim_menu.menu_item_name            AS menu_item_name,
    dim_menu.item_category             AS item_category,
    dim_menu.item_subcategory          AS item_subcategory,

    dim_truck.truck_home_city          AS primary_city,
    dim_truck.truck_region             AS region,
    dim_truck.truck_country            AS country,

    dim_location.location_city         AS city,
    dim_location.location_region       AS region,
    dim_location.location_country      AS country,

    dim_customer_loyalty.customer_city    AS city,
    dim_customer_loyalty.customer_country AS country,
    dim_customer_loyalty.favourite_brand  AS favourite_brand
)

METRICS (
    -- Revenue included here too (not just in the sales view) so margin
    -- can be computed within this one view, without cross-referencing
    -- the other semantic view.
    fct_order_detail.total_revenue AS SUM(fct_order_detail.line_total),

    -- New: actual cost realized against what was actually sold --
    -- quantity sold times each item's catalog cost, summed at the
    -- line-item level (not just a catalog-level number).
    fct_order_detail.total_cost AS SUM(fct_order_detail.quantity * dim_menu.cost_of_goods_fact),

    -- New: the metric this whole view exists for. Realized gross profit,
    -- computed per line item (revenue minus cost for that line) then
    -- summed -- not catalog margin, actual margin on what was sold.
    fct_order_detail.gross_profit AS SUM(
        fct_order_detail.line_total - (fct_order_detail.quantity * dim_menu.cost_of_goods_fact)
    )
)

AI_VERIFIED_QUERIES (
    gross_profit_by_truck_brand AS (
        QUESTION 'What is our gross profit by truck brand?'
        SQL 'SELECT truck_brand_name, AGG(gross_profit) AS gross_profit
             FROM tasty_bytes_profitability_semantic_view
             GROUP BY truck_brand_name ORDER BY gross_profit DESC'
    ),
    profit_margin_by_category AS (
        QUESTION 'What is our profit margin percentage by menu category?'
        SQL 'SELECT item_category,
                    AGG(gross_profit) / AGG(total_revenue) * 100 AS profit_margin_pct
             FROM tasty_bytes_profitability_semantic_view
             GROUP BY item_category ORDER BY profit_margin_pct DESC'
    ),
    highest_cost_menu_items AS (
        QUESTION 'Which menu items have the highest cost of goods?'
        SQL 'SELECT menu_item_name, AVG(cost_of_goods_fact) AS avg_cost
             FROM tasty_bytes_profitability_semantic_view
             GROUP BY menu_item_name ORDER BY avg_cost DESC'
    )
)