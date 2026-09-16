-- One row per line item within an order. No date filter applied here --
-- it inherits the 2-year window from stg_order_header via the join
-- in the Gold fact table (Step 3).

SELECT
    order_detail_id,
    order_id,
    menu_item_id,
    line_number,
    quantity,
    unit_price,
    price
FROM {{ source('tasty_bytes_raw', 'order_detail') }}