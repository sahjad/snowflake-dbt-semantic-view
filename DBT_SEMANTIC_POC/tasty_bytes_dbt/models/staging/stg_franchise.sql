-- One row per franchise owner. The source table was loaded into Bronze from
-- day one (Step1: Ingestion.sql) but never referenced anywhere downstream --
-- dim_truck.franchise_id has been pointing at nothing until this model and
-- gold/dim_franchise.sql exist.
--
-- KNOWN SOURCE DATA QUIRK, confirmed against live data: 10 franchise_id
-- values have two rows each in raw.franchise -- same person (identical
-- first_name/last_name/e_mail/phone_number), but a different city on each
-- row (e.g. franchise_id 37 = Mary Sanders, one row for Seattle, one for
-- Boston). This looks like a franchisee operating out of more than one
-- home-base city, not a load error.
--
-- dim_truck.franchise_id is a single-valued FK, so dim_franchise needs
-- exactly one row per franchise_id for that relationship to mean anything.
-- QUALIFY picks one row deterministically (alphabetically first city) --
-- a deliberate, documented simplification, not a silent drop. See
-- _sources.yml for the matching source-level test, kept as a `warn` rather
-- than a hard failure specifically so this stays visible without blocking
-- the build.

SELECT
    franchise_id,
    first_name,
    last_name,
    city,
    country,
    e_mail,
    phone_number
FROM {{ source('tasty_bytes_raw', 'franchise') }}
QUALIFY ROW_NUMBER() OVER (PARTITION BY franchise_id ORDER BY city) = 1
