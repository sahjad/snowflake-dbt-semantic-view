import streamlit as st
from snowflake.snowpark.context import get_active_session
import pandas as pd
import uuid
import re


def strip_html(text):
    """Remove HTML tags and collapse resulting whitespace.

    Description fields can come from rich-text sources (confirmed: a
    Marketplace listing's description literally stores markup like
    "<p><br/></p>") -- this keeps the popup showing clean text
    regardless of what formatting the original field happens to contain.
    """
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()

st.set_page_config(page_title="Tasty Bytes Graph Explorer", layout="wide")
session = get_active_session()

# Graph Algorithms (WCC / PageRank / Louvain) hidden for now -- flip this
# back to True whenever it should be shown again. Nothing below it was
# deleted, just wrapped in this flag.
SHOW_GRAPH_ALGORITHMS = False

NODE_COLORS = {
    "TABLE": "#4A90D9", "VIEW": "#27AE60", "SEMANTIC_VIEW": "#8E44AD",
    "DATA_PRODUCT": "#E67E22", "COLUMN": "#95A5A6", "LOGICAL_TABLE": "#16A085",
    "DIMENSION": "#BB8FCE", "FACT": "#D35400", "METRIC": "#F1C40F",
}
EDGE_COLORS = {
    "FK_TO": "#3498DB", "DEPENDS_ON": "#E74C3C", "DEFINED_OVER": "#8E44AD",
    "SHARED_AS": "#E67E22", "HAS_COLUMN": "#BDC3C7",
    "BELONGS_TO_LOGICAL_TABLE": "#16A085", "HAS_DIMENSION": "#BB8FCE",
    "HAS_FACT": "#D35400", "HAS_METRIC": "#F1C40F", "REFERENCES": "#2980B9",
}

@st.cache_data(ttl=300)
def load_nodes():
    return session.sql("SELECT * FROM NEO4J_LINEAGE_DB.PUBLIC.NODES_VW").to_pandas()


@st.cache_data(ttl=300)
def load_rels():
    return session.sql("SELECT * FROM NEO4J_LINEAGE_DB.PUBLIC.RELATIONSHIPS_VW").to_pandas()


@st.cache_data(ttl=60)
def load_algo_results(table_name):
    try:
        return session.sql(
            f"SELECT * FROM NEO4J_LINEAGE_DB.PUBLIC.{table_name}"
        ).to_pandas()
    except Exception:
        return None


_NVL_HTML = """
<div class="nvl-shell" id="nvl-shell">
  <button class="nvl-expand-btn" id="nvl-expand-btn" title="Expand to fill screen">⛶ Expand</button>
  <button class="nvl-home-btn" id="nvl-home-btn" title="Return to full graph">🏠 Home</button>
  <button class="nvl-unused-btn" id="nvl-unused-btn" title="Show Gold tables with no semantic view">⚠ Unused Tables</button>
  <div id="neo4j-viz-root" style="width:100%;height:100%;"></div>
  <div class="nvl-detail-panel" id="nvl-detail-panel">
    <button class="nvl-detail-close" id="nvl-detail-close" title="Close">✕</button>
    <div class="nvl-detail-content" id="nvl-detail-content"></div>
  </div>
</div>
"""

_NVL_CSS = """
.nvl-shell {
    position: relative;
    width: 100%;
    /* height intentionally not set here via CSS percentage -- that depends
       on every ancestor having an explicit resolved height, which isn't
       guaranteed inside a CCv2 mount point. Set explicitly via JS instead,
       from the same height value passed to the Python mount call. */
}
.nvl-shell.nvl-focus {
    position: fixed !important;
    inset: 0 !important;
    z-index: 999999;
    width: 100vw !important;
    height: 100vh !important;
    background: white;
}
.nvl-expand-btn {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 10;
    background: rgba(255,255,255,0.92);
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
    font-family: sans-serif;
    color: #333;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
.nvl-home-btn {
    position: absolute;
    top: 44px;
    left: 8px;
    z-index: 10;
    background: rgba(255,255,255,0.92);
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
    font-family: sans-serif;
    color: #333;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
.nvl-unused-btn {
    position: absolute;
    top: 80px;
    left: 8px;
    z-index: 10;
    background: rgba(255,255,255,0.92);
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
    font-family: sans-serif;
    color: #333;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
#neo4j-viz-root {
    width: 100%;
    height: 100%;
}
.nvl-detail-panel {
    position: absolute;
    width: 280px;
    max-height: 340px;
    background: white;
    border-radius: 10px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.12), 0 8px 24px rgba(0,0,0,0.16);
    z-index: 500;
    overflow-y: auto;
    box-sizing: border-box;
    padding: 16px 14px;
    font-family: sans-serif;
    opacity: 0;
    transform: scale(0.92) translateY(6px);
    transform-origin: top left;
    transition: opacity 0.15s ease, transform 0.15s ease;
    pointer-events: none;
    visibility: hidden;
}
.nvl-detail-panel.nvl-open {
    opacity: 1;
    transform: scale(1) translateY(0);
    pointer-events: auto;
    visibility: visible;
}
.nvl-detail-close {
    position: absolute;
    top: 10px;
    right: 10px;
    background: none;
    border: none;
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    color: #888;
    padding: 4px;
}
.nvl-detail-close:hover {
    color: #333;
}
.nvl-detail-title {
    margin: 0 28px 4px 0;
    font-size: 15px;
    font-weight: 700;
    color: #1a1a1a;
    overflow-wrap: break-word;
    word-break: break-word;
}
.nvl-detail-type-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    color: white;
    padding: 2px 8px;
    border-radius: 10px;
    margin-bottom: 14px;
}
.nvl-detail-row {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid #f0f0f0;
}
.nvl-detail-row .k {
    color: #888;
    font-size: 11.5px;
    white-space: nowrap;
}
.nvl-detail-row .v {
    text-align: right;
    font-size: 12.5px;
    color: #222;
    word-break: break-word;
}
"""

