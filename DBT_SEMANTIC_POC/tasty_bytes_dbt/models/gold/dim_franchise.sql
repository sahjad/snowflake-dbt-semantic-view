-- franchise_owner_name is explicitly CAST (not just left as the bare result
-- of ||) so its declared contract type in schema.yml is guaranteed to match
-- what Snowflake actually produces -- string concatenation can otherwise
-- infer a longer VARCHAR than either operand alone, which would break the
-- model contract on first run.

SELECT
    franchise_id,
    first_name,
    last_name,
    CAST(first_name || ' ' || last_name AS VARCHAR(16777216)) AS franchise_owner_name,
    city    AS franchise_home_city,
    country AS franchise_home_country,
    e_mail,
    phone_number
FROM {{ ref('stg_franchise') }}
