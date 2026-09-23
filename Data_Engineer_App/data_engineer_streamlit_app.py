import streamlit as st
import pandas as pd
import uuid
import re
from snowflake.snowpark.context import get_active_session

session = get_active_session()

TOOL_DB = "TASTY_BYTES_DB"
TOOL_SCHEMA = "SEMANTIC_TOOL"
TOOL_PATH = f"{TOOL_DB}.{TOOL_SCHEMA}"

DEFAULT_TARGET_DB = "TASTY_BYTES_DB"
ENV_SCHEMAS = {"DEV": "DEV", "PROD": "PROD"}

MACRO_LINE = "{{ config(materialized='semantic_view_yaml') }}"

# The Git-connected workspace holding the dbt project, and the folder
# inside it where semantic view model files live. Confirmed working via
# COPY FILES against snow://workspace/... -- writes register as tracked
# changes (marked "A") in that workspace's own Changes tab, same as a
# manual edit through the editor.
#
# IMPORTANT: must use the literal personal database name ("USER$<name>"),
# not the bare USER$ alias -- USER$ alone resolves contextually to
# whoever's session is running the query, which is the Streamlit service
# identity here, not the actual engineer. Built from current_user() below,
# since each engineer clones the same repo into their own personal
# workspace -- "who's using the app" and "whose workspace this is" are the
# same person by design, not a coincidence specific to one user.
WORKSPACE_NAME = "snowflake-dbt-semantic-view"
WORKSPACE_MODEL_FOLDER = "DBT_SEMANTIC_POC/tasty_bytes_dbt/models/semantic_view"
WORKSPACE_PROJECT_FOLDER = "DBT_SEMANTIC_POC/tasty_bytes_dbt"

# Created once, manually, by any engineer, in a worksheet -- not by this
# app. A normal schema-level object: unlike the workspace, any role with
# access to this schema can ADD VERSION / EXECUTE it, sidestepping the
# "must be the workspace owner" restriction that blocks running directly
# FROM WORKSPACE from a service identity.
DBT_PROJECT_OBJECT = f"{TOOL_PATH}.tasty_bytes_dbt_deploy"


def workspace_path(engineer_username):
    return f'"USER${engineer_username}".PUBLIC."{WORKSPACE_NAME}"'

st.set_page_config(page_title="Semantic View Review", layout="wide")


# ============================================================
# Helpers
# ============================================================