_NVL_JS_WRAPPER_HEAD = """
export default function(component) {
    const { parentElement, data } = component;

    // data now carries the COMPLETE dataset (Python no longer pre-filters
    // by sidebar selection) -- this is what lets drill-down reach columns,
    // Raw/Silver lineage, and semantic internals regardless of what the
    // sidebar's Node Type/Schema filters currently show by default.
    const fullNodes = data.nodes || [];
    const fullRels = data.relationships || [];
    const defaultVisibleIds = new Set(data.defaultVisibleIds || []);
    const unusedTableIds = new Set(data.unusedTableIds || []);
    const defaultEdgeTypes = new Set(data.defaultEdgeTypes || []);

    // Builds the default/unfocused view -- respects the sidebar's current
    // filters, same behavior as before this redesign, just computed
    // client-side now instead of by Python pre-filtering the dataset.
    const getDefaultViewData = () => {
        const nodes = fullNodes
            .filter((n) => defaultVisibleIds.has(n.id))
            .map((n) => Object.assign({}, n, { selected: false }));
        const rels = fullRels.filter(
            (r) =>
                defaultVisibleIds.has(r.from) &&
                defaultVisibleIds.has(r.to) &&
                defaultEdgeTypes.has(r.caption)
        );
        return Object.assign({}, data, { nodes: nodes, relationships: rels });
    };

    // Remove any stale data script from a previous mount/rerun, then inject
    // the INITIAL (default/filtered) view -- not the complete dataset --
    // the same way the original template did (a JSON script tag the
    // bundle's own code reads via getElementById) -- only the delivery
    // mechanism changed (CCv2's data channel instead of Python-side HTML
    // string replacement), the bundle's own reading logic is untouched.
    const existingData = parentElement.querySelector('#neo4j-viz-data');
    if (existingData) existingData.remove();
    const dataScript = document.createElement('script');
    dataScript.type = 'application/json';
    dataScript.id = 'neo4j-viz-data';
    dataScript.textContent = JSON.stringify(getDefaultViewData());
    parentElement.appendChild(dataScript);

    // Focus-mode toggle -- same two-layer approach as this project's
    // original (retired) Cytoscape Lineage Explorer: try the real
    // Fullscreen API first, gracefully fall back to a pure CSS
    // position:fixed cover if the browser blocks it. Unlike the earlier
    // st.iframe()-based attempt, this component mounts directly in the
    // page's own DOM (isolate_styles=False, no iframe, no Shadow DOM), so
    // the CSS fallback can genuinely cover the real viewport this time --
    // there's no iframe boundary left to constrain it.
    const shell = parentElement.querySelector('#nvl-shell');
    const expandBtn = parentElement.querySelector('#nvl-expand-btn');
    let focusMode = false;

    // Explicit height, set directly rather than relying on CSS percentage
    // cascading through ancestor elements whose own height we don't
    // control. Sourced from the same value passed to the Python mount
    // call (see componentHeight in nvl_data below) -- single source of
    // truth, no risk of the two drifting out of sync. The .nvl-focus CSS
    // class (with !important) cleanly overrides this when toggled on.
    shell.style.height = (data.componentHeight || 700) + "px";

    const applyFocusState = (enabled) => {
        focusMode = enabled;
        shell.classList.toggle('nvl-focus', enabled);
        expandBtn.textContent = enabled ? '\\u2715 Exit' : '\\u26f6 Expand';
    };

    // Nudges the graph's internal canvas to recompute its size -- it
    // likely sizes itself based on listening for window resize events
    // rather than directly observing its own container's CSS, so a pure
    // CSS-driven size change (our fullscreen toggle) can otherwise leave
    // it thinking it's still the previous size. The delay lets the CSS
    // transition/reflow settle before dispatching.
    // window.dispatchEvent alone wasn't reliable -- the real browser
    // window never actually changes size in this scenario (only our
    // shell's CSS does), so resize listeners comparing actual window
    // dimensions would see no change and skip recalculating. Also force
    // a genuine re-render (rerenderAtCurrentSize, defined further below
    // near the other render functions -- safe as a forward reference
    // here since this only ever runs after a user click, well after the
    // whole script has finished its initial synchronous execution).
    // Best-effort: click NVL's own "Zoom to fit" button rather than
    // guessing at zoom/pan math ourselves. Not a settable option in our
    // own data (confirmed: internal React ref/state only reachable
    // through NVL's own UI), so this simulates the existing button.
    // Degrades silently if the selector doesn't match, rather than
    // breaking anything else. delayMs lets callers wait for the canvas
    // to settle at a new size (e.g. after a fullscreen toggle) before
    // attempting the fit.
    const tryZoomToFit = (delayMs) => {
        setTimeout(() => {
            try {
                const btn = parentElement.querySelector(
                    '[aria-label="Zoom to fit"], [title="Zoom to fit"]'
                );
                if (btn) btn.click();
            } catch (_) {
                // Silent -- best-effort convenience, not critical path.
            }
        }, delayMs || 0);
    };

    const nudgeResize = () => {
        setTimeout(() => {
            window.dispatchEvent(new Event("resize"));
            rerenderAtCurrentSize();
            // The canvas dimensions just changed significantly
            // (entering/exiting fullscreen), so whatever zoom/pan was set
            // for the old size no longer fits the new one. Scheduled
            // after the resize/rerender above so the canvas has settled
            // at its new size first.
            tryZoomToFit(150);
        }, 400);
    };

    const enterFocus = async () => {
        if (focusMode) return;
        applyFocusState(true);
        try {
            if (shell.requestFullscreen && document.fullscreenElement !== shell) {
                await shell.requestFullscreen();
            }
        } catch (_) {
            // CSS fallback (already applied above) remains active.
        }
        nudgeResize();
    };

    const exitFocus = async () => {
        if (!focusMode) return;
        try {
            if (document.fullscreenElement === shell && document.exitFullscreen) {
                await document.exitFullscreen();
            }
        } catch (_) {}
        applyFocusState(false);
        nudgeResize();
    };

    expandBtn.addEventListener('click', () => (focusMode ? exitFocus() : enterFocus()));
    document.addEventListener('fullscreenchange', () => {
        if (focusMode && document.fullscreenElement !== shell) applyFocusState(false);
    });
    document.addEventListener('keydown', (event) => {
        if (focusMode && event.key === 'Escape') {
            event.preventDefault();
            exitFocus();
        }
    });

    // Floating detail card, positioned near the actual click. Entirely
    // self-contained client-side -- the full properties dict for every
    // node is already present in data.nodes (same data the bundle's own
    // built-in panel reads), so no Python round-trip or rerun is needed.
    const detailPanel = parentElement.querySelector('#nvl-detail-panel');
    const detailContent = parentElement.querySelector('#nvl-detail-content');
    const detailClose = parentElement.querySelector('#nvl-detail-close');

    const nodesById = {};
    (data.nodes || []).forEach((n) => { nodesById[n.id] = n; });

    const toTitleCase = (s) =>
        s.replace(/_/g, " ").replace(/\\b\\w/g, (c) => c.toUpperCase());

    // Track the real click position via a standard DOM listener -- this is
    // reliable regardless of whatever shape the graph library's own
    // internal click-callback arguments turn out to have (confirmed the
    // library's internal call site passes 3 arguments matching its
    // documented (node, hits, evt) signature, but its exact evt shape
    // isn't something we can verify without live testing, so this avoids
    // depending on it at all).
    let lastClickX = 0;
    let lastClickY = 0;
    const root = parentElement.querySelector('#neo4j-viz-root');
    // true = capture phase. The library's own click handler is attached to
    // its inner canvas and fires in the default bubble phase -- a capture
    // listener on this outer, shallower element fires BEFORE that, on the
    // way down to the target, fixing the one-click lag (previously this
    // listener only updated the coordinates AFTER the library's handler --
    // and therefore renderDetailPanel -- had already run for that click).
    root.addEventListener('click', (ev) => {
        lastClickX = ev.clientX;
        lastClickY = ev.clientY;
    }, true);

    // NOTE: a synthetic-click approach was tried here (dispatching a real
    // click event at the canvas center after the re-render settled, to
    // reach a fresh listener rather than a stale one) but confirmed
    // unreliable in practice -- removed. Reverted to the simpler,
    // reliably-working behavior: zoom to neighborhood, no attempt to
    // chase the selection ring. The ring itself is suppressed entirely
    // below (see "selected: false" on every node), rather than left to
    // show up on the wrong node.

    // Precise per-node collision avoidance was attempted and confirmed
    // architecturally impossible: traced the bundle's node rendering and
    // found it builds an SVG structure (with the data-id attribute),
    // serializes it to a string, rasterizes that onto a <canvas> via
    // drawImage(), then explicitly calls .remove() on the SVG -- nothing
    // persists in the live DOM to ever query. Not a selector bug, a hard
    // wall. Falling back to something fully within our own control
    // instead: a fixed, predictable right-anchored position (see below).
    const findCardPosition = (clickX, clickY, cardWidth, cardHeight) => {
        // Fixed, predictable position -- right-anchored, vertically
        // centered -- rather than chasing the click point. We have no
        // reliable way to know where other nodes are (confirmed: nothing
        // persists in the DOM to query), so no amount of click-relative
        // offsetting can actually guarantee avoiding them. A fixed spot
        // at least makes the behavior consistent and predictable, and
        // combined with the neighborhood auto-zoom (which tends to
        // center the focused cluster), the right edge is more likely to
        // be clear space than any point directly under the cursor.
        const shellRect = shell.getBoundingClientRect();
        const margin = 16;
        const left = shellRect.width - cardWidth - margin;
        const top = Math.max(margin, (shellRect.height - cardHeight) / 2);
        return { left, top };
    };

    const renderDetailPanel = (nodeId) => {
        const node = nodesById[nodeId];
        if (!node) return;
        const props = node.properties || {};
        const nodeColor = node.color || "#95A5A6";
        let html = "";
        html += '<div class="nvl-detail-title">' + (node.caption || nodeId) + "</div>";
        html += '<span class="nvl-detail-type-badge" style="background:' + nodeColor + '">'
              + (props.type || "") + "</span>";
        Object.keys(props).forEach((k) => {
            if (k === "type") return;  // already shown as the badge above
            html += '<div class="nvl-detail-row"><span class="k">'
                  + toTitleCase(k) + '</span><span class="v">' + props[k] + "</span></div>";
        });
        detailContent.innerHTML = html;

        const pos = findCardPosition(lastClickX, lastClickY, 280, 340);
        detailPanel.style.left = pos.left + "px";
        detailPanel.style.top = pos.top + "px";
        detailPanel.classList.add("nvl-open");
    };

    // Neighborhood focus, take two. The first attempt crashed with
    // "t.get is not a function" -- traced this to its real cause by
    // finding the bundle's own Lre() function, confirmed to wrap plain
    // data into a reactive {get, set, on, off, save_changes} shape
    // (textbook anywidget model API) BEFORE it's ever passed as "model".
    // The bundle's bootstrap does this itself for the initial render --
    // my first attempt passed a plain object instead, which has no
    // .get() method at all, hence the crash. Fix: wrap filtered data
    // through the same Lre() the bundle already defines, so it has the
    // identical shape the internal render code expects.
    //
    // Lre is a true function DECLARATION (not a const/let assignment),
    // so unlike Ire/$9 (safe only because clicks can't fire mid-script),
    // this one is fully hoisted -- safely callable from anywhere in this
    // scope with no timing caveat needed at all.
    let isFocused = false;
    // null = showing the full graph (nothing filtered yet). Once
    // focused, holds the set of node ids currently on screen -- lets us
    // skip re-rendering entirely when a click lands on a node that's
    // already visible, since there's nothing new to show.
    let currentVisibleNodeIds = null;
    // Tracks the EXACT relationships the current cluster-building
    // function decided to include (e.g. getDataProductCluster
    // deliberately excludes FK_TO edges) -- kept separate from
    // currentVisibleNodeIds so a later resize can reuse this precise set
    // rather than re-deriving a broader one from scratch.
    let currentVisibleRels = null;

    // The selection ring is deliberately suppressed entirely rather than
    // chased further -- three real attempts to make it correctly follow
    // clicks (data-driven selected flag, call reordering, synthetic
    // click) were all confirmed unreliable. Setting selected:false on
    // every node was, in an earlier attempt, confirmed to reliably
    // produce "no ring anywhere" -- that's now the deliberate goal,
    // since a ring stuck on the wrong node is worse than no ring at all,
    // and the detail card already clearly identifies the clicked node
    // by name regardless.
    // ---- Hierarchy-aware drill-down ----
    //
    // Replaces a generic "walk any edge" BFS, which had a real bug: a
    // Gold table shared by multiple semantic views (a true, correct fact
    // about this data) would pull in ALL of those views' other,
    // unrelated tables too, since a symmetric walk has no concept of
    // "ownership" vs "just happens to be reachable". These rules instead
    // follow only the specific edge types and directions that make sense
    // for each node type, confirmed from how this project's own graph
    // model was built:
    //   DATA_PRODUCT --SHARED_AS--> SEMANTIC_VIEW (reversed from the
    //   underlying SQL's natural direction specifically so the
    //   hierarchical layout, which follows edge direction source-on-top,
    //   places Data Product above Semantic View -- see the swap in the
    //   Python nvl_rels construction, which this matches)
    //   SEMANTIC_VIEW --DEFINED_OVER--> TABLE (Gold)
    //   TABLE --HAS_COLUMN--> COLUMN
    //   SEMANTIC_VIEW --HAS_DIMENSION/HAS_FACT/HAS_METRIC--> item
    //   item --BELONGS_TO_LOGICAL_TABLE--> LOGICAL_TABLE
    //   downstream --DEPENDS_ON--> upstream (lineage, Gold -> Silver -> Raw)

    const relsWhere = (pred) => fullRels.filter(pred);

    // Walks DEPENDS_ON in one direction repeatedly until nothing new is
    // found -- a simple linear lineage chain, not a branching ownership
    // tree, so a plain repeated expansion (not full BFS bookkeeping) is
    // enough. direction: "upstream" follows from->to (Gold depends on
    // Silver depends on Raw); "downstream" follows to->from.
    const walkDependsOn = (startIds, direction) => {
        let frontier = new Set(startIds);
        const visited = new Set(startIds);
        const rels = [];
        for (let i = 0; i < 20; i++) {
            const next = new Set();
            fullRels.forEach((r) => {
                if (r.caption !== "DEPENDS_ON") return;
                const from = direction === "upstream" ? r.from : r.to;
                const to = direction === "upstream" ? r.to : r.from;
                if (!frontier.has(from)) return;
                rels.push(r);
                if (!visited.has(to)) {
                    visited.add(to);
                    next.add(to);
                }
            });
            frontier = next;
            if (frontier.size === 0) break;
        }
        return { nodeIds: visited, rels };
    };

    const getColumnsOf = (tableIds) => {
        const rels = relsWhere(
            (r) => r.caption === "HAS_COLUMN" && tableIds.has(r.from)
        );
        const nodeIds = new Set(rels.map((r) => r.to));
        return { nodeIds, rels };
    };

    // Semantic internals (logical tables, dimensions, facts, metrics) for
    // a given set of semantic views -- a two-step walk: the view's own
    // dimensions/facts/metrics, then each of those items' parent logical
    // table. These are inherently owned by exactly one semantic view
    // each (unlike Gold tables, which can be legitimately shared), so
    // there's no equivalent cross-contamination risk here.
    const getSemanticInternals = (semanticViewIds) => {
        const itemRels = relsWhere(
            (r) =>
                ["HAS_DIMENSION", "HAS_FACT", "HAS_METRIC"].includes(r.caption) &&
                semanticViewIds.has(r.from)
        );
        const itemIds = new Set(itemRels.map((r) => r.to));
        const logicalRels = relsWhere(
            (r) => r.caption === "BELONGS_TO_LOGICAL_TABLE" && itemIds.has(r.from)
        );
        const logicalIds = new Set(logicalRels.map((r) => r.to));
        const nodeIds = new Set([...itemIds, ...logicalIds]);
        return { nodeIds, rels: [...itemRels, ...logicalRels] };
    };

    const getTablesOf = (semanticViewIds) => {
        const rels = relsWhere(
            (r) => r.caption === "DEFINED_OVER" && semanticViewIds.has(r.from)
        );
        const nodeIds = new Set(rels.map((r) => r.to));
        return { nodeIds, rels };
    };

    const getSemanticViewsSharedToDataProduct = (semanticViewId) =>
        relsWhere((r) => r.caption === "SHARED_AS" && r.to === semanticViewId);

    const getOwningSemanticViews = (tableId) =>
        relsWhere((r) => r.caption === "DEFINED_OVER" && r.to === tableId);

    // Merges several {nodeIds, rels} partial results into one combined
    // node set + deduped relationship list.
    const mergeParts = (parts, extraNodeIds, extraRels) => {
        const nodeIds = new Set(extraNodeIds || []);
        const relsById = new Map();
        (extraRels || []).forEach((r) => relsById.set(r.id, r));
        parts.forEach((p) => {
            p.nodeIds.forEach((id) => nodeIds.add(id));
            p.rels.forEach((r) => relsById.set(r.id, r));
        });
        fullRels.forEach((r) => {
            if (r.caption === "FK_TO" && nodeIds.has(r.from) && nodeIds.has(r.to)) {
                relsById.set(r.id, r);
            }
        });
        return { nodeIds, rels: [...relsById.values()] };
    };

    const getDataProductCluster = (dataProductId) => {
        const sharedRels = relsWhere(
            (r) => r.caption === "SHARED_AS" && r.from === dataProductId
        );
        const semanticViewIds = new Set(sharedRels.map((r) => r.to));
        const tables = getTablesOf(semanticViewIds);
        const columns = getColumnsOf(tables.nodeIds);
        const internals = getSemanticInternals(semanticViewIds);
        const upstream = walkDependsOn(tables.nodeIds, "upstream");
        return mergeParts(
            [tables, columns, internals, upstream],
            [dataProductId, ...semanticViewIds],
            sharedRels
        );
    };

    const getSemanticViewCluster = (semanticViewId) => {
        // If this view belongs to a listing, show the WHOLE cluster
        // (the listing + all its semantic views), not just this one --
        // matching how a data-product click behaves.
        const sharedRels = getSemanticViewsSharedToDataProduct(semanticViewId);
        if (sharedRels.length > 0) {
            return getDataProductCluster(sharedRels[0].from);
        }
        // No listing -- standalone cluster rooted at just this view.
        const tables = getTablesOf(new Set([semanticViewId]));
        const columns = getColumnsOf(tables.nodeIds);
        const internals = getSemanticInternals(new Set([semanticViewId]));
        const upstream = walkDependsOn(tables.nodeIds, "upstream");
        return mergeParts([tables, columns, internals, upstream], [semanticViewId], []);
    };

    const getGoldTableCluster = (tableId) => {
        const upstream = walkDependsOn(new Set([tableId]), "upstream");
        // Gold tables are usually terminal (nothing else DEPENDS_ON
        // them), so this is often a no-op in practice -- but checking
        // both directions explicitly is more correct than assuming.
        const downstream = walkDependsOn(new Set([tableId]), "downstream");
        const columns = getColumnsOf(new Set([tableId]));
        const owningRels = getOwningSemanticViews(tableId);
        if (owningRels.length === 0) {
            // Not used by any semantic view -- pure lineage only,
            // nothing from the semantic layer above it.
            return mergeParts([upstream, downstream, columns], [tableId], []);
        }
        const semanticViewIds = new Set(owningRels.map((r) => r.from));
        // Deliberately NOT expanding each owning view's other tables --
        // that's the exact bug being fixed. Only the views themselves,
        // their own data product (if any), and their own internals.
        const dataProductRels = [];
        semanticViewIds.forEach((svId) => {
            dataProductRels.push(...getSemanticViewsSharedToDataProduct(svId));
        });
        const dataProductIds = new Set(dataProductRels.map((r) => r.from));
        const internals = getSemanticInternals(semanticViewIds);
        return mergeParts(
            [upstream, downstream, columns, internals],
            [tableId, ...semanticViewIds, ...dataProductIds],
            [...owningRels, ...dataProductRels]
        );
    };

    const getGenericLineageCluster = (nodeId) => {
        // Anything else (Silver views, Raw tables, or a Gold table
        // reached only via pure lineage) -- just its own DEPENDS_ON
        // chain in both directions, nothing from the semantic layer.
        const upstream = walkDependsOn(new Set([nodeId]), "upstream");
        const downstream = walkDependsOn(new Set([nodeId]), "downstream");
        return mergeParts([upstream, downstream], [nodeId], []);
    };

    const getNeighborhoodData = (nodeId) => {
        const node = fullNodes.find((n) => n.id === nodeId);
        const type = node && node.properties ? node.properties.type : null;
        const schema = node && node.properties ? node.properties.schema : null;

        let result;
        if (type === "DATA_PRODUCT") {
            result = getDataProductCluster(nodeId);
        } else if (type === "SEMANTIC_VIEW") {
            result = getSemanticViewCluster(nodeId);
        } else if (type === "TABLE" && schema === "DEV") {
            result = getGoldTableCluster(nodeId);
        } else {
            result = getGenericLineageCluster(nodeId);
        }

        const subsetNodes = fullNodes
            .filter((n) => result.nodeIds.has(n.id))
            .map((n) => {
                const base = Object.assign({}, n, { selected: false });
                // If this node has already settled somewhere in a
                // previous render (confirmed: the library mutates x/y
                // directly onto these same objects), pin it there so it
                // doesn't get swept up in a fresh layout pass. Genuinely
                // new nodes (first time reached) have no x/y yet and are
                // left unpinned, so they settle in naturally.
                if (typeof n.x === "number" && typeof n.y === "number") {
                    base.pinned = true;
                    base.x = n.x;
                    base.y = n.y;
                }
                return base;
            });
        return Object.assign({}, data, {
            nodes: subsetNodes,
            relationships: result.rels,
        });
    };

    // Forces a genuine re-render of whatever should currently be on
    // screen (the full graph, or the current filtered neighborhood if
    // one is active) -- used specifically after a fullscreen enter/exit
    // transition to make the canvas recompute its size correctly. A
    // generic window resize event alone isn't reliable for this (see
    // nudgeResize above), but we know Ire.render() genuinely works for
    // forcing a fresh layout pass, since it's the same mechanism the
    // neighborhood-focus feature already relies on. Existing settled
    // positions are preserved via the same pinning approach used
    // elsewhere, so this doesn't itself cause any reshuffling.
    // Shared by restoreFullGraph and the unfocused branch below -- the
    // sidebar-filtered default view, not the complete 342-node dataset,
    // with existing settled positions preserved the same way as the
    // drill-down views.
    const getDefaultViewPinned = () => {
        const nodes = fullNodes
            .filter((n) => defaultVisibleIds.has(n.id))
            .map((n) => {
                const base = Object.assign({}, n, { selected: false });
                if (typeof n.x === "number" && typeof n.y === "number") {
                    base.pinned = true;
                    base.x = n.x;
                    base.y = n.y;
                }
                return base;
            });
        const rels = fullRels.filter(
            (r) =>
                defaultVisibleIds.has(r.from) &&
                defaultVisibleIds.has(r.to) &&
                defaultEdgeTypes.has(r.caption)
        );
        return Object.assign({}, data, { nodes: nodes, relationships: rels });
    };

    const getUnusedTablesViewPinned = () => {
        const nodes = fullNodes
            .filter((n) => unusedTableIds.has(n.id))
            .map((n) => {
                const base = Object.assign({}, n, { selected: false });
                if (typeof n.x === "number" && typeof n.y === "number") {
                    base.pinned = true;
                    base.x = n.x;
                    base.y = n.y;
                }
                return base;
            });
        return Object.assign({}, data, { nodes: nodes, relationships: [] });
    };

    const rerenderAtCurrentSize = () => {
        if (!currentVisibleNodeIds) {
            Ire.render({ model: Lre(getDefaultViewPinned()), el: $9 });
            return;
        }
        const nodesToShow = fullNodes
            .filter((n) => currentVisibleNodeIds.has(n.id))
            .map((n) => {
                const base = Object.assign({}, n, { selected: false });
                if (typeof n.x === "number" && typeof n.y === "number") {
                    base.pinned = true;
                    base.x = n.x;
                    base.y = n.y;
                }
                return base;
            });
        // Reuse the exact relationships the original cluster-building
        // function decided to include -- NOT a generic "both endpoints
        // currently visible" filter. That generic approach was the actual
        // bug: it accidentally pulled in relationship types (e.g. FK_TO)
        // that the careful hierarchy-aware functions had deliberately
        // left out, which is why Expand/Exit (triggering this function
        // via nudgeResize) showed extra lines the normal view never had.
        const relsToShow = currentVisibleRels || [];
        Ire.render({
            model: Lre(
                Object.assign({}, data, { nodes: nodesToShow, relationships: relsToShow })
            ),
            el: $9,
        });
    };

    const focusOnNeighborhood = (nodeId) => {
        // The real fix: if this node is already part of what's currently
        // on screen, there's nothing new to show -- skip the re-render
        // entirely rather than reshuffle everything for no visual gain.
        // This is why "click the same node again" already held still --
        // not because pinning worked, but because nothing re-rendered at
        // all. Extending that same logic to any already-visible node.
        if (currentVisibleNodeIds && currentVisibleNodeIds.has(nodeId)) {
            return;
        }
        const neighborhoodData = getNeighborhoodData(nodeId);
        currentVisibleNodeIds = new Set(neighborhoodData.nodes.map((n) => n.id));
        currentVisibleRels = neighborhoodData.relationships;
        isFocused = true;
        Ire.render({ model: Lre(neighborhoodData), el: $9 });
        tryZoomToFit(150);
    };

    const restoreFullGraph = () => {
        if (!isFocused) return;
        isFocused = false;
        currentVisibleNodeIds = null;
        currentVisibleRels = null;
        Ire.render({ model: Lre(getDefaultViewPinned()), el: $9 });
    };

    const closeDetailPanel = () => {
        detailPanel.classList.remove("nvl-open");
        // Reset the inline position rather than just hiding the panel --
        // visibility:hidden/opacity:0 still occupies whatever position
        // was last set, so a stale left computed while the shell was at
        // fullscreen width (e.g. left: 1800px) would otherwise persist
        // and stretch the page's scrollable area even while invisible,
        // until the next click recalculated it fresh.
        detailPanel.style.left = "0px";
        detailPanel.style.top = "0px";
        // NOTE: deliberately does NOT call restoreFullGraph() -- closing
        // the popup should only dismiss the popup, leaving the zoomed
        // neighborhood view intact so exploration can continue. Returning
        // to the full graph is now a separate, explicit action (Home
        // button) rather than an automatic side effect of closing this.
    };

    detailClose.addEventListener("click", closeDetailPanel);

    const homeBtn = parentElement.querySelector('#nvl-home-btn');
    homeBtn.addEventListener("click", () => {
        // Deliberately does NOT call restoreFullGraph() -- that function
        // guards with "if (!isFocused) return", which assumed isFocused
        // === false always meant "already showing the default home
        // view". That broke once Unused Tables introduced a second,
        // separate view that also sets isFocused = false -- the guard
        // couldn't tell the two apart. Home is an explicit action and
        // should always force a return to the default view regardless
        // of whatever view we're currently on.
        closeDetailPanel();
        isFocused = false;
        currentVisibleNodeIds = null;
        currentVisibleRels = null;
        Ire.render({ model: Lre(getDefaultViewPinned()), el: $9 });
        tryZoomToFit(150);
    });

    const unusedBtn = parentElement.querySelector('#nvl-unused-btn');
    unusedBtn.addEventListener("click", () => {
        closeDetailPanel();
        isFocused = false;
        currentVisibleNodeIds = null;
        currentVisibleRels = null;
        Ire.render({ model: Lre(getUnusedTablesViewPinned()), el: $9 });
        tryZoomToFit(150);
    });

    // Initial page load -- longer delay than other callers since this
    // waits for the bundle's own first mount/render below to actually
    // complete, not just a quick rerender of already-mounted content.
    tryZoomToFit(700);

    // ---- Original neo4j-viz bundle begins here, unmodified except for the
    // earlier container-ID fix already applied below ----
"""


