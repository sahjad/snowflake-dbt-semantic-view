-- Calendar dimension, generated natively via Snowflake's GENERATOR table
-- function -- deliberately NOT using dbt_utils.date_spine, since that
-- package requires `dbt deps` and therefore an External Access Integration,
-- the exact thing this whole project avoids (see the vendored macros in
-- macros/). This needs nothing beyond what Snowflake already provides.
--
-- Range: 2015-01-01 through 2030-12-31 (5,844 days) -- wide enough to cover
-- the full Tasty Bytes history plus headroom for future demo data, without
-- depending on a live MIN/MAX scan of the fact tables (which would create a
-- dependency from a dimension back onto a fact -- backwards for a star
-- schema).
--
-- Every derived column below is wrapped in an explicit CAST. Built-in date
-- functions like YEAR()/MONTH()/DAYNAME() don't have a single universally
-- documented return precision, so leaving them bare risks a mismatch against
-- the exact data_type declared in schema.yml, which would fail this model's
-- contract. The CAST makes the type deterministic regardless of what
-- Snowflake would have inferred on its own.

WITH date_spine AS (
    SELECT DATEADD(day, SEQ4(), '2015-01-01'::DATE) AS date_day
    FROM TABLE(GENERATOR(ROWCOUNT => 5844))
)

SELECT
    date_day,
    CAST(YEAR(date_day)         AS NUMBER(4,0)) AS year,
    CAST(QUARTER(date_day)      AS NUMBER(1,0)) AS quarter,
    CAST(MONTH(date_day)        AS NUMBER(2,0)) AS month,
    CAST(MONTHNAME(date_day)    AS VARCHAR(3))  AS month_name,
    CAST(WEEKISO(date_day)      AS NUMBER(2,0)) AS week_of_year,
    CAST(DAYOFWEEKISO(date_day) AS NUMBER(1,0)) AS day_of_week,   -- 1 = Mon ... 7 = Sun
    CAST(DAYNAME(date_day)      AS VARCHAR(3))  AS day_name,
    CAST(DAYOFMONTH(date_day)   AS NUMBER(2,0)) AS day_of_month,
    CAST(DAYOFYEAR(date_day)    AS NUMBER(3,0)) AS day_of_year,
    IFF(DAYOFWEEKISO(date_day) IN (6, 7), TRUE, FALSE) AS is_weekend
FROM date_spine
