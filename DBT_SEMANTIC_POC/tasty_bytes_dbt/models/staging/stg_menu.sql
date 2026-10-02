-- menu_item_health_metrics_obj is carried through as-is (VARIANT) -- it was
-- dropped silently by the original version of this model. See
-- gold/dim_menu_item_health_metrics.sql for the (unverified, best-effort)
-- flattening of this object, and the verification query to run before
-- trusting it.

SELECT
    menu_item_id,
    menu_type,
    truck_brand_name,
    menu_item_name,
    item_category,
    item_subcategory,
    cost_of_goods_usd,
    sale_price_usd,
    menu_item_health_metrics_obj
FROM {{ source('tasty_bytes_raw', 'menu') }}
