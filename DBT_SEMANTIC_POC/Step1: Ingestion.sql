-- ============================================================================
-- STEP 1: INGESTION / BRONZE LAYER
-- Tasty Bytes source data -> raw tables in Snowflake
-- Verified against: Snowflake-Labs/getting-started-with-dbt-on-snowflake
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- ----------------------------------------------------------------------------
-- 1. Warehouse
-- Fresh warehouse for this trial account. XLARGE speeds up the one-time
-- COPY INTO load; we resize down to SMALL afterward since that's plenty
-- for day-to-day dbt runs and Cortex Agent queries.
-- ----------------------------------------------------------------------------
CREATE WAREHOUSE IF NOT EXISTS TASTY_BYTES_WH
  WAREHOUSE_SIZE = XLARGE
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

USE WAREHOUSE TASTY_BYTES_WH;

-- ----------------------------------------------------------------------------
-- 2. Database and schemas
-- raw  -> Bronze layer, untouched source data (this step)
-- dev  -> where dbt will materialize Silver/Gold models during development (Step 2+)
-- prod -> where dbt will materialize the production-ready models (later)
-- ----------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS TASTY_BYTES_DB;
CREATE SCHEMA IF NOT EXISTS TASTY_BYTES_DB.raw;
CREATE SCHEMA IF NOT EXISTS TASTY_BYTES_DB.dev;
CREATE SCHEMA IF NOT EXISTS TASTY_BYTES_DB.prod;

-- ----------------------------------------------------------------------------
-- 3. File format + external stage pointing at Snowflake's public quickstart S3 bucket
-- No AWS credentials needed -- this bucket is public and Snowflake-hosted.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FILE FORMAT TASTY_BYTES_DB.raw.csv_ff
  TYPE = 'csv';

CREATE OR REPLACE STAGE TASTY_BYTES_DB.raw.s3load
  COMMENT = 'Tasty Bytes quickstart S3 stage'
  URL = 's3://sfquickstarts/frostbyte_tastybytes/'
  FILE_FORMAT = TASTY_BYTES_DB.raw.csv_ff;

