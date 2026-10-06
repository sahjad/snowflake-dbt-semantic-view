from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from components.cytoscape import render_cytoscape
from src.graph_builder import (
    build_lineage_elements,
    build_schema_elements,
    build_semantic_elements,
    elements_as_json,
    graph_counts,
    graph_layer_counts,
)
from src.snowflake_metadata import (
    ObjectRef,
    get_columns,
    get_lineage,
    get_schema_lineage,
    get_semantic_model,
    list_databases,
    list_objects,
    list_schemas,
    make_lineage_key,
)


SCHEMA_OVERVIEW_KEY = "schema-overview"
SCHEMA_OVERVIEW_LIMIT = 150

st.set_page_config(
    page_title="Snowflake Lineage Explorer",
    page_icon=":material/account_tree:",
    layout="wide",
)


@st.cache_data(ttl=300, show_spinner=False)
def cached_databases(_session: Any) -> list[str]:
    return list_databases(_session)


@st.cache_data(ttl=300, show_spinner=False)
def cached_schemas(
    _session: Any,
    database: str,
) -> list[str]:
    return list_schemas(_session, database)


@st.cache_data(ttl=180, show_spinner=False)
def cached_objects(
    _session: Any,
    database: str,
    schema: str,
) -> pd.DataFrame:
    return list_objects(_session, database, schema)


@st.cache_data(ttl=180, show_spinner=False)
def cached_lineage(
    _session: Any,
    database: str,
    schema: str,
    object_name: str,
    object_type: str,
    direction: str,
    depth: int,
) -> pd.DataFrame:
    ref = ObjectRef(database, schema, object_name, object_type)
    return get_lineage(_session, ref, direction, depth)