@st.cache_resource
def get_graph_component():
    """Register the graph as a true CCv2 component -- mounts directly in the
    page's own DOM rather than an iframe, which is specifically what makes
    the focus-mode CSS fallback able to cover the real browser viewport.
    isolate_styles=False is deliberate: the bundle injects its own <style>
    tags via document.head.appendChild() internally (confirmed earlier via
    direct grep of the bundle) -- Shadow DOM isolation (the default) would
    likely break that self-styling mechanism, since it creates a scoped
    boundary those document.head-targeted styles wouldn't cleanly cross.
    """
    with open("nvl_template.html", "r") as f:
        template = f.read()

    start_tag = '<script type="module" crossorigin>'
    end_tag = "</script>"
    start = template.find(start_tag) + len(start_tag)
    end = template.find(end_tag, start)
    bundle_js = template[start:end]

    # Same container-ID fix as before -- the bundle has this exact ID
    # hardcoded in from whenever it was originally extracted, and our own
    # div is deliberately named to match it here.
    bundle_js = bundle_js.replace("neo4j-viz-62e55b93f824", "neo4j-viz-root")

    # Patch the bundle's own compiled click handler to also call our
    # renderDetailPanel function (defined above, in the same closure scope
    # as the pasted bundle code below -- plain JS scoping, no postMessage
    # needed since there's no iframe boundary anymore). Confirmed exact
    # compiled line via direct grep of the bundle. The bundle's own
    # internal click handling (l({...})) is left untouched -- this only
    # adds a second thing that happens on the same click, it doesn't
    # replace anything.
    old_click = "mouseEventCallbacks:{onNodeClick:e=>l({type:`node_click`,id:String(e.id)})"
    new_click = (
        "mouseEventCallbacks:{onNodeClick:e=>{if(isFocused){renderDetailPanel(String(e.id));}"
        "setTimeout(()=>focusOnNeighborhood(String(e.id)),30)}"
    )
    if old_click in bundle_js:
        bundle_js = bundle_js.replace(old_click, new_click)
    # If the exact string isn't found (e.g. a future template regeneration
    # changed minified variable names), this silently no-ops -- the graph
    # and its own built-in panel still work, just without our extra panel.

    full_js = _NVL_JS_WRAPPER_HEAD + bundle_js + "\n}\n"

    return st.components.v2.component(
        name="tasty_bytes_graph_explorer",
        html=_NVL_HTML,
        css=_NVL_CSS,
        js=full_js,
        isolate_styles=False,
    )


