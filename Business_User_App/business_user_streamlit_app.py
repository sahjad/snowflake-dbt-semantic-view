import streamlit as st
import pandas as pd
import uuid
import yaml
from snowflake.snowpark.context import get_active_session

session = get_active_session()

TOOL_DB = "TASTY_BYTES_DB"
TOOL_SCHEMA = "SEMANTIC_TOOL"
TOOL_PATH = f"{TOOL_DB}.{TOOL_SCHEMA}"

# Where deployed semantic views land. Business users do not choose this --
# it is a deployment decision the engineer confirms at deploy time.
DEFAULT_TARGET_DB = "TASTY_BYTES_DB"

# Environments are shown to users as DEV / PROD; these map to real schemas.
ENV_SCHEMAS = {"DEV": "DEV", "PROD": "PROD"}

st.set_page_config(page_title="Semantic View Builder", layout="wide")


# ============================================================
# Helpers
# ============================================================

def current_user():
    """The person viewing the app.

    CURRENT_USER() does NOT work here: in Streamlit in Snowflake (owner's
    rights), it returns the Streamlit object's service identity, not the
    viewer -- and that identity changes between deployments, so it can't be
    used as a stable owner value. st.user is the documented API for viewer
    identity. Falls back to CURRENT_USER() only if st.user is unavailable
    (e.g. running outside Streamlit in Snowflake).
    """
    try:
        name = st.user.user_name
        if name:
            return name
    except Exception:
        pass
    try:
        return session.sql("SELECT CURRENT_USER()").collect()[0][0] or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def new_id():
    return str(uuid.uuid4())


def esc(s):
    """Escape a value for use inside a single-quoted SQL literal.

    Backslashes must be escaped FIRST: Snowflake treats backslash as an
    escape character inside string literals, so an unescaped one would be
    silently consumed -- which corrupts YAML containing escaped quotes.
    """
    return (s or "").replace("\\", "\\\\").replace("'", "''")


def run(sql):
    return session.sql(sql).collect()


def df(sql):
    return session.sql(sql).to_pandas()


def _row_get(row_dict, target):
    """Case/quote-insensitive key lookup -- SHOW/DESC results vary in casing."""
    def clean(k):
        return k.strip().strip('"').strip("'").upper()
    for k in row_dict:
        if clean(k) == target.upper():
            return row_dict[k]
    raise KeyError(f"Column '{target}' not found. Actual: {list(row_dict.keys())}")


@st.cache_data(ttl=120)
def get_databases():
    rows = session.sql("SHOW DATABASES").collect()
    return [_row_get(r.as_dict(), "name") for r in rows]


@st.cache_data(ttl=120)
def get_schemas(db):
    rows = session.sql(f"SHOW SCHEMAS IN DATABASE {db}").collect()
    return [_row_get(r.as_dict(), "name") for r in rows]


@st.cache_data(ttl=120)
def get_tables(db, schema):
    rows = session.sql(f"SHOW TABLES IN SCHEMA {db}.{schema}").collect()
    if not rows:
        return [], {}
    dicts = [r.as_dict() for r in rows]
    names = [_row_get(d, "name") for d in dicts]
    comments = {_row_get(d, "name"): (_row_get(d, "comment") or "") for d in dicts}
    return names, comments


@st.cache_data(ttl=120)
def get_columns(db, schema, table):
    rows = session.sql(f"DESC TABLE {db}.{schema}.{table}").collect()
    if not rows:
        return [], {}
    dicts = [r.as_dict() for r in rows]
    names = [_row_get(d, "name") for d in dicts]
    comments = {_row_get(d, "name"): (_row_get(d, "comment") or "") for d in dicts}
    types = {_row_get(d, "name"): (_row_get(d, "type") or "") for d in dicts}
    return names, {"comments": comments, "types": types}


def fmt_with_comment(comments_dict):
    return lambda x: f"{x} — {comments_dict.get(x) or 'no description set'}"


COMMON_PREFIXES = ("DIM_", "FCT_", "STG_")


def suggest_primary_key(db, schema, table, columns):
    """Best-effort primary key guess, in order of confidence. Always just a
    suggestion the business user confirms or overrides -- never applied
    silently -- since a wrong guess baked in unreviewed is worse than no
    guess at all.

    1. A real declared constraint, if one exists (most of our own Gold
       tables won't have one -- they were built as plain SELECTs -- but
       this is checked first in case a table does).
    2. An exact match: strip a common prefix (DIM_/FCT_/STG_) from the
       table name and look for "<stripped>_ID" among its columns -- this
       resolves even multi-key tables like FCT_ORDER_DETAIL correctly.
    3. If exactly one column ends in "_ID", use it -- true for every one
       of our dimension tables.
    4. Otherwise, no suggestion -- leave it for manual selection.
    """
    try:
        rows = session.sql(f"SHOW PRIMARY KEYS IN TABLE {db}.{schema}.{table}").collect()
        if rows:
            cols = [_row_get(r.as_dict(), "column_name") for r in rows]
            if cols:
                return cols
    except Exception:
        pass

    stripped = table.upper()
    for p in COMMON_PREFIXES:
        if stripped.startswith(p):
            stripped = stripped[len(p):]
            break
    exact = f"{stripped}_ID"
    if exact in [c.upper() for c in columns]:
        match = next(c for c in columns if c.upper() == exact)
        return [match]

    id_cols = [c for c in columns if c.upper().endswith("_ID")]
    if len(id_cols) == 1:
        return id_cols

    return []


