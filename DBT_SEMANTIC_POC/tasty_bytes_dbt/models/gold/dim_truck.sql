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
FROM {{ ref('stg_truck') }}