# Snowflake Semantic View via dbt — Tasty Bytes Demo

A native Snowflake Semantic View, materialized entirely through **dbt Core running natively inside Snowflake** ("dbt Projects on Snowflake"), with zero external package dependencies — built and validated end-to-end against Snowflake's official Tasty Bytes dataset.

What started as a single semantic view has grown into a full **propose → review → validate → deploy → explore** workflow: business users define what they need through a guided visual tool, data engineers review and deploy through a governed app with real dbt execution, and a separate lineage explorer makes the whole resulting graph — from raw tables through to the Cortex Agent — visually inspectable.

## Component map

| Component | What it does | Where to look |
|---|---|---|
| **dbt semantic view project** | The core pipeline: Bronze → Silver → Gold → native `SEMANTIC VIEW`, plus the Cortex Agent | `DBT_SEMANTIC_POC/` |
| **Business User App** | Visual, no-SQL builder for proposing new or updated semantic views | `Business_User_App/` |
| **Data Engineer App** | Review queue, validation, verified-query authoring, and governed deployment | `Data_Engineer_App/` |
| **Lineage Explorer** | Interactive graph of how every object — stage through Cortex Agent — connects | `Lineage_Explorer/` |

## What this is

- A Bronze → Silver → Gold medallion pipeline over the Tasty Bytes dataset
- A native Snowflake `SEMANTIC VIEW` object, materialized directly from dbt models
- Verified Queries (VQR) embedded in the semantic view to improve natural-language accuracy
- A Cortex Agent that answers questions like *"What's our total revenue by truck brand?"* using governed metrics — not ad-hoc SQL
- A **Business User App** — a guided, visual Streamlit tool that lets a non-technical user propose a new semantic view (or a change to an existing one) by picking tables, dimensions, facts, metrics, and relationships from dropdowns, with AI-assisted SQL generation for custom metric expressions
- A **Data Engineer App** — the governed other half: a review queue, live validation against Snowflake, verified-query authoring (with built-in guardrails against the easy-to-get-wrong Snowflake rules), and a deploy flow that runs a real `dbt run` and only records a deployment once dbt's own output confirms success
- A **Lineage Explorer** — a separate Streamlit app that renders the full technical and semantic lineage graph as an interactive, explorable diagram

## Architecture

### Core semantic view pipeline

```
Raw Tasty Bytes data (public S3, loaded once)
    │
    ▼
dbt staging models (Silver) — cleanup + 2-year date filter
    │
    ▼
dbt Gold models — proper star schema (1 fact table + 4 dimensions)
    │
    ▼
Semantic view materialization — a genuine native Snowflake SEMANTIC VIEW
    │
    ▼
Verified Queries (VQR) embedded in the semantic view
    │
    ▼
Cortex Agent (cortex_analyst_text_to_sql tool)
    │
    └──▶ Natural language Q&A
```

### Full governance workflow

```
Business User App                 Data Engineer App
(visual builder, AI-assisted)      (review, validate, deploy)
        │                                   │
        ▼                                   │
 SEMANTIC_TOOL schema  ───────────────────▶ │
 (proposals, SCD2 versions,                 │
  append-only deployment log)               │
        │                                   ▼
        │                      Live dry-run validation (SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML)
        │                                   │
        │                                   ▼
        │                    Workspace write + shared DBT PROJECT object
        │                                   │
        │                                   ▼
        │                       Real `dbt run`, verified via actual output
        │                                   │
        └──────────────────── Deployed semantic view (dev / prod, tracked independently)
                                             │
                                             ▼
                                      Cortex Agent
                                             │
                                             ▼
                               Lineage Explorer (cross-cutting view of all of the above)
```

## Why this exists (the interesting part)

Snowflake's `dbt_semantic_view` package requires `dbt deps` to install from `hub.getdbt.com`/GitHub — which needs an **External Access Integration**. Trial accounts unconditionally disallow External Access Integration, with no workaround via privileges.

**The fix:** the entire package is really just one small custom dbt materialization macro. This repo vendors that macro locally (`macros/semantic_view_materialization.sql`) instead of installing the package — meaning **zero external network access is required at any point** in this build. It works identically on a trial account or a full paid account.