def current_user():
    """The engineer viewing the app.

    CURRENT_USER() returns the Streamlit service identity in a deployed app
    (and it changes between deployments), so st.user is the reliable source.
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
    """Case/quote-insensitive lookup -- SHOW/DESC column casing varies."""
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


def validate_yaml(yaml_text, target_schema_fqn):
    """Dry run -- checks the YAML without creating anything.

    This is a stored procedure, so it needs CALL (not SELECT) -- the same
    form used in the dbt semantic_view_yaml materialization macro. The
    third argument TRUE is the dry-run flag.
    """
    try:
        res = session.sql(
            "CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(?, ?, TRUE)",
            params=[target_schema_fqn, yaml_text],
        ).collect()
        return True, (res[0][0] if res else "Valid.")
    except Exception as e:
        return False, str(e)


def merge_verified_queries(yaml_text, vq_df):
    """Return yaml_text with its verified_queries block replaced by vq_df.

    Done as text manipulation rather than parse/re-dump so the engineer's
    formatting, comments and key ordering survive untouched -- a round trip
    through a YAML parser would silently rewrite all of it.
    """
    lines = yaml_text.split("\n")

    # Strip an existing top-level verified_queries block, if present.
    out, skipping = [], False
    for ln in lines:
        if ln.startswith("verified_queries:"):
            skipping = True
            continue
        if skipping:
            # The block ends at the next top-level key (no leading whitespace).
            if ln.strip() and not ln[0].isspace():
                skipping = False
            else:
                continue
        out.append(ln)

    while out and not out[-1].strip():
        out.pop()

    if vq_df.empty:
        return "\n".join(out) + "\n"

    out.append("verified_queries:")
    for _, v in vq_df.iterrows():
        sql_one_line = " ".join(str(v["SQL_TEXT"]).split())
        out.append(f"  - name: {v['QUERY_NAME']}")
        out.append(f"    question: {yaml_quote(v['QUESTION'])}")
        out.append(f"    sql: {yaml_quote(sql_one_line)}")

    return "\n".join(out) + "\n"


def yaml_quote(s):
    """Double-quote a scalar for YAML, escaping what needs escaping."""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def workspace_file_exists(model_name, engineer_username):
    target_dir = f"snow://workspace/{workspace_path(engineer_username)}/versions/live/{WORKSPACE_MODEL_FOLDER}"
    try:
        rows = session.sql(f"LIST '{target_dir}/{model_name}.sql'").collect()
        return len(rows) > 0
    except Exception:
        # If LIST itself fails, don't block the write on an unrelated error --
        # let add_to_workspace's own try/except surface the real problem.
        return False


def add_to_workspace(model_name, file_body, engineer_username):
    """Write a dbt model file directly into the engineer's own Git-connected
    workspace (each engineer clones the same repo into their own personal
    workspace, so this always targets the caller's own clone -- never a
    fixed, hardcoded person's).

    Uses session.file.put_stream to write bytes directly to the stage --
    NOT `COPY INTO @stage FROM (SELECT '...')`. That first version used
    CSV file format, which backslash-escapes every comma and newline it
    finds inside the field (since FIELD_OPTIONALLY_ENCLOSED_BY = NONE
    leaves no quote-enclosure to protect them) -- corrupting exactly the
    content we're trying to write, since a multi-line YAML file is full
    of both. put_stream has no format/delimiter concept at all: it writes
    the exact bytes given, with nothing to escape.

    Confirmed separately: files landing in the workspace's live version
    this way show up in its own Changes tab as a normal tracked addition
    (marked "A"), identical to a manual save through the editor.
    Committing and pushing stays a manual step in the workspace UI --
    that decision should stay with a human, not be automated away.
    """
    import io

    stage = f"{TOOL_PATH}.tmp_ws_write"
    run(f"CREATE STAGE IF NOT EXISTS {stage}")
    filename = f"{model_name}.sql"

    session.file.put_stream(
        io.BytesIO(file_body.encode("utf-8")),
        f"@{stage}/{filename}",
        auto_compress=False,
        overwrite=True,
    )

    target = f"snow://workspace/{workspace_path(engineer_username)}/versions/live/{WORKSPACE_MODEL_FOLDER}/"
    run(f"COPY FILES INTO '{target}' FROM @{stage}/{filename}")
    return target + filename


def sync_and_run(engineer_username, model_name, target_env):
    """Refresh the shared DBT PROJECT object from the CALLING engineer's own
    workspace (dynamic -- never hardcoded, since the object is shared and
    the last person to sync determines what it currently holds), then run
    dbt against it for one environment.

    Returns (success, output_text). EXECUTE DBT PROJECT returns three
    columns: SUCCESS (bool), EXCEPTION (text or null), STDOUT (the dbt
    CLI output, confirmed via a direct worksheet test -- not guessed).
    SUCCESS is trusted as the primary signal; the dbt-reported error
    count in STDOUT is checked too, as a belt-and-suspenders sanity check
    in case SUCCESS and an individual model failure ever disagree.
    """
    ws_project_source = f"snow://workspace/{workspace_path(engineer_username)}/versions/live/{WORKSPACE_PROJECT_FOLDER}"

    run(f"""ALTER DBT PROJECT {DBT_PROJECT_OBJECT}
            ADD VERSION FROM '{ws_project_source}'""")

    args = f"run --target {target_env.lower()} --select models/semantic_view/{model_name}.sql"
    result = session.sql(
        f"EXECUTE DBT PROJECT {DBT_PROJECT_OBJECT} ARGS = '{args}'"
    ).collect()

    if not result:
        return False, "EXECUTE DBT PROJECT returned no result."

    row = result[0].as_dict()
    success = bool(row.get("SUCCESS"))
    exception_text = row.get("EXCEPTION")
    stdout_text = row.get("STDOUT") or ""

    # dbt's CLI output carries ANSI color codes (e.g. \x1b[32m) meant for
    # a terminal -- strip them so st.code() shows plain, readable text.
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", stdout_text)

    if not success:
        detail = exception_text or "EXECUTE DBT PROJECT reported failure."
        return False, detail + ("\n\n" + clean_output if clean_output else "")

    if "ERROR=" in clean_output:
        error_count = clean_output.split("ERROR=")[1].split()[0].rstrip(".")
        if error_count.strip("0") != "":
            return False, clean_output

    return True, clean_output


def touch(pid):
    run(f"UPDATE {TOOL_PATH}.svt_proposals SET updated_at = CURRENT_TIMESTAMP() "
        f"WHERE proposal_id = '{esc(pid)}'")


def current_version_row(pid):
    d = df(f"""SELECT * FROM {TOOL_PATH}.svt_versions
               WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")
    return None if d.empty else d.iloc[0]


def bump_version(pid, yaml_text, user, note=""):
    """Freeze the current version and open a new mutable one carrying yaml_text."""
    prop = df(f"SELECT * FROM {TOOL_PATH}.svt_proposals WHERE proposal_id = '{esc(pid)}'").iloc[0]
    new_num = int(prop["CURRENT_VERSION_NUMBER"]) + 1
    run(f"""UPDATE {TOOL_PATH}.svt_versions SET is_current = FALSE
            WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")
    run(f"""INSERT INTO {TOOL_PATH}.svt_versions
            (version_id, proposal_id, version_number, yaml_content, modified_by,
             review_notes, is_current)
            VALUES ('{new_id()}', '{esc(pid)}', {new_num}, '{esc(yaml_text)}',
                    '{esc(user)}', '{esc(note)}', TRUE)""")
    run(f"""UPDATE {TOOL_PATH}.svt_proposals
            SET current_version_number = {new_num}, updated_at = CURRENT_TIMESTAMP()
            WHERE proposal_id = '{esc(pid)}'""")
    return new_num


user = current_user()
st.sidebar.title("Semantic View Review")
st.sidebar.caption(f"Engineer: `{user}`")

counts = df(f"""
    SELECT
      SUM(IFF(status = 'SUBMITTED', 1, 0)) AS q,
      SUM(IFF(status = 'VALIDATED'
              AND (deployed_dev_version IS NULL
                   OR deployed_dev_version < current_version_number
                   OR deployed_prod_version IS NULL
                   OR deployed_prod_version < current_version_number), 1, 0)) AS v,
      SUM(IFF(deployed_dev_version IS NOT NULL
              OR deployed_prod_version IS NOT NULL, 1, 0)) AS d
    FROM {TOOL_PATH}.svt_proposals
""")
n_queue = int(counts["Q"][0] or 0)
n_val = int(counts["V"][0] or 0)
n_dep = int(counts["D"][0] or 0)

page = st.sidebar.radio(
    "View",
    [f"Review queue ({n_queue})",
     f"Ready to deploy ({n_val})",
     f"Deployed ({n_dep})"],
)


# ============================================================
# PAGE 1: REVIEW QUEUE
# ============================================================

if page.startswith("Review queue"):
    st.header("Review queue")

    q = df(f"""
        SELECT p.proposal_id, p.view_name, p.owner, p.description,
               p.current_version_number, p.is_update_to_existing,
               p.existing_view_reference, p.updated_at,
               v.yaml_content, v.modified_by, v.review_notes
        FROM {TOOL_PATH}.svt_proposals p
        JOIN {TOOL_PATH}.svt_versions v
          ON p.proposal_id = v.proposal_id AND v.is_current = TRUE
        WHERE p.status = 'SUBMITTED'
        ORDER BY p.updated_at
    """)

    if q.empty:
        st.info("Nothing awaiting review.")
        st.stop()

    labels = {
        r["PROPOSAL_ID"]: f"{r['VIEW_NAME']} — {r['OWNER']} (v{r['CURRENT_VERSION_NUMBER']})"
        for _, r in q.iterrows()
    }
    pid = st.selectbox("Proposal", list(labels.keys()), format_func=lambda x: labels[x])
    row = q[q["PROPOSAL_ID"] == pid].iloc[0]

    c = st.columns(4)
    c[0].metric("View", row["VIEW_NAME"])
    c[1].metric("Owner", row["OWNER"])
    c[2].metric("Version", int(row["CURRENT_VERSION_NUMBER"]))
    c[3].metric("Type", "Update" if row["IS_UPDATE_TO_EXISTING"] else "New view")

    if row["DESCRIPTION"]:
        st.caption(f"**Purpose:** {row['DESCRIPTION']}")
    if row["IS_UPDATE_TO_EXISTING"] and row["EXISTING_VIEW_REFERENCE"]:
        st.info(f"Proposed update to live view: `{row['EXISTING_VIEW_REFERENCE']}`")
    if row["REVIEW_NOTES"]:
        st.caption(f"_Earlier notes: {row['REVIEW_NOTES']}_")

    st.divider()

    tab_yaml, tab_vq, tab_hist = st.tabs(["YAML", "Verified queries", "Version history"])

    # ---------- YAML review + inline edit ----------
    with tab_yaml:
        st.caption(
            "Edit inline if needed. Editing and validating in one go keeps the "
            "same version -- it does not bounce back to the business user."
        )

        # If verified queries were just merged, show that version instead of
        # what's stored, until it's validated and approved.
        pending = st.session_state.get(f"pending_yaml_{pid}")
        if pending:
            st.info(
                "Verified queries have been merged into the YAML below but are "
                "**not saved yet**. Re-run validation, then approve to save."
            )

        # The key carries a revision counter. Bumping it on merge makes
        # Streamlit treat this as a new widget, which is the only reliable
        # way to force it to take a new value -- clearing the old key doesn't
        # work here because this tab renders before the merge button runs.
        rev = st.session_state.get(f"yamlrev_{pid}", 0)
        edited = st.text_area(
            "Semantic view YAML",
            pending if pending else row["YAML_CONTENT"],
            height=420,
            key=f"yaml_{pid}_{rev}",
        )
        changed = edited != row["YAML_CONTENT"]
        if changed and not pending:
            st.warning("Unsaved edits. Validating will save them to this version.")

        # Validation is environment-independent here: the YAML carries fully
        # qualified base_table references, so the schema argument only says
        # where the object would be created, not what gets checked.
        target_fqn = f"{DEFAULT_TARGET_DB}.{ENV_SCHEMAS['DEV']}"

        if st.button("Run validation", type="primary"):
            ok, msg = validate_yaml(edited, target_fqn)
            st.session_state[f"val_{pid}"] = (ok, msg, edited)

        if f"val_{pid}" in st.session_state:
            ok, msg, validated_text = st.session_state[f"val_{pid}"]
            if ok:
                st.success(f"Validation passed. {msg}")
            else:
                st.error(f"Validation failed:\n\n{msg}")

            st.divider()
            a, b, c2 = st.columns(3)

            with a:
                if st.button("Approve", type="primary", disabled=not ok,
                             help="Marks this version validated and ready to deploy"):
                    run(f"""UPDATE {TOOL_PATH}.svt_versions
                            SET yaml_content = '{esc(validated_text)}',
                                modified_by = '{esc(user)}',
                                validator = '{esc(user)}',
                                validated_at = CURRENT_TIMESTAMP()
                            WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")
                    run(f"""UPDATE {TOOL_PATH}.svt_proposals
                            SET status = 'VALIDATED', updated_at = CURRENT_TIMESTAMP()
                            WHERE proposal_id = '{esc(pid)}'""")
                    st.session_state.pop(f"val_{pid}", None)
                    st.session_state.pop(f"pending_yaml_{pid}", None)
                    st.session_state.pop(f"yamlrev_{pid}", None)
                    st.success("Approved.")
                    st.rerun()

            with b:
                with st.popover("Send back"):
                    note_b = st.text_area("What needs changing?", key=f"sb_{pid}")
                    if st.button("Confirm send back", key=f"sbc_{pid}") and note_b.strip():
                        run(f"""UPDATE {TOOL_PATH}.svt_versions
                                SET review_notes = '{esc(note_b)}'
                                WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")
                        run(f"""UPDATE {TOOL_PATH}.svt_proposals
                                SET status = 'NEEDS_REVISION', updated_at = CURRENT_TIMESTAMP()
                                WHERE proposal_id = '{esc(pid)}'""")
                        st.session_state.pop(f"val_{pid}", None)
                        st.session_state.pop(f"pending_yaml_{pid}", None)
                        st.session_state.pop(f"yamlrev_{pid}", None)
                        st.rerun()

            with c2:
                with st.popover("Reject"):
                    st.caption("Closes this proposal permanently.")
                    note_r = st.text_area("Reason", key=f"rj_{pid}")
                    if st.button("Confirm reject", key=f"rjc_{pid}") and note_r.strip():
                        run(f"""UPDATE {TOOL_PATH}.svt_versions
                                SET review_notes = '{esc(note_r)}'
                                WHERE proposal_id = '{esc(pid)}' AND is_current = TRUE""")
                        run(f"""UPDATE {TOOL_PATH}.svt_proposals
                                SET status = 'CLOSED', closed_reason = 'REJECTED',
                                    updated_at = CURRENT_TIMESTAMP()
                                WHERE proposal_id = '{esc(pid)}'""")
                        st.session_state.pop(f"val_{pid}", None)
                        st.session_state.pop(f"pending_yaml_{pid}", None)
                        st.session_state.pop(f"yamlrev_{pid}", None)
                        st.rerun()

    # ---------- Verified queries (engineer-only) ----------
    with tab_vq:
        st.caption(
            "Verified queries pin an exact answer to an exact question. "
            "Three rules, all enforced by Snowflake and easy to get wrong: "
            "reference **logical tables** (not the semantic view name), use "
            "**declared fact/dimension names** (not raw columns), and use "
            "**plain SQL aggregates** -- `AGG()` is not valid here."
        )

        vqs = df(f"""SELECT * FROM {TOOL_PATH}.svt_builder_verified_queries
                     WHERE proposal_id = '{esc(pid)}' ORDER BY created_at""")

        with st.form(f"add_vq_{pid}"):
            vq_name = st.text_input("Name (identifier)").strip()
            vq_q = st.text_input("Question a user would ask")
            vq_sql = st.text_area(
                "SQL",
                placeholder=(
                    "SELECT dim_menu.truck_brand_name,\n"
                    "       SUM(fct_order_detail.line_total_fact) AS total_revenue\n"
                    "FROM fct_order_detail\n"
                    "JOIN dim_menu ON fct_order_detail.menu_item_id = dim_menu.menu_item_id\n"
                    "GROUP BY dim_menu.truck_brand_name"
                ),
                height=150,
            )
            if st.form_submit_button("Add verified query") and vq_name and vq_q and vq_sql:
                bad = []
                if "AGG(" in vq_sql.upper():
                    bad.append("Uses AGG() -- not valid in verified queries.")
                if row["VIEW_NAME"].upper() in vq_sql.upper():
                    bad.append(
                        f"References the semantic view name ({row['VIEW_NAME']}). "
                        "Reference the logical tables instead."
                    )
                if bad:
                    for b_ in bad:
                        st.error(b_)
                else:
                    run(f"""INSERT INTO {TOOL_PATH}.svt_builder_verified_queries
                            (item_id, proposal_id, query_name, question, sql_text)
                            VALUES ('{new_id()}', '{esc(pid)}', '{esc(vq_name)}',
                                    '{esc(vq_q)}', '{esc(vq_sql)}')""")
                    st.rerun()

        st.write("**Added verified queries**")
        if vqs.empty:
            st.caption("None. Optional -- add them for questions that must always "
                       "return the same answer.")
        else:
            # These are saved to the proposal immediately, but that's separate
            # from being present in the YAML -- make the difference visible.
            live_yaml = st.session_state.get(f"pending_yaml_{pid}", row["YAML_CONTENT"]) or ""
            in_yaml = [n for n in vqs["QUERY_NAME"] if f"name: {n}" in live_yaml]
            if len(in_yaml) == len(vqs):
                st.success(f"All {len(vqs)} saved and present in the YAML.")
            elif in_yaml:
                st.warning(
                    f"{len(in_yaml)} of {len(vqs)} are in the YAML. "
                    "Press **Add to YAML** to include the rest."
                )
            else:
                st.warning(
                    f"{len(vqs)} saved to this proposal but **not yet in the YAML**. "
                    "Press **Add to YAML** below."
                )
            for _, v in vqs.iterrows():
                x, y = st.columns([6, 1])
                x.markdown(f"**{v['QUERY_NAME']}** — _{v['QUESTION']}_")
                x.code(v["SQL_TEXT"], language="sql")
                if y.button("Delete", key=f"delvq_{v['ITEM_ID']}"):
                    run(f"DELETE FROM {TOOL_PATH}.svt_builder_verified_queries "
                        f"WHERE item_id = '{esc(v['ITEM_ID'])}'")
                    st.rerun()

            st.divider()
            st.caption(
                "Merging replaces any existing `verified_queries:` block in the "
                "YAML with the queries above. Nothing is saved to the database "
                "until you re-validate and approve on the YAML tab."
            )
            if st.button("Add to YAML", type="primary", key=f"merge_{pid}"):
                rev = st.session_state.get(f"yamlrev_{pid}", 0)
                base = st.session_state.get(f"yaml_{pid}_{rev}", row["YAML_CONTENT"])
                merged = merge_verified_queries(base, vqs)
                # Stage the merged YAML and clear any prior validation result,
                # so Approve cannot be pressed against a stale check.
                st.session_state[f"pending_yaml_{pid}"] = merged
                st.session_state.pop(f"val_{pid}", None)
                # New key -> fresh widget -> it will actually show the merge.
                st.session_state[f"yamlrev_{pid}"] = rev + 1
                st.success(
                    f"Merged {len(vqs)} verified query(ies) into the YAML. "
                    "Go to the YAML tab, re-run validation, then approve."
                )
                st.rerun()

    # ---------- Version history ----------
    with tab_hist:
        hist = df(f"""SELECT version_number AS "Version", modified_by AS "Modified by",
                             validator AS "Validated by", validated_at AS "Validated at",
                             review_notes AS "Notes", is_current AS "Current",
                             created_at AS "Created"
                      FROM {TOOL_PATH}.svt_versions
                      WHERE proposal_id = '{esc(pid)}'
                      ORDER BY version_number DESC""")
        st.dataframe(hist, use_container_width=True, hide_index=True)

        vnums = df(f"""SELECT version_number FROM {TOOL_PATH}.svt_versions
                       WHERE proposal_id = '{esc(pid)}'
                       ORDER BY version_number DESC""")["VERSION_NUMBER"].tolist()
        if len(vnums) > 1:
            pick = st.selectbox("View YAML from version", vnums)
            old = df(f"""SELECT yaml_content FROM {TOOL_PATH}.svt_versions
                         WHERE proposal_id = '{esc(pid)}' AND version_number = {int(pick)}""")
            st.code(old["YAML_CONTENT"][0], language="yaml")


# ============================================================
# PAGE 2: READY TO DEPLOY
# ============================================================

elif page.startswith("Ready to deploy"):
    st.header("Ready to deploy")
    st.caption("Validated proposals not yet live, or live on an older version.")

    rd = df(f"""
        SELECT p.proposal_id, p.view_name, p.owner, p.current_version_number,
               p.deployed_dev_version, p.deployed_prod_version, p.target_database,
               v.validator, v.validated_at
        FROM {TOOL_PATH}.svt_proposals p
        JOIN {TOOL_PATH}.svt_versions v
          ON p.proposal_id = v.proposal_id AND v.is_current = TRUE
        WHERE p.status = 'VALIDATED'
          AND v.validator IS NOT NULL
          AND (p.deployed_dev_version  IS NULL OR p.deployed_dev_version  < p.current_version_number
            OR p.deployed_prod_version IS NULL OR p.deployed_prod_version < p.current_version_number)
        ORDER BY v.validated_at
    """)

    if rd.empty:
        st.info("Nothing ready to deploy.")
        st.stop()

    show = rd[["VIEW_NAME", "OWNER", "CURRENT_VERSION_NUMBER",
               "DEPLOYED_DEV_VERSION", "DEPLOYED_PROD_VERSION", "VALIDATOR"]].copy()
    show.columns = ["View", "Owner", "Validated version", "Live in dev", "Live in prod", "Validated by"]
    show = show.fillna("—")
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.divider()

    labels = {r["PROPOSAL_ID"]: f"{r['VIEW_NAME']} (v{r['CURRENT_VERSION_NUMBER']})"
              for _, r in rd.iterrows()}
    pid = st.selectbox("Deploy which proposal?", list(labels.keys()),
                       format_func=lambda x: labels[x])
    prop = rd[rd["PROPOSAL_ID"] == pid].iloc[0]

    # Only validated versions are deployable -- an unreviewed version must
    # never reach an environment.
    deployable = df(f"""
        SELECT version_number, validator, validated_at, yaml_content
        FROM {TOOL_PATH}.svt_versions
        WHERE proposal_id = '{esc(pid)}' AND validator IS NOT NULL
        ORDER BY version_number DESC
    """)

    if deployable.empty:
        st.error("No validated versions for this proposal.")
        st.stop()

    # Outside any form: the file preview below depends on these.
    vlabels = {
        int(r["VERSION_NUMBER"]):
            f"v{int(r['VERSION_NUMBER'])} — validated by {r['VALIDATOR']}"
            + (" (current)" if int(r["VERSION_NUMBER"]) == int(prop["CURRENT_VERSION_NUMBER"]) else "")
        for _, r in deployable.iterrows()
    }
    chosen_v = st.selectbox("Version to deploy", list(vlabels.keys()),
                            format_func=lambda x: vlabels[x])
    if chosen_v < int(prop["CURRENT_VERSION_NUMBER"]):
        st.warning(f"v{chosen_v} is older than the current validated version "
                   f"(v{int(prop['CURRENT_VERSION_NUMBER'])}) -- this is a rollback.")

    tgt_db = st.selectbox(
        "Target database", get_databases(),
        index=get_databases().index(prop["TARGET_DATABASE"])
        if prop["TARGET_DATABASE"] in get_databases() else 0,
    )

    yaml_text = deployable[deployable["VERSION_NUMBER"] == chosen_v]["YAML_CONTENT"].iloc[0]
    model_name = prop["VIEW_NAME"].lower()
    file_body = f"{MACRO_LINE}\n{yaml_text}"

    st.divider()
    st.subheader("dbt model file")
    st.caption(
        f"This becomes `models/semantic_view/{model_name}.sql`. Use **Add to "
        "Workspace** to write it directly, or **Download** to add it yourself."
    )
    st.code(file_body, language="yaml")

    b1, b2 = st.columns(2)
    with b1:
        st.download_button(
            f"Download {model_name}.sql",
            file_body,
            file_name=f"{model_name}.sql",
            mime="text/plain",
            help="Save this into models/semantic_view/ in the dbt project",
        )
    with b2:
        confirm_key = f"ws_confirm_needed_{pid}"
        if st.button(f"Add to Workspace", type="primary",
                     help="Writes the file into your own dbt project workspace"):
            # Clear any previous message immediately -- otherwise a stale
            # success banner from an earlier click lingers on screen
            # alongside whatever this new click is about to show.
            st.session_state.pop(f"ws_last_written_{pid}", None)
            st.session_state.pop(f"ws_error_{pid}", None)
            if workspace_file_exists(model_name, user):
                st.session_state[confirm_key] = True
            else:
                try:
                    written_to = add_to_workspace(model_name, file_body, user)
                    st.session_state[f"ws_last_written_{pid}"] = {
                        "version": chosen_v, "path": written_to}
                    st.session_state[f"ws_confirmed_{pid}_{chosen_v}"] = True
                except Exception as e:
                    st.session_state[f"ws_error_{pid}"] = str(e)

    # Overwrite confirmation -- outside the button's own if-block, since a
    # button click always triggers a rerun, and the Yes/No choice needs to
    # survive that rerun to actually be answerable.
    if st.session_state.get(confirm_key):
        st.warning(f"`{model_name}.sql` already exists in the workspace.")
        c1, c2 = st.columns(2)
        if c1.button("Overwrite", key=f"ws_overwrite_yes_{pid}"):
            st.session_state.pop(f"ws_last_written_{pid}", None)
            st.session_state.pop(f"ws_error_{pid}", None)
            try:
                written_to = add_to_workspace(model_name, file_body, user)
                st.session_state[f"ws_last_written_{pid}"] = {
                    "version": chosen_v, "path": written_to}
                st.session_state[f"ws_confirmed_{pid}_{chosen_v}"] = True
            except Exception as e:
                st.session_state[f"ws_error_{pid}"] = str(e)
            st.session_state[confirm_key] = False
            st.rerun()
        if c2.button("Cancel", key=f"ws_overwrite_no_{pid}"):
            st.session_state[confirm_key] = False
            st.rerun()

    # Persistent success/error display -- survives unrelated reruns (like
    # clicking a checkbox below) since it's read from session_state on
    # every render, not just the run where the button was clicked.
    if st.session_state.get(f"ws_last_written_{pid}"):
        info = st.session_state[f"ws_last_written_{pid}"]
        st.success(f"v{info['version']} written to the workspace: `{info['path']}`")
    if st.session_state.get(f"ws_error_{pid}"):
        st.error(
            f"Couldn't write to the workspace: {st.session_state[f'ws_error_{pid}']}\n\n"
            "Use Download instead and add the file manually."
        )

    # Checkboxes come after the file is written, not before -- Deploy syncs
    # the DBT PROJECT object from whatever is CURRENTLY sitting in the
    # workspace at the moment it's clicked. Checking these earlier risks
    # deploying before the file even exists there.
    st.divider()
    st.subheader("Deploy")

    dev_now = prop["DEPLOYED_DEV_VERSION"]
    prod_now = prop["DEPLOYED_PROD_VERSION"]
    e1, e2 = st.columns(2)
    to_dev = e1.checkbox(
        f"Deploy to DEV  (currently: {'v' + str(int(dev_now)) if pd.notna(dev_now) else 'nothing'})"
    )
    if pd.notna(dev_now) and int(dev_now) == chosen_v:
        e1.caption(f"DEV is already on v{chosen_v} -- this re-applies it.")
    to_prod = e2.checkbox(
        f"Deploy to PROD  (currently: {'v' + str(int(prod_now)) if pd.notna(prod_now) else 'nothing'})"
    )
    if pd.notna(prod_now) and int(prod_now) == chosen_v:
        e2.caption(f"PROD is already on v{chosen_v} -- this re-applies it.")

    envs = [e for e, on in (("DEV", to_dev), ("PROD", to_prod)) if on]

    # Was chosen_v deployed before, AND is it still the current version?
    # If something newer was validated and written since, that write would
    # have overwritten this version's file at the same shared filename --
    # so this shortcut only applies when nothing newer exists to have done
    # that. Anything else (never deployed, or an older/rolled-back version)
    # requires an explicit, this-session confirmation that the file
    # currently in the workspace actually is this version's content.
    already_live_and_current = (
        chosen_v == int(prop["CURRENT_VERSION_NUMBER"])
        and (
            (pd.notna(dev_now) and int(dev_now) == chosen_v)
            or (pd.notna(prod_now) and int(prod_now) == chosen_v)
        )
    )
    workspace_confirmed_this_version = st.session_state.get(f"ws_confirmed_{pid}_{chosen_v}", False)

    if st.button("Deploy", type="primary", disabled=not envs):
        if not already_live_and_current and not workspace_confirmed_this_version:
            st.error(
                f"v{chosen_v} hasn't been written to the workspace yet this session "
                "-- click **Add to Workspace** above first, so Deploy syncs the "
                "right content."
            )
        else:
            any_failed = False
            for e in envs:
                with st.spinner(f"Syncing and running dbt for {e}..."):
                    try:
                        success, output = sync_and_run(user, model_name, e)
                    except Exception as ex:
                        success, output = False, str(ex)

                if success:
                    st.success(f"{e}: dbt run succeeded.")
                    run(f"""INSERT INTO {TOOL_PATH}.svt_deployment_log
                            (log_id, proposal_id, version_number, environment,
                             deployed_by, deploy_notes)
                            VALUES ('{new_id()}', '{esc(pid)}', {int(chosen_v)}, '{e}',
                                    '{esc(user)}', 'Auto-verified via EXECUTE DBT PROJECT')""")
                    col = "deployed_dev_version" if e == "DEV" else "deployed_prod_version"
                    run(f"""UPDATE {TOOL_PATH}.svt_proposals
                            SET {col} = {int(chosen_v)}, target_database = '{esc(tgt_db)}',
                                updated_at = CURRENT_TIMESTAMP()
                            WHERE proposal_id = '{esc(pid)}'""")
                else:
                    any_failed = True
                    st.error(f"{e}: dbt run did not succeed. Nothing recorded for this environment.")

                with st.expander(f"{e} output"):
                    st.code(output or "(no output returned)")

    with st.expander("Already deployed this outside the app? Mark it manually"):
        st.caption(
            "Use this only if the deployment already happened somewhere else -- "
            "a manual run, a scheduled task, or another tool -- and this "
            "tracking table just needs to catch up. This does not run dbt."
        )
        manual_envs = st.multiselect("Which environment(s)?", ["DEV", "PROD"])
        note = st.text_input("Note (recommended -- explain where this ran)")
        if st.button("Record manually", disabled=not manual_envs):
            for e in manual_envs:
                run(f"""INSERT INTO {TOOL_PATH}.svt_deployment_log
                        (log_id, proposal_id, version_number, environment,
                         deployed_by, deploy_notes)
                        VALUES ('{new_id()}', '{esc(pid)}', {int(chosen_v)}, '{e}',
                                '{esc(user)}', '{esc(note)}')""")
                col = "deployed_dev_version" if e == "DEV" else "deployed_prod_version"
                run(f"""UPDATE {TOOL_PATH}.svt_proposals
                        SET {col} = {int(chosen_v)}, target_database = '{esc(tgt_db)}',
                            updated_at = CURRENT_TIMESTAMP()
                        WHERE proposal_id = '{esc(pid)}'""")
            st.success("Recorded.")
            st.rerun()


# ============================================================
# PAGE 3: DEPLOYED
# ============================================================

else:
    st.header("Deployed")

    dep = df(f"""
        SELECT p.proposal_id, p.view_name AS "View", p.owner AS "Owner",
               p.target_database AS "Database",
               p.current_version_number AS "Latest version",
               p.deployed_dev_version AS "Live in dev",
               p.deployed_prod_version AS "Live in prod",
               p.status AS "Status"
        FROM {TOOL_PATH}.svt_proposals p
        WHERE p.deployed_dev_version IS NOT NULL
           OR p.deployed_prod_version IS NOT NULL
        ORDER BY p.updated_at DESC
    """)

    if dep.empty:
        st.info("Nothing deployed yet.")
        st.stop()

    st.dataframe(dep.drop(columns=["PROPOSAL_ID"]).fillna("—"),
                 use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Deployment history")

    labels = {r["PROPOSAL_ID"]: r["View"] for _, r in dep.iterrows()}
    pid = st.selectbox("Proposal", list(labels.keys()), format_func=lambda x: labels[x])

    hist = df(f"""
        SELECT version_number AS "Version", environment AS "Environment",
               deployed_by AS "Deployed by", deployed_at AS "When",
               deploy_notes AS "Note"
        FROM {TOOL_PATH}.svt_deployment_log
        WHERE proposal_id = '{esc(pid)}'
        ORDER BY deployed_at DESC
    """)
    st.dataframe(hist.fillna("—"), use_container_width=True, hide_index=True)