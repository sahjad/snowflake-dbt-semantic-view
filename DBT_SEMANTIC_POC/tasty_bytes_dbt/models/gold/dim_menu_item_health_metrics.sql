-- Verified against live data in the new account (menu_item_id 10-14 sampled
-- directly from raw.menu) -- confirmed structure:
--
--   menu_item_health_metrics_obj:menu_item_health_metrics[0]:<field>
--
-- is_dairy_free_flag / is_gluten_free_flag / is_healthy_flag /
-- is_nut_free_flag are literal 'Y'/'N' strings in the source, not booleans
-- or 1/0 -- so each is normalized here via `= 'Y'` into a real BOOLEAN,
-- which is what schema.yml's contract now declares for them.
--
-- ingredients is a flat array of strings -- see
-- bridge_menu_item_ingredient.sql for the flattened (menu_item_id,
-- ingredient) grain version of the same field.
--
-- Kept as its own model, separate from dim_menu, so this one stays cheap to
-- adjust in isolation if a different menu item or a future reload ever
-- shows a shape that doesn't match what was sampled here.

SELECT
    menu_item_id,
    menu_item_health_metrics_obj:menu_item_health_metrics[0]:is_dairy_free_flag::VARCHAR  = 'Y' AS is_dairy_free_flag,
    menu_item_health_metrics_obj:menu_item_health_metrics[0]:is_gluten_free_flag::VARCHAR = 'Y' AS is_gluten_free_flag,
    menu_item_health_metrics_obj:menu_item_health_metrics[0]:is_healthy_flag::VARCHAR     = 'Y' AS is_healthy_flag,
    menu_item_health_metrics_obj:menu_item_health_metrics[0]:is_nut_free_flag::VARCHAR    = 'Y' AS is_nut_free_flag,
    menu_item_health_metrics_obj:menu_item_health_metrics[0]:ingredients::VARIANT         AS ingredients
FROM {{ ref('stg_menu') }}
