from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import streamlit as st


_COMPONENT_DIR = Path(__file__).resolve().parent
_BUNDLE_PATH = _COMPONENT_DIR / "dist" / "cytoscape_component.js"

_COMPONENT_HTML = """
<div class="cy-shell">
  <div class="cy-toolbar">
    <div class="cy-legend" aria-label="Graph legend">
      <span><i class="legend-dot stage-dot"></i>Stage</span>
      <span><i class="legend-dot table-dot"></i>Table</span>
      <span><i class="legend-dot view-dot"></i>View</span>
      <span><i class="legend-dot semantic-dot"></i>Semantic view</span>
      <span><i class="legend-dot agent-dot"></i>Agent</span>
    </div>
    <div class="cy-actions">
      <span class="cy-pan-hint">Drag to pan · wheel or buttons to zoom</span>
      <div class="cy-zoom" role="group" aria-label="Graph zoom controls">
        <button
          type="button"
          class="cy-icon-button"
          data-action="zoom-out"
          aria-label="Zoom out"
          title="Zoom out"
        >−</button>
        <span class="cy-zoom-level" data-role="zoom-level" aria-live="polite">100%</span>
        <button
          type="button"
          class="cy-icon-button"
          data-action="zoom-in"
          aria-label="Zoom in"
          title="Zoom in"
        >+</button>
      </div>
      <button type="button" data-action="fit" title="Fit the complete graph">Fit</button>
      <button type="button" data-action="center" title="Centre the selected or anchor object">Centre</button>
      <button type="button" data-action="explore" title="Use the selected node as the anchor" disabled>Explore</button>
      <button type="button" data-action="expand" title="Open the graph in focus mode">Expand</button>
    </div>
  </div>
  <div id="cy" role="application" aria-label="Snowflake layered lineage graph"></div>
  <div class="cy-tooltip" data-role="tooltip" hidden></div>
</div>
"""

_COMPONENT_CSS = """
:host {
  display: block;
  width: 100%;
  height: 100%;
}

.cy-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 560px;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: 12px;
  overflow: hidden;
  background: var(--st-background-color);
  font-family: var(--st-font);
}

.cy-shell.cy-focus,
.cy-shell:fullscreen {
  position: fixed;
  inset: 0;
  z-index: 2147483000;
  width: 100vw;
  height: 100vh;
  min-height: 100vh;
  border: 0;
  border-radius: 0;
  background: var(--st-background-color);
}

.cy-toolbar {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 14px;
  padding: 9px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--st-text-color) 14%, transparent);
  background: color-mix(in srgb, var(--st-secondary-background-color) 78%, transparent);
}

.cy-focus .cy-toolbar,
.cy-shell:fullscreen .cy-toolbar {
  padding: 10px 16px;
}

.cy-focus .cy-legend,
.cy-focus .cy-pan-hint,
.cy-shell:fullscreen .cy-legend,
.cy-shell:fullscreen .cy-pan-hint {
  display: none;
}

.cy-focus .cy-actions,
.cy-shell:fullscreen .cy-actions {
  width: 100%;
  justify-content: flex-end;
}

.cy-legend,
.cy-actions,
.cy-zoom {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.cy-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--st-text-color);
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}

.stage-dot { background: #eeca3b; }
.table-dot { background: #4c78a8; }
.view-dot { background: #72b7b2; }
.semantic-dot { background: #f58518; }
.agent-dot { background: #ff9da6; }

.cy-pan-hint {
  font-size: 11px;
  color: color-mix(in srgb, var(--st-text-color) 65%, transparent);
  white-space: nowrap;
}

.cy-zoom {
  gap: 4px;
  padding: 2px;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: 8px;
  background: var(--st-background-color);
}

.cy-actions button {
  min-height: 30px;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  border-radius: 7px;
  background: var(--st-background-color);
  color: var(--st-text-color);
  padding: 5px 9px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.cy-actions .cy-icon-button {
  width: 30px;
  min-width: 30px;
  padding: 3px;
  border: 0;
  font-size: 19px;
  font-weight: 600;
  line-height: 1;
}

.cy-actions button:hover:not(:disabled) {
  border-color: var(--st-primary-color);
  color: var(--st-primary-color);
}

.cy-actions .cy-icon-button:hover {
  background: color-mix(in srgb, var(--st-primary-color) 9%, transparent);
}

.cy-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.cy-actions button:focus-visible {
  outline: 2px solid var(--st-primary-color);
  outline-offset: 2px;
}

.cy-zoom-level {
  min-width: 48px;
  text-align: center;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--st-text-color);
  user-select: none;
}

#cy {
  flex: 1;
  width: 100%;
  min-height: 510px;
  background-image:
    linear-gradient(color-mix(in srgb, var(--st-text-color) 4%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--st-text-color) 4%, transparent) 1px, transparent 1px);
  background-size: 24px 24px;
}

.cy-focus #cy,
.cy-shell:fullscreen #cy {
  min-height: 0;
}

.cy-tooltip {
  position: absolute;
  z-index: 20;
  display: grid;
  gap: 3px;
  max-width: 290px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--st-background-color) 96%, transparent);
  box-shadow: 0 7px 24px color-mix(in srgb, #000000 16%, transparent);
  color: var(--st-text-color);
  pointer-events: none;
}

.cy-tooltip strong {
  font-size: 12px;
  line-height: 1.25;
}

.cy-tooltip span {
  font-size: 10px;
  line-height: 1.25;
  color: color-mix(in srgb, var(--st-text-color) 68%, transparent);
}

@media (max-width: 1080px) {
  .cy-pan-hint {
    display: none;
  }
}
"""