def suggest_relationships(bt_df):
    """Auto-suggest relationships between already-added tables.

    For each pair, look for a column name appearing in both tables' full
    column lists. A suggestion is only made when that column is the
    primary key of exactly one side -- that's what makes the direction
    unambiguous (parent = whichever table it's a key on). If it's a key
    on both sides, or neither, it's genuinely ambiguous and is skipped
    rather than guessed -- left for the manual relationship form instead.
    """
    suggestions = []
    rows = list(bt_df.iterrows())
    for i in range(len(rows)):
        for j in range(len(rows)):
            if i == j:
                continue
            _, a = rows[i]
            _, b = rows[j]
            a_cols, _ = get_columns(a["PHYSICAL_DATABASE"], a["PHYSICAL_SCHEMA"], a["PHYSICAL_TABLE"])
            b_cols, _ = get_columns(b["PHYSICAL_DATABASE"], b["PHYSICAL_SCHEMA"], b["PHYSICAL_TABLE"])
            a_pk = [c.strip().upper() for c in (a["PRIMARY_KEY_COLS"] or "").split(",") if c.strip()]
            b_pk = [c.strip().upper() for c in (b["PRIMARY_KEY_COLS"] or "").split(",") if c.strip()]

            shared = set(c.upper() for c in a_cols) & set(c.upper() for c in b_cols)
            for col in shared:
                a_is_pk = col in a_pk
                b_is_pk = col in b_pk
                if a_is_pk and not b_is_pk:
                    # a is the parent (one side), b references it (many side)
                    real_col_a = next(c for c in a_cols if c.upper() == col)
                    real_col_b = next(c for c in b_cols if c.upper() == col)
                    suggestions.append({
                        "left_table": b["TABLE_ALIAS"], "right_table": a["TABLE_ALIAS"],
                        "left_column": real_col_b, "right_column": real_col_a,
                    })
    # de-duplicate (each true pair gets found from both directions of the i/j loop)
    seen = set()
    unique = []
    for s in suggestions:
        key = (s["left_table"], s["right_table"], s["left_column"], s["right_column"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def touch_proposal(pid):
    run(f"UPDATE {TOOL_PATH}.svt_proposals SET updated_at = CURRENT_TIMESTAMP() "
        f"WHERE proposal_id = '{esc(pid)}'")


# ============================================================
# YAML generation
# ============================================================

def generate_yaml(pid, view_name, description):
    """Build the semantic view YAML from the builder tables.

    Uses declared semantic names throughout (not raw physical columns) --
    this is what keeps downstream verified queries and the stricter YAML
    validator happy.
    """
    tables = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_tables WHERE proposal_id = '{esc(pid)}' ORDER BY created_at")
    dims = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_dimensions WHERE proposal_id = '{esc(pid)}' ORDER BY created_at")
    facts = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_facts WHERE proposal_id = '{esc(pid)}' ORDER BY created_at")
    metrics = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_metrics WHERE proposal_id = '{esc(pid)}' ORDER BY created_at")
    rels = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_relationships WHERE proposal_id = '{esc(pid)}' ORDER BY created_at")

    if tables.empty:
        return None, "Add at least one table before generating YAML."

    spec = {"name": view_name}
    if description:
        spec["description"] = description
    spec["tables"] = []

    for _, t in tables.iterrows():
        alias = t["TABLE_ALIAS"]
        entry = {
            "name": alias,
            "base_table": {
                "database": t["PHYSICAL_DATABASE"],
                "schema": t["PHYSICAL_SCHEMA"],
                "table": t["PHYSICAL_TABLE"],
            },
        }
        if t["DESCRIPTION"]:
            entry["description"] = t["DESCRIPTION"]
        if t["PRIMARY_KEY_COLS"]:
            entry["primary_key"] = {
                "columns": [c.strip() for c in t["PRIMARY_KEY_COLS"].split(",") if c.strip()]
            }

        t_dims = dims[dims["TABLE_ALIAS"] == alias] if not dims.empty else pd.DataFrame()
        if not t_dims.empty:
            entry["dimensions"] = []
            for _, d in t_dims.iterrows():
                item = {"name": d["DIMENSION_NAME"], "expr": d["EXPR"]}
                if d["DATA_TYPE"]:
                    item["data_type"] = d["DATA_TYPE"]
                if d["DESCRIPTION"]:
                    item["description"] = d["DESCRIPTION"]
                if d["SYNONYMS"]:
                    item["synonyms"] = [s.strip() for s in d["SYNONYMS"].split(",") if s.strip()]
                entry["dimensions"].append(item)

        t_facts = facts[facts["TABLE_ALIAS"] == alias] if not facts.empty else pd.DataFrame()
        if not t_facts.empty:
            entry["facts"] = []
            for _, f in t_facts.iterrows():
                item = {"name": f["FACT_NAME"], "expr": f["EXPR"]}
                if f["DATA_TYPE"]:
                    item["data_type"] = f["DATA_TYPE"]
                if f["DESCRIPTION"]:
                    item["description"] = f["DESCRIPTION"]
                entry["facts"].append(item)

        t_metrics = metrics[metrics["TABLE_ALIAS"] == alias] if not metrics.empty else pd.DataFrame()
        if not t_metrics.empty:
            entry["metrics"] = []
            for _, m in t_metrics.iterrows():
                item = {"name": m["METRIC_NAME"], "expr": m["EXPR"]}
                if m["DESCRIPTION"]:
                    item["description"] = m["DESCRIPTION"]
                entry["metrics"].append(item)

        spec["tables"].append(entry)

    if not rels.empty:
        spec["relationships"] = []
        for _, r in rels.iterrows():
            spec["relationships"].append({
                "name": r["RELATIONSHIP_NAME"],
                "left_table": r["LEFT_TABLE"],
                "right_table": r["RIGHT_TABLE"],
                "relationship_columns": [
                    {"left_column": r["LEFT_COLUMN"], "right_column": r["RIGHT_COLUMN"]}
                ],
                "relationship_type": r["RELATIONSHIP_TYPE"],
            })

    return yaml.dump(spec, sort_keys=False, default_flow_style=False), None


def save_version_yaml(pid, yaml_text, user):
    """Write the generated YAML into the current (mutable) version row."""
    run(f"""UPDATE {TOOL_PATH}.svt_versions
            SET yaml_content = '{esc(yaml_text)}', modified_by = '{esc(user)}'
            WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")


# ============================================================
# Sidebar: proposal selection
# ============================================================

user = current_user()
st.sidebar.title("Semantic View Builder")
st.sidebar.caption(f"Signed in as `{user}`")

my_props = df(f"""
    SELECT proposal_id, view_name, status, current_version_number
    FROM {TOOL_PATH}.svt_proposals
    WHERE owner = '{esc(user)}'
    ORDER BY updated_at DESC
""")

st.sidebar.divider()

# After creating a proposal, land straight in it rather than leaving the
# user on a form they've already finished with.
jump_pid = st.session_state.pop("jump_to_pid", None)

# Streamlit won't allow setting a widget's own session_state key AFTER
# that widget has already rendered in the same run -- even right before
# a rerun. So the button handlers below set a plain flag instead, and
# it's only applied to the radio's actual key here, before the radio
# widget is instantiated for this run.
forced_mode = st.session_state.pop("force_mode_next_run", None)
if forced_mode:
    st.session_state["mode_radio"] = forced_mode

mode_options = ["My proposals", "Start a new view", "Change a live view"]
mode = st.sidebar.radio("Mode", mode_options, index=0, key="mode_radio")

active_pid = None

if mode == "My proposals":
    if my_props.empty:
        st.sidebar.info("No proposals yet. Create one.")
    else:
        NONE_SENTINEL = "__none__"
        labels = {
            NONE_SENTINEL: "— Select a proposal to open —",
        }
        labels.update({
            r["PROPOSAL_ID"]: f"{r['VIEW_NAME']} (v{r['CURRENT_VERSION_NUMBER']}, {r['STATUS']})"
            for _, r in my_props.iterrows()
        })
        ids = list(labels.keys())
        # Default to the placeholder, so landing on the app shows the
        # submissions overview rather than opening something unasked.
        # After creating a proposal, jump_pid selects it instead.
        default_idx = ids.index(jump_pid) if jump_pid in ids else 0
        picked = st.sidebar.selectbox(
            "Open proposal", ids, index=default_idx, format_func=lambda x: labels[x],
            key="open_proposal_select",
        )
        active_pid = None if picked == NONE_SENTINEL else picked

elif mode == "Start a new view":
    st.sidebar.caption("Propose a semantic view that doesn't exist yet.")
    with st.sidebar.form("new_prop"):
        nv_name = st.text_input("Semantic view name").strip().upper()
        nv_desc = st.text_area("What is this view for?")
        if st.form_submit_button("Create draft") and nv_name:
            existing = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_proposals
                              WHERE UPPER(view_name) = '{esc(nv_name)}'
                                AND status != 'CLOSED'""")
            if existing["C"][0] > 0:
                st.sidebar.error(f"A proposal named {nv_name} already exists.")
            else:
                pid, vid = new_id(), new_id()
                run(f"""INSERT INTO {TOOL_PATH}.svt_proposals
                        (proposal_id, view_name, description, owner, status,
                         current_version_number, target_database)
                        VALUES ('{pid}', '{esc(nv_name)}', '{esc(nv_desc)}',
                                '{esc(user)}', 'DRAFT', 1, '{DEFAULT_TARGET_DB}')""")
                run(f"""INSERT INTO {TOOL_PATH}.svt_versions
                        (version_id, proposal_id, version_number, yaml_content,
                         modified_by, is_current)
                        VALUES ('{vid}', '{pid}', 1, '', '{esc(user)}', TRUE)""")
                st.sidebar.success(f"Draft created: {nv_name}")
                st.session_state["jump_to_pid"] = pid
                st.session_state["force_mode_next_run"] = "My proposals"
                st.rerun()

else:
    st.sidebar.caption(
        "Propose a change to a semantic view that is already live. "
        "The proposal starts empty -- rebuild the structure you want, "
        "and an engineer will review it as an update."
    )

    # Outside the form: changing environment must refresh the view list live.
    up_env = st.sidebar.radio("Which environment?", ["DEV", "PROD"], horizontal=True)
    up_schema = ENV_SCHEMAS[up_env]

    existing_views = []
    try:
        rows = session.sql(
            f"SHOW SEMANTIC VIEWS IN SCHEMA {DEFAULT_TARGET_DB}.{up_schema}"
        ).collect()
        existing_views = [_row_get(r.as_dict(), "name") for r in rows]
    except Exception:
        existing_views = []

    if not existing_views:
        st.sidebar.info(f"No live semantic views found in {up_env}.")
    else:
        with st.sidebar.form("update_prop"):
            up_view = st.selectbox("Semantic view to change", existing_views)
            if st.form_submit_button("Create update proposal") and up_view:
                pid, vid = new_id(), new_id()
                ref = f"{DEFAULT_TARGET_DB}.{up_schema}.{up_view}"
                run(f"""INSERT INTO {TOOL_PATH}.svt_proposals
                        (proposal_id, view_name, owner, status, current_version_number,
                         is_update_to_existing, existing_view_reference, target_database)
                        VALUES ('{pid}', '{esc(up_view)}', '{esc(user)}', 'DRAFT', 1,
                                TRUE, '{esc(ref)}', '{DEFAULT_TARGET_DB}')""")
                run(f"""INSERT INTO {TOOL_PATH}.svt_versions
                        (version_id, proposal_id, version_number, yaml_content,
                         modified_by, is_current)
                        VALUES ('{vid}', '{pid}', 1, '', '{esc(user)}', TRUE)""")
                st.sidebar.success(f"Update proposal created for {up_view}")
                st.session_state["jump_to_pid"] = pid
                st.session_state["force_mode_next_run"] = "My proposals"
                st.rerun()


# ============================================================
# My submissions (always visible)
# ============================================================

st.header("My submissions")

if my_props.empty:
    st.info("No proposals yet. Use the sidebar to create one.")
else:
    subs = df(f"""
        SELECT p.view_name AS "Name",
               p.status AS "Status",
               CASE
                 -- Nothing live anywhere
                 WHEN p.deployed_dev_version IS NULL
                  AND p.deployed_prod_version IS NULL
                   THEN CASE WHEN p.status = 'VALIDATED'
                             THEN 'Awaiting deployment' ELSE '—' END

                 -- Current version is live in both
                 WHEN p.deployed_dev_version  = p.current_version_number
                  AND p.deployed_prod_version = p.current_version_number
                   THEN 'Live in DEV & PROD'

                 -- Current version live in one env, nothing in the other
                 WHEN p.deployed_dev_version = p.current_version_number
                  AND p.deployed_prod_version IS NULL
                   THEN 'Live in DEV'
                 WHEN p.deployed_prod_version = p.current_version_number
                  AND p.deployed_dev_version IS NULL
                   THEN 'Live in PROD'

                 -- Current version live in one env, older version in the other
                 WHEN p.deployed_dev_version = p.current_version_number
                   THEN 'Live in DEV · v' || p.deployed_prod_version || ' in PROD'
                 WHEN p.deployed_prod_version = p.current_version_number
                   THEN 'Live in PROD · v' || p.deployed_dev_version || ' in DEV'

                 -- Current version live nowhere; older versions are out there
                 WHEN p.deployed_dev_version IS NOT NULL
                  AND p.deployed_prod_version IS NOT NULL
                   THEN 'v' || p.deployed_dev_version || ' in DEV, v'
                        || p.deployed_prod_version || ' in PROD · v'
                        || p.current_version_number || ' pending'
                 WHEN p.deployed_dev_version IS NOT NULL
                   THEN 'v' || p.deployed_dev_version || ' in DEV · v'
                        || p.current_version_number || ' pending'
                 ELSE 'v' || p.deployed_prod_version || ' in PROD · v'
                      || p.current_version_number || ' pending'
               END AS "Deployment",
               COALESCE(p.closed_reason, '—') AS "Closed reason",
               p.current_version_number AS "Ver",
               COALESCE(TO_VARCHAR(p.deployed_dev_version), '—') AS "Dev",
               COALESCE(TO_VARCHAR(p.deployed_prod_version), '—') AS "Prod",
               COALESCE(v.validator, '—') AS "Validated by",
               TO_VARCHAR(p.updated_at, 'DD Mon HH24:MI') AS "Last updated"
        FROM {TOOL_PATH}.svt_proposals p
        LEFT JOIN {TOOL_PATH}.svt_versions v
               ON p.proposal_id = v.proposal_id AND v.is_current = TRUE
        WHERE p.owner = '{esc(user)}'
        ORDER BY p.updated_at DESC
    """)
    st.dataframe(subs, use_container_width=True, hide_index=True)

    if not active_pid:
        st.caption("Pick a proposal in the sidebar to open it, or start a new one.")


# ============================================================
# Builder (only when a proposal is selected)
# ============================================================

if not active_pid:
    st.stop()

prop = df(f"SELECT * FROM {TOOL_PATH}.svt_proposals WHERE proposal_id = '{esc(active_pid)}'").iloc[0]
ver = df(f"""SELECT * FROM {TOOL_PATH}.svt_versions
             WHERE proposal_id = '{esc(active_pid)}' AND is_current = TRUE""").iloc[0]

status = prop["STATUS"]
editable = status in ("DRAFT", "SUBMITTED", "NEEDS_REVISION")

st.divider()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Proposal", prop["VIEW_NAME"])
c2.metric("Status", status)
c3.metric("Version", int(prop["CURRENT_VERSION_NUMBER"]))
c4.metric("Type", "Update" if prop["IS_UPDATE_TO_EXISTING"] else "New view")

if status == "NEEDS_REVISION" and ver["REVIEW_NOTES"]:
    st.warning(f"**Engineer notes:** {ver['REVIEW_NOTES']}")

if status == "VALIDATED":
    st.success(
        f"Validated by {ver['VALIDATOR']}. This version is frozen — "
        "any edit below will create a new version and return it for review."
    )

if status == "CLOSED":
    st.error(f"This proposal is closed ({prop['CLOSED_REASON']}). It cannot be edited.")
    st.stop()


def start_new_version_if_needed():
    """If the current version is frozen (validated), branch a new mutable one."""
    if status != "VALIDATED":
        return False
    new_num = int(prop["CURRENT_VERSION_NUMBER"]) + 1
    run(f"""UPDATE {TOOL_PATH}.svt_versions SET is_current = FALSE
            WHERE proposal_id = '{esc(active_pid)}' AND is_current = TRUE""")
    run(f"""INSERT INTO {TOOL_PATH}.svt_versions
            (version_id, proposal_id, version_number, yaml_content, modified_by, is_current)
            VALUES ('{new_id()}', '{esc(active_pid)}', {new_num},
                    '{esc(ver['YAML_CONTENT'] or '')}', '{esc(user)}', TRUE)""")
    run(f"""UPDATE {TOOL_PATH}.svt_proposals
            SET current_version_number = {new_num}, status = 'SUBMITTED',
                updated_at = CURRENT_TIMESTAMP()
            WHERE proposal_id = '{esc(active_pid)}'""")
    return True


tabs = st.tabs([
    "Info", "1. Tables", "2. Dimensions", "3. Facts",
    "4. Metrics", "5. Relationships", "6. Review & submit"
])

bt = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_tables WHERE proposal_id = '{esc(active_pid)}' ORDER BY created_at")
aliases = bt["TABLE_ALIAS"].tolist() if not bt.empty else []


def delete_button(table, item_id, label, key):
    """Render a delete control for one builder row."""
    if st.button("Delete", key=key, help=f"Remove {label}"):
        if start_new_version_if_needed():
            st.info("Created a new version for this change.")
        run(f"DELETE FROM {TOOL_PATH}.{table} WHERE item_id = '{esc(item_id)}'")
        touch_proposal(active_pid)
        st.rerun()


# ---------------- TAB 0: INFO ----------------
with tabs[0]:
    st.subheader("How this works")
    st.markdown("""
Building a proposal has six steps. Work through them in order, using the
tabs above:

1. **Tables** — Choose the data tables that hold what you need, and give
   each one a short name you'll use in every step below.
2. **Dimensions** — Pick the categories you'll want to group or filter
   by later — things like city, category, or brand.
3. **Facts** — Pick the raw numbers behind your data — quantity, price,
   amount. These aren't calculations yet, just the building blocks.
4. **Metrics** — Combine your facts into the actual numbers you want to
   see — total revenue, average order value, and so on.
5. **Relationships** — Tell us how your tables connect to each other.
   Once you've added at least two tables, we'll suggest likely
   connections automatically — you can accept or dismiss each one, or
   add your own.
6. **Review & submit** — Check everything looks right, then send it to
   a data engineer for review.

**What happens after you submit?** A data engineer reviews your
proposal. They may approve it, send it back with notes for you to fix,
or reject it — you'll see the status update in **My Submissions**, and
any notes will show right here when you reopen the proposal.
    """)


# ---------------- TAB 1: TABLES ----------------
with tabs[1]:
    st.subheader("Tables")
    st.caption(
        "Choose the tables that hold the data for this view, and give each "
        "one a name you'll use everywhere else in this proposal."
    )

    with st.expander("Browse table descriptions"):
        b_db = st.selectbox("Database", get_databases(), key="br_db")
        b_sc = st.selectbox("Schema", get_schemas(b_db) if b_db else [], key="br_sc")
        if b_sc:
            n, c = get_tables(b_db, b_sc)
            st.dataframe(
                pd.DataFrame({"Table": n, "Description": [c.get(x) or "—" for x in n]}),
                use_container_width=True, hide_index=True
            )

    if editable or status == "VALIDATED":
        col1, col2 = st.columns(2)
        t_db = col1.selectbox("Database", get_databases(), key="t_db",
                              help="Where the data lives in Snowflake")
        t_sc = col2.selectbox("Schema", get_schemas(t_db) if t_db else [], key="t_sc",
                              help="A folder inside the database")
        t_names, t_comments = get_tables(t_db, t_sc) if t_sc else ([], {})
        t_tbl = st.selectbox(
            "Select the table you want to add", t_names,
            format_func=fmt_with_comment(t_comments) if t_names else (lambda x: x),
            key="t_tbl"
        )
        t_cols, t_meta = get_columns(t_db, t_sc, t_tbl) if t_tbl else ([], {})

        pk_suggestion = suggest_primary_key(t_db, t_sc, t_tbl, t_cols) if t_tbl else []
        if pk_suggestion:
            st.caption(f"Suggested unique ID column: **{', '.join(pk_suggestion)}** -- remove it below if this isn't right.")
        elif t_tbl:
            st.caption("Couldn't guess a unique ID column for this table -- please choose one below.")

        with st.form("add_table"):
            alias = st.text_input(
                "Short name for this table (used everywhere else below)",
                t_tbl.upper() if t_tbl else "",
                help="This is how you'll refer to this table in Dimensions, Facts, Metrics, and Relationships"
            )
            pk = st.multiselect(
                "Unique ID column(s) for this table (Primary Key)", t_cols, default=pk_suggestion,
                help="The column (or columns) that uniquely identify one row -- e.g. an ID"
            )
            tdesc = st.text_area(
                "What does this table represent?",
                key=f"tdesc_{t_db}_{t_sc}_{t_tbl}"
            )
            if st.form_submit_button("Add table") and alias and t_tbl:
                if alias in aliases:
                    st.error(f"{alias} is already added.")
                else:
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    run(f"""INSERT INTO {TOOL_PATH}.svt_builder_tables
                            (item_id, proposal_id, table_alias, physical_database,
                             physical_schema, physical_table, primary_key_cols, description)
                            VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(alias)}',
                                    '{esc(t_db)}', '{esc(t_sc)}', '{esc(t_tbl)}',
                                    '{esc(",".join(pk))}', '{esc(tdesc)}')""")
                    touch_proposal(active_pid)
                    st.rerun()

    st.write("**Added tables**")
    if bt.empty:
        st.caption("None yet.")
    else:
        for _, r in bt.iterrows():
            a, b = st.columns([5, 1])
            a.markdown(
                f"**{r['TABLE_ALIAS']}** — `{r['PHYSICAL_DATABASE']}.{r['PHYSICAL_SCHEMA']}.{r['PHYSICAL_TABLE']}`  \n"
                f"PK: {r['PRIMARY_KEY_COLS'] or '—'}"
            )
            with b:
                dep_f = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_builder_facts
                               WHERE proposal_id = '{esc(active_pid)}'
                                 AND table_alias = '{esc(r['TABLE_ALIAS'])}'""")["C"][0]
                dep_d = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_builder_dimensions
                               WHERE proposal_id = '{esc(active_pid)}'
                                 AND table_alias = '{esc(r['TABLE_ALIAS'])}'""")["C"][0]
                dep_m = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_builder_metrics
                               WHERE proposal_id = '{esc(active_pid)}'
                                 AND table_alias = '{esc(r['TABLE_ALIAS'])}'""")["C"][0]
                dep_r = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_builder_relationships
                               WHERE proposal_id = '{esc(active_pid)}'
                                 AND (left_table = '{esc(r['TABLE_ALIAS'])}'
                                   OR right_table = '{esc(r['TABLE_ALIAS'])}')""")["C"][0]
                total = int(dep_f + dep_d + dep_m + dep_r)

                if st.button("Delete", key=f"del_t_{r['ITEM_ID']}"):
                    if total > 0:
                        st.session_state[f"confirm_t_{r['ITEM_ID']}"] = True
                    else:
                        run(f"DELETE FROM {TOOL_PATH}.svt_builder_tables WHERE item_id = '{esc(r['ITEM_ID'])}'")
                        touch_proposal(active_pid)
                        st.rerun()

            if st.session_state.get(f"confirm_t_{r['ITEM_ID']}"):
                st.warning(
                    f"Deleting **{r['TABLE_ALIAS']}** will also remove "
                    f"{int(dep_d)} dimension(s), {int(dep_f)} fact(s), "
                    f"{int(dep_m)} metric(s) and {int(dep_r)} relationship(s). "
                    "This cannot be undone."
                )
                y, n = st.columns(2)
                if y.button("Delete anyway", key=f"yes_t_{r['ITEM_ID']}"):
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    al = esc(r["TABLE_ALIAS"])
                    for tbl, cond in [
                        ("svt_builder_facts", f"table_alias = '{al}'"),
                        ("svt_builder_dimensions", f"table_alias = '{al}'"),
                        ("svt_builder_metrics", f"table_alias = '{al}'"),
                        ("svt_builder_relationships", f"left_table = '{al}' OR right_table = '{al}'"),
                    ]:
                        run(f"DELETE FROM {TOOL_PATH}.{tbl} WHERE proposal_id = '{esc(active_pid)}' AND ({cond})")
                    run(f"DELETE FROM {TOOL_PATH}.svt_builder_tables WHERE item_id = '{esc(r['ITEM_ID'])}'")
                    st.session_state.pop(f"confirm_t_{r['ITEM_ID']}", None)
                    touch_proposal(active_pid)
                    st.rerun()
                if n.button("Cancel", key=f"no_t_{r['ITEM_ID']}"):
                    st.session_state.pop(f"confirm_t_{r['ITEM_ID']}", None)
                    st.rerun()


