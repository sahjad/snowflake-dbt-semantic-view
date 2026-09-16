{% materialization semantic_view, default %}
  {%- set identifier = model.name -%}
  {%- set target_relation = api.Relation.create(
      database=database,
      schema=schema,
      identifier=identifier,
      type='view') -%}

  {{ run_hooks(pre_hooks) }}

  {% call statement('main') -%}
    CREATE OR REPLACE SEMANTIC VIEW {{ target_relation }}
    {{ sql }}
    COPY GRANTS
  {%- endcall %}

  {{ run_hooks(post_hooks) }}
  {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}