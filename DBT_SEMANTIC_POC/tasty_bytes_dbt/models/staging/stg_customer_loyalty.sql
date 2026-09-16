SELECT
    customer_id,
    first_name,
    last_name,
    city,
    country,
    preferred_language,
    favourite_brand,
    marital_status,
    sign_up_date
FROM {{ source('tasty_bytes_raw', 'customer_loyalty') }}