# ---------------- TAB 2: DIMENSIONS ----------------
with tabs[2]:
    st.subheader("Dimensions")
    st.caption("Attributes you group or filter by — category, region, name, date.")

    if not aliases:
        st.info("Add a table first.")
    else:
        sel = st.selectbox("Table", aliases, key="d_tbl",
                           help="Which table this attribute comes from")
        row = bt[bt["TABLE_ALIAS"] == sel].iloc[0]
        cols, meta = get_columns(row["PHYSICAL_DATABASE"], row["PHYSICAL_SCHEMA"], row["PHYSICAL_TABLE"])

        # Outside the form: the data type is looked up from this selection,
        # and inside a form it would lag one interaction behind -- silently
        # storing the wrong type.
        dcol = st.selectbox(
            "Select the column you want to use", cols,
            format_func=fmt_with_comment(meta.get("comments", {})) if cols else (lambda x: x),
            key="d_col",
        )
        if dcol:
            st.caption(f"Type: `{meta.get('types', {}).get(dcol, 'unknown')}`")

        with st.form("add_dim"):
            dname = st.text_input(
                "Name for this dimension",
                help="What you'll call this when grouping or filtering",
                key=f"dname_{sel}_{dcol}"
            ).strip()
            ddesc = st.text_area("Description", key=f"ddesc_{sel}_{dcol}")
            dsyn = st.text_input("Synonyms (comma-separated, optional)",
                                 help="Other words people use for this, e.g. 'sales, turnover'",
                                 key=f"dsyn_{sel}_{dcol}")
            if st.form_submit_button("Add dimension") and dname and dcol:
                if start_new_version_if_needed():
                    st.info("Created a new version for this change.")
                dtype = meta.get("types", {}).get(dcol, "")
                run(f"""INSERT INTO {TOOL_PATH}.svt_builder_dimensions
                        (item_id, proposal_id, table_alias, dimension_name, expr,
                         data_type, description, synonyms)
                        VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(sel)}',
                                '{esc(dname)}', '{esc(dcol)}', '{esc(dtype)}',
                                '{esc(ddesc)}', '{esc(dsyn)}')""")
                touch_proposal(active_pid)
                st.rerun()

    bd = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_dimensions WHERE proposal_id = '{esc(active_pid)}' ORDER BY created_at")
    st.write("**Added dimensions**")
    if bd.empty:
        st.caption("None yet.")
    else:
        for _, r in bd.iterrows():
            a, b = st.columns([5, 1])
            a.markdown(f"**{r['DIMENSION_NAME']}** — `{r['TABLE_ALIAS']}.{r['EXPR']}`")
            with b:
                delete_button("svt_builder_dimensions", r["ITEM_ID"],
                              r["DIMENSION_NAME"], f"del_d_{r['ITEM_ID']}")


