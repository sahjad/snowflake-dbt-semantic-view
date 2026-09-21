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
    fct_order_detail.order_id_fact        AS order_id,
    fct_order_detail.quantity_fact        AS quantity,
    fct_order_detail.unit_price_fact      AS unit_price,
    fct_order_detail.line_total_fact      AS line_total
)

DIMENSIONS (
    fct_order_detail.order_ts          AS order_ts,
    fct_order_detail.order_channel     AS order_channel,

    dim_menu.menu_type                 AS menu_type,
    dim_menu.truck_brand_name          AS truck_brand_name,
    dim_menu.menu_item_name            AS menu_item_name,
    dim_menu.item_category             AS item_category,
    dim_menu.item_subcategory          AS item_subcategory,

    dim_truck.truck_home_city          AS primary_city,
    dim_truck.truck_region             AS region,
    dim_truck.truck_country            AS country,
    dim_truck.make                     AS make,
    dim_truck.ev_flag                  AS ev_flag,

    dim_location.location_city         AS city,
    dim_location.location_region       AS region,
    dim_location.location_country      AS country,

    dim_customer_loyalty.customer_city    AS city,
    dim_customer_loyalty.customer_country AS country,
    dim_customer_loyalty.preferred_language AS preferred_language,
    dim_customer_loyalty.favourite_brand    AS favourite_brand,
    dim_customer_loyalty.marital_status     AS marital_status
)

METRICS (
    fct_order_detail.total_revenue       AS SUM(fct_order_detail.line_total_fact),
    fct_order_detail.total_orders        AS COUNT(DISTINCT fct_order_detail.order_id_fact),
    fct_order_detail.total_quantity_sold AS SUM(fct_order_detail.quantity_fact)
)

AI_VERIFIED_QUERIES (
    revenue_by_truck_brand AS (
        QUESTION 'What is our total revenue by truck brand?'
        SQL 'SELECT dim_menu.truck_brand_name, SUM(fct_order_detail.line_total_fact) AS total_revenue
             FROM fct_order_detail
             JOIN dim_menu ON fct_order_detail.menu_item_id = dim_menu.menu_item_id
             GROUP BY dim_menu.truck_brand_name ORDER BY total_revenue DESC'
    ),
    orders_loyalty_vs_nonmember AS (
        QUESTION 'How many orders came from loyalty members versus non-members?'
        SQL 'SELECT CASE WHEN dim_customer_loyalty.customer_city IS NULL THEN ''Non-Member''
                          ELSE ''Loyalty Member'' END AS customer_type,
                    COUNT(DISTINCT fct_order_detail.order_id_fact) AS order_count
             FROM fct_order_detail
             LEFT JOIN dim_customer_loyalty ON fct_order_detail.customer_id = dim_customer_loyalty.customer_id
             GROUP BY customer_type'
    ),
    avg_order_value_by_city AS (
        QUESTION 'What is the average order value by city?'
        SQL 'SELECT dim_location.location_city,
                    SUM(fct_order_detail.line_total_fact) / COUNT(DISTINCT fct_order_detail.order_id_fact) AS avg_order_value
             FROM fct_order_detail
             JOIN dim_location ON fct_order_detail.location_id = dim_location.location_id
             GROUP BY dim_location.location_city ORDER BY avg_order_value DESC'
    )
)