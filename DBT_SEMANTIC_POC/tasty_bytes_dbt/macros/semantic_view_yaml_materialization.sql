-- Sibling to semantic_view_materialization.sql, but for models whose body
-- is a YAML semantic model spec instead of TABLES/RELATIONSHIPS/FACTS/
-- DIMENSIONS/METRICS SQL DDL. Calls SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML
-- instead of CREATE SEMANTIC VIEW.
--
-- Signature (4 args, last two optional):
--   SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(
--     '<fully_qualified_schema_name>',
--     '<yaml_specification>'
--     [ , <verify_only> ]
--     [ , <create_or_alter> ]
--   )
--
-- verify_only     TRUE = validate without creating anything (used by the
--                 engineer review app, not here).
-- create_or_alter TRUE = use CREATE OR ALTER SEMANTIC VIEW semantics,
--                 which preserves existing materializations where possible.
--                 We pass TRUE.
--
-- No DROP is needed or wanted. Left to its default the procedure already
-- behaves like CREATE OR REPLACE SEMANTIC VIEW ... COPY GRANTS when the
-- view exists; dropping first would destroy the grants it is trying to
-- copy, breaking any share or listing that points at this view.
--
-- The semantic view's actual NAME comes from the "name:" field inside the
-- YAML body, not from dbt's model filename -- keep the two in sync by
-- convention, since dbt has no way to enforce it.
--
-- create_or_alter is a newer addition to this procedure. If an older
-- Snowflake version rejects the 4-argument form, drop the trailing
-- ", FALSE, TRUE" and the default replace-and-copy-grants behavior still
-- applies.

{% materialization semantic_view_yaml, default %}
  {%- set identifier = model.name -%}
  {%- set target_relation = api.Relation.create(
      database=database,
      schema=schema,
      identifier=identifier,
      type='view') -%}

  {{ run_hooks(pre_hooks) }}

  {% call statement('main') -%}
    CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(
      '{{ database }}.{{ schema }}',
      $${{ sql }}$$,
      FALSE,
      TRUE
    )
  {%- endcall %}

  {{ run_hooks(post_hooks) }}
  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}