-- ----------------------------------------------------------------------------
-- 4. Raw table DDL (Bronze -- exact column list/types, matches source files)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.country (
    country_id       NUMBER(18,0),
    country          VARCHAR(16777216),
    iso_currency     VARCHAR(3),
    iso_country      VARCHAR(2),
    city_id          NUMBER(19,0),
    city             VARCHAR(16777216),
    city_population  VARCHAR(16777216)
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.franchise (
    franchise_id  NUMBER(38,0),
    first_name    VARCHAR(16777216),
    last_name     VARCHAR(16777216),
    city          VARCHAR(16777216),
    country       VARCHAR(16777216),
    e_mail        VARCHAR(16777216),
    phone_number  VARCHAR(16777216)
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.location (
    location_id       NUMBER(19,0),
    placekey          VARCHAR(16777216),
    location          VARCHAR(16777216),
    city              VARCHAR(16777216),
    region            VARCHAR(16777216),
    iso_country_code  VARCHAR(16777216),
    country           VARCHAR(16777216)
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.menu (
    menu_id                        NUMBER(19,0),
    menu_type_id                   NUMBER(38,0),
    menu_type                      VARCHAR(16777216),
    truck_brand_name               VARCHAR(16777216),
    menu_item_id                   NUMBER(38,0),
    menu_item_name                 VARCHAR(16777216),
    item_category                  VARCHAR(16777216),
    item_subcategory               VARCHAR(16777216),
    cost_of_goods_usd              NUMBER(38,4),
    sale_price_usd                 NUMBER(38,4),
    menu_item_health_metrics_obj   VARIANT
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.truck (
    truck_id             NUMBER(38,0),
    menu_type_id         NUMBER(38,0),
    primary_city         VARCHAR(16777216),
    region               VARCHAR(16777216),
    iso_region           VARCHAR(16777216),
    country              VARCHAR(16777216),
    iso_country_code     VARCHAR(16777216),
    franchise_flag       NUMBER(38,0),
    year                 NUMBER(38,0),
    make                 VARCHAR(16777216),
    model                VARCHAR(16777216),
    ev_flag              NUMBER(38,0),
    franchise_id         NUMBER(38,0),
    truck_opening_date   DATE
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.order_header (
    order_id                 NUMBER(38,0),
    truck_id                 NUMBER(38,0),
    location_id              FLOAT,
    customer_id              NUMBER(38,0),
    discount_id              VARCHAR(16777216),
    shift_id                 NUMBER(38,0),
    shift_start_time         TIME(9),
    shift_end_time           TIME(9),
    order_channel            VARCHAR(16777216),
    order_ts                 TIMESTAMP_NTZ(9),
    served_ts                VARCHAR(16777216),
    order_currency           VARCHAR(3),
    order_amount             NUMBER(38,4),
    order_tax_amount         VARCHAR(16777216),
    order_discount_amount    VARCHAR(16777216),
    order_total              NUMBER(38,4)
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.order_detail (
    order_detail_id              NUMBER(38,0),
    order_id                     NUMBER(38,0),
    menu_item_id                 NUMBER(38,0),
    discount_id                  VARCHAR(16777216),
    line_number                  NUMBER(38,0),
    quantity                     NUMBER(5,0),
    unit_price                   NUMBER(38,4),
    price                        NUMBER(38,4),
    order_item_discount_amount   VARCHAR(16777216)
);

CREATE OR REPLACE TABLE TASTY_BYTES_DB.raw.customer_loyalty (
    customer_id          NUMBER(38,0),
    first_name           VARCHAR(16777216),
    last_name            VARCHAR(16777216),
    city                 VARCHAR(16777216),
    country              VARCHAR(16777216),
    postal_code          VARCHAR(16777216),
    preferred_language   VARCHAR(16777216),
    gender               VARCHAR(16777216),
    favourite_brand      VARCHAR(16777216),
    marital_status       VARCHAR(16777216),
    children_count       VARCHAR(16777216),
    sign_up_date         DATE,
    birthday_date        DATE,
    e_mail               VARCHAR(16777216),
    phone_number         VARCHAR(16777216)
);

-- ----------------------------------------------------------------------------
-- 5. Load data from the S3 stage into each raw table
-- ----------------------------------------------------------------------------

COPY INTO TASTY_BYTES_DB.raw.country
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/country/;

COPY INTO TASTY_BYTES_DB.raw.franchise
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/franchise/;

COPY INTO TASTY_BYTES_DB.raw.location
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/location/;

COPY INTO TASTY_BYTES_DB.raw.menu
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/menu/;

COPY INTO TASTY_BYTES_DB.raw.truck
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/truck/;

COPY INTO TASTY_BYTES_DB.raw.customer_loyalty
FROM @TASTY_BYTES_DB.raw.s3load/raw_customer/customer_loyalty/;

COPY INTO TASTY_BYTES_DB.raw.order_header
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/order_header/;

COPY INTO TASTY_BYTES_DB.raw.order_detail
FROM @TASTY_BYTES_DB.raw.s3load/raw_pos/order_detail/;

-- ----------------------------------------------------------------------------
-- 6. Resize warehouse back down now that the one-time load is done
-- ----------------------------------------------------------------------------
ALTER WAREHOUSE TASTY_BYTES_WH SET WAREHOUSE_SIZE = SMALL;

-- ----------------------------------------------------------------------------
-- 7. Verification -- confirm every table actually loaded rows
-- ----------------------------------------------------------------------------
SELECT 'country' AS table_name, COUNT(*) AS row_count FROM TASTY_BYTES_DB.raw.country
UNION ALL
SELECT 'franchise', COUNT(*) FROM TASTY_BYTES_DB.raw.franchise
UNION ALL
SELECT 'location', COUNT(*) FROM TASTY_BYTES_DB.raw.location
UNION ALL
SELECT 'menu', COUNT(*) FROM TASTY_BYTES_DB.raw.menu
UNION ALL
SELECT 'truck', COUNT(*) FROM TASTY_BYTES_DB.raw.truck
UNION ALL
SELECT 'customer_loyalty', COUNT(*) FROM TASTY_BYTES_DB.raw.customer_loyalty
UNION ALL
SELECT 'order_header', COUNT(*) FROM TASTY_BYTES_DB.raw.order_header
UNION ALL
SELECT 'order_detail', COUNT(*) FROM TASTY_BYTES_DB.raw.order_detail;