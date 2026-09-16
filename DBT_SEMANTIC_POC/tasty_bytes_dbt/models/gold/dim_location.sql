SELECT
    location_id,
    location,
    city,
    region,
    country
FROM {{ ref('stg_location') }}