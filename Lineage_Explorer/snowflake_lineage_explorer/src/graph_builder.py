from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import pandas as pd

from src.snowflake_metadata import ObjectRef, make_lineage_key


LAYER_DEFINITIONS: dict[str, dict[str, Any]] = {
    "source": {"order": 0, "label": "Sources / Stages"},
    "raw": {"order": 1, "label": "Raw / Base Tables"},
    "staging": {"order": 2, "label": "Silver / Staging Views"},
    "gold": {"order": 3, "label": "Gold — Dimensions & Facts"},
    "logical": {"order": 4, "label": "Semantic Logical Tables"},
    "semantic": {"order": 5, "label": "Semantic Views"},
    "consumer": {"order": 6, "label": "AI / Consumers"},
}


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple, dict, str, int, float, bool)):
        return value
    return str(value)


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(clean_value(part) or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def snowflake_object_id(
    domain: str | None,
    database: str | None,
    schema: str | None,
    name: str | None,
    column_name: str | None = None,
    namespace: str | None = None,
    external_id: str | None = None,
) -> str:
    if str(domain or "").upper() in {"EXTERNAL", "EXTERNAL_COLUMN"}:
        return stable_id(
            "external",
            domain,
            namespace,
            external_id,
            name,
            column_name,
        )
    return stable_id(
        "node",
        domain,
        database,
        schema,
        name,
        column_name,
    )


def class_for_object(domain: str | None, dataset_type: str | None) -> str:
    domain_value = str(domain or "UNKNOWN").upper()
    dataset_value = str(dataset_type or "").upper().replace(" ", "_")

    if domain_value == "SEMANTIC_VIEW":
        return "semantic-view"
    if domain_value == "STAGE":
        return "stage"
    if domain_value == "CORTEX_AGENT":
        return "cortex-agent"
    if domain_value == "LOGICAL_TABLE":
        return "logical-table"
    if domain_value == "DATASET":
        return "dataset"
    if domain_value == "MODULE":
        return "model"
    if domain_value in {"EXTERNAL", "EXTERNAL_COLUMN"}:
        return "external"

    if dataset_value in {"VIEW", "SECURE_VIEW"}:
        return "view"
    if dataset_value == "MATERIALIZED_VIEW":
        return "materialized-view"
    if dataset_value == "DYNAMIC_TABLE":
        return "dynamic-table"
    if dataset_value == "EXTERNAL_TABLE":
        return "external-table"
    if dataset_value == "ICEBERG_TABLE":
        return "iceberg-table"
    if dataset_value == "EVENT_TABLE":
        return "event-table"
    return "table"


def object_label(
    name: str | None,
    column_name: str | None,
    dataset_type: str | None,
    domain: str | None,
) -> str:
    base = str(name or "Unknown")
    if column_name:
        base = f"{base}.{column_name}"
    type_label = str(dataset_type or domain or "OBJECT").replace("_", " ")
    return f"{base}\n{type_label}"


def fully_qualified_name(
    database: str | None,
    schema: str | None,
    name: str | None,
    column_name: str | None = None,
) -> str:
    parts = [part for part in (database, schema, name) if part]
    value = ".".join(str(part) for part in parts)
    if column_name:
        value = f"{value}.{column_name}" if value else str(column_name)
    return value


def _class_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value if item}
    return {item for item in str(value or "").split() if item}


def _upsert_node(
    nodes: dict[str, dict[str, Any]],
    node: dict[str, Any],
) -> None:
    node_id = str(node.get("data", {}).get("id") or "")
    if not node_id:
        return
    current = nodes.get(node_id)
    if current is None:
        nodes[node_id] = node
        return

    merged_data = dict(current.get("data", {}))
    for key, value in node.get("data", {}).items():
        if value not in (None, "", [], {}):
            merged_data[key] = value
        elif key not in merged_data:
            merged_data[key] = value

    classes = _class_set(current.get("classes")) | _class_set(node.get("classes"))
    nodes[node_id] = {
        **current,
        **node,
        "data": merged_data,
        "classes": " ".join(sorted(classes)),
    }


