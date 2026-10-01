from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

import pandas as pd

if TYPE_CHECKING:
    from snowflake.snowpark import Session
else:
    Session = Any


LINEAGE_COLUMNS = [
    "SOURCE_OBJECT_DATABASE",
    "SOURCE_OBJECT_SCHEMA",
    "SOURCE_OBJECT_NAME",
    "SOURCE_OBJECT_DOMAIN",
    "SOURCE_OBJECT_VERSION",
    "SOURCE_COLUMN_NAME",
    "SOURCE_STATUS",
    "SOURCE_DATASET_TYPE",
    "SOURCE_ORIGIN",
    "SOURCE_NAMESPACE",
    "SOURCE_EXTERNAL_ID",
    "TARGET_OBJECT_DATABASE",
    "TARGET_OBJECT_SCHEMA",
    "TARGET_OBJECT_NAME",
    "TARGET_OBJECT_DOMAIN",
    "TARGET_OBJECT_VERSION",
    "TARGET_COLUMN_NAME",
    "TARGET_STATUS",
    "TARGET_DATASET_TYPE",
    "TARGET_ORIGIN",
    "TARGET_NAMESPACE",
    "TARGET_EXTERNAL_ID",
    "DISTANCE",
    "PROCESS_JSON",
]

INVENTORY_COLUMNS = [
    "DATABASE_NAME",
    "SCHEMA_NAME",
    "OBJECT_NAME",
    "OBJECT_TYPE",
    "OBJECT_OWNER",
    "ROW_COUNT",
    "CREATED",
    "LAST_ALTERED",
    "COMMENT",
    "LINEAGE_DOMAIN",
    "LINEAGE_KEY",
    "DISPLAY_LABEL",
]


def quote_identifier(value: str) -> str:
    """Return a safely double-quoted Snowflake identifier."""
    return '"' + value.replace('"', '""') + '"'


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(column).upper() for column in result.columns]
    return result


def rows_to_frame(rows: Iterable[Any]) -> pd.DataFrame:
    """Convert Snowpark Row values from a SHOW command into a DataFrame."""
    values: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "as_dict"):
            item = row.as_dict()
        elif hasattr(row, "asDict"):
            item = row.asDict()
        else:
            try:
                item = dict(row)
            except (TypeError, ValueError):
                continue
        values.append({str(key).upper(): value for key, value in item.items()})
    return pd.DataFrame(values)


def empty_lineage_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=LINEAGE_COLUMNS)