nodes_df = load_nodes()
rels_df = load_rels()

# ── main canvas: a clean entity catalog, no connections ─────────────
# No sidebar -- "click to explore" is the only interaction model now.
# The canvas shows exactly these three entity types, as separate,
# unconnected nodes (defaultEdgeTypes is empty below); clicking any one
# reveals its full upstream/downstream lineage via the hierarchy-aware
# drill-down built into the graph component (see get_graph_component).
DEFAULT_NODE_TYPES = ["DATA_PRODUCT", "SEMANTIC_VIEW"]
mask = nodes_df["NODE_TYPE"].isin(DEFAULT_NODE_TYPES)
mask &= nodes_df["SCHEMA_NAME"].isin(["DEV"]) | nodes_df["SCHEMA_NAME"].isna()
visible_ids = set(nodes_df[mask]["NODEID"].tolist())

# Gold tables with no semantic view defined over them -- computed live
# from the actual DEFINED_OVER edges, not a hardcoded name list, so this
# stays correct as new tables/semantic views are added later.
defined_over_targets = set(
    rels_df[rels_df["RELATIONSHIP_TYPE"] == "DEFINED_OVER"]["TARGETNODEID"].tolist()
)
gold_table_mask = (nodes_df["NODE_TYPE"] == "TABLE") & (nodes_df["SCHEMA_NAME"] == "DEV")
unused_table_ids = set(
    nodes_df[gold_table_mask & ~nodes_df["NODEID"].isin(defined_over_targets)]["NODEID"].tolist()
)