@st.cache_data(ttl=300, show_spinner=False)
def cached_schema_lineage(
    _session: Any,
    object_specs: tuple[tuple[str, str, str, str], ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    refs = [ObjectRef(*spec) for spec in object_specs]
    return get_schema_lineage(_session, refs, max_distance=1)


@st.cache_data(ttl=300, show_spinner=False)
def cached_columns(
    _session: Any,
    database: str,
    schema: str,
    object_name: str,
) -> pd.DataFrame:
    return get_columns(_session, database, schema, object_name)


@st.cache_data(ttl=180, show_spinner=False)
def cached_semantic_model(
    _session: Any,
    database: str,
    schema: str,
    object_name: str,
) -> dict[str, pd.DataFrame]:
    ref = ObjectRef(database, schema, object_name, "SEMANTIC_VIEW")
    return get_semantic_model(_session, ref)


def object_ref_from_key(inventory: pd.DataFrame, lineage_key: str) -> ObjectRef:
    row = inventory.loc[inventory["LINEAGE_KEY"] == lineage_key]
    if row.empty:
        raise KeyError(f"Object key not found: {lineage_key}")
    return ObjectRef.from_inventory_row(row.iloc[0])


def find_anchor_id(elements: list[dict[str, Any]]) -> str | None:
    for element in elements:
        data = element.get("data", {})
        if data.get("is_anchor") and "source" not in data:
            return str(data.get("id"))
    return None


def anchor_selection_payload(
    elements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for element in elements:
        data = element.get("data", {})
        if data.get("is_anchor") and "source" not in data:
            return {
                "kind": "node",
                "data": data,
                "classes": element.get("classes", ""),
            }
    return None


def pretty_process(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def render_key_value(data: dict[str, Any], fields: list[tuple[str, str]]) -> None:
    for key, label in fields:
        value = data.get(key)
        if value not in (None, "", [], {}):
            st.markdown(f"**{label}:** `{value}`")


def set_pending_explore(data: dict[str, Any]) -> bool:
    database = data.get("database")
    schema = data.get("schema")
    object_name = data.get("object_name")
    domain = str(data.get("domain") or "").upper()
    if not database or not schema or not object_name or not domain:
        return False

    st.session_state["pending_explore"] = {
        "database": str(database),
        "schema": str(schema),
        "lineage_key": str(
            data.get("lineage_key")
            or make_lineage_key(database, schema, object_name, domain)
        ),
    }
    return True


def process_component_explore(explore: dict[str, Any] | None) -> None:
    if not explore or explore.get("kind") != "node":
        return
    nonce = explore.get("selected_at")
    if not nonce or st.session_state.get("last_component_explore") == nonce:
        return
    st.session_state["last_component_explore"] = nonce
    if set_pending_explore(explore.get("data", {})):
        st.rerun()


def render_selection_panel(
    selected: dict[str, Any] | None,
    elements: list[dict[str, Any]],
    session: Any,
) -> None:
    st.subheader("Selection")
    if not selected:
        st.caption(
            "Select a node or relationship. Use **Explore** in the graph toolbar "
            "or the button below to drill into an object."
        )
        return

    kind = selected.get("kind")
    data = selected.get("data", {})

    if kind == "edge":
        st.markdown(f"### {data.get('label', 'Relationship')}")
        node_lookup = {
            element.get("data", {}).get("id"): element.get("data", {})
            for element in elements
            if "source" not in element.get("data", {})
        }
        source = node_lookup.get(data.get("source"), {})
        target = node_lookup.get(data.get("target"), {})
        st.markdown(f"**From:** `{source.get('fq_name') or source.get('label')}`")
        st.markdown(f"**To:** `{target.get('fq_name') or target.get('label')}`")
        render_key_value(
            data,
            [
                ("relationship_type", "Type"),
                ("distance", "Distance"),
                ("relationship_name", "Relationship name"),
                ("foreign_keys", "Foreign keys"),
                ("referenced_keys", "Referenced keys"),
            ],
        )
        process = pretty_process(data.get("process"))
        if process is not None:
            st.markdown("**Lineage process**")
            if isinstance(process, (dict, list)):
                st.json(process)
            else:
                st.code(str(process))
        return

    st.markdown(f"### {data.get('object_name') or data.get('label', 'Object')}")
    render_key_value(
        data,
        [
            ("fq_name", "Fully qualified name"),
            ("object_type", "Object type"),
            ("domain", "Lineage domain"),
            ("layer_label", "Architecture layer"),
            ("layer_subgroup", "Layer subgroup"),
            ("layer_reason", "Layer rule"),
            ("status", "Status"),
            ("owner", "Owner"),
            ("row_count", "Row count"),
            ("created", "Created"),
            ("last_altered", "Last altered"),
            ("stage_type", "Stage type"),
            ("stage_url", "Stage URL"),
            ("primary_keys", "Primary keys"),
            ("dimension_count", "Dimensions"),
            ("fact_count", "Facts"),
            ("metric_count", "Metrics"),
            ("origin", "Lineage origin"),
            ("namespace", "External namespace"),
            ("external_to_scope", "Outside selected schema"),
        ],
    )
    if data.get("comment"):
        st.markdown("**Description**")
        st.write(data["comment"])

    database = data.get("database")
    schema = data.get("schema")
    object_name = data.get("object_name")
    domain = str(data.get("domain") or "").upper()

    if database and schema and object_name and domain not in {
        "LOGICAL_TABLE",
        "EXTERNAL",
        "EXTERNAL_COLUMN",
        "LAYER_HEADER",
    }:
        if st.button(
            "Explore this object",
            type="primary",
            use_container_width=True,
            key=f"explore-{data.get('id')}",
        ):
            if set_pending_explore(data):
                st.rerun()

    if domain == "TABLE" and database and schema and object_name:
        with st.expander("Columns", expanded=False):
            try:
                columns = cached_columns(
                    session,
                    str(database),
                    str(schema),
                    str(object_name),
                )
                if columns.empty:
                    st.caption("No accessible column metadata was returned.")
                else:
                    st.dataframe(columns, width="stretch", hide_index=True)
            except Exception as exc:
                st.warning(f"Column metadata could not be loaded: {exc}")

    with st.expander("Raw node metadata", expanded=False):
        st.json(data)


def render_model_tables(model: dict[str, pd.DataFrame]) -> None:
    tab_names = ["Logical tables", "Relationships", "Dimensions", "Facts", "Metrics"]
    tabs = st.tabs(tab_names)
    keys = ["tables", "relationships", "dimensions", "facts", "metrics"]
    for tab, key in zip(tabs, keys):
        with tab:
            frame = model.get(key, pd.DataFrame())
            if frame.empty:
                st.caption(f"No {key} were returned.")
            else:
                st.dataframe(frame, width="stretch", hide_index=True)


def connect_to_snowflake() -> Any:
    try:
        connection = st.connection("snowflake")
        return connection.session()
    except Exception as exc:
        st.error("The app could not connect to Snowflake.")
        st.exception(exc)
        st.markdown(
            "In Snowsight Workspaces, run this as a Streamlit in Snowflake app. "
            "For optional local development, configure a Snowflake connection "
            "in `.streamlit/secrets.toml`."
        )
        st.stop()


session = connect_to_snowflake()

st.title("Snowflake Lineage and Semantic Explorer")
st.caption(
    "Start with a complete schema overview, then optionally select or explore an "
    "object for focused upstream/downstream lineage. The graph uses one fixed "
    "layered layout from sources to consumers."
)

pending_explore = st.session_state.pop("pending_explore", None)

with st.sidebar:
    st.header("Graph controls")
    viewer_name = getattr(st.user, "user_name", None)
    if viewer_name:
        st.caption(f"Signed in as: {viewer_name}")

    if st.button("Refresh metadata", icon=":material/refresh:", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    try:
        databases = cached_databases(session)
    except Exception as exc:
        st.error(f"Databases could not be listed: {exc}")
        st.stop()

    if not databases:
        st.warning("No accessible databases were returned for `LINEAGE_APP_ROLE`.")
        st.stop()

    if pending_explore and pending_explore.get("database") in databases:
        st.session_state["database_selector"] = pending_explore["database"]
    if st.session_state.get("database_selector") not in databases:
        preferred = next(
            (name for name in databases if name.upper() == "TASTY_BYTES_DB"),
            databases[0],
        )
        st.session_state["database_selector"] = preferred

    database = st.selectbox("Database", databases, key="database_selector")

    try:
        schemas = cached_schemas(session, database)
    except Exception as exc:
        st.error(f"Schemas could not be listed: {exc}")
        st.stop()

    if not schemas:
        st.warning("No accessible schemas were returned for the selected database.")
        st.stop()

    if (
        pending_explore
        and pending_explore.get("database") == database
        and pending_explore.get("schema") in schemas
    ):
        st.session_state["schema_selector"] = pending_explore["schema"]
    if st.session_state.get("schema_selector") not in schemas:
        preferred_schema = next(
            (
                name
                for preferred_name in ("DEV", "PUBLIC")
                for name in schemas
                if name.upper() == preferred_name
            ),
            schemas[0],
        )
        st.session_state["schema_selector"] = preferred_schema

    schema = st.selectbox("Schema", schemas, key="schema_selector")

    try:
        inventory = cached_objects(session, database, schema)
    except Exception as exc:
        st.error(f"Objects could not be listed: {exc}")
        st.stop()

    if inventory.empty:
        st.warning(
            "No accessible tables, views, stages, semantic views, or agents were returned."
        )
        st.stop()

    object_types = sorted(inventory["OBJECT_TYPE"].dropna().astype(str).unique())
    selected_types = st.multiselect(
        "Object types",
        object_types,
        default=object_types,
    )
    object_filter = st.text_input(
        "Filter schema objects",
        placeholder="Search by object name or type",
    )

    filtered_inventory = inventory.loc[
        inventory["OBJECT_TYPE"].isin(selected_types)
    ].copy()
    if object_filter.strip():
        query = object_filter.strip().casefold()
        filtered_inventory = filtered_inventory.loc[
            filtered_inventory["DISPLAY_LABEL"]
            .astype(str)
            .str.casefold()
            .str.contains(query, regex=False)
        ]

    if filtered_inventory.empty:
        st.warning("No objects match the current filters.")
        st.stop()

    option_keys = filtered_inventory["LINEAGE_KEY"].tolist()
    labels = dict(
        zip(filtered_inventory["LINEAGE_KEY"], filtered_inventory["DISPLAY_LABEL"])
    )
    anchor_options = [SCHEMA_OVERVIEW_KEY, *option_keys]

    pending_key = None
    if pending_explore and pending_explore.get("database") == database:
        pending_key = pending_explore.get("lineage_key")
    if pending_key in option_keys:
        st.session_state["anchor_selector"] = pending_key
    if st.session_state.get("anchor_selector") not in anchor_options:
        st.session_state["anchor_selector"] = SCHEMA_OVERVIEW_KEY

    anchor_key = st.selectbox(
        "Anchor object (optional)",
        anchor_options,
        format_func=lambda value: (
            "None — Schema overview"
            if value == SCHEMA_OVERVIEW_KEY
            else labels.get(value, value)
        ),
        key="anchor_selector",
    )
    schema_overview = anchor_key == SCHEMA_OVERVIEW_KEY
    anchor = None if schema_overview else object_ref_from_key(inventory, anchor_key)

    if not schema_overview and st.button(
        "Back to schema overview",
        icon=":material/arrow_back:",
        use_container_width=True,
    ):
        st.session_state["anchor_selector"] = SCHEMA_OVERVIEW_KEY
        st.rerun()

    if schema_overview:
        st.caption(
            "Schema overview displays every filtered object, including isolated "
            "objects, and retrieves direct lineage edges for the selected schema."
        )
        include_external = st.checkbox(
            "Show connected objects outside this schema",
            value=True,
        )
        graph_mode = "Schema overview"
        direction = "BOTH"
        depth = 1
    else:
        include_external = True
        mode_options = ["Technical lineage"]
        if anchor and anchor.lineage_domain == "SEMANTIC_VIEW":
            mode_options.append("Semantic model")
        graph_mode = st.radio("Graph mode", mode_options, horizontal=True)
        if graph_mode == "Technical lineage":
            direction = st.segmented_control(
                "Direction",
                ["UPSTREAM", "DOWNSTREAM", "BOTH"],
                default="BOTH",
                selection_mode="single",
            )
            direction = direction or "BOTH"
            depth = st.slider("Lineage depth", min_value=1, max_value=5, value=3)
        else:
            direction = "BOTH"
            depth = 1

    show_edge_labels = st.checkbox("Always show relationship labels", value=False)
    graph_search = st.text_input(
        "Highlight in graph",
        placeholder="Object, schema, layer, type, or relationship",
    )

if schema_overview and len(filtered_inventory) > SCHEMA_OVERVIEW_LIMIT:
    st.warning(
        f"The filtered schema contains {len(filtered_inventory):,} objects. "
        f"Narrow the object types or filter to {SCHEMA_OVERVIEW_LIMIT} objects or "
        "fewer before building the schema overview."
    )
    st.stop()

schema_failures = pd.DataFrame()
try:
    if schema_overview:
        object_specs = tuple(
            (
                str(row["DATABASE_NAME"]),
                str(row["SCHEMA_NAME"]),
                str(row["OBJECT_NAME"]),
                str(row["OBJECT_TYPE"]),
            )
            for _, row in filtered_inventory.iterrows()
        )
        with st.spinner(
            f"Building the {schema} schema overview from "
            f"{len(object_specs)} objects..."
        ):
            lineage, schema_failures = cached_schema_lineage(session, object_specs)
        elements = build_schema_elements(
            lineage,
            filtered_inventory,
            database=database,
            schema=schema,
            include_external=include_external,
        )
        semantic_model = None
    elif graph_mode == "Technical lineage" and anchor is not None:
        with st.spinner("Retrieving Snowflake lineage..."):
            lineage = cached_lineage(
                session,
                anchor.database,
                anchor.schema,
                anchor.name,
                anchor.object_type,
                direction,
                depth,
            )
        elements = build_lineage_elements(lineage, anchor)
        semantic_model = None
    elif anchor is not None:
        with st.spinner("Retrieving semantic view metadata..."):
            semantic_model = cached_semantic_model(
                session,
                anchor.database,
                anchor.schema,
                anchor.name,
            )
        elements = build_semantic_elements(anchor, semantic_model)
        lineage = pd.DataFrame()
    else:
        raise RuntimeError("No valid graph scope was selected.")
except Exception as exc:
    st.error("The selected graph could not be built.")
    st.exception(exc)
    st.info(
        "Confirm that `LINEAGE_APP_ROLE` has VIEW LINEAGE, USAGE on the database "
        "and schema, and a privilege such as REFERENCES, USAGE, MONITOR, or SELECT "
        "on the relevant objects."
    )
    st.stop()

node_count, edge_count = graph_counts(elements)
metric1, metric2, metric3, metric4 = st.columns(4)
metric1.metric(
    "Scope",
    f"{schema} schema" if schema_overview else (anchor.name if anchor else "—"),
)
metric2.metric("Nodes", node_count)
metric3.metric("Relationships", edge_count)
metric4.metric("Mode", graph_mode)

if schema_overview and not schema_failures.empty:
    st.info(
        f"Lineage could not be queried for {len(schema_failures)} object(s). "
        "Those inventory objects still appear in the graph and may be shown as isolated."
    )
elif not schema_overview and graph_mode == "Technical lineage" and lineage.empty:
    st.warning(
        "Snowflake returned no lineage edges for this object. The graph still shows "
        "the anchor object. This can mean that no lineage has been recorded, the "
        "object is unsupported, or the current role cannot resolve related objects."
    )

left, right = st.columns([3.45, 1.05], gap="large")
with left:
    anchor_id = find_anchor_id(elements)
    graph_state = render_cytoscape(
        elements,
        search=graph_search,
        show_edge_labels=show_edge_labels,
        anchor_id=anchor_id,
        height=790,
        key=(
            f"graph::{database}::{schema}::{anchor_key}::{graph_mode}::"
            f"{direction}::{depth}::{include_external}"
        ),
    )
    process_component_explore(graph_state.get("explore"))
with right:
    default_selection = None if schema_overview else anchor_selection_payload(elements)
    render_selection_panel(
        graph_state.get("selected") or default_selection,
        elements,
        session,
    )

st.divider()
if schema_overview:
    raw_tab, layers_tab, graph_tab, diagnostics_tab = st.tabs(
        ["Schema lineage rows", "Layer summary", "Graph JSON", "Diagnostics"]
    )
    with raw_tab:
        if lineage.empty:
            st.caption("No direct lineage rows were returned for the filtered schema.")
        else:
            st.dataframe(lineage, width="stretch", hide_index=True)
            st.download_button(
                "Download schema lineage CSV",
                data=lineage.to_csv(index=False).encode("utf-8"),
                file_name=f"{database}_{schema}_schema_lineage.csv",
                mime="text/csv",
            )
    with layers_tab:
        layer_frame = pd.DataFrame(
            [
                {"LAYER": layer, "OBJECT_COUNT": count}
                for layer, count in graph_layer_counts(elements).items()
            ]
        )
        if not layer_frame.empty:
            st.dataframe(layer_frame, width="stretch", hide_index=True)
    with graph_tab:
        graph_json = elements_as_json(elements)
        st.code(graph_json, language="json")
        st.download_button(
            "Download schema graph JSON",
            data=graph_json.encode("utf-8"),
            file_name=f"{database}_{schema}_schema_graph.json",
            mime="application/json",
        )
    with diagnostics_tab:
        if schema_failures.empty:
            st.success("All filtered schema objects were queried successfully.")
        else:
            st.dataframe(schema_failures, width="stretch", hide_index=True)
elif graph_mode == "Technical lineage" and anchor is not None:
    raw_tab, graph_tab = st.tabs(["Lineage rows", "Graph JSON"])
    with raw_tab:
        if lineage.empty:
            st.caption("No lineage rows were returned.")
        else:
            st.dataframe(lineage, width="stretch", hide_index=True)
            st.download_button(
                "Download lineage CSV",
                data=lineage.to_csv(index=False).encode("utf-8"),
                file_name=f"{anchor.name}_lineage.csv",
                mime="text/csv",
            )
    with graph_tab:
        graph_json = elements_as_json(elements)
        st.code(graph_json, language="json")
        st.download_button(
            "Download graph JSON",
            data=graph_json.encode("utf-8"),
            file_name=f"{anchor.name}_graph.json",
            mime="application/json",
        )
elif anchor is not None:
    render_model_tables(semantic_model or {})
    with st.expander("Graph JSON", expanded=False):
        graph_json = elements_as_json(elements)
        st.code(graph_json, language="json")
        st.download_button(
            "Download semantic graph JSON",
            data=graph_json.encode("utf-8"),
            file_name=f"{anchor.name}_semantic_graph.json",
            mime="application/json",
        )