def _node_from_lineage_side(
    row: pd.Series,
    side: str,
    anchor_key: str | None = None,
) -> dict[str, Any]:
    prefix = side.upper()
    database = clean_value(row.get(f"{prefix}_OBJECT_DATABASE"))
    schema = clean_value(row.get(f"{prefix}_OBJECT_SCHEMA"))
    name = clean_value(row.get(f"{prefix}_OBJECT_NAME"))
    domain = clean_value(row.get(f"{prefix}_OBJECT_DOMAIN")) or "UNKNOWN"
    column_name = clean_value(row.get(f"{prefix}_COLUMN_NAME"))
    dataset_type = clean_value(row.get(f"{prefix}_DATASET_TYPE"))
    namespace = clean_value(row.get(f"{prefix}_NAMESPACE"))
    external_id = clean_value(row.get(f"{prefix}_EXTERNAL_ID"))
    status = clean_value(row.get(f"{prefix}_STATUS"))
    origin = clean_value(row.get(f"{prefix}_ORIGIN"))
    version = clean_value(row.get(f"{prefix}_OBJECT_VERSION"))

    node_id = snowflake_object_id(
        domain,
        database,
        schema,
        name,
        column_name,
        namespace,
        external_id,
    )
    lineage_key = make_lineage_key(database, schema, name, domain)
    is_anchor = bool(
        anchor_key and lineage_key.casefold() == anchor_key.casefold()
    )
    object_type = dataset_type or domain
    classes = [class_for_object(domain, dataset_type)]
    if is_anchor:
        classes.append("anchor")
    if str(status or "").upper() == "MASKED":
        classes.append("masked")

    return {
        "data": {
            "id": node_id,
            "label": object_label(name, column_name, dataset_type, domain),
            "database": database,
            "schema": schema,
            "object_name": name,
            "column_name": column_name,
            "fq_name": fully_qualified_name(database, schema, name, column_name),
            "domain": domain,
            "object_type": object_type,
            "dataset_type": dataset_type,
            "status": status,
            "origin": origin,
            "namespace": namespace,
            "external_id": external_id,
            "version": version,
            "lineage_key": lineage_key,
            "is_anchor": is_anchor,
        },
        "classes": " ".join(classes),
    }


def _inventory_node(row: pd.Series, anchor_key: str | None = None) -> dict[str, Any]:
    database = clean_value(row.get("DATABASE_NAME"))
    schema = clean_value(row.get("SCHEMA_NAME"))
    name = clean_value(row.get("OBJECT_NAME"))
    object_type = str(clean_value(row.get("OBJECT_TYPE")) or "TABLE").upper()
    domain = str(clean_value(row.get("LINEAGE_DOMAIN")) or "TABLE").upper()
    lineage_key = str(
        clean_value(row.get("LINEAGE_KEY"))
        or make_lineage_key(database, schema, name, domain)
    )
    is_anchor = bool(
        anchor_key and lineage_key.casefold() == anchor_key.casefold()
    )
    classes = [class_for_object(domain, object_type)]
    if is_anchor:
        classes.append("anchor")

    return {
        "data": {
            "id": snowflake_object_id(domain, database, schema, name),
            "label": object_label(name, None, object_type, domain),
            "database": database,
            "schema": schema,
            "object_name": name,
            "fq_name": fully_qualified_name(database, schema, name),
            "domain": domain,
            "object_type": object_type,
            "dataset_type": object_type,
            "owner": clean_value(row.get("OBJECT_OWNER")),
            "comment": clean_value(row.get("COMMENT")),
            "row_count": clean_value(row.get("ROW_COUNT")),
            "created": clean_value(row.get("CREATED")),
            "last_altered": clean_value(row.get("LAST_ALTERED")),
            "stage_type": clean_value(row.get("STAGE_TYPE")),
            "stage_url": clean_value(row.get("STAGE_URL")),
            "profile": clean_value(row.get("PROFILE")),
            "is_secure": clean_value(row.get("IS_SECURE")),
            "lineage_key": lineage_key,
            "is_anchor": is_anchor,
        },
        "classes": " ".join(classes),
    }