A second, sibling macro (`macros/semantic_view_yaml_materialization.sql`) supports building a semantic view directly from a YAML spec instead of SQL DDL — useful when a definition is authored elsewhere (e.g. Snowflake's own Semantic Studio, or generated by the Business User App) and handed to an engineer as YAML rather than hand-written DDL.

## Project structure

```
.
├── README.md                     # this file
├── Business_User_App/
│   └── business_user_streamlit_app.py
├── Data_Engineer_App/
│   └── data_engineer_streamlit_app.py
├── Lineage_Explorer/
│   ├── setup.sql                  # one-time: role, database, schema, warehouse
│   ├── validate_lineage.sql       # checks visibility end to end before deploying
│   └── snowflake_lineage_explorer/
│       ├── streamlit_app.py
│       ├── pyproject.toml
│       ├── snowflake.yml
│       ├── src/
│       │   ├── graph_builder.py       # layer classification rules live here
│       │   └── snowflake_metadata.py
│       └── components/cytoscape/      # locally bundled -- no external CDN
└── DBT_SEMANTIC_POC/
    └── tasty_bytes_dbt/
        ├── dbt_project.yml
        ├── profiles.yml
        ├── macros/
        │   ├── semantic_view_materialization.sql       # SQL DDL path, CREATE OR ALTER
        │   └── semantic_view_yaml_materialization.sql  # YAML path, create_or_alter=TRUE
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
            └── semantic_view/    # Native Snowflake semantic views (one file per view)
                ├── tasty_bytes_semantic_view.sql
                ├── tasty_bytes_profitability_semantic_view.sql
                └── customer_loyalty_insights.sql
```

## Prerequisites

- Snowflake account, **Enterprise Edition or higher** (Semantic Views require it)
- A role with, at minimum: `CREATE SCHEMA` on the target database, `CREATE SEMANTIC VIEW`, `CREATE AGENT`, `CREATE DBT PROJECT`
- A warehouse (any size — `XLARGE` recommended only for the one-time initial data load, then safe to resize down)
- Streamlit-in-Snowflake, for both the Business User App and Data Engineer App
- Access to Cortex `AI_COMPLETE` (used for AI-assisted metric and verified-query SQL generation) — check `SHOW CORTEX BASE MODELS` for what's current in your account, since model availability changes often
- A Git-connected Workspace (for the dbt project, and for the apps' "write directly to workspace" deploy feature)
- For the Lineage Explorer specifically: Streamlit **container runtime** on Python 3.11, access to `SYSTEM_COMPUTE_POOL_CPU` (or an equivalent compute pool), and a role that can be granted `VIEW LINEAGE` and `RESOLVE ALL` at the account level — see its setup steps below

## Getting started

### 1. Core pipeline (dbt)

1. **Load the raw data** — run the ingestion script (creates `raw`/`dev`/`prod` schemas, loads all 8 Tasty Bytes tables from Snowflake's public S3 quickstart bucket, no AWS credentials needed).
2. **Open this repo in a Snowflake Workspace** (Projects → Workspaces → From Git repository → paste this repo's URL).
3. **Set your target environment** in `profiles.yml` — defaults to `dev`. A `prod` output is also defined; promote by running the whole project with `--target prod`.
4. **Run the project:**
   ```
   run --target dev
   ```
   This builds all Silver views, all Gold tables, and every semantic view, in dependency order.
5. **Verify:**
   ```sql
   SHOW SEMANTIC VIEWS IN SCHEMA <your_db>.dev;

   SELECT truck_brand_name, AGG(total_revenue) AS revenue
   FROM <your_db>.dev.tasty_bytes_semantic_view
   GROUP BY truck_brand_name
   ORDER BY revenue DESC;
   ```
6. **Create the Cortex Agent** (plain SQL, run in a worksheet — not part of the dbt project) to start asking natural-language questions.

### 2. The governance apps

1. Create the `SEMANTIC_TOOL` schema and its tables (`svt_proposals`, `svt_versions`, `svt_deployment_log`, and the `svt_builder_*` working tables) in your target database.
2. Deploy `Business_User_App/business_user_streamlit_app.py` and `Data_Engineer_App/data_engineer_streamlit_app.py` as two separate Streamlit-in-Snowflake apps.
3. One-time per engineer: `CREATE DBT PROJECT` once (sourced from your Git workspace), and each engineer grants their own role `WRITE` on their own personal workspace — both are one-off setup steps tied to how Snowflake handles personal workspace identity, not something the apps can do on your behalf.
4. Open the Business User App, propose a new view end to end, then switch to the Data Engineer App to review, validate, and deploy it.

### 3. Lineage Explorer

1. Run `Lineage_Explorer/setup.sql` once — creates `LINEAGE_APP_ROLE`, `LINEAGE_APP_DB`, and `LINEAGE_APP_WH`, and grants the role `VIEW LINEAGE`, `RESOLVE ALL`, and metadata access to your Tasty Bytes database. This is account-level, so it needs a role that can grant those privileges.
2. Run `Lineage_Explorer/validate_lineage.sql` to confirm visibility into databases, schemas, tables, and lineage before deploying the app itself.
3. Open `Lineage_Explorer/snowflake_lineage_explorer/` as a Streamlit app from a Workspace, using `LINEAGE_APP_ROLE`, container runtime / Python 3.11, and `SYSTEM_COMPUTE_POOL_CPU` (or your own compute pool) as the execution environment.
4. Test with Database `TASTY_BYTES_DB`, Schema `DEV`, no anchor (Schema Overview), then try a focused lineage query on `FCT_ORDER_DETAIL` to confirm native lineage is actually being returned.

## The Business User App

A guided, visual builder — no SQL required to propose a new semantic view or a change to an existing one.

- **Tables, Dimensions, Facts, Metrics, Relationships** as separate tabs, each with add *and* delete, and clear dependency warnings before a delete cascades
- **Primary keys suggested automatically** per table (a real constraint if one exists, an exact-name match, or a single `_ID` column — falling back to manual choice only when genuinely ambiguous)
- **Relationships suggested automatically** once two tables share a column that's a primary key on exactly one side — accept, dismiss, or add manually
- **AI-assisted metric expressions**: describe a metric in plain language (*"average price per unit"*), and `AI_COMPLETE` — grounded in the exact fact names already declared, not left to guess — generates both a name and the SQL expression
- A dedicated **Info tab** walking a first-time user through all six steps before they build anything
- Every proposal is versioned (SCD Type 2): editing something already validated creates a new version rather than mutating history

## The Data Engineer App

The governed other half of the workflow — three pages: **Review queue**, **Ready to deploy**, **Deployed**.

- **Live validation** against Snowflake (a real dry run via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`, not a syntax check)
- **Verified query authoring with built-in guardrails** against the three Snowflake rules that are easy to get wrong: no `AGG()` inside verified queries, reference logical tables rather than the semantic view's own name, and use declared fact/dimension names rather than raw physical columns
- **AI-assisted verified query generation**, grounded in the actual YAML under review (tables, facts, dimensions, relationships), with the same guardrails enforced on whatever comes back
- **Deploy that's actually verified, not self-reported**: picks a validated version, writes the file into the engineer's own Git-connected workspace, syncs a shared `DBT PROJECT` object, and runs `dbt run` for real — only recording a deployment once dbt's own `SUCCESS`/error output confirms it, with the full raw output always shown
- **Independent dev/prod tracking**: each environment has its own deployed-version pointer, so a proposal can be live on an older version in prod while a newer one sits validated and ready, with nothing overwritten until someone deliberately deploys
- **Full audit trail**: `svt_versions` (who modified/validated each version), `svt_deployment_log` (append-only, one row per deploy per environment — rollback is just deploying an older version again), and `svt_proposals` (current state, with `closed_reason` distinguishing engineer rejection from business-user withdrawal)

## The Lineage Explorer

A separate Streamlit application that combines Information Schema metadata, Snowflake's native lineage (`SNOWFLAKE.CORE.GET_LINEAGE`), and semantic-view metadata into one interactive, layered Cytoscape.js graph — stages and raw tables through Silver, Gold, semantic views, logical semantic tables, and Cortex Agents, all explorable in a single diagram.

**Two exploration modes:**
- **Schema Overview** — database and schema are mandatory, no anchor object required. Shows every filtered object in the schema, including ones with no recorded native lineage (useful for telling a genuinely standalone object apart from one whose lineage just hasn't been recorded yet).
- **Object Lineage** — focused lineage for one anchor object, in `UPSTREAM`, `DOWNSTREAM`, or `BOTH` direction, with depth selectable from 1 to 5. The selected object stays in its architectural layer rather than jumping to the front of the graph.

**Layered architecture**, assigned from object metadata, naming conventions (`STG_*`, `DIM_*`, `FCT_*`), and graph relationships:
```
AI / Consumers
     ↑
Semantic Views
     ↑
Semantic Logical Tables   (semantic-model mode only)
     ↑
Gold — Dimensions & Facts
     ↑
Silver / Staging Views
     ↑
Raw / Base Tables
     ↑
Sources / Stages
```

**Semantic model mode** — selecting a semantic view as the anchor exposes its logical tables, physical base objects, relationships, dimensions, facts, metrics, primary keys, and descriptions/synonyms directly in the graph, not just the technical table-to-table lineage.

**Interaction**: zoom/pan, Fit, Centre, click-to-explore drill-down, graph search and highlighting, an expanded full-canvas mode with keyboard shortcuts (`+`/`-` zoom, `0` fit, `C` centre, `Esc` exit), and CSV/JSON export of both lineage rows and graph elements.

**Deployment is self-contained and separate from the rest of this repo**: a one-time `Lineage_Explorer/setup.sql` creates its own role, database, schema, and warehouse (`LINEAGE_APP_ROLE`, `LINEAGE_APP_DB`, `LINEAGE_APP_WH`) and grants exactly what's needed — `VIEW LINEAGE`, `RESOLVE ALL`, and metadata access to the target data database. A companion `validate_lineage.sql` checks visibility end to end (databases, schemas, tables, upstream/downstream lineage for a known object) before deploying the app itself. Cytoscape.js is bundled locally under `components/cytoscape/dist/` — the app never loads JavaScript from an external CDN, the same network-independence principle followed everywhere else in this project.

**Known limitations specific to this component:**
- Native lineage only reflects what Snowflake has actually recorded — objects created or transformed outside Snowflake, or via dynamic SQL/external orchestration, can have incomplete lineage.
- Layer placement partly relies on the Tasty Bytes naming conventions (`STG_`, `DIM_`, `FCT_`) rather than being fully convention-free.
- The POC deliberately uses one broad role (`LINEAGE_APP_ROLE`) for development, deployment, and viewing alike — a production deployment would want a separate owner/developer/viewer model.

## Key design decisions worth knowing

- **2-year date filter** (`order_ts >= '2020-11-01'`), applied once in `stg_order_header`, cascades to the Gold fact table automatically via a join — kept in for fast, cheap iteration during development rather than processing the full ~4-year, 673M-row dataset every run.
- **Deliberately minimal metrics** (`total_revenue`, `total_orders`, `total_quantity_sold`). Every relevant column is still exposed as a fact/dimension, so ad-hoc aggregations (`COUNT`, `AVG`, `MIN`, `MAX`) work on the fly without a formal metric for every possible question — validated directly against the live Cortex Agent.
- **Distinct dimension naming for ambiguous concepts.** `dim_truck`, `dim_location`, and `dim_customer_loyalty` each have their own city/region/country — but they mean different things (a truck's home base vs. where an order happened vs. a customer's home). Each got a distinct name (`truck_home_city`, `location_city`, `customer_city`) rather than relying on ambiguous-name auto-resolution. When asked *"break down revenue by category and city"* with no further specification, the Cortex Agent correctly inferred `location_city` on its own.
- **`CREATE OR ALTER`, not `CREATE OR REPLACE`.** Both materialization macros use `CREATE OR ALTER` (and `create_or_alter=TRUE` for the YAML path) specifically so grants — including Internal Marketplace listing shares — survive a redeploy instead of needing `COPY GRANTS` to patch over a drop-and-recreate cycle.
- **Workspace writes use `session.file.put_stream`, not `COPY INTO ... FROM (SELECT ...)`.** The latter routes text through CSV file-format semantics, which silently backslash-escapes embedded commas and newlines — corrupting exactly the kind of multi-line YAML this project writes. `put_stream` writes bytes verbatim.
- **`USER$` alone only resolves inside an interactive Snowsight worksheet.** From any other execution context (a Streamlit app's Snowpark session, a script), it must be the literal personal database name (`USER$<username>`, built from the actual calling user) — otherwise it silently resolves to the wrong identity's workspace.
- **AI generation is grounded, never left to guess names.** Every `AI_COMPLETE` prompt in both apps includes the exact declared table/fact/dimension names already in scope, plus the same hard syntax rules enforced elsewhere in the project — the model combines known-good pieces rather than inventing new ones.

## Known limitations

- `order_channel` is `NULL` for all 248M+ rows in the source data — not a bug in this pipeline, confirmed against the full unfiltered raw table.
- Power BI connectivity was evaluated but not built — Snowflake's official Power BI connector doesn't natively support semantic views out of the box.
- The shared `DBT PROJECT` object used for deployment is a single object, not one per engineer — if two engineers deploy at nearly the same moment, the second sync overwrites the first mid-flight. Fine at current scale; the fix if it ever matters is one `DBT PROJECT` object per engineer.
- Each engineer must grant their own role `WRITE` on their own personal workspace once, and this can't be done on their behalf — Snowflake deliberately excludes personal databases from normal role-based grant delegation.
- AI-generated SQL (metric expressions, verified queries) is a starting point, not an authoritative answer — it's always reviewable/editable before being added, and still passes through the same validation and guardrails as hand-written SQL.

## License

Apache 2.0, consistent with the vendored `dbt_semantic_view` macro.