-- Grain: one row per line item within an order.
-- The INNER JOIN to stg_order_header is what applies the 2-year filter
-- here -- stg_order_header only contains orders >= 2020-11-01, so only
-- line items belonging to those orders survive this join.

SELECT
    od.order_detail_id,
    od.order_id,
    oh.order_ts,
    oh.order_channel,
    oh.truck_id,
    oh.location_id,
    oh.customer_id,
    od.menu_item_id,
    od.line_number,
    od.quantity,
    od.unit_price,
    od.price AS line_total
FROM {{ ref('stg_order_detail') }} od
INNER JOIN {{ ref('stg_order_header') }} oh
    ON od.order_id = oh.order_id