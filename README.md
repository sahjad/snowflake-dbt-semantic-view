# Snowflake Semantic View via dbt - Tasty Bytes Demo

A native Snowflake Semantic View, materialized entirely through **dbt Core running natively inside Snowflake** ("dbt Projects on Snowflake"), with zero external package dependencies - built and validated end-to-end against Snowflake's official Tasty Bytes dataset.

This project answers natural-language business questions through a Cortex Agent, wired directly to a governed, version-controlled semantic layer.

## What this is

- A Bronze → Silver → Gold medallion pipeline over the Tasty Bytes dataset
- A native Snowflake `SEMANTIC VIEW` object, materialized directly from dbt models
- Verified Queries (VQR) embedded in the semantic view to improve natural-language accuracy
- A Cortex Agent that answers questions like *"What's our total revenue by truck brand?"* using governed metrics - not ad-hoc SQL

## Architecture

```
Raw Tasty Bytes data (public S3, loaded once)
    │
    ▼
dbt staging models (Silver) - cleanup + 2-year date filter
    │
    ▼
dbt Gold models - proper star schema (1 fact table + 4 dimensions)
    │
    ▼
Semantic view materialization - a genuine native Snowflake SEMANTIC VIEW
    │
    ▼
Verified Queries (VQR) embedded in the semantic view
    │
    ▼
Cortex Agent (cortex_analyst_text_to_sql tool)
    │
    └──▶ Natural language Q&A
```

## Why this exists (the interesting part)

Snowflake's `dbt_semantic_view` package requires `dbt deps` to install from `hub.getdbt.com`/GitHub - which needs an **External Access Integration**. Trial accounts unconditionally disallow External Access Integration, with no workaround via privileges.

**The fix:** the entire package is really just one small custom dbt materialization macro (~15 lines). This repo vendors that macro locally (`macros/semantic_view_materialization.sql`) instead of installing the package - meaning **zero external network access is required at any point** in this build. It works identically on a trial account or a full paid account.

## Project structure

```
tasty_bytes_dbt/
├── dbt_project.yml
├── profiles.yml
├── macros/
│   └── semantic_view_materialization.sql   # vendored -- no `dbt deps` needed
└── models/
    ├── staging/          # Silver: 6 views, light cleanup, 2-year filter applied here
    │   ├── _sources.yml
    │   ├── stg_order_header.sql
    │   ├── stg_order_detail.sql
    │   ├── stg_menu.sql
    │   ├── stg_truck.sql
    │   ├── stg_location.sql
    │   └── stg_customer_loyalty.sql
    ├── gold/             # Gold: 5 tables, proper star schema
    │   ├── fct_order_detail.sql
    │   ├── dim_menu.sql
    │   ├── dim_truck.sql
    │   ├── dim_location.sql
    │   └── dim_customer_loyalty.sql
    └── semantic_view/    # The native Snowflake semantic view
        └── tasty_bytes_semantic_view.sql
```

## Prerequisites

- Snowflake account, **Enterprise Edition or higher** (Semantic Views require it)
- A role with, at minimum: `CREATE SCHEMA` on the target database, `CREATE SEMANTIC VIEW`, `CREATE AGENT`
- A warehouse (any size - `XLARGE` recommended only for the one-time initial data load, then safe to resize down)

## Getting started

**1. Load the raw data** - run the ingestion script (creates `raw`/`dev`/`prod` schemas, loads all 8 Tasty Bytes tables from Snowflake's public S3 quickstart bucket, no AWS credentials needed).

**2. Open this repo in a Snowflake Workspace** (Projects → Workspaces → From Git repository → paste this repo's URL).

**3. Set your target environment** in `profiles.yml` - defaults to `dev`. A `prod` output is also defined; promote by running the whole project with `--target prod`.

**4. Run the project:**
```
run --target dev
```
This builds all 6 Silver views, all 5 Gold tables, and the semantic view itself, in dependency order - one command, no separate steps needed for the semantic view.

**5. Verify:**
```sql
SHOW SEMANTIC VIEWS IN SCHEMA <your_db>.dev;

SELECT truck_brand_name, AGG(total_revenue) AS revenue
FROM <your_db>.dev.tasty_bytes_semantic_view
GROUP BY truck_brand_name
ORDER BY revenue DESC;
```

**6. Create the Cortex Agent** (plain SQL, run in a worksheet - not part of the dbt project) to start asking natural-language questions.

## Key design decisions worth knowing

- **2-year date filter** (`order_ts >= '2020-11-01'`), applied once in `stg_order_header`, cascades to the Gold fact table automatically via a join - kept in for fast, cheap iteration during development rather than processing the full ~4-year, 673M-row dataset every run.
- **Deliberately minimal metrics** (`total_revenue`, `total_orders`, `total_quantity_sold`). Every relevant column is still exposed as a fact/dimension, so ad-hoc aggregations (`COUNT`, `AVG`, `MIN`, `MAX`) work on the fly without a formal metric for every possible question - validated directly against the live Cortex Agent.
- **Distinct dimension naming for ambiguous concepts.** `dim_truck`, `dim_location`, and `dim_customer_loyalty` each have their own city/region/country - but they mean different things (a truck's home base vs. where an order happened vs. a customer's home). Each got a distinct name (`truck_home_city`, `location_city`, `customer_city`) rather than relying on ambiguous-name auto-resolution. When asked *"break down revenue by category and city"* with no further specification, the Cortex Agent correctly inferred `location_city` on its own.
- **`COUNTRY` and `FRANCHISE`** are loaded in Bronze but intentionally unused downstream - kept for parity with the standard Tasty Bytes dataset, available for future extension (e.g., a `dim_franchise` table for franchisee-level reporting).

## Known limitations

- `order_channel` is `NULL` for all 248M+ rows in the source data - not a bug in this pipeline, confirmed against the full unfiltered raw table.
- Power BI connectivity was evaluated but not built - Snowflake's official Power BI connector doesn't natively support semantic views out of the box; see the `docs/` folder (if present) for the tradeoffs between a wrapper SQL view, a community DirectQuery connector, and native SQL queries per report.
- This build uses `CREATE OR REPLACE` semantics (via the vendored macro) - if Snowflake-native semantic view *materializations* (a separate, performance-oriented feature) are ever added, this macro would need a `CREATE OR ALTER` option to avoid dropping them on every run.

## License

Apache 2.0, consistent with the vendored `dbt_semantic_view` macro.