# ---------------- TAB 3: FACTS ----------------
with tabs[3]:
    st.subheader("Facts")
    st.caption(
        "Raw numbers behind this view -- quantity, price, amount -- that "
        "get added up in Metrics next."
    )

    if not aliases:
        st.info("Add a table first.")
    else:
        sel_f = st.selectbox("Table", aliases, key="f_tbl",
                             help="Which table this number comes from")
        row_f = bt[bt["TABLE_ALIAS"] == sel_f].iloc[0]
        cols_f, meta_f = get_columns(row_f["PHYSICAL_DATABASE"], row_f["PHYSICAL_SCHEMA"], row_f["PHYSICAL_TABLE"])

        # Outside the form: the suggested fact name below depends on this,
        # so it has to refresh as soon as the column changes.
        fcol = st.selectbox(
            "Select the column with the number you need", cols_f,
            format_func=fmt_with_comment(meta_f.get("comments", {})) if cols_f else (lambda x: x),
            key="f_col"
        )

        with st.form("add_fact"):
            default_name = f"{fcol.lower()}_fact" if fcol else ""
            fname = st.text_input(
                "Name for this number", default_name,
                help="Kept unique automatically so it doesn't get confused with a similar column on another table"
            ).strip()
            fdesc = st.text_area("Description", key=f"fdesc_{sel_f}_{fcol}")
            if st.form_submit_button("Add fact") and fname and fcol:
                if start_new_version_if_needed():
                    st.info("Created a new version for this change.")
                ftype = meta_f.get("types", {}).get(fcol, "")
                run(f"""INSERT INTO {TOOL_PATH}.svt_builder_facts
                        (item_id, proposal_id, table_alias, fact_name, expr,
                         data_type, description)
                        VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(sel_f)}',
                                '{esc(fname)}', '{esc(fcol)}', '{esc(ftype)}', '{esc(fdesc)}')""")
                touch_proposal(active_pid)
                st.rerun()

    bf = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_facts WHERE proposal_id = '{esc(active_pid)}' ORDER BY created_at")
    st.write("**Added facts**")
    if bf.empty:
        st.caption("None yet.")
    else:
        for _, r in bf.iterrows():
            a, b = st.columns([5, 1])
            a.markdown(f"**{r['FACT_NAME']}** — `{r['TABLE_ALIAS']}.{r['EXPR']}`")
            with b:
                used_by = df(f"""SELECT COUNT(*) AS c FROM {TOOL_PATH}.svt_builder_metrics
                                 WHERE proposal_id = '{esc(active_pid)}'
                                   AND target_fact = '{esc(r['FACT_NAME'])}'""")["C"][0]
                if st.button("Delete", key=f"del_f_{r['ITEM_ID']}"):
                    if int(used_by) > 0:
                        st.session_state[f"confirm_f_{r['ITEM_ID']}"] = True
                    else:
                        run(f"DELETE FROM {TOOL_PATH}.svt_builder_facts WHERE item_id = '{esc(r['ITEM_ID'])}'")
                        touch_proposal(active_pid)
                        st.rerun()

            if st.session_state.get(f"confirm_f_{r['ITEM_ID']}"):
                st.warning(
                    f"**{r['FACT_NAME']}** is used by {int(used_by)} metric(s). "
                    "Deleting it will leave those metrics broken."
                )
                y, n = st.columns(2)
                if y.button("Delete anyway", key=f"yes_f_{r['ITEM_ID']}"):
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    run(f"DELETE FROM {TOOL_PATH}.svt_builder_facts WHERE item_id = '{esc(r['ITEM_ID'])}'")
                    st.session_state.pop(f"confirm_f_{r['ITEM_ID']}", None)
                    touch_proposal(active_pid)
                    st.rerun()
                if n.button("Cancel", key=f"no_f_{r['ITEM_ID']}"):
                    st.session_state.pop(f"confirm_f_{r['ITEM_ID']}", None)
                    st.rerun()