def _anchor_node(anchor: ObjectRef) -> dict[str, Any]:
    object_type = anchor.object_type.upper()
    dataset_type = object_type
    return {
        "data": {
            "id": snowflake_object_id(
                anchor.lineage_domain,
                anchor.database,
                anchor.schema,
                anchor.name,
            ),
            "label": object_label(
                anchor.name,
                None,
                dataset_type,
                anchor.lineage_domain,
            ),
            "database": anchor.database,
            "schema": anchor.schema,
            "object_name": anchor.name,
            "fq_name": anchor.fq_name,
            "domain": anchor.lineage_domain,
            "object_type": anchor.object_type,
            "dataset_type": dataset_type,
            "owner": anchor.owner,
            "comment": anchor.comment,
            "row_count": anchor.row_count,
            "created": clean_value(anchor.created),
            "last_altered": clean_value(anchor.last_altered),
            "lineage_key": anchor.lineage_key,
            "is_anchor": True,
        },
        "classes": f"{class_for_object(anchor.lineage_domain, dataset_type)} anchor",
    }


def _lineage_edge(
    row: pd.Series,
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    pair_only: bool = False,
) -> dict[str, Any]:
    process_json = clean_value(row.get("PROCESS_JSON"))
    distance = clean_value(row.get("DISTANCE"))
    edge_id_parts: list[Any] = [
        source["data"]["id"],
        target["data"]["id"],
    ]
    if not pair_only:
        edge_id_parts.append(process_json)
    edge_id = stable_id("edge", *edge_id_parts)
    edge_classes = ["lineage-edge"]
    if target["data"].get("domain") == "SEMANTIC_VIEW":
        edge_classes.append("semantic-lineage")
    if target["data"].get("domain") == "CORTEX_AGENT":
        edge_classes.append("consumer-lineage")
    return {
        "data": {
            "id": edge_id,
            "source": source["data"]["id"],
            "target": target["data"]["id"],
            "label": "LINEAGE",
            "relationship_type": "LINEAGE",
            "distance": distance,
            "process": process_json,
        },
        "classes": " ".join(edge_classes),
    }


def _node_in_scope(
    node: dict[str, Any],
    database: str,
    schema: str,
) -> bool:
    data = node.get("data", {})
    return (
        str(data.get("database") or "").casefold() == database.casefold()
        and str(data.get("schema") or "").casefold() == schema.casefold()
    )


def build_lineage_elements(
    lineage: pd.DataFrame,
    anchor: ObjectRef,
    group_by_schema: bool = False,
) -> list[dict[str, Any]]:
    del group_by_schema  # retained for backwards compatibility with older callers
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    anchor_element = _anchor_node(anchor)
    _upsert_node(nodes, anchor_element)

    for _, row in lineage.iterrows():
        source = _node_from_lineage_side(row, "SOURCE", anchor.lineage_key)
        target = _node_from_lineage_side(row, "TARGET", anchor.lineage_key)
        _upsert_node(nodes, source)
        _upsert_node(nodes, target)
        edge = _lineage_edge(row, source, target)
        edges[edge["data"]["id"]] = edge

    elements = [*nodes.values(), *edges.values()]
    return decorate_graph_layers(elements)