def _safe_component_key(value: str) -> str:
    """Return a stable Components v2 key without Streamlit's reserved ``__`` delimiter.

    The logical graph key may contain database, schema, or object names supplied by
    Snowflake. Any of those identifiers can legally contain double underscores, so
    the logical value is hashed before it is passed to the bidirectional component.
    """
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"cygraph-{digest}"


def _load_bundle() -> str:
    if not _BUNDLE_PATH.exists():
        raise FileNotFoundError(
            "The Cytoscape bundle is missing. Run npm install and npm run build "
            "inside components/cytoscape/frontend before deploying."
        )
    return _BUNDLE_PATH.read_text(encoding="utf-8")


if not hasattr(st.components, "v2"):
    raise RuntimeError(
        "This app requires Streamlit 1.64 or later because it uses Components v2."
    )

_CYTOSCAPE_COMPONENT = st.components.v2.component(
    name="snowflake_lineage_cytoscape",
    html=_COMPONENT_HTML,
    css=_COMPONENT_CSS,
    js=_load_bundle(),
    isolate_styles=True,
)


def render_cytoscape(
    elements: list[dict[str, Any]],
    *,
    search: str = "",
    show_edge_labels: bool = False,
    anchor_id: str | None = None,
    wheel_sensitivity: float = 0.9,
    height: int = 780,
    key: str = "lineage_graph",
) -> dict[str, Any]:
    result = _CYTOSCAPE_COMPONENT(
        data={
            "elements": elements,
            "search": search,
            "show_edge_labels": show_edge_labels,
            "anchor_id": anchor_id,
            "wheel_sensitivity": max(0.05, min(float(wheel_sensitivity), 2.0)),
        },
        default={"selected": None, "explore": None},
        on_selected_change=lambda: None,
        on_explore_change=lambda: None,
        key=_safe_component_key(key),
        height=height,
        width="stretch",
    )
    selected = getattr(result, "selected", None)
    explore = getattr(result, "explore", None)
    return {
        "selected": selected if isinstance(selected, dict) else None,
        "explore": explore if isinstance(explore, dict) else None,
    }