# ---------------- TAB 4: METRICS ----------------
with tabs[4]:
    st.subheader("Metrics")
    st.caption(
        "Combine your facts into the numbers you actually want to see -- "
        "total revenue, average order value, and so on."
    )

    if bf.empty:
        st.info("Add at least one fact first.")
    else:
        sel_m = st.selectbox("Table", aliases, key="m_tbl")
        avail = bf[bf["TABLE_ALIAS"] == sel_m]["FACT_NAME"].tolist()

        # A revision counter, bumped after every successful add. Keying
        # fields by table alone wouldn't clear them between two adds from
        # the SAME table -- bumping this on success forces a fresh set of
        # widgets even when the table selection hasn't changed.
        m_rev = st.session_state.get(f"metric_rev_{active_pid}_{sel_m}", 0)
        mkey = lambda field: f"m_{field}_{sel_m}_{m_rev}"

        with st.form("add_metric"):
            mname = st.text_input(
                "Name for this metric",
                help="What you'll call this calculated number, e.g. total_revenue",
                key=mkey("name")
            ).strip()
            agg = st.selectbox(
                "How to combine the numbers",
                ["— Select —", "SUM", "AVG", "COUNT", "COUNT DISTINCT", "MIN", "MAX"],
                help="SUM adds them all up, AVG takes the average, COUNT counts rows",
                key=mkey("agg")
            )
            agg = None if agg == "— Select —" else agg
            tgt_options = ["— Select —"] + avail
            tgt = st.selectbox("Which number to use", tgt_options, key=mkey("tgt")) if avail else None
            tgt = None if tgt == "— Select —" else tgt
            custom = st.text_input(
                "Custom formula (optional — overrides the above)",
                help="For ratios or multi-step calculations. Reference the names you gave in Facts.",
                key=mkey("custom")
            )
            mdesc = st.text_area("Description", key=mkey("desc"))
            if st.form_submit_button("Add metric") and mname:
                if not custom and not (agg and tgt):
                    st.error("Pick both how to combine and which number, or enter a custom formula.")
                else:
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    if custom:
                        expr, agg_v, tgt_v = custom, "", ""
                    else:
                        inner = f"{sel_m}.{tgt}"
                        expr = (f"COUNT(DISTINCT {inner})" if agg == "COUNT DISTINCT"
                                else f"{agg}({inner})")
                        agg_v, tgt_v = agg, tgt
                    run(f"""INSERT INTO {TOOL_PATH}.svt_builder_metrics
                            (item_id, proposal_id, table_alias, metric_name,
                             agg_function, target_fact, expr, description)
                            VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(sel_m)}',
                                    '{esc(mname)}', '{esc(agg_v)}', '{esc(tgt_v)}',
                                    '{esc(expr)}', '{esc(mdesc)}')""")
                    touch_proposal(active_pid)
                    st.session_state[f"metric_rev_{active_pid}_{sel_m}"] = m_rev + 1
                    st.rerun()

    bm = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_metrics WHERE proposal_id = '{esc(active_pid)}' ORDER BY created_at")
    st.write("**Added metrics**")
    if bm.empty:
        st.caption("None yet.")
    else:
        for _, r in bm.iterrows():
            a, b = st.columns([5, 1])
            a.markdown(f"**{r['METRIC_NAME']}** — `{r['EXPR']}`")
            with b:
                delete_button("svt_builder_metrics", r["ITEM_ID"],
                              r["METRIC_NAME"], f"del_m_{r['ITEM_ID']}")


