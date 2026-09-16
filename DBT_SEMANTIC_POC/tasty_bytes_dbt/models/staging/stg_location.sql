SELECT
    location_id,
    location,
    city,
    region,
    country
FROM {{ source('tasty_bytes_raw', 'location') }}