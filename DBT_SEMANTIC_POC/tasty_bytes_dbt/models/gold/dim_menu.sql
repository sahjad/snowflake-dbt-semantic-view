SELECT
    menu_item_id,
    menu_type,
    truck_brand_name,
    menu_item_name,
    item_category,
    item_subcategory,
    cost_of_goods_usd,
    sale_price_usd
FROM {{ ref('stg_menu') }}