/* ============================================================================
   SNOWFLAKE LINEAGE AND SEMANTIC EXPLORER - POC SETUP

   Final POC decisions:
     * One role only: LINEAGE_APP_ROLE
     * Development and deployment through Snowsight Workspaces
     * No Snowflake CLI, named code stage, owner/viewer role split, or post-deploy SQL

   This script assumes the person running it should receive LINEAGE_APP_ROLE.
   The target data database is TASTY_BYTES_DB. Change that name if required.
   ============================================================================ */

-- Capture the user who runs this script so the new role can be granted back to
-- that user automatically. An administrator can replace the final user grant
-- when setting this up on behalf of someone else.
SET POC_USER = (SELECT CURRENT_USER());

USE ROLE ACCOUNTADMIN;

/* --------------------------------------------------------------------------
   1. One role for creating, running, deploying, and viewing the POC
   -------------------------------------------------------------------------- */

CREATE ROLE IF NOT EXISTS LINEAGE_APP_ROLE
  COMMENT = 'POC role for the Snowflake lineage and semantic explorer';

-- Keep the custom role in the normal role hierarchy.
GRANT ROLE LINEAGE_APP_ROLE TO ROLE SYSADMIN;

-- Give the person running this script the POC role.
GRANT ROLE LINEAGE_APP_ROLE TO USER IDENTIFIER($POC_USER);

/* --------------------------------------------------------------------------
   2. Native lineage and Python package access
   -------------------------------------------------------------------------- */

GRANT VIEW LINEAGE ON ACCOUNT TO ROLE LINEAGE_APP_ROLE;

-- Allows GET_LINEAGE to resolve connected object names even when a related
-- object is outside the database currently selected in the application.
-- Remove this later if production RBAC must be restricted database by database.
GRANT RESOLVE ALL ON ACCOUNT TO ROLE LINEAGE_APP_ROLE;

-- Lets a container-runtime Streamlit app install the pinned packages declared
-- in pyproject.toml from Snowflake's managed PyPI repository.
GRANT DATABASE ROLE SNOWFLAKE.PYPI_REPOSITORY_USER
  TO ROLE LINEAGE_APP_ROLE;

/* --------------------------------------------------------------------------
   3. Application database, schema, and query warehouse
   -------------------------------------------------------------------------- */

USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS LINEAGE_APP_DB
  COMMENT = 'Database for the Snowflake lineage explorer POC';

CREATE SCHEMA IF NOT EXISTS LINEAGE_APP_DB.APPS
  COMMENT = 'Schema for Streamlit applications';

CREATE WAREHOUSE IF NOT EXISTS LINEAGE_APP_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Query warehouse for the Snowflake lineage explorer POC';

/* --------------------------------------------------------------------------
   4. Streamlit creation and execution privileges
   -------------------------------------------------------------------------- */

USE ROLE SECURITYADMIN;

GRANT USAGE ON DATABASE LINEAGE_APP_DB TO ROLE LINEAGE_APP_ROLE;
GRANT USAGE ON SCHEMA LINEAGE_APP_DB.APPS TO ROLE LINEAGE_APP_ROLE;
GRANT CREATE STREAMLIT, CREATE WORKSPACE ON SCHEMA LINEAGE_APP_DB.APPS
  TO ROLE LINEAGE_APP_ROLE;
GRANT USAGE ON WAREHOUSE LINEAGE_APP_WH TO ROLE LINEAGE_APP_ROLE;
GRANT USAGE ON COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU
  TO ROLE LINEAGE_APP_ROLE;

/* --------------------------------------------------------------------------
   5. POC access to the database being visualized

   These broad metadata/read grants are intentionally simple for the POC.
   They let the single role discover objects through INFORMATION_SCHEMA and
   inspect semantic-view metadata. Replace this section with inherited data
   roles or tighter grants when production RBAC is designed.
   -------------------------------------------------------------------------- */

GRANT USAGE ON DATABASE TASTY_BYTES_DB TO ROLE LINEAGE_APP_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT USAGE ON FUTURE SCHEMAS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

-- Regular tables.
GRANT REFERENCES ON ALL TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

-- Standard and secure views.
GRANT REFERENCES ON ALL VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

-- Table-like object types that have their own grant syntax.
GRANT MONITOR ON ALL DYNAMIC TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT MONITOR ON FUTURE DYNAMIC TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

GRANT REFERENCES ON ALL MATERIALIZED VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE MATERIALIZED VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

GRANT REFERENCES ON ALL ICEBERG TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE ICEBERG TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

-- External tables support SELECT rather than REFERENCES. This is intentionally
-- broad for the POC so they are visible in metadata and lineage results.
GRANT SELECT ON ALL EXTERNAL TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT SELECT ON FUTURE EXTERNAL TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

GRANT REFERENCES ON ALL EVENT TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE EVENT TABLES IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

-- Semantic views are a distinct Snowflake object type.
GRANT REFERENCES ON ALL SEMANTIC VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;
GRANT REFERENCES ON FUTURE SEMANTIC VIEWS IN DATABASE TASTY_BYTES_DB
  TO ROLE LINEAGE_APP_ROLE;

/* --------------------------------------------------------------------------
   6. Confirm the role is usable
   -------------------------------------------------------------------------- */

USE ROLE LINEAGE_APP_ROLE;
USE WAREHOUSE LINEAGE_APP_WH;

SHOW DATABASES;
