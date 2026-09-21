-- Derived from Snowflake Labs' dbt_semantic_view package
-- (https://github.com/Snowflake-Labs/dbt_semantic_view), licensed under
-- Apache License 2.0. Vendored locally here rather than installed via
-- `dbt deps`, since External Access Integration -- required for `dbt deps`
-- to reach hub.getdbt.com -- is unconditionally unsupported on Snowflake
-- trial accounts. See this repo's LICENSE file for the full Apache 2.0 text.
--
-- Uses CREATE OR ALTER (Snowflake preview, May 2026) rather than
-- CREATE OR REPLACE. The object is modified in place instead of being
-- dropped and recreated -- grants (including shares/listings) are never
-- disturbed at all, so COPY GRANTS is no longer needed. Supports
-- everything this project uses: tables, relationships, facts,
-- dimensions, metrics, comments, and verified queries.
--
-- Being a preview feature, worth testing carefully after any real
-- definition change (as opposed to CREATE OR REPLACE, which is GA and
-- has more mileage). If it ever misbehaves, reverting the one line
-- below back to "CREATE OR REPLACE ... COPY GRANTS" restores the
-- previous, more battle-tested behavior.

{% materialization semantic_view, default %}
  {%- set identifier = model.name -%}
  {%- set target_relation = api.Relation.create(
      database=database,
      schema=schema,
      identifier=identifier,
      type='view') -%}

  {{ run_hooks(pre_hooks) }}

  {% call statement('main') -%}
    CREATE OR ALTER SEMANTIC VIEW {{ target_relation }}
    {{ sql }}
  {%- endcall %}

  {{ run_hooks(post_hooks) }}
  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}