highlight_dq = False  # no sidebar toggle anymore; DQ color-highlighting off by default


# ── DQ issue detection ─────────────────────────────────────────────
def has_dq_issue(row):
    if row.get("NODE_TYPE") != "COLUMN":
        return False
    dc = row.get("DQ_DUPLICATE_COUNT")
    if pd.notna(dc) and dc > 0:
        return True
    if row.get("IS_PRIMARY_KEY") == True:  # noqa: E712
        nc = row.get("DQ_NULL_COUNT")
        if pd.notna(nc) and nc > 0:
            return True
    return False


# ── build NVL graph data ──────────────────────────────────────────
# NOTE: iterates the COMPLETE dataset (nodes_df), not the sidebar-filtered
# "filtered" subset -- the drill-down feature (click a data product/
# semantic view/table) needs access to everything (columns, Raw/Silver
# lineage, semantic internals) regardless of what the sidebar's Node
# Type/Schema filters currently show by default. "visible_ids" (computed
# above from the sidebar filters) is passed separately below as
# defaultVisibleIds, used only for the initial, unfocused render.
nvl_nodes = []
for _, r in nodes_df.iterrows():
    nid = str(r["NODEID"])
    nt = r["NODE_TYPE"]
    caption = r["NAME"]
    # NOTE: a manual truncation step was tried here and reverted -- it
    # permanently capped the caption BEFORE NVL ever saw it, meaning no
    # amount of zooming could ever reveal more of the name, since the
    # extra characters were already discarded. NVL's own wrapping is
    # confirmed zoom-responsive (can show 3-4 lines at closer zoom), so
    # it needs the full, untruncated name to actually make use of that.

    color = NODE_COLORS.get(nt, "#95A5A6")
    if r.get("IS_PRIMARY_KEY") == True:  # noqa: E712
        color = "#FFD700"
    if highlight_dq and has_dq_issue(r):
        color = "#E74C3C"

    # Sizes bumped up from the original 30/22/12 -- labels were getting
    # hard-truncated. Note: the bundle scales font size in exact fixed
    # proportion to node size (confirmed directly from rendered SVG output:
    # font-size / size = 0.2597 constant), so this helps absolute
    # readability but may not fully eliminate wrapping on the very longest
    # names (e.g. DIM_MENU_ITEM_HEALTH_METRICS) -- shortening captions
    # would be the complementary fix if this alone isn't enough.
    size = (
        85
        if nt in ("SEMANTIC_VIEW", "DATA_PRODUCT")
        else 65 if nt == "TABLE"
        else 48 if nt in ("VIEW", "LOGICAL_TABLE") else 16
    )

    # Full property set -- everything the old bottom "Node Detail" panel
    # showed, now shown here instead, since this panel already updates
    # instantly on click with zero reload (it's entirely internal to the
    # iframe, no bridge to Python involved at all).
    props = {
        "name": str(r.get("NAME", "")),
        "type": nt,
        "fqn": str(r.get("FQN", "")),
    }
    if pd.notna(r.get("DESCRIPTION")):
        clean_description = strip_html(str(r["DESCRIPTION"]))
        if clean_description:
            props["description"] = clean_description
    if pd.notna(r.get("SCHEMA_NAME")):
        props["schema"] = str(r["SCHEMA_NAME"])
    if pd.notna(r.get("DATA_TYPE")):
        props["data_type"] = str(r["DATA_TYPE"])
    if r.get("IS_PRIMARY_KEY") == True:  # noqa: E712
        props["primary_key"] = "yes"
    if r.get("IS_FOREIGN_KEY") == True:  # noqa: E712
        props["foreign_key"] = "yes"
    if pd.notna(r.get("CONSTRAINT_NAME")):
        props["constraint"] = str(r["CONSTRAINT_NAME"])
    if nt in ("TABLE", "VIEW"):
        props["dmf_monitoring"] = (
            "active" if r.get("HAS_DMF") == True else "not monitored"  # noqa: E712
        )
    if pd.notna(r.get("DQ_ROW_COUNT")):
        props["row_count"] = f"{int(r['DQ_ROW_COUNT']):,}"
    if pd.notna(r.get("DQ_FRESHNESS")):
        props["freshness"] = f"{int(r['DQ_FRESHNESS']):,}s since last order"
    if pd.notna(r.get("DQ_NULL_COUNT")):
        pct = r.get("DQ_NULL_PERCENT", 0)
        pct = pct if pd.notna(pct) else 0
        props["null_count"] = f"{int(r['DQ_NULL_COUNT']):,} ({pct:.2f}%)"
    if pd.notna(r.get("DQ_DUPLICATE_COUNT")):
        props["duplicate_count"] = f"{int(r['DQ_DUPLICATE_COUNT']):,}"
    if pd.notna(r.get("LAST_DQ_MEASUREMENT_TIME")):
        props["last_dq_check"] = str(r["LAST_DQ_MEASUREMENT_TIME"])

    # Computed DQ verdict -- same logic has_dq_issue() already applies for
    # the red-highlight color, now also surfaced as a plain-language message
    # so it shows up right here instead of only affecting node color.
    if nt == "COLUMN":
        if has_dq_issue(r):
            props["dq_status"] = (
                "⚠ Issue: duplicates on a unique column, or nulls on a primary key"
            )
        elif pd.notna(r.get("DQ_NULL_COUNT")) and r.get("DQ_NULL_COUNT") > 0:
            props["dq_status"] = (
                "ℹ Informational -- elevated null rate is expected here "
                "(e.g. non-loyalty-member orders), not a data quality problem"
            )
        elif pd.notna(r.get("DQ_DUPLICATE_COUNT")) or pd.notna(
            r.get("DQ_NULL_COUNT")
        ):
            props["dq_status"] = "✓ No issues detected"

    nvl_nodes.append({
        "id": nid, "caption": caption, "size": size,
        "color": color, "properties": props,
    })

