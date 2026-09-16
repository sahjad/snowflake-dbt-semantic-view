-- ============================================================
-- STEP 6: CORTEX AGENT
-- Wires a Cortex Agent to the tasty_bytes_semantic_view built in Step 4.
-- Run this in a worksheet -- it's plain SQL, not part of the dbt project.
-- ============================================================

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE TASTY_BYTES_WH;
USE DATABASE TASTY_BYTES_DB;
USE SCHEMA dev;

CREATE OR REPLACE AGENT tasty_bytes_agent
  COMMENT = 'Answers questions about Tasty Bytes sales: revenue, orders, quantity sold, by truck brand, menu category, city, region, and customer loyalty status'
  PROFILE = '{"display_name": "Tasty Bytes Sales Assistant", "color": "orange"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto

  instructions:
    response: "Respond concisely. Include the relevant numbers in your answer."
    orchestration: "Use the tasty_bytes_analyst tool for any question about revenue, orders, quantity sold, truck brands, menu items, categories, cities, regions, or customer loyalty status."
    sample_questions:
      - question: "What is our total revenue by truck brand?"
      - question: "How many orders came from loyalty members versus non-members?"
      - question: "What is the average order value by city?"

  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "tasty_bytes_analyst"
        description: "Answers questions about Tasty Bytes sales -- revenue, order counts, quantity sold, average order value -- broken down by truck brand, menu category, city, region, order channel, or customer loyalty status."

  tool_resources:
    tasty_bytes_analyst:
      semantic_view: "TASTY_BYTES_DB.dev.tasty_bytes_semantic_view"
      execution_environment:
        type: warehouse
        warehouse: TASTY_BYTES_WH
  $$;

-- ============================================================
-- TEST IT
-- Go to Snowsight -> AI & ML -> Agents -> tasty_bytes_agent, or use
-- the Cortex Agents REST API. Try these, in order of increasing risk:
--
-- 1. Exact match to a verified query (should be fast and highly accurate):
--    "What is our total revenue by truck brand?"
--
-- 2. Same underlying question, different phrasing (tests generalization
--    beyond the exact verified query wording):
--    "Which truck brand makes the most money?"
--
-- 3. Ad-hoc aggregation, never defined as a metric -- tests whether the
--    agent can still use exposed facts on the fly (same pattern we
--    proved works throughout this whole build):
--    "How many line items were sold through each order channel?"
--    -> should use COUNT() on order_detail_id_fact, since no
--       "line item count" metric was ever defined
--
-- 4. Cross-table question spanning multiple relationships at once:
--    "Break down revenue by menu category and city"
-- ============================================================