# ---------------- TAB 5: RELATIONSHIPS ----------------
with tabs[5]:
    st.subheader("Relationships")
    st.caption(
        "Relationships tell us how your tables connect to each other. "
        "Left = the table with many rows per match (usually your main "
        "table); Right = the table with one matching row (usually a "
        "reference table like customers or products)."
    )

    if len(aliases) < 2:
        st.info("Add at least two tables first.")
    else:
        br_existing = df(f"""SELECT left_table, right_table, left_column, right_column
                             FROM {TOOL_PATH}.svt_builder_relationships
                             WHERE proposal_id = '{esc(active_pid)}'""")
        existing_keys = set(
            (r["LEFT_TABLE"], r["RIGHT_TABLE"], r["LEFT_COLUMN"], r["RIGHT_COLUMN"])
            for _, r in br_existing.iterrows()
        ) if not br_existing.empty else set()
        dismissed = st.session_state.get(f"rel_dismissed_{active_pid}", set())

        raw_suggestions = suggest_relationships(bt)
        pending = [
            s for s in raw_suggestions
            if (s["left_table"], s["right_table"], s["left_column"], s["right_column"])
               not in existing_keys
            and (s["left_table"], s["right_table"], s["left_column"], s["right_column"])
               not in dismissed
        ]

        if pending:
            st.write("**Suggested, based on matching column names:**")
            for i, s in enumerate(pending):
                key = (s["left_table"], s["right_table"], s["left_column"], s["right_column"])
                a, b, c = st.columns([5, 1, 1])
                a.markdown(f"`{s['left_table']}.{s['left_column']}`  →  `{s['right_table']}.{s['right_column']}`")
                if b.button("Add", key=f"rel_add_{i}"):
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    rname = f"{s['left_table']}_to_{s['right_table']}".lower()
                    run(f"""INSERT INTO {TOOL_PATH}.svt_builder_relationships
                            (item_id, proposal_id, relationship_name, left_table,
                             right_table, left_column, right_column, relationship_type)
                            VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(rname)}',
                                    '{esc(s["left_table"])}', '{esc(s["right_table"])}',
                                    '{esc(s["left_column"])}', '{esc(s["right_column"])}',
                                    'many_to_one')""")
                    touch_proposal(active_pid)
                    st.rerun()
                if c.button("Dismiss", key=f"rel_dismiss_{i}"):
                    dismissed = dismissed | {key}
                    st.session_state[f"rel_dismissed_{active_pid}"] = dismissed
                    st.rerun()
            st.divider()

        st.write("**Add one manually:**")
        col_l, col_r = st.columns(2)
        lt = col_l.selectbox("Left table (the many side)", aliases, key="r_lt")
        rt = col_r.selectbox("Right table (the one side)", aliases, key="r_rt")

        lrow = bt[bt["TABLE_ALIAS"] == lt].iloc[0]
        rrow = bt[bt["TABLE_ALIAS"] == rt].iloc[0]
        lcols, lmeta = get_columns(lrow["PHYSICAL_DATABASE"], lrow["PHYSICAL_SCHEMA"], lrow["PHYSICAL_TABLE"])
        rcols, rmeta = get_columns(rrow["PHYSICAL_DATABASE"], rrow["PHYSICAL_SCHEMA"], rrow["PHYSICAL_TABLE"])

        lc = st.selectbox(
            "Matching column on the left table", lcols,
            format_func=fmt_with_comment(lmeta.get("comments", {})) if lcols else (lambda x: x),
            key="r_lc",
        )
        rc = st.selectbox(
            "Matching column on the right table", rcols,
            format_func=fmt_with_comment(rmeta.get("comments", {})) if rcols else (lambda x: x),
            key="r_rc",
        )

        with st.form("add_rel"):
            rname = st.text_input("Name for this relationship", f"{lt}_to_{rt}".lower()).strip()
            rtype = st.selectbox("Type", ["many_to_one", "one_to_one"],
                                 help="many_to_one is by far the most common")
            if st.form_submit_button("Add relationship") and rname:
                if lt == rt:
                    st.error("Left and right tables must differ.")
                else:
                    if start_new_version_if_needed():
                        st.info("Created a new version for this change.")
                    run(f"""INSERT INTO {TOOL_PATH}.svt_builder_relationships
                            (item_id, proposal_id, relationship_name, left_table,
                             right_table, left_column, right_column, relationship_type)
                            VALUES ('{new_id()}', '{esc(active_pid)}', '{esc(rname)}',
                                    '{esc(lt)}', '{esc(rt)}', '{esc(lc)}',
                                    '{esc(rc)}', '{esc(rtype)}')""")
                    touch_proposal(active_pid)
                    st.rerun()

    br = df(f"SELECT * FROM {TOOL_PATH}.svt_builder_relationships WHERE proposal_id = '{esc(active_pid)}' ORDER BY created_at")
    st.write("**Added relationships**")
    if br.empty:
        st.caption("None yet.")
    else:
        for _, r in br.iterrows():
            a, b = st.columns([5, 1])
            a.markdown(
                f"**{r['RELATIONSHIP_NAME']}** — "
                f"`{r['LEFT_TABLE']}.{r['LEFT_COLUMN']}` → `{r['RIGHT_TABLE']}.{r['RIGHT_COLUMN']}`"
            )
            with b:
                delete_button("svt_builder_relationships", r["ITEM_ID"],
                              r["RELATIONSHIP_NAME"], f"del_r_{r['ITEM_ID']}")