nvl_rels = []
for _, e in rels_df.iterrows():
    rt = e["RELATIONSHIP_TYPE"]
    src, tgt = str(e["SOURCENODEID"]), str(e["TARGETNODEID"])
    src_name, tgt_name = e["SOURCE_NAME"], e["TARGET_NAME"]
    if rt == "SHARED_AS":
        # Swapped specifically for this relationship type -- see note
        # above DATA_PRODUCT/SEMANTIC_VIEW drill-down functions, which
        # were updated to match this same new direction.
        src, tgt = tgt, src
        src_name, tgt_name = tgt_name, src_name
    nvl_rels.append({
        "id": uuid.uuid4().hex,
        "from": src,
        "to": tgt,
        "caption": rt,
        "color": EDGE_COLORS.get(rt, "#BDC3C7"),
        "properties": {
            "source": src_name,
            "target": tgt_name,
        },
    })

GRAPH_HEIGHT = 700

nvl_data = {
    "nodes": nvl_nodes,
    "relationships": nvl_rels,
    "defaultVisibleIds": [str(x) for x in visible_ids],
    "unusedTableIds": [str(x) for x in unused_table_ids],
    "defaultEdgeTypes": [],
    "width": "100%",
    "height": "100%",
    "componentHeight": GRAPH_HEIGHT,
    "theme": "light",
    "options": {
        "layout": "hierarchical",
        "nvlOptions": {
            "disableWebGL": True,
            "minZoom": 0.075,
            "maxZoom": 10.0,
            "allowDynamicMinZoom": True,
        },
        "showLayoutButton": True,
        "showSearchButton": True,
    },
    "legend": {"visible": True},
}

