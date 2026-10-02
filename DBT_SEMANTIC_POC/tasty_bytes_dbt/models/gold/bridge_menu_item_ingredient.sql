-- Verified against live data in the new account -- ingredients is a flat
-- array of strings nested under menu_item_health_metrics[0] (see
-- dim_menu_item_health_metrics.sql for the full note and the sampled
-- example rows).
--
-- Grain: one row per (menu_item_id, ingredient) -- this is why its primary
-- key in schema.yml is declared at the model level (composite) rather than
-- on a single column.

SELECT
    m.menu_item_id,
    ingredient.value::VARCHAR AS ingredient_name
FROM {{ ref('stg_menu') }} m,
LATERAL FLATTEN(
    input => m.menu_item_health_metrics_obj:menu_item_health_metrics[0]:ingredients
) AS ingredient
