import cytoscape from "cytoscape";

function asText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch (_) {
    return String(value);
  }
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function normaliseLabelText(value) {
  return asText(value)
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function splitLongWord(word, maxCharacters) {
  const parts = [];
  for (let index = 0; index < word.length; index += maxCharacters) {
    parts.push(word.slice(index, index + maxCharacters));
  }
  return parts;
}

function wrapWords(value, maxCharacters) {
  const text = normaliseLabelText(value);
  if (!text) return [];

  const tokens = text
    .split(" ")
    .flatMap((token) =>
      token.length > maxCharacters
        ? splitLongWord(token, maxCharacters)
        : [token]
    );

  const lines = [];
  let current = "";
  for (const token of tokens) {
    const candidate = current ? `${current} ${token}` : token;
    if (candidate.length <= maxCharacters || !current) {
      current = candidate;
    } else {
      lines.push(current);
      current = token;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function hasClass(element, className) {
  const classValue = Array.isArray(element?.classes)
    ? element.classes.join(" ")
    : asText(element?.classes);
  return classValue.split(/\s+/).includes(className);
}

function isEdgeElement(element) {
  const data = element?.data || {};
  return Object.prototype.hasOwnProperty.call(data, "source") &&
    Object.prototype.hasOwnProperty.call(data, "target");
}

function nodePresentation(element) {
  const rawLabel = asText(
    element?.data?.label || element?.data?.object_name || "Object"
  );
  const rawLines = rawLabel.split(/\r?\n/).filter(Boolean);
  const name = rawLines.shift() || rawLabel;
  const typeLine = rawLines.join(" ");

  const isSemantic = hasClass(element, "semantic-view");
  const isLogical = hasClass(element, "logical-table");
  const isAgent = hasClass(element, "cortex-agent");
  const isStage = hasClass(element, "stage");

  const maxCharacters = isSemantic ? 22 : isLogical ? 21 : isAgent ? 16 : 20;
  const nameLines = wrapWords(name, maxCharacters);
  const typeLines = typeLine ? wrapWords(typeLine, maxCharacters) : [];
  const displayLines = [...nameLines, ...typeLines];
  const displayLabel = displayLines.join("\n") || normaliseLabelText(rawLabel);
  const longestLine = Math.max(1, ...displayLines.map((line) => line.length));

  let minimumWidth = 168;
  let maximumWidth = 250;
  let horizontalPadding = 34;
  let minimumHeight = 66;
  let verticalPadding = 28;

  if (isSemantic) {
    minimumWidth = 220;
    maximumWidth = 300;
    horizontalPadding = 74;
    minimumHeight = 96;
    verticalPadding = 36;
  } else if (isLogical) {
    minimumWidth = 195;
    maximumWidth = 280;
    horizontalPadding = 52;
    minimumHeight = 80;
    verticalPadding = 30;
  } else if (isAgent) {
    minimumWidth = 130;
    maximumWidth = 190;
    horizontalPadding = 48;
    minimumHeight = 112;
    verticalPadding = 40;
  } else if (isStage) {
    minimumWidth = 176;
    maximumWidth = 260;
    horizontalPadding = 40;
    minimumHeight = 72;
  }

  const nodeWidth = Math.round(
    clamp(longestLine * 7.1 + horizontalPadding, minimumWidth, maximumWidth)
  );
  const lineCount = Math.max(1, displayLines.length);
  const nodeHeight = Math.round(
    clamp(lineCount * 16 + verticalPadding, minimumHeight, 154)
  );
  const textMaxWidth = Math.max(
    80,
    nodeWidth - (isSemantic ? 68 : isLogical ? 46 : 30)
  );

  return {
    display_label: displayLabel,
    node_width: nodeWidth,
    node_height: nodeHeight,
    text_max_width: textMaxWidth
  };
}

function prepareElements(elements) {
  return elements.map((element) => {
    if (isEdgeElement(element)) return element;
    return {
      ...element,
      data: {
        ...(element?.data || {}),
        ...nodePresentation(element)
      }
    };
  });
}

function mean(values) {
  if (!values.length) return Number.POSITIVE_INFINITY;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function regularNodes(elements) {
  return elements.filter(
    (element) => !isEdgeElement(element) && !hasClass(element, "layer-header")
  );
}

function addLayerHeaders(elements) {
  const layers = new Map();
  for (const element of regularNodes(elements)) {
    const data = element.data || {};
    const layerKey = asText(data.layer_key || "other");
    if (!layers.has(layerKey)) {
      layers.set(layerKey, {
        key: layerKey,
        label: asText(data.layer_label || layerKey),
        order: Number(data.layer_order ?? 0)
      });
    }
  }

  const headers = [...layers.values()].map((layer) => ({
    data: {
      id: `__layer_header__${layer.key}`,
      label: layer.label,
      display_label: layer.label,
      object_name: layer.label,
      object_type: "LAYER_HEADER",
      domain: "LAYER_HEADER",
      layer_key: layer.key,
      layer_label: layer.label,
      layer_order: layer.order,
      node_width: 226,
      node_height: 46,
      text_max_width: 206
    },
    classes: `layer-header layer-${layer.key}`,
    selectable: false,
    grabbable: false,
    locked: true
  }));
  return [...elements, ...headers];
}

function layeredPositions(elements) {
  const nodes = regularNodes(elements);
  const nodeById = new Map(nodes.map((node) => [asText(node.data.id), node]));
  const incoming = new Map(nodes.map((node) => [asText(node.data.id), []]));
  const outgoing = new Map(nodes.map((node) => [asText(node.data.id), []]));

  for (const edge of elements.filter(isEdgeElement)) {
    const source = asText(edge.data.source);
    const target = asText(edge.data.target);
    if (nodeById.has(source) && nodeById.has(target)) {
      outgoing.get(source).push(target);
      incoming.get(target).push(source);
    }
  }

  const byLayer = new Map();
  for (const node of nodes) {
    const order = Number(node.data.layer_order ?? 0);
    if (!byLayer.has(order)) byLayer.set(order, []);
    byLayer.get(order).push(node);
  }
  const layerOrders = [...byLayer.keys()].sort((a, b) => a - b);

  const stableNodeSort = (left, right) => {
    const leftGroup = Number(left.data.layer_subgroup_order ?? 0);
    const rightGroup = Number(right.data.layer_subgroup_order ?? 0);
    if (leftGroup !== rightGroup) return leftGroup - rightGroup;
    const leftIsolated = left.data.is_isolated ? 1 : 0;
    const rightIsolated = right.data.is_isolated ? 1 : 0;
    if (leftIsolated !== rightIsolated) return leftIsolated - rightIsolated;
    return asText(left.data.object_name || left.data.label).localeCompare(
      asText(right.data.object_name || right.data.label)
    );
  };
  layerOrders.forEach((order) => byLayer.get(order).sort(stableNodeSort));

  const indexMap = () => {
    const result = new Map();
    for (const order of layerOrders) {
      byLayer.get(order).forEach((node, index) => {
        result.set(asText(node.data.id), index);
      });
    }
    return result;
  };

  for (let iteration = 0; iteration < 4; iteration += 1) {
    let indices = indexMap();
    for (let layerIndex = 1; layerIndex < layerOrders.length; layerIndex += 1) {
      const order = layerOrders[layerIndex];
      byLayer.get(order).sort((left, right) => {
        const groupDifference =
          Number(left.data.layer_subgroup_order ?? 0) -
          Number(right.data.layer_subgroup_order ?? 0);
        if (groupDifference !== 0) return groupDifference;
        const leftScore = mean(
          (incoming.get(asText(left.data.id)) || [])
            .filter((id) => indices.has(id))
            .map((id) => indices.get(id))
        );
        const rightScore = mean(
          (incoming.get(asText(right.data.id)) || [])
            .filter((id) => indices.has(id))
            .map((id) => indices.get(id))
        );
        if (leftScore !== rightScore) return leftScore - rightScore;
        return stableNodeSort(left, right);
      });
      indices = indexMap();
    }

    indices = indexMap();
    for (let layerIndex = layerOrders.length - 2; layerIndex >= 0; layerIndex -= 1) {
      const order = layerOrders[layerIndex];
      byLayer.get(order).sort((left, right) => {
        const groupDifference =
          Number(left.data.layer_subgroup_order ?? 0) -
          Number(right.data.layer_subgroup_order ?? 0);
        if (groupDifference !== 0) return groupDifference;
        const leftScore = mean(
          (outgoing.get(asText(left.data.id)) || [])
            .filter((id) => indices.has(id))
            .map((id) => indices.get(id))
        );
        const rightScore = mean(
          (outgoing.get(asText(right.data.id)) || [])
            .filter((id) => indices.has(id))
            .map((id) => indices.get(id))
        );
        if (leftScore !== rightScore) return leftScore - rightScore;
        return stableNodeSort(left, right);
      });
      indices = indexMap();
    }
  }

  const horizontalGap = 76;
  const verticalGap = 225;
  const rowWidths = new Map();
  for (const order of layerOrders) {
    const row = byLayer.get(order);
    const totalWidth = row.reduce(
      (total, node) => total + Number(node.data.node_width || 170),
      horizontalGap * Math.max(0, row.length - 1)
    );
    rowWidths.set(order, totalWidth);
  }
  const maximumRowWidth = Math.max(300, ...rowWidths.values());
  const positions = new Map();

  layerOrders.forEach((order, displayIndex) => {
    const row = byLayer.get(order);
    const rowWidth = rowWidths.get(order);
    let cursor = -rowWidth / 2;
    const y = (layerOrders.length - 1 - displayIndex) * verticalGap;
    for (const node of row) {
      const width = Number(node.data.node_width || 170);
      positions.set(asText(node.data.id), {
        x: cursor + width / 2,
        y
      });
      cursor += width + horizontalGap;
    }
    positions.set(`__layer_header__${asText(row[0]?.data?.layer_key)}`, {
      x: -maximumRowWidth / 2 - 175,
      y
    });
  });

  return positions;
}

function withPresetPositions(elements) {
  const enriched = addLayerHeaders(prepareElements(elements));
  const positions = layeredPositions(enriched);
  return enriched.map((element) => {
    if (isEdgeElement(element)) return element;
    const position = positions.get(asText(element.data.id));
    return position ? { ...element, position } : element;
  });
}

function graphStyles(showEdgeLabels) {
  return [
    {
      selector: "node",
      style: {
        width: "data(node_width)",
        height: "data(node_height)",
        shape: "round-rectangle",
        "background-color": "#4c78a8",
        "border-width": 1.5,
        "border-color": "#2f4b6c",
        label: "data(display_label)",
        color: "#ffffff",
        "font-size": 12,
        "font-weight": 600,
        "text-wrap": "wrap",
        "text-max-width": "data(text_max_width)",
        "text-valign": "center",
        "text-halign": "center",
        "text-justification": "center",
        "line-height": 1.15,
        "overlay-opacity": 0,
        "transition-property": "opacity, border-width, border-color",
        "transition-duration": "160ms"
      }
    },
    {
      selector: "node.view",
      style: {
        "background-color": "#72b7b2",
        "border-color": "#3d7773"
      }
    },
    {
      selector: "node.materialized-view",
      style: {
        "background-color": "#54a24b",
        "border-color": "#32612d"
      }
    },
    {
      selector: "node.dynamic-table",
      style: {
        "background-color": "#59a14f",
        "border-style": "double",
        "border-width": 4,
        "border-color": "#2f6430"
      }
    },
    {
      selector: "node.semantic-view",
      style: {
        shape: "hexagon",
        "background-color": "#f58518",
        "border-color": "#a54d00",
        "font-size": 12.5
      }
    },
    {
      selector: "node.logical-table",
      style: {
        shape: "tag",
        "background-color": "#b279a2",
        "border-color": "#784b6b"
      }
    },
    {
      selector: "node.stage",
      style: {
        shape: "barrel",
        "background-color": "#eeca3b",
        "border-color": "#9a7d08",
        color: "#1f1f1f"
      }
    },
    {
      selector: "node.cortex-agent",
      style: {
        shape: "diamond",
        "background-color": "#ff9da6",
        "border-color": "#a24d56",
        color: "#222222"
      }
    },
    {
      selector: "node.external",
      style: {
        shape: "ellipse",
        "background-color": "#9d755d",
        "border-color": "#624536"
      }
    },
    {
      selector: "node.dataset, node.model",
      style: {
        shape: "diamond",
        "background-color": "#bab0ab",
        "border-color": "#6c6662",
        color: "#202020"
      }
    },
    {
      selector: "node.anchor",
      style: {
        "border-width": 5,
        "border-color": "#e45756",
        "underlay-color": "#e45756",
        "underlay-opacity": 0.15,
        "underlay-padding": 9
      }
    },
    {
      selector: "node.scope-external",
      style: {
        "border-style": "dashed",
        "border-width": 3,
        opacity: 0.82
      }
    },
    {
      selector: "node.isolated",
      style: {
        "border-style": "dashed"
      }
    },
    {
      selector: "node.masked",
      style: {
        opacity: 0.55,
        "border-style": "dashed"
      }
    },
    {
      selector: "node.layer-header",
      style: {
        shape: "round-rectangle",
        width: "data(node_width)",
        height: "data(node_height)",
        "background-color": "#eef2f7",
        "background-opacity": 0.96,
        "border-width": 1,
        "border-color": "#c8d2df",
        label: "data(display_label)",
        color: "#243447",
        "font-size": 13,
        "font-weight": 700,
        "text-wrap": "wrap",
        "text-max-width": "data(text_max_width)",
        "text-valign": "center",
        "text-halign": "center",
        events: "no",
        "overlay-opacity": 0,
        "z-index": 1
      }
    },
    {
      selector: "node.layer-source",
      style: { "border-color": "#d4af1e" }
    },
    {
      selector: "node.layer-semantic",
      style: { "border-color": "#e36f00" }
    },
    {
      selector: "node.layer-consumer",
      style: { "border-color": "#d66a78" }
    },
    {
      selector: "edge",
      style: {
        width: 2.2,
        "line-color": "#87919c",
        "target-arrow-color": "#87919c",
        "target-arrow-shape": "triangle",
        "arrow-scale": 1.05,
        "curve-style": "taxi",
        "taxi-direction": "upward",
        "taxi-turn": "50%",
        "taxi-turn-min-distance": 18,
        "taxi-radius": 8,
        label: showEdgeLabels ? "data(label)" : "",
        color: "#4f4f4f",
        "font-size": 9,
        "font-weight": 600,
        "text-rotation": "autorotate",
        "text-background-color": "#ffffff",
        "text-background-opacity": 0.9,
        "text-background-padding": 2,
        "text-border-width": 0.5,
        "text-border-color": "#d0d0d0",
        "text-border-opacity": 0.85,
        "overlay-opacity": 0,
        "z-index": 8
      }
    },
    {
      selector: "edge.hovered, edge:selected",
      style: {
        label: "data(label)",
        width: 3.2,
        "line-color": "#e45756",
        "target-arrow-color": "#e45756"
      }
    },
    {
      selector: "edge.semantic-relationship",
      style: {
        width: 3,
        "line-color": "#b279a2",
        "target-arrow-color": "#b279a2",
        "line-style": "dashed",
        "curve-style": "bezier"
      }
    },
    {
      selector: "edge.base-table-edge",
      style: {
        "line-color": "#4c78a8",
        "target-arrow-color": "#4c78a8"
      }
    },
    {
      selector: "edge.semantic-membership, edge.semantic-lineage",
      style: {
        width: 3,
        "line-color": "#f58518",
        "target-arrow-color": "#f58518"
      }
    },
    {
      selector: ":selected",
      style: {
        "border-width": 5,
        "border-color": "#e45756"
      }
    },
    {
      selector: ".search-muted",
      style: { opacity: 0.12 }
    },
    {
      selector: ".search-match",
      style: {
        opacity: 1,
        "border-width": 5,
        "border-color": "#eeca3b"
      }
    }
  ];
}

function applySearch(cy, query) {
  const normalized = (query || "").trim().toLowerCase();
  cy.elements().removeClass("search-muted search-match");
  if (!normalized) return;

  cy.nodes().not(".layer-header").forEach((node) => {
    const dataText = Object.values(node.data()).map(asText).join(" ").toLowerCase();
    if (dataText.includes(normalized)) {
      node.addClass("search-match");
      node.connectedEdges().addClass("search-match");
      node.neighborhood("node").addClass("search-match");
    } else {
      node.addClass("search-muted");
    }
  });

  cy.edges().forEach((edge) => {
    const sourceMatch = edge.source().hasClass("search-match");
    const targetMatch = edge.target().hasClass("search-match");
    if (!sourceMatch && !targetMatch) edge.addClass("search-muted");
  });
}

function selectedPayload(kind, element) {
  return {
    kind,
    data: element.data(),
    classes: element.classes(),
    position: kind === "node" ? element.position() : null,
    selected_at: Date.now()
  };
}

function canExplore(node) {
  if (!node || node.hasClass("layer-header")) return false;
  const data = node.data();
  return Boolean(data.database && data.schema && data.object_name && data.domain);
}

export default function componentRenderer(component) {
  const { data, parentElement, setStateValue } = component;
  const shell = parentElement.querySelector(".cy-shell");
  const container = parentElement.querySelector("#cy");
  const zoomInButton = parentElement.querySelector('[data-action="zoom-in"]');
  const zoomOutButton = parentElement.querySelector('[data-action="zoom-out"]');
  const fitButton = parentElement.querySelector('[data-action="fit"]');
  const centerButton = parentElement.querySelector('[data-action="center"]');
  const exploreButton = parentElement.querySelector('[data-action="explore"]');
  const expandButton = parentElement.querySelector('[data-action="expand"]');
  const zoomLevel = parentElement.querySelector('[data-role="zoom-level"]');
  const tooltip = parentElement.querySelector('[data-role="tooltip"]');

  if (!shell || !container) return undefined;

  const rawElements = Array.isArray(data?.elements) ? data.elements : [];
  const elements = withPresetPositions(rawElements);
  const anchorId = data?.anchor_id || null;
  const requestedWheelSensitivity = Number(data?.wheel_sensitivity ?? 0.9);
  const wheelSensitivity = Number.isFinite(requestedWheelSensitivity)
    ? clamp(requestedWheelSensitivity, 0.05, 2)
    : 0.9;

  const cy = cytoscape({
    container,
    elements,
    style: graphStyles(Boolean(data?.show_edge_labels)),
    layout: { name: "preset", fit: false },
    minZoom: 0.08,
    maxZoom: 5,
    wheelSensitivity,
    boxSelectionEnabled: true,
    autounselectify: false,
    selectionType: "single"
  });

  cy.nodes(".layer-header").lock();
  applySearch(cy, data?.search || "");

  let selectedNode = null;
  let focusMode = false;
  let previousBodyOverflow = "";

  const selectableElements = () => cy.elements().not(".layer-header");
  const viewportCenter = () => ({
    x: Math.max(0, container.clientWidth / 2),
    y: Math.max(0, container.clientHeight / 2)
  });
  const updateZoomLevel = () => {
    if (zoomLevel) zoomLevel.textContent = `${Math.round(cy.zoom() * 100)}%`;
  };
  const updateExploreButton = () => {
    if (exploreButton) exploreButton.disabled = !canExplore(selectedNode);
  };
  const setZoom = (level) => {
    const boundedLevel = clamp(level, cy.minZoom(), cy.maxZoom());
    cy.zoom({ level: boundedLevel, renderedPosition: viewportCenter() });
    updateZoomLevel();
  };
  const zoomIn = () => setZoom(cy.zoom() * 1.25);
  const zoomOut = () => setZoom(cy.zoom() / 1.25);
  const fitGraph = () => {
    cy.resize();
    cy.fit(cy.elements(":visible"), focusMode ? 95 : 75);
    updateZoomLevel();
  };
  const activeNode = () => {
    if (selectedNode && !selectedNode.removed()) return selectedNode;
    if (anchorId) {
      const anchor = cy.$id(anchorId);
      if (anchor.nonempty()) return anchor;
    }
    const first = cy.nodes().not(".layer-header").first();
    return first.nonempty() ? first : null;
  };
  const centerSelected = () => {
    const node = activeNode();
    if (!node) return;
    cy.center(node);
    if (cy.zoom() < 0.72) setZoom(0.82);
    updateZoomLevel();
  };
  const exploreSelected = () => {
    const node = activeNode();
    if (!canExplore(node)) return;
    setStateValue("explore", selectedPayload("node", node));
  };

  const hideTooltip = () => {
    if (tooltip) tooltip.hidden = true;
  };
  const showTooltip = (event) => {
    if (!tooltip || event.target.hasClass("layer-header")) return;
    const nodeData = event.target.data();
    tooltip.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = asText(nodeData.object_name || nodeData.label || "Object");
    const details = document.createElement("span");
    details.textContent = [nodeData.object_type, nodeData.layer_label]
      .filter(Boolean)
      .join(" · ");
    tooltip.append(title, details);

    const shellRect = shell.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const point = event.renderedPosition || { x: 0, y: 0 };
    tooltip.style.left = `${containerRect.left - shellRect.left + point.x + 14}px`;
    tooltip.style.top = `${containerRect.top - shellRect.top + point.y + 14}px`;
    tooltip.hidden = false;
  };

  const nodeTap = (event) => {
    selectedNode = event.target;
    setStateValue("selected", selectedPayload("node", event.target));
    updateExploreButton();
  };
  const edgeTap = (event) => {
    selectedNode = null;
    setStateValue("selected", selectedPayload("edge", event.target));
    updateExploreButton();
  };
  const backgroundTap = (event) => {
    if (event.target !== cy) return;
    selectedNode = null;
    setStateValue("selected", null);
    updateExploreButton();
    hideTooltip();
  };
  const edgeOver = (event) => event.target.addClass("hovered");
  const edgeOut = (event) => event.target.removeClass("hovered");

  const updateExpandButton = () => {
    if (!expandButton) return;
    expandButton.textContent = focusMode ? "Exit" : "Expand";
    expandButton.setAttribute(
      "aria-label",
      focusMode ? "Exit expanded graph" : "Expand graph"
    );
    expandButton.title = focusMode
      ? "Exit expanded graph"
      : "Open the graph in focus mode";
  };
  const applyFocusState = (enabled) => {
    focusMode = enabled;
    shell.classList.toggle("cy-focus", enabled);
    if (enabled) {
      previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = previousBodyOverflow;
    }
    updateExpandButton();
    window.setTimeout(() => {
      cy.resize();
      fitGraph();
    }, 80);
  };
  const enterFocus = async () => {
    if (focusMode) return;
    applyFocusState(true);
    try {
      if (shell.requestFullscreen && document.fullscreenElement !== shell) {
        await shell.requestFullscreen();
      }
    } catch (_) {
      // The fixed-position focus mode remains active when fullscreen is blocked.
    }
  };
  const exitFocus = async () => {
    if (!focusMode) return;
    try {
      if (document.fullscreenElement === shell && document.exitFullscreen) {
        await document.exitFullscreen();
      }
    } catch (_) {
      // Continue with the focus-mode cleanup below.
    }
    applyFocusState(false);
  };
  const toggleFocus = () => (focusMode ? exitFocus() : enterFocus());
  const fullscreenChanged = () => {
    if (focusMode && document.fullscreenElement !== shell) {
      applyFocusState(false);
    }
  };
  const keyDown = (event) => {
    if (!focusMode) return;
    if (event.key === "Escape") {
      event.preventDefault();
      exitFocus();
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomIn();
    } else if (event.key === "-") {
      event.preventDefault();
      zoomOut();
    } else if (event.key === "0") {
      event.preventDefault();
      fitGraph();
    } else if (event.key.toLowerCase() === "c") {
      event.preventDefault();
      centerSelected();
    }
  };

  cy.on("tap", "node:not(.layer-header)", nodeTap);
  cy.on("tap", "edge", edgeTap);
  cy.on("tap", backgroundTap);
  cy.on("mouseover", "node:not(.layer-header)", showTooltip);
  cy.on("mouseout", "node:not(.layer-header)", hideTooltip);
  cy.on("mouseover", "edge", edgeOver);
  cy.on("mouseout", "edge", edgeOut);
  cy.on("zoom", updateZoomLevel);

  zoomInButton?.addEventListener("click", zoomIn);
  zoomOutButton?.addEventListener("click", zoomOut);
  fitButton?.addEventListener("click", fitGraph);
  centerButton?.addEventListener("click", centerSelected);
  exploreButton?.addEventListener("click", exploreSelected);
  expandButton?.addEventListener("click", toggleFocus);
  document.addEventListener("fullscreenchange", fullscreenChanged);
  document.addEventListener("keydown", keyDown);

  const resizeObserver = new ResizeObserver(() => cy.resize());
  resizeObserver.observe(shell);

  updateExploreButton();
  updateExpandButton();
  requestAnimationFrame(() => {
    fitGraph();
    updateZoomLevel();
  });

  return () => {
    resizeObserver.disconnect();
    if (focusMode) applyFocusState(false);
    zoomInButton?.removeEventListener("click", zoomIn);
    zoomOutButton?.removeEventListener("click", zoomOut);
    fitButton?.removeEventListener("click", fitGraph);
    centerButton?.removeEventListener("click", centerSelected);
    exploreButton?.removeEventListener("click", exploreSelected);
    expandButton?.removeEventListener("click", toggleFocus);
    document.removeEventListener("fullscreenchange", fullscreenChanged);
    document.removeEventListener("keydown", keyDown);
    cy.off("tap", "node:not(.layer-header)", nodeTap);
    cy.off("tap", "edge", edgeTap);
    cy.off("tap", backgroundTap);
    cy.off("mouseover", "node:not(.layer-header)", showTooltip);
    cy.off("mouseout", "node:not(.layer-header)", hideTooltip);
    cy.off("mouseover", "edge", edgeOver);
    cy.off("mouseout", "edge", edgeOut);
    cy.off("zoom", updateZoomLevel);
    cy.destroy();
  };
}