NODE_TYPE_LABELS = {
    "TABLE": "Table",
    "VIEW": "View (staging)",
    "SEMANTIC_VIEW": "Semantic View",
    "DATA_PRODUCT": "Data Product (listing)",
    "COLUMN": "Column",
    "LOGICAL_TABLE": "Logical Table",
    "DIMENSION": "Dimension",
    "FACT": "Fact",
    "METRIC": "Metric",
}
EDGE_TYPE_LABELS = {
    "FK_TO": "Foreign key reference",
    "DEPENDS_ON": "Depends on (lineage)",
    "DEFINED_OVER": "Defined over (semantic view → base table)",
    "SHARED_AS": "Shared as (Data Product → semantic view)",
    "HAS_COLUMN": "Has column",
    "BELONGS_TO_LOGICAL_TABLE": "Belongs to logical table",
    "HAS_DIMENSION": "Has dimension",
    "HAS_FACT": "Has fact",
    "HAS_METRIC": "Has metric",
    "REFERENCES": "References (semantic FK)",
}


def _swatch(color, label, shape="circle"):
    if shape == "circle":
        marker = (
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'border-radius:50%;background:{color};margin-right:6px;'
            f'vertical-align:middle;"></span>'
        )
    else:
        marker = (
            f'<span style="display:inline-block;width:20px;height:3px;'
            f'background:{color};margin-right:6px;vertical-align:middle;">'
            f"</span>"
        )
    st.markdown(f"{marker}{label}", unsafe_allow_html=True)


