-- Order-grain fact: one row per order. A fact constellation alongside the
-- existing fct_order_detail (line-item grain) -- same business process, two
-- grains, for different questions. This is what lets "average order value",
-- tax, and discount be computed directly instead of re-deriving them from
-- line items every time.
--
-- order_date is a separate explicit column (not just DATE(order_ts) inline
-- wherever it's needed) specifically so it can be declared as a real FK to
-- dim_date.date_day.

SELECT
    order_id,
    truck_id,
    location_id,
    customer_id,
    CAST(order_ts AS DATE) AS order_date,
    order_ts,
    order_channel,
    order_currency,
    discount_id,
    shift_id,
    shift_start_time,
    shift_end_time,
    served_ts,
    order_amount,
    order_tax_amount,
    order_discount_amount,
    order_total
FROM {{ ref('stg_order_header') }}