# ---------------- TAB 6: REVIEW & SUBMIT ----------------
with tabs[6]:
    st.subheader("Review and submit")

    y1, y2, y3, y4, y5 = (len(bt), len(bd), len(bf), len(bm), len(br))
    m = st.columns(5)
    m[0].metric("Tables", y1)
    m[1].metric("Dimensions", y2)
    m[2].metric("Facts", y3)
    m[3].metric("Metrics", y4)
    m[4].metric("Relationships", y5)

    problems = []
    if y1 == 0:
        problems.append("No tables added.")
    if y2 == 0 and y3 == 0:
        problems.append("Add at least one dimension or fact.")
    if y1 > 1 and y5 == 0:
        problems.append(f"{y1} tables added but no relationships defined — they won't be joinable.")

    if problems:
        for p in problems:
            st.warning(p)

    yaml_text, err = generate_yaml(active_pid, prop["VIEW_NAME"], prop["DESCRIPTION"])
    if err:
        st.error(err)
    else:
        st.code(yaml_text, language="yaml")
        st.caption(
            "This is what an engineer will review. It's generated from your "
            "selections -- no need to edit it directly."
        )

        if status in ("DRAFT", "NEEDS_REVISION"):
            if st.button("Submit for review", type="primary", disabled=bool(problems)):
                save_version_yaml(active_pid, yaml_text, user)
                run(f"""UPDATE {TOOL_PATH}.svt_proposals
                        SET status = 'SUBMITTED', updated_at = CURRENT_TIMESTAMP()
                        WHERE proposal_id = '{esc(active_pid)}'""")
                st.success("Submitted for review.")
                st.rerun()

        elif status == "SUBMITTED":
            st.info("Submitted and awaiting engineer review.")
            if st.button("Save changes"):
                save_version_yaml(active_pid, yaml_text, user)
                touch_proposal(active_pid)
                st.success("Saved.")
            st.divider()
            if st.button("Revoke submission"):
                run(f"""UPDATE {TOOL_PATH}.svt_proposals
                        SET status = 'CLOSED', closed_reason = 'WITHDRAWN',
                            updated_at = CURRENT_TIMESTAMP()
                        WHERE proposal_id = '{esc(active_pid)}'""")
                st.warning("Submission revoked.")
                st.rerun()

        elif status == "VALIDATED":
            if st.button("Save changes as new version"):
                start_new_version_if_needed()
                latest = df(f"""SELECT * FROM {TOOL_PATH}.svt_versions
                                WHERE proposal_id = '{esc(active_pid)}' AND is_current = TRUE""").iloc[0]
                save_version_yaml(active_pid, yaml_text, user)
                st.success(f"Created version {int(latest['VERSION_NUMBER'])} and returned it for review.")
                st.rerun()