with st.expander("🎨 Legend — what the colors mean", expanded=False):
    leg_col1, leg_col2 = st.columns(2)
    with leg_col1:
        st.markdown("**Node types**")
        for nt, color in NODE_COLORS.items():
            _swatch(color, NODE_TYPE_LABELS.get(nt, nt), "circle")
        st.markdown("---")
        _swatch("#FFD700", "Primary key column", "circle")
        _swatch(
            "#E74C3C",
            'DQ issue (only when "Highlight DQ issues" is on)',
            "circle",
        )
    with leg_col2:
        st.markdown("**Relationship types** (shown when you click into an entity's lineage)")
        for rt, color in EDGE_COLORS.items():
            _swatch(color, EDGE_TYPE_LABELS.get(rt, rt), "line")

graph_component = get_graph_component()
graph_component(data=nvl_data, height=GRAPH_HEIGHT, key="tasty_bytes_graph")

# ── algorithm panel ────────────────────────────────────────────────
if SHOW_GRAPH_ALGORITHMS:
    st.markdown("### Graph Algorithms")


    def run_algo(name, sql):
        with st.spinner(f"Running {name}... (20-30s)"):
            try:
                session.sql(sql).collect()
                st.success(f"{name} complete!")
                load_algo_results.clear()
            except Exception as e:
                st.error(f"{name} failed: {e}")


    WCC_SQL = (
        "CALL NEO4J_GRAPH_ANALYTICS.graph.wcc('CPU_X64_XS', {"
        "'defaultTablePrefix': 'NEO4J_LINEAGE_DB.PUBLIC',"
        "'project': {"
        "  'nodeTables': ['GRAPH_NODES_VW'],"
        "  'relationshipTables': {"
        "    'GRAPH_RELS_VW': {"
        "      'sourceTable': 'GRAPH_NODES_VW',"
        "      'targetTable': 'GRAPH_NODES_VW',"
        "      'orientation': 'UNDIRECTED'"
        "    }"
        "  }"
        "},"
        "'compute': { 'consecutiveIds': true },"
        "'write': [{ 'nodeLabel': 'GRAPH_NODES_VW',"
        "  'outputTable': 'result_wcc_lineage_components' }]"
        "})"
    )

    PR_SQL = (
        "CALL NEO4J_GRAPH_ANALYTICS.graph.page_rank('CPU_X64_XS', {"
        "'defaultTablePrefix': 'NEO4J_LINEAGE_DB.PUBLIC',"
        "'project': {"
        "  'nodeTables': ['GRAPH_NODES_VW'],"
        "  'relationshipTables': {"
        "    'GRAPH_RELS_VW': {"
        "      'sourceTable': 'GRAPH_NODES_VW',"
        "      'targetTable': 'GRAPH_NODES_VW',"
        "      'orientation': 'NATURAL'"
        "    }"
        "  }"
        "},"
        "'compute': {},"
        "'write': [{ 'nodeLabel': 'GRAPH_NODES_VW',"
        "  'outputTable': 'result_pagerank_lineage_centrality' }]"
        "})"
    )

    LV_SQL = (
        "CALL NEO4J_GRAPH_ANALYTICS.graph.louvain('CPU_X64_XS', {"
        "'defaultTablePrefix': 'NEO4J_LINEAGE_DB.PUBLIC',"
        "'project': {"
        "  'nodeTables': ['GRAPH_NODES_VW'],"
        "  'relationshipTables': {"
        "    'GRAPH_RELS_VW': {"
        "      'sourceTable': 'GRAPH_NODES_VW',"
        "      'targetTable': 'GRAPH_NODES_VW',"
        "      'orientation': 'UNDIRECTED'"
        "    }"
        "  }"
        "},"
        "'compute': { 'consecutiveIds': true },"
        "'write': [{ 'nodeLabel': 'GRAPH_NODES_VW',"
        "  'outputTable': 'result_louvain_lineage_communities' }]"
        "})"
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Run WCC", use_container_width=True):
            run_algo("WCC", WCC_SQL)
        if st.button("Run PageRank", use_container_width=True):
            run_algo("PageRank", PR_SQL)
    with c2:
        if st.button("Run Louvain", use_container_width=True):
            run_algo("Louvain", LV_SQL)
        if st.button("Refresh Data", use_container_width=True):
            load_nodes.clear()
            load_rels.clear()
            load_algo_results.clear()
            st.rerun()

    for label, table, col_name in [
        ("PageRank", "RESULT_PAGERANK_LINEAGE_CENTRALITY", "PAGERANK"),
        ("WCC Components", "RESULT_WCC_LINEAGE_COMPONENTS", "COMPONENT"),
        ("Louvain Communities", "RESULT_LOUVAIN_LINEAGE_COMMUNITIES", "COMMUNITY"),
    ]:
        rdf = load_algo_results(table)
        if rdf is not None and len(rdf) > 0:
            with st.expander(f"{label} Results", expanded=(label == "PageRank")):
                merged = rdf.merge(
                    nodes_df[["NODEID", "NODE_TYPE", "NAME", "FQN", "SCHEMA_NAME"]],
                    on="NODEID",
                    how="inner",
                )
                if col_name == "PAGERANK":
                    merged = merged.sort_values("PAGERANK", ascending=False).head(15)
                    st.dataframe(
                        merged[["NODE_TYPE", "NAME", "SCHEMA_NAME", "PAGERANK"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    summary = (
                        merged.groupby(col_name)
                        .agg(
                            nodes=("NODEID", "count"),
                            types=(
                                "NODE_TYPE",
                                lambda x: ", ".join(sorted(x.unique())),
                            ),
                        )
                        .sort_values("nodes", ascending=False)
                        .head(15)
                    )
                    st.dataframe(summary, use_container_width=True)