def build_schema_elements(
    lineage: pd.DataFrame,
    inventory: pd.DataFrame,
    *,
    database: str,
    schema: str,
    include_external: bool = True,
) -> list[dict[str, Any]]:
    """Build a schema overview while retaining isolated inventory objects."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for _, row in inventory.iterrows():
        _upsert_node(nodes, _inventory_node(row))

    for _, row in lineage.iterrows():
        source = _node_from_lineage_side(row, "SOURCE")
        target = _node_from_lineage_side(row, "TARGET")
        source_in_scope = _node_in_scope(source, database, schema)
        target_in_scope = _node_in_scope(target, database, schema)

        if not include_external and not (source_in_scope and target_in_scope):
            continue

        if not source_in_scope:
            source["classes"] = (
                f"{source.get('classes', '')} scope-external".strip()
            )
            source["data"]["external_to_scope"] = True
        if not target_in_scope:
            target["classes"] = (
                f"{target.get('classes', '')} scope-external".strip()
            )
            target["data"]["external_to_scope"] = True

        _upsert_node(nodes, source)
        _upsert_node(nodes, target)
        edge = _lineage_edge(row, source, target, pair_only=True)
        edges[edge["data"]["id"]] = edge

    elements = [*nodes.values(), *edges.values()]
    return decorate_graph_layers(elements)


def _semantic_table_counts(
    model: dict[str, pd.DataFrame],
    logical_table: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("dimensions", "facts", "metrics"):
        frame = model.get(key, pd.DataFrame())
        if frame.empty:
            counts[key] = 0
            continue
        parent_column = next(
            (
                column
                for column in (
                    "TABLE_NAME",
                    "PARENT_ENTITY",
                    "SEMANTIC_TABLE_NAME",
                    "LOGICAL_TABLE_NAME",
                )
                if column in frame.columns
            ),
            None,
        )
        if parent_column:
            counts[key] = int(
                frame[parent_column]
                .astype(str)
                .str.casefold()
                .eq(logical_table.casefold())
                .sum()
            )
        else:
            counts[key] = 0
    return counts


def build_semantic_elements(
    object_ref: ObjectRef,
    model: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    if object_ref.lineage_domain != "SEMANTIC_VIEW":
        raise ValueError("Semantic graph requires a semantic view")

    semantic_view_id = stable_id("semantic-view", object_ref.fq_name)
    elements: list[dict[str, Any]] = [
        {
            "data": {
                "id": semantic_view_id,
                "label": f"{object_ref.name}\nSEMANTIC VIEW",
                "database": object_ref.database,
                "schema": object_ref.schema,
                "object_name": object_ref.name,
                "fq_name": object_ref.fq_name,
                "domain": "SEMANTIC_VIEW",
                "object_type": "SEMANTIC_VIEW",
                "lineage_key": object_ref.lineage_key,
                "is_anchor": True,
                "comment": object_ref.comment,
            },
            "classes": "semantic-view anchor",
        }
    ]

    logical_ids: dict[str, str] = {}
    semantic_tables = model.get("tables", pd.DataFrame())
    for _, row in semantic_tables.iterrows():
        logical_name = str(row.get("NAME") or "UNKNOWN_LOGICAL_TABLE")
        logical_id = stable_id("logical-table", object_ref.fq_name, logical_name)
        logical_ids[logical_name.casefold()] = logical_id
        counts = _semantic_table_counts(model, logical_name)
        primary_keys = clean_value(row.get("PRIMARY_KEYS"))
        synonyms = clean_value(row.get("SYNONYMS"))
        definition = clean_value(row.get("DEFINITION"))
        elements.append(
            {
                "data": {
                    "id": logical_id,
                    "label": f"{logical_name}\nLOGICAL TABLE",
                    "database": object_ref.database,
                    "schema": object_ref.schema,
                    "object_name": logical_name,
                    "fq_name": f"{object_ref.fq_name}.{logical_name}",
                    "domain": "LOGICAL_TABLE",
                    "object_type": "LOGICAL_TABLE",
                    "semantic_view": object_ref.fq_name,
                    "primary_keys": primary_keys,
                    "synonyms": synonyms,
                    "comment": clean_value(row.get("COMMENT")),
                    "definition": definition,
                    "dimension_count": counts["dimensions"],
                    "fact_count": counts["facts"],
                    "metric_count": counts["metrics"],
                },
                "classes": "logical-table",
            }
        )

        in_view_edge_id = stable_id(
            "semantic-membership", logical_id, semantic_view_id
        )
        elements.append(
            {
                "data": {
                    "id": in_view_edge_id,
                    "source": logical_id,
                    "target": semantic_view_id,
                    "label": "IN SEMANTIC VIEW",
                    "relationship_type": "SEMANTIC_MEMBERSHIP",
                },
                "classes": "semantic-membership",
            }
        )

        base_database = clean_value(row.get("BASE_TABLE_CATALOG"))
        base_schema = clean_value(row.get("BASE_TABLE_SCHEMA"))
        base_name = clean_value(row.get("BASE_TABLE_NAME"))
        if base_database and base_schema and base_name:
            base_id = snowflake_object_id(
                "TABLE",
                str(base_database),
                str(base_schema),
                str(base_name),
            )
            elements.append(
                {
                    "data": {
                        "id": base_id,
                        "label": f"{base_name}\nPHYSICAL OBJECT",
                        "database": base_database,
                        "schema": base_schema,
                        "object_name": base_name,
                        "fq_name": fully_qualified_name(
                            str(base_database), str(base_schema), str(base_name)
                        ),
                        "domain": "TABLE",
                        "object_type": "PHYSICAL_OBJECT",
                        "dataset_type": "TABLE",
                        "lineage_key": make_lineage_key(
                            str(base_database),
                            str(base_schema),
                            str(base_name),
                            "TABLE",
                        ),
                    },
                    "classes": "table physical-base",
                }
            )
            base_edge_id = stable_id("base-table", base_id, logical_id)
            elements.append(
                {
                    "data": {
                        "id": base_edge_id,
                        "source": base_id,
                        "target": logical_id,
                        "label": "BASE TABLE",
                        "relationship_type": "BASE_TABLE",
                    },
                    "classes": "base-table-edge",
                }
            )

    relationships = model.get("relationships", pd.DataFrame())
    for _, row in relationships.iterrows():
        source_name = str(row.get("TABLE_NAME") or "")
        target_name = str(row.get("REF_TABLE_NAME") or "")
        source_id = logical_ids.get(source_name.casefold())
        target_id = logical_ids.get(target_name.casefold())
        if not source_id or not target_id:
            continue

        relationship_name = str(row.get("NAME") or "RELATIONSHIP")
        foreign_keys = clean_value(row.get("FOREIGN_KEYS"))
        ref_keys = clean_value(row.get("REF_KEYS"))
        key_text = ""
        if foreign_keys or ref_keys:
            key_text = f" | {foreign_keys} -> {ref_keys}"
        edge_id = stable_id(
            "semantic-relationship",
            object_ref.fq_name,
            relationship_name,
            source_name,
            target_name,
        )
        elements.append(
            {
                "data": {
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "label": f"{relationship_name}{key_text}",
                    "relationship_type": "SEMANTIC_RELATIONSHIP",
                    "relationship_name": relationship_name,
                    "foreign_keys": foreign_keys,
                    "referenced_keys": ref_keys,
                },
                "classes": "semantic-relationship",
            }
        )

    return decorate_graph_layers(deduplicate_elements(elements))


def _starts_with_any(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def _contains_token(value: str, tokens: tuple[str, ...]) -> bool:
    normalized = value.replace("-", "_").replace(" ", "_")
    parts = {part for part in normalized.split("_") if part}
    return any(token in parts for token in tokens)


def _classify_layer(
    data: dict[str, Any],
    predecessors: list[dict[str, Any]],
    successors: list[dict[str, Any]],
) -> tuple[str, str, int, str]:
    domain = str(data.get("domain") or "").upper()
    object_type = str(
        data.get("dataset_type") or data.get("object_type") or domain
    ).upper().replace(" ", "_")
    name = str(data.get("object_name") or data.get("label") or "").upper()
    schema = str(data.get("schema") or "").upper()

    if domain == "CORTEX_AGENT" or object_type in {"CORTEX_AGENT", "AGENT"}:
        return "consumer", "AI / Agent", 0, "Cortex Agent"
    if domain == "SEMANTIC_VIEW" or object_type == "SEMANTIC_VIEW":
        return "semantic", "Semantic view", 0, "Semantic view"
    if domain == "LOGICAL_TABLE" or object_type == "LOGICAL_TABLE":
        return "logical", "Logical table", 0, "Semantic logical table"
    if domain == "STAGE" or object_type == "STAGE":
        return "source", "Stage", 0, "Snowflake stage"
    if domain in {"EXTERNAL", "EXTERNAL_COLUMN"}:
        if predecessors and not successors:
            return "consumer", "External target", 1, "Downstream external object"
        return "source", "External source", 0, "External source"
    if domain in {"DATASET", "MODULE"} or object_type in {"DATASET", "MODULE"}:
        return "consumer", "Consumer", 2, "Downstream dataset or model"

    if _starts_with_any(name, ("DIM_", "D_")):
        return "gold", "Dimensions", 0, "Dimension naming convention"
    if _starts_with_any(name, ("FCT_", "FACT_", "F_")):
        return "gold", "Facts", 1, "Fact naming convention"
    if _starts_with_any(name, ("AGG_", "MART_")) or _contains_token(
        schema, ("GOLD", "MART")
    ):
        return "gold", "Other Gold", 2, "Gold or mart naming convention"

    if _starts_with_any(name, ("STG_", "STAGING_", "INT_", "INTERMEDIATE_")):
        return "staging", "Staging", 0, "Staging naming convention"
    if _contains_token(schema, ("SILVER", "STAGE", "STAGING", "INT")):
        return "staging", "Staging", 0, "Silver or staging schema"

    if _starts_with_any(name, ("RAW_", "SRC_", "SOURCE_")):
        return "raw", "Raw", 0, "Raw naming convention"
    if _contains_token(schema, ("RAW", "BRONZE", "SOURCE")):
        return "raw", "Raw", 0, "Raw or bronze schema"

    successor_domains = {
        str(item.get("domain") or "").upper() for item in successors
    }
    predecessor_domains = {
        str(item.get("domain") or "").upper() for item in predecessors
    }
    if "SEMANTIC_VIEW" in successor_domains or "LOGICAL_TABLE" in successor_domains:
        return "gold", "Other Gold", 2, "Feeds the semantic layer"
    if predecessor_domains & {"STAGE", "EXTERNAL", "EXTERNAL_COLUMN"}:
        return "raw", "Raw", 0, "Loaded from a source or stage"

    if object_type in {"VIEW", "SECURE_VIEW", "MATERIALIZED_VIEW"}:
        return "staging", "Staging", 0, "View defaults to the staging layer"
    if object_type == "DYNAMIC_TABLE":
        if successors:
            return "staging", "Staging", 0, "Dynamic transformation object"
        return "gold", "Other Gold", 2, "Terminal dynamic table"

    return "raw", "Raw", 0, "Base table default"


def decorate_graph_layers(
    elements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign deterministic architecture layers used by the client layout."""
    result = deduplicate_elements(elements)
    node_lookup = {
        str(element.get("data", {}).get("id")): element
        for element in result
        if "source" not in element.get("data", {})
    }
    predecessors: dict[str, list[str]] = {node_id: [] for node_id in node_lookup}
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_lookup}

    for element in result:
        data = element.get("data", {})
        source = str(data.get("source") or "")
        target = str(data.get("target") or "")
        if source in node_lookup and target in node_lookup:
            successors[source].append(target)
            predecessors[target].append(source)

    for node_id, element in node_lookup.items():
        data = element.setdefault("data", {})
        predecessor_data = [
            node_lookup[item].get("data", {})
            for item in predecessors.get(node_id, [])
            if item in node_lookup
        ]
        successor_data = [
            node_lookup[item].get("data", {})
            for item in successors.get(node_id, [])
            if item in node_lookup
        ]
        layer_key, subgroup, subgroup_order, reason = _classify_layer(
            data,
            predecessor_data,
            successor_data,
        )
        definition = LAYER_DEFINITIONS[layer_key]
        data.update(
            {
                "layer_key": layer_key,
                "layer_label": definition["label"],
                "layer_order": definition["order"],
                "layer_subgroup": subgroup,
                "layer_subgroup_order": subgroup_order,
                "layer_reason": reason,
                "is_isolated": not predecessors.get(node_id)
                and not successors.get(node_id),
            }
        )

        classes = _class_set(element.get("classes"))
        classes.add(f"layer-{layer_key}")
        if layer_key == "gold" and subgroup == "Dimensions":
            classes.add("gold-dimension")
        elif layer_key == "gold" and subgroup == "Facts":
            classes.add("gold-fact")
        if data["is_isolated"]:
            classes.add("isolated")
        element["classes"] = " ".join(sorted(classes))

    return result


def deduplicate_elements(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for element in elements:
        element_id = str(element.get("data", {}).get("id"))
        if not element_id or element_id == "None":
            continue
        result[element_id] = element
    return list(result.values())


def graph_counts(elements: Iterable[dict[str, Any]]) -> tuple[int, int]:
    node_count = 0
    edge_count = 0
    for element in elements:
        data = element.get("data", {})
        if "source" in data and "target" in data:
            edge_count += 1
        else:
            node_count += 1
    return node_count, edge_count


def graph_layer_counts(elements: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in elements:
        data = element.get("data", {})
        if "source" in data:
            continue
        label = str(data.get("layer_label") or "Unclassified")
        counts[label] = counts.get(label, 0) + 1
    return counts


def elements_as_json(elements: Iterable[dict[str, Any]]) -> str:
    return json.dumps(list(elements), indent=2, default=str)
