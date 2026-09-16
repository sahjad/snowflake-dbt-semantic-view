-- One row per order. This is the ONLY place we apply the 2-year date
-- filter -- order_detail has no date column of its own, so it inherits
-- this filter later via the join in the Gold fact table (Step 3).

SELECT
    order_id,
    truck_id,
    -- location_id arrives as FLOAT in the raw source; cast to a clean
    -- integer type so it joins cleanly against location.location_id later
    CAST(location_id AS NUMBER(19,0)) AS location_id,
    customer_id,
    shift_id,
    order_channel,
    order_ts,
    order_amount,
    order_total
FROM {{ source('tasty_bytes_raw', 'order_header') }}
WHERE order_ts >= '2020-11-01'