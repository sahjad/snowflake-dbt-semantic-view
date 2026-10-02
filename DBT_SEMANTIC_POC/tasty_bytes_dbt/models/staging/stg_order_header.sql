-- One row per order. This is the ONLY place we apply the 2-year date filter --
-- order_detail has no date column of its own, so it inherits this filter later
-- via the join in fct_order_detail, and fct_order_header reads straight from
-- this model so it inherits it too.
--
-- order_tax_amount, order_discount_amount, and served_ts arrive as VARCHAR in
-- the raw source (not their "natural" numeric/timestamp types) -- using
-- TRY_TO_NUMBER / TRY_TO_TIMESTAMP_NTZ here so a stray non-numeric or blank
-- value becomes NULL instead of failing the whole run.

SELECT
    order_id,
    truck_id,
    -- location_id arrives as FLOAT in the raw source; cast to a clean
    -- integer type so it joins cleanly against location.location_id later
    CAST(location_id AS NUMBER(19,0)) AS location_id,
    customer_id,
    discount_id,
    shift_id,
    shift_start_time,
    shift_end_time,
    order_channel,
    order_ts,
    TRY_TO_TIMESTAMP_NTZ(served_ts) AS served_ts,
    order_currency,
    order_amount,
    TRY_TO_NUMBER(order_tax_amount, 38, 4) AS order_tax_amount,
    TRY_TO_NUMBER(order_discount_amount, 38, 4) AS order_discount_amount,
    order_total
FROM {{ source('tasty_bytes_raw', 'order_header') }}
WHERE order_ts >= '2020-11-01'
