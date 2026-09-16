SELECT
    truck_id,
    primary_city,
    region,
    country,
    year,
    make,
    model,
    ev_flag,
    franchise_id,
    truck_opening_date
FROM {{ source('tasty_bytes_raw', 'truck') }}