@dataclass(frozen=True)
class ObjectRef:
    database: str
    schema: str
    name: str
    object_type: str
    owner: str | None = None
    comment: str | None = None
    row_count: int | None = None
    created: Any | None = None
    last_altered: Any | None = None

    @property
    def fq_name(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"

    @property
    def quoted_fq_name(self) -> str:
        return ".".join(
            quote_identifier(part) for part in (self.database, self.schema, self.name)
        )

    @property
    def lineage_domain(self) -> str:
        object_type = self.object_type.upper()
        if object_type == "SEMANTIC_VIEW":
            return "SEMANTIC_VIEW"
        if object_type == "STAGE":
            return "STAGE"
        if object_type in {"CORTEX_AGENT", "AGENT"}:
            return "CORTEX_AGENT"
        return "TABLE"

    @property
    def lineage_key(self) -> str:
        return make_lineage_key(
            self.database,
            self.schema,
            self.name,
            self.lineage_domain,
        )

    @classmethod
    def from_inventory_row(cls, row: pd.Series) -> "ObjectRef":
        row_count = row.get("ROW_COUNT")
        if pd.isna(row_count):
            row_count = None
        elif row_count is not None:
            row_count = int(row_count)

        def nullable(value: Any) -> Any | None:
            try:
                return None if pd.isna(value) else value
            except (TypeError, ValueError):
                return value

        return cls(
            database=str(row["DATABASE_NAME"]),
            schema=str(row["SCHEMA_NAME"]),
            name=str(row["OBJECT_NAME"]),
            object_type=str(row["OBJECT_TYPE"]),
            owner=nullable(row.get("OBJECT_OWNER")),
            comment=nullable(row.get("COMMENT")),
            row_count=row_count,
            created=nullable(row.get("CREATED")),
            last_altered=nullable(row.get("LAST_ALTERED")),
        )


def make_lineage_key(
    database: str | None,
    schema: str | None,
    name: str | None,
    domain: str | None,
) -> str:
    return "|".join(
        [
            str(domain or "UNKNOWN").upper(),
            str(database or ""),
            str(schema or ""),
            str(name or ""),
        ]
    )


def list_databases(session: Session) -> list[str]:
    """Return databases visible to the Streamlit app owner role."""
    frame = rows_to_frame(session.sql("SHOW TERSE DATABASES").collect())
    if frame.empty or "NAME" not in frame.columns:
        return []

    databases = []
    for value in frame["NAME"].dropna().astype(str):
        if value.upper() in {"SNOWFLAKE", "SNOWFLAKE_LOCAL"}:
            continue
        databases.append(value)
    return sorted(set(databases), key=str.casefold)


def list_schemas(session: Session, database: str) -> list[str]:
    database_id = quote_identifier(database)
    frame = normalize_columns(
        session.sql(
            f"""
            SELECT SCHEMA_NAME
            FROM {database_id}.INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME <> 'INFORMATION_SCHEMA'
            ORDER BY SCHEMA_NAME
            """
        ).to_pandas()
    )
    if frame.empty:
        return []
    return frame["SCHEMA_NAME"].dropna().astype(str).tolist()


def _physical_inventory(
    session: Session,
    database: str,
    schema: str | None,
) -> pd.DataFrame:
    database_id = quote_identifier(database)
    schema_filter = ""
    params: list[Any] = []
    if schema:
        schema_filter = "AND TABLE_SCHEMA = ?"
        params.append(schema)

    sql = f"""
        SELECT
            TABLE_CATALOG AS DATABASE_NAME,
            TABLE_SCHEMA AS SCHEMA_NAME,
            TABLE_NAME AS OBJECT_NAME,
            CASE
                WHEN IS_DYNAMIC = 'YES' THEN 'DYNAMIC_TABLE'
                WHEN IS_ICEBERG = 'YES' THEN 'ICEBERG_TABLE'
                WHEN TABLE_TYPE = 'MATERIALIZED VIEW' THEN 'MATERIALIZED_VIEW'
                WHEN TABLE_TYPE = 'VIEW' THEN 'VIEW'
                WHEN TABLE_TYPE = 'EXTERNAL TABLE' THEN 'EXTERNAL_TABLE'
                WHEN TABLE_TYPE = 'EVENT TABLE' THEN 'EVENT_TABLE'
                ELSE 'TABLE'
            END AS OBJECT_TYPE,
            TABLE_OWNER AS OBJECT_OWNER,
            ROW_COUNT,
            CREATED,
            LAST_ALTERED,
            COMMENT
        FROM {database_id}.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA'
          {schema_filter}
    """
    return normalize_columns(session.sql(sql, params=params).to_pandas())


def _semantic_inventory(
    session: Session,
    database: str,
    schema: str | None,
) -> pd.DataFrame:
    database_id = quote_identifier(database)
    schema_filter = ""
    params: list[Any] = []
    if schema:
        schema_filter = "AND SCHEMA = ?"
        params.append(schema)

    sql = f"""
        SELECT
            CATALOG AS DATABASE_NAME,
            SCHEMA AS SCHEMA_NAME,
            NAME AS OBJECT_NAME,
            'SEMANTIC_VIEW' AS OBJECT_TYPE,
            OWNER AS OBJECT_OWNER,
            NULL::NUMBER AS ROW_COUNT,
            CREATED,
            NULL::TIMESTAMP_LTZ AS LAST_ALTERED,
            COMMENT
        FROM {database_id}.INFORMATION_SCHEMA.SEMANTIC_VIEWS
        WHERE 1 = 1
          {schema_filter}
    """
    try:
        return normalize_columns(session.sql(sql, params=params).to_pandas())
    except Exception:
        return pd.DataFrame()


def _stage_inventory(
    session: Session,
    database: str,
    schema: str | None,
) -> pd.DataFrame:
    database_id = quote_identifier(database)
    schema_filter = ""
    params: list[Any] = []
    if schema:
        schema_filter = "AND STAGE_SCHEMA = ?"
        params.append(schema)

    sql = f"""
        SELECT
            STAGE_CATALOG AS DATABASE_NAME,
            STAGE_SCHEMA AS SCHEMA_NAME,
            STAGE_NAME AS OBJECT_NAME,
            'STAGE' AS OBJECT_TYPE,
            STAGE_OWNER AS OBJECT_OWNER,
            NULL::NUMBER AS ROW_COUNT,
            CREATED,
            LAST_ALTERED,
            COMMENT,
            STAGE_TYPE,
            STAGE_URL
        FROM {database_id}.INFORMATION_SCHEMA.STAGES
        WHERE STAGE_SCHEMA <> 'INFORMATION_SCHEMA'
          {schema_filter}
    """
    try:
        return normalize_columns(session.sql(sql, params=params).to_pandas())
    except Exception:
        return pd.DataFrame()


def _agent_inventory(
    session: Session,
    database: str,
    schema: str | None,
) -> pd.DataFrame:
    database_id = quote_identifier(database)
    if schema:
        scope = f"IN SCHEMA {database_id}.{quote_identifier(schema)}"
    else:
        scope = f"IN DATABASE {database_id}"

    try:
        rows = session.sql(f"SHOW AGENTS {scope}").collect()
    except Exception:
        return pd.DataFrame()

    frame = rows_to_frame(rows)
    if frame.empty or "NAME" not in frame.columns:
        return pd.DataFrame()

    result = pd.DataFrame(
        {
            "DATABASE_NAME": frame.get("DATABASE_NAME"),
            "SCHEMA_NAME": frame.get("SCHEMA_NAME"),
            "OBJECT_NAME": frame.get("NAME"),
            "OBJECT_TYPE": "CORTEX_AGENT",
            "OBJECT_OWNER": frame.get("OWNER"),
            "ROW_COUNT": None,
            "CREATED": frame.get("CREATED_ON"),
            "LAST_ALTERED": None,
            "COMMENT": frame.get("COMMENT"),
            "PROFILE": frame.get("PROFILE"),
            "IS_SECURE": frame.get("IS_SECURE"),
        }
    )
    return normalize_columns(result)


def list_objects(
    session: Session,
    database: str,
    schema: str | None = None,
) -> pd.DataFrame:
    """List accessible schema objects used by the lineage explorer.

    Tables/views, semantic views, named stages, and Cortex Agents are included.
    Optional object families fail independently so that an unavailable feature does
    not prevent the core table/view inventory from loading.
    """
    frames = [
        _physical_inventory(session, database, schema),
        _semantic_inventory(session, database, schema),
        _stage_inventory(session, database, schema),
        _agent_inventory(session, database, schema),
    ]
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame(columns=INVENTORY_COLUMNS)

    combined = pd.concat(populated, ignore_index=True, sort=False)
    combined = normalize_columns(combined)
    combined = combined.loc[
        combined["DATABASE_NAME"].notna()
        & combined["SCHEMA_NAME"].notna()
        & combined["OBJECT_NAME"].notna()
    ].copy()

    def lineage_domain(value: Any) -> str:
        object_type = str(value).upper()
        if object_type == "SEMANTIC_VIEW":
            return "SEMANTIC_VIEW"
        if object_type == "STAGE":
            return "STAGE"
        if object_type in {"CORTEX_AGENT", "AGENT"}:
            return "CORTEX_AGENT"
        return "TABLE"

    combined["LINEAGE_DOMAIN"] = combined["OBJECT_TYPE"].map(lineage_domain)
    combined["LINEAGE_KEY"] = combined.apply(
        lambda row: make_lineage_key(
            row["DATABASE_NAME"],
            row["SCHEMA_NAME"],
            row["OBJECT_NAME"],
            row["LINEAGE_DOMAIN"],
        ),
        axis=1,
    )
    combined["DISPLAY_LABEL"] = combined.apply(
        lambda row: (
            f"{row['SCHEMA_NAME']}.{row['OBJECT_NAME']} "
            f"[{str(row['OBJECT_TYPE']).replace('_', ' ')}]"
        ),
        axis=1,
    )
    combined = combined.drop_duplicates(subset=["LINEAGE_KEY"], keep="first")
    return combined.sort_values(
        ["SCHEMA_NAME", "OBJECT_TYPE", "OBJECT_NAME"],
        key=lambda series: series.astype(str).str.casefold(),
    ).reset_index(drop=True)


def _query_lineage(
    session: Session,
    object_ref: ObjectRef,
    direction: str,
    max_distance: int,
) -> pd.DataFrame:
    direction = direction.upper()
    if direction not in {"UPSTREAM", "DOWNSTREAM"}:
        raise ValueError("direction must be UPSTREAM or DOWNSTREAM")
    if max_distance < 1 or max_distance > 5:
        raise ValueError("max_distance must be between 1 and 5")

    sql = """
        SELECT
            SOURCE_OBJECT_DATABASE,
            SOURCE_OBJECT_SCHEMA,
            SOURCE_OBJECT_NAME,
            SOURCE_OBJECT_DOMAIN,
            SOURCE_OBJECT_VERSION,
            SOURCE_COLUMN_NAME,
            SOURCE_STATUS,
            SOURCE_DETAILS:dataset_type::VARCHAR AS SOURCE_DATASET_TYPE,
            SOURCE_DETAILS:origin::VARCHAR AS SOURCE_ORIGIN,
            SOURCE_DETAILS:namespace::VARCHAR AS SOURCE_NAMESPACE,
            SOURCE_DETAILS:external_id::VARCHAR AS SOURCE_EXTERNAL_ID,
            TARGET_OBJECT_DATABASE,
            TARGET_OBJECT_SCHEMA,
            TARGET_OBJECT_NAME,
            TARGET_OBJECT_DOMAIN,
            TARGET_OBJECT_VERSION,
            TARGET_COLUMN_NAME,
            TARGET_STATUS,
            TARGET_DETAILS:dataset_type::VARCHAR AS TARGET_DATASET_TYPE,
            TARGET_DETAILS:origin::VARCHAR AS TARGET_ORIGIN,
            TARGET_DETAILS:namespace::VARCHAR AS TARGET_NAMESPACE,
            TARGET_DETAILS:external_id::VARCHAR AS TARGET_EXTERNAL_ID,
            DISTANCE,
            TO_JSON(PROCESS) AS PROCESS_JSON
        FROM TABLE(
            SNOWFLAKE.CORE.GET_LINEAGE(
                object_name => ?,
                object_domain => ?,
                direction => ?,
                max_distance => ?
            )
        )
    """
    frame = normalize_columns(
        session.sql(
            sql,
            params=[
                object_ref.quoted_fq_name,
                object_ref.lineage_domain,
                direction,
                max_distance,
            ],
        ).to_pandas()
    )
    if frame.empty:
        return empty_lineage_frame()
    for column in LINEAGE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame[LINEAGE_COLUMNS]


def _deduplicate_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return empty_lineage_frame()
    dedupe_columns = [
        "SOURCE_OBJECT_DATABASE",
        "SOURCE_OBJECT_SCHEMA",
        "SOURCE_OBJECT_NAME",
        "SOURCE_OBJECT_DOMAIN",
        "SOURCE_COLUMN_NAME",
        "TARGET_OBJECT_DATABASE",
        "TARGET_OBJECT_SCHEMA",
        "TARGET_OBJECT_NAME",
        "TARGET_OBJECT_DOMAIN",
        "TARGET_COLUMN_NAME",
    ]
    return frame.drop_duplicates(subset=dedupe_columns).reset_index(drop=True)


def get_lineage(
    session: Session,
    object_ref: ObjectRef,
    direction: str,
    max_distance: int,
) -> pd.DataFrame:
    direction = direction.upper()
    if direction == "BOTH":
        frames = [
            _query_lineage(session, object_ref, "UPSTREAM", max_distance),
            _query_lineage(session, object_ref, "DOWNSTREAM", max_distance),
        ]
        return _deduplicate_lineage(
            pd.concat(frames, ignore_index=True, sort=False)
        )
    return _query_lineage(session, object_ref, direction, max_distance)


def get_schema_lineage(
    session: Session,
    object_refs: Iterable[ObjectRef],
    *,
    max_distance: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a direct-edge lineage set for a schema inventory.

    GET_LINEAGE is object-centric, so the schema view queries each visible object
    in both directions at distance one, then de-duplicates the returned edges.
    Failures are returned separately and do not prevent the remaining graph from
    rendering.
    """
    frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []

    for object_ref in object_refs:
        try:
            frame = get_lineage(
                session,
                object_ref,
                direction="BOTH",
                max_distance=max_distance,
            )
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:  # one unsupported object must not break the schema
            failures.append(
                {
                    "DATABASE_NAME": object_ref.database,
                    "SCHEMA_NAME": object_ref.schema,
                    "OBJECT_NAME": object_ref.name,
                    "OBJECT_TYPE": object_ref.object_type,
                    "ERROR": str(exc),
                }
            )

    if frames:
        lineage = _deduplicate_lineage(
            pd.concat(frames, ignore_index=True, sort=False)
        )
    else:
        lineage = empty_lineage_frame()

    return lineage, pd.DataFrame(failures)


def get_columns(
    session: Session,
    database: str,
    schema: str,
    object_name: str,
) -> pd.DataFrame:
    database_id = quote_identifier(database)
    sql = f"""
        SELECT
            ORDINAL_POSITION,
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE,
            COMMENT
        FROM {database_id}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """
    return normalize_columns(
        session.sql(sql, params=[schema, object_name]).to_pandas()
    )


def get_semantic_model(
    session: Session,
    object_ref: ObjectRef,
) -> dict[str, pd.DataFrame]:
    if object_ref.lineage_domain != "SEMANTIC_VIEW":
        raise ValueError("get_semantic_model requires a semantic view")

    database_id = quote_identifier(object_ref.database)
    source_views = {
        "tables": "SEMANTIC_TABLES",
        "relationships": "SEMANTIC_RELATIONSHIPS",
        "dimensions": "SEMANTIC_DIMENSIONS",
        "facts": "SEMANTIC_FACTS",
        "metrics": "SEMANTIC_METRICS",
    }
    result: dict[str, pd.DataFrame] = {}
    for key, source_view in source_views.items():
        sql = f"""
            SELECT *
            FROM {database_id}.INFORMATION_SCHEMA.{source_view}
            WHERE SEMANTIC_VIEW_SCHEMA = ?
              AND SEMANTIC_VIEW_NAME = ?
        """
        try:
            result[key] = normalize_columns(
                session.sql(sql, params=[object_ref.schema, object_ref.name]).to_pandas()
            )
        except Exception:
            result[key] = pd.DataFrame()
    return result
