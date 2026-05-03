"use strict";

const RIGHT_MIN_X = 25;
const BUILDINGS = ["road", "conveyor", "bridge", "harvester", "foundry", "barrier"];
const WALKABLE_BUILDINGS = new Set(["road", "conveyor", "bridge", "armoured_conveyor"]);
const CONVEYOR_DIRECTIONS = ["north", "east", "south", "west"];
const DIRECTIONS = CONVEYOR_DIRECTIONS;
const BUILDER_ACTION_RADIUS_SQ = 2;
const BRIDGE_TARGET_RADIUS_SQ = 9;
const CONVEYOR_ROTATION_DEG = {
  west: 0,
  north: 90,
  east: 180,
  south: 270,
};
const ARROW_DELTAS = {
  ArrowUp: [0, -1],
  ArrowRight: [1, 0],
  ArrowDown: [0, 1],
  ArrowLeft: [-1, 0],
};
const SHORTCUTS = {
  r: "road",
  c: "conveyor",
  b: "bridge",
  h: "harvester",
  f: "foundry",
  w: "barrier",
  x: "clear",
};
const ENTITY_ICON = {
  road: "/assets/entities/road.png",
  conveyor: "/assets/entities/conveyor.png",
  bridge: "/assets/entities/bridge.png",
  harvester: "/assets/entities/harvester.png",
  foundry: "/assets/entities/foundry.png",
  barrier: "/assets/entities/barrier.png",
  core: "/assets/entities/core.png",
};
const RESOURCE_ICON = {
  1: "/assets/resources/wall.jpg",
  2: "/assets/resources/titanium-ore.png",
  3: "/assets/resources/axionite-ore.png",
};
const ENV_NAME = {
  0: "empty",
  1: "wall",
  2: "titanium ore",
  3: "axionite ore",
};

const state = {
  mode: "layout",
  map: null,
  plan: null,
  spawnSchedule: [],
  strategies: new Map(),
  selected: null,
  currentBuilder: 1,
  currentTurn: 1,
  strategyClickMode: "append",
  strategyActionMode: "plan_build",
  pickingSpawnTile: false,
  bridgePick: null,
  layoutDraft: {
    building: "",
    direction: "south",
    bridgeTarget: null,
  },
  overrideDraft: {
    building: "",
    direction: "south",
    bridgeTarget: null,
  },
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  fillDirectionSelects();
  bindEvents();
  loadState();
});

function cacheElements() {
  Object.assign(els, {
    status: document.getElementById("status"),
    mapGrid: document.getElementById("mapGrid"),
    layoutModeButton: document.getElementById("layoutModeButton"),
    strategyModeButton: document.getElementById("strategyModeButton"),
    savePlanButton: document.getElementById("savePlanButton"),
    saveStrategyButton: document.getElementById("saveStrategyButton"),
    layoutPanel: document.getElementById("layoutPanel"),
    strategyPanel: document.getElementById("strategyPanel"),
    builderSelect: document.getElementById("builderSelect"),
    addBuilderButton: document.getElementById("addBuilderButton"),
    selectedTileLabel: document.getElementById("selectedTileLabel"),
    layoutBuildingSelect: document.getElementById("layoutBuildingSelect"),
    layoutDirectionSelect: document.getElementById("layoutDirectionSelect"),
    layoutDirectionField: document.getElementById("layoutDirectionField"),
    layoutBridgeField: document.getElementById("layoutBridgeField"),
    layoutBridgeTargetLabel: document.getElementById("layoutBridgeTargetLabel"),
    pickLayoutBridgeTargetButton: document.getElementById("pickLayoutBridgeTargetButton"),
    turnSlider: document.getElementById("turnSlider"),
    turnNumber: document.getElementById("turnNumber"),
    spawnTurnNumber: document.getElementById("spawnTurnNumber"),
    spawnTileLabel: document.getElementById("spawnTileLabel"),
    firstActionTurnLabel: document.getElementById("firstActionTurnLabel"),
    pickSpawnTileButton: document.getElementById("pickSpawnTileButton"),
    saveSpawnButton: document.getElementById("saveSpawnButton"),
    appendModeButton: document.getElementById("appendModeButton"),
    currentModeButton: document.getElementById("currentModeButton"),
    appendPlanBuildButton: document.getElementById("appendPlanBuildButton"),
    appendOverrideBuildButton: document.getElementById("appendOverrideBuildButton"),
    appendMoveButton: document.getElementById("appendMoveButton"),
    appendDestroyButton: document.getElementById("appendDestroyButton"),
    clearFutureButton: document.getElementById("clearFutureButton"),
    overrideBuildingSelect: document.getElementById("overrideBuildingSelect"),
    overrideDirectionSelect: document.getElementById("overrideDirectionSelect"),
    overrideDirectionField: document.getElementById("overrideDirectionField"),
    overrideBridgeField: document.getElementById("overrideBridgeField"),
    overrideBridgeTargetLabel: document.getElementById("overrideBridgeTargetLabel"),
    pickOverrideBridgeTargetButton: document.getElementById("pickOverrideBridgeTargetButton"),
    turnActionList: document.getElementById("turnActionList"),
    strategyWarningList: document.getElementById("strategyWarningList"),
    selectionDetails: document.getElementById("selectionDetails"),
  });
}

function fillDirectionSelects() {
  for (const select of [els.layoutDirectionSelect, els.overrideDirectionSelect]) {
    for (const direction of DIRECTIONS) {
      const option = document.createElement("option");
      option.value = direction;
      option.textContent = title(direction);
      select.appendChild(option);
    }
    select.value = "south";
  }
}

function bindEvents() {
  els.layoutModeButton.addEventListener("click", () => setMode("layout"));
  els.strategyModeButton.addEventListener("click", () => setMode("strategy"));
  els.savePlanButton.addEventListener("click", savePlan);
  els.saveStrategyButton.addEventListener("click", saveCurrentStrategy);
  els.builderSelect.addEventListener("change", () => {
    state.currentBuilder = Number(els.builderSelect.value);
    ensureStrategy(state.currentBuilder);
    ensureSpawnForBuilder(state.currentBuilder);
    syncTurnBounds();
    render();
  });
  els.addBuilderButton.addEventListener("click", addBuilder);

  els.layoutBuildingSelect.addEventListener("change", () => {
    applyLayoutBuilding(els.layoutBuildingSelect.value);
  });
  els.layoutDirectionSelect.addEventListener("change", () => {
    state.layoutDraft.direction = els.layoutDirectionSelect.value;
    updateSelectedLayoutSpec();
  });
  els.pickLayoutBridgeTargetButton.addEventListener("click", () => startBridgePick("layout"));

  els.turnSlider.addEventListener("input", () => setTurn(Number(els.turnSlider.value)));
  els.turnNumber.addEventListener("change", () => setTurn(Number(els.turnNumber.value)));
  els.spawnTurnNumber.addEventListener("change", () => setCurrentBuilderSpawnTurn(Number(els.spawnTurnNumber.value)));
  els.pickSpawnTileButton.addEventListener("click", startSpawnTilePick);
  els.saveSpawnButton.addEventListener("click", saveSpawnSchedule);
  els.appendModeButton.addEventListener("click", () => setStrategyClickMode("append"));
  els.currentModeButton.addEventListener("click", () => setStrategyClickMode("current"));

  els.appendPlanBuildButton.addEventListener("click", () => setStrategyActionMode("plan_build"));
  els.appendOverrideBuildButton.addEventListener("click", () => setStrategyActionMode("override_build"));
  els.appendMoveButton.addEventListener("click", () => setStrategyActionMode("move"));
  els.appendDestroyButton.addEventListener("click", () => setStrategyActionMode("destroy"));
  els.clearFutureButton.addEventListener("click", clearFutureActions);
  els.overrideBuildingSelect.addEventListener("change", () => {
    state.overrideDraft.building = els.overrideBuildingSelect.value;
    updatePanelVisibility();
  });
  els.overrideDirectionSelect.addEventListener("change", () => {
    state.overrideDraft.direction = els.overrideDirectionSelect.value;
  });
  els.pickOverrideBridgeTargetButton.addEventListener("click", () => startBridgePick("override"));

  document.querySelectorAll("[data-shortcut-building]").forEach((button) => {
    button.addEventListener("click", () => {
      const building = button.dataset.shortcutBuilding;
      if (building === "clear") clearSelectedPlanTile();
      else applyLayoutBuilding(building);
    });
  });

  document.addEventListener("keydown", handleShortcut);
}

async function loadState() {
  setStatus("Loading editor data");
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("Could not load editor state");
  const payload = await response.json();
  state.map = payload.map;
  state.plan = payload.plan;
  state.spawnSchedule = normalizeSpawnSchedule(payload.spawn_schedule || []);
  state.strategies.clear();
  for (const item of payload.strategies) {
    state.strategies.set(item.builder, normalizeStrategy(item.strategy));
  }
  for (const builder of builderNumbers()) ensureSpawnForBuilder(builder);
  if (!state.strategies.has(1)) state.strategies.set(1, normalizeStrategy({ turns: { 1: [] } }));
  state.currentBuilder = Math.min(...builderNumbers());
  state.selected = { x: state.map.cores[1].center.x, y: state.map.cores[1].center.y };
  renderBuilderSelect();
  syncTurnBounds();
  render();
  setStatus("Ready", "ok");
}

function render() {
  renderGrid();
  renderPanels();
}

function renderGrid() {
  els.mapGrid.textContent = "";
  const coreKeys = coreFootprintKeys();
  const assigned = assignedBuildTiles();
  const visibleAtTurn = visibleBuildTilesAtTurn();
  const currentTurnKeys = buildTilesForTurn(state.currentTurn);
  const bridgeTarget = selectedBridgeTarget();
  const spawnTile = state.mode === "strategy" ? builderSpawnPosition() : null;

  for (let y = 0; y < state.map.height; y += 1) {
    for (let x = RIGHT_MIN_X; x < state.map.width; x += 1) {
      const key = tileKey(x, y);
      const env = state.map.rows[y][x];
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "tile";
      tile.dataset.x = String(x);
      tile.dataset.y = String(y);
      tile.title = `${x},${y} ${ENV_NAME[env]}`;

      if (env === 1) tile.classList.add("is-wall");
      if (env === 2) tile.classList.add("is-titanium");
      if (env === 3) tile.classList.add("is-axionite");
      if (coreKeys.has(key)) tile.classList.add("is-core");
      if (state.selected && state.selected.x === x && state.selected.y === y) {
        tile.classList.add("is-selected");
      }
      if (state.bridgePick) {
        tile.classList.add("is-pick-target");
        if (isBridgeTargetInRange(state.bridgePick.origin, { x, y })) {
          tile.classList.add("is-valid-bridge-target");
        } else {
          tile.classList.add("is-invalid-bridge-target");
        }
      }
      if (bridgeTarget && bridgeTarget.x === x && bridgeTarget.y === y) {
        tile.classList.add("is-bridge-target");
      }
      if (state.pickingSpawnTile) {
        tile.classList.add("is-pick-target");
        if (isValidSpawnTile({ x, y })) {
          tile.classList.add("is-valid-spawn-target");
        } else {
          tile.classList.add("is-invalid-spawn-target");
        }
      }

      const spec = planSpecAt(x, y);
      appendTileImage(tile, env, coreKeys.has(key), spec);
      if (specType(spec) === "harvester") {
        if (env === 2) tile.classList.add("is-harvester-titanium");
        if (env === 3) tile.classList.add("is-harvester-axionite");
      }

      if (state.mode === "strategy") {
        const hasPlan = spec !== null;
        if (assigned.has(key)) tile.classList.add("is-assigned");
        if (visibleAtTurn.built.has(key)) tile.classList.add("is-built");
        if (visibleAtTurn.future.has(key)) tile.classList.add("is-future");
        if (currentTurnKeys.has(key)) tile.classList.add("is-current-turn");
        if (hasPlan && !assigned.has(key)) tile.classList.add("is-greyed");
        const order = assigned.get(key);
        if (spawnTile && spawnTile.x === x && spawnTile.y === y) {
          tile.classList.add("is-spawn-tile");
          appendMark(tile, "S");
        } else if (order !== undefined) {
          appendMark(tile, String(order));
        }
      }

      tile.addEventListener("click", () => handleTileClick(x, y));
      els.mapGrid.appendChild(tile);
    }
  }
}

function appendTileImage(tile, env, isCore, spec) {
  let src = null;
  if (isCore) src = ENTITY_ICON.core;
  else if (spec) src = ENTITY_ICON[specType(spec)];
  else src = RESOURCE_ICON[env];
  if (!src) return;
  const img = document.createElement("img");
  img.src = src;
  img.alt = "";
  const normalized = normalizeSpec(spec);
  if (normalized?.type === "conveyor") {
    img.classList.add("is-conveyor-icon");
    img.style.transform = `rotate(${conveyorRotationDeg(normalized.direction)}deg)`;
  }
  tile.appendChild(img);
}

function appendMark(tile, text) {
  const mark = document.createElement("span");
  mark.className = "small-mark";
  mark.textContent = text;
  tile.appendChild(mark);
}

function renderPanels() {
  const selected = state.selected;
  els.selectedTileLabel.textContent = selected ? `${selected.x}, ${selected.y}` : "No tile selected";
  if (selected) {
    const spec = planSpecAt(selected.x, selected.y);
    const normalized = normalizeSpec(spec);
    els.layoutBuildingSelect.value = normalized?.type ?? "";
    const layoutDirection = cardinalDirection(
      normalized?.direction ?? state.layoutDraft.direction,
    );
    els.layoutDirectionSelect.value = layoutDirection;
    state.layoutDraft.building = normalized?.type ?? "";
    state.layoutDraft.direction = layoutDirection;
    state.layoutDraft.bridgeTarget = normalized?.target ? posFromAny(normalized.target) : state.layoutDraft.bridgeTarget;
  }
  updatePanelVisibility();
  renderSpawnControls();
  renderTurnActions();
  renderStrategyWarnings();
  renderSelectionDetails();
}

function renderTurnActions() {
  els.turnActionList.textContent = "";
  const actions = currentTurnActions();
  if (actions.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = "No actions on this turn";
    els.turnActionList.appendChild(empty);
    return;
  }
  actions.forEach((action, index) => {
    const item = document.createElement("li");
    if (action.implicit) item.classList.add("is-implicit-action");
    const label = document.createElement("span");
    label.textContent = describeAction(action);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Remove";
    button.addEventListener("click", () => removeActionAtCurrentTurn(index));
    item.append(label, button);
    els.turnActionList.appendChild(item);
  });
}

function renderStrategyWarnings() {
  els.strategyWarningList.textContent = "";
  const warnings = impossibleActionWarnings();
  if (warnings.length === 0) {
    const empty = document.createElement("li");
    empty.className = "is-ok";
    empty.textContent = "No impossible actions detected";
    els.strategyWarningList.appendChild(empty);
    return;
  }
  for (const warning of warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    els.strategyWarningList.appendChild(item);
  }
}

function renderSpawnControls() {
  const spawn = currentSpawnEntry();
  const spawnPos = posFromAny(spawn.tile);
  els.spawnTurnNumber.value = String(spawn.turn);
  els.spawnTileLabel.textContent = formatPos(spawnPos);
  els.firstActionTurnLabel.textContent = String(spawn.turn + 1);
}

function renderSelectionDetails() {
  els.selectionDetails.textContent = "";
  if (!state.selected) return;
  const { x, y } = state.selected;
  const env = state.map.rows[y][x];
  const spec = planSpecAt(x, y);
  const rows = [
    ["Tile", `${x},${y}`],
    ["Environment", ENV_NAME[env]],
    ["Locked", isLockedTile(x, y) ? "yes" : "no"],
    ["Plan", spec ? JSON.stringify(spec) : "none"],
  ];
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    els.selectionDetails.append(dt, dd);
  }
}

function updatePanelVisibility() {
  els.layoutPanel.classList.toggle("is-hidden", state.mode !== "layout");
  els.strategyPanel.classList.toggle("is-hidden", state.mode !== "strategy");
  const layoutType = els.layoutBuildingSelect.value;
  els.layoutDirectionField.style.display = layoutType === "conveyor" ? "grid" : "none";
  els.layoutBridgeField.style.display = layoutType === "bridge" ? "grid" : "none";
  els.layoutBridgeTargetLabel.textContent = formatPos(state.layoutDraft.bridgeTarget);

  const overrideType = els.overrideBuildingSelect.value;
  els.overrideDirectionField.style.display = overrideType === "conveyor" ? "grid" : "none";
  els.overrideBridgeField.style.display = overrideType === "bridge" ? "grid" : "none";
  els.overrideBridgeTargetLabel.textContent = formatPos(state.overrideDraft.bridgeTarget);

  els.layoutModeButton.classList.toggle("is-active", state.mode === "layout");
  els.strategyModeButton.classList.toggle("is-active", state.mode === "strategy");
  els.appendModeButton.classList.toggle("is-active", state.strategyClickMode === "append");
  els.currentModeButton.classList.toggle("is-active", state.strategyClickMode === "current");
  els.appendPlanBuildButton.classList.toggle("is-active", state.strategyActionMode === "plan_build");
  els.appendOverrideBuildButton.classList.toggle("is-active", state.strategyActionMode === "override_build");
  els.appendMoveButton.classList.toggle("is-active", state.strategyActionMode === "move");
  els.appendDestroyButton.classList.toggle("is-active", state.strategyActionMode === "destroy");
  els.pickSpawnTileButton.classList.toggle("is-active", state.pickingSpawnTile);
}

function handleTileClick(x, y) {
  if (state.pickingSpawnTile) {
    setCurrentBuilderSpawnTile({ x, y });
    return;
  }
  if (state.bridgePick) {
    finishBridgePick(x, y);
    return;
  }
  state.selected = { x, y };
  if (state.mode === "strategy") {
    applySelectedStrategyAction();
    return;
  }
  render();
}

function handleShortcut(event) {
  const tag = event.target?.tagName?.toLowerCase();
  if (["input", "select", "textarea"].includes(tag)) return;

  const arrowDelta = ARROW_DELTAS[event.key];
  if (arrowDelta) {
    event.preventDefault();
    moveSelection(arrowDelta[0], arrowDelta[1]);
    return;
  }

  if (event.key === "Delete" || event.key === "Backspace") {
    if (state.mode === "layout") clearSelectedPlanTile();
    return;
  }
  const building = SHORTCUTS[event.key.toLowerCase()];
  if (!building) return;
  event.preventDefault();
  if (building === "clear") {
    if (state.mode === "layout") clearSelectedPlanTile();
    return;
  }
  if (state.mode === "layout") {
    if (building === "conveyor" && selectedPlanType() === "conveyor") {
      cycleSelectedConveyorDirection();
    } else {
      applyLayoutBuilding(building);
    }
  } else {
    els.overrideBuildingSelect.value = building;
    state.overrideDraft.building = building;
    updatePanelVisibility();
  }
}

function moveSelection(dx, dy) {
  if (!state.map) return;
  const current = state.selected ?? { x: RIGHT_MIN_X, y: 0 };
  const next = {
    x: Math.min(state.map.width - 1, Math.max(RIGHT_MIN_X, current.x + dx)),
    y: Math.min(state.map.height - 1, Math.max(0, current.y + dy)),
  };
  state.selected = next;
  render();
}

function setMode(mode) {
  state.mode = mode;
  state.bridgePick = null;
  state.pickingSpawnTile = false;
  render();
}

function setStrategyClickMode(mode) {
  state.strategyClickMode = mode;
  render();
}

function setStrategyActionMode(mode) {
  state.strategyActionMode = mode;
  render();
  setStatus(`${strategyActionModeLabel(mode)} selected. Click a tile to add it.`);
}

function setTurn(turn) {
  state.currentTurn = Math.max(1, Number.isFinite(turn) ? Math.floor(turn) : 1);
  if (state.currentTurn > Number(els.turnSlider.max)) {
    els.turnSlider.max = String(state.currentTurn);
  }
  els.turnSlider.value = String(state.currentTurn);
  els.turnNumber.value = String(state.currentTurn);
  render();
}

function setCurrentBuilderSpawnTurn(turn) {
  const spawn = currentSpawnEntry();
  spawn.turn = Math.max(0, Number.isFinite(turn) ? Math.floor(turn) : 0);
  render();
  setStatus(`Builder ${state.currentBuilder} spawn turn set to ${spawn.turn}`);
}

function startSpawnTilePick() {
  state.pickingSpawnTile = true;
  state.bridgePick = null;
  render();
  setStatus("Click one of the core tiles to set this builder's spawn tile");
}

function setCurrentBuilderSpawnTile(pos) {
  state.selected = { ...pos };
  if (!isValidSpawnTile(pos)) {
    setStatus("Builder spawn tiles must be on the right-side core footprint", "error");
    render();
    return;
  }
  const spawn = currentSpawnEntry();
  spawn.tile = [pos.x, pos.y];
  state.pickingSpawnTile = false;
  render();
  setStatus(`Builder ${state.currentBuilder} spawn tile set to ${formatPos(pos)}`);
}

function applyLayoutBuilding(type) {
  if (!state.selected) return setStatus("Select a tile first", "error");
  if (type === "") return clearSelectedPlanTile();
  if (isLockedTile(state.selected.x, state.selected.y)) {
    return setStatus("Walls and core tiles are locked", "error");
  }
  state.layoutDraft.building = type;
  els.layoutBuildingSelect.value = type;
  if (type === "bridge" && !state.layoutDraft.bridgeTarget) {
    startBridgePick("layout");
    return;
  }
  updateSelectedLayoutSpec();
}

function selectedPlanType() {
  if (!state.selected) return "";
  return specType(planSpecAt(state.selected.x, state.selected.y));
}

function cycleSelectedConveyorDirection() {
  if (!state.selected) return;
  if (isLockedTile(state.selected.x, state.selected.y)) return;

  const current = normalizeSpec(planSpecAt(state.selected.x, state.selected.y));
  const currentDirection = current?.direction ?? state.layoutDraft.direction ?? "south";
  const currentIndex = CONVEYOR_DIRECTIONS.indexOf(currentDirection);
  const nextDirection =
    CONVEYOR_DIRECTIONS[(currentIndex + 1 + CONVEYOR_DIRECTIONS.length) % CONVEYOR_DIRECTIONS.length];

  state.layoutDraft.building = "conveyor";
  state.layoutDraft.direction = nextDirection;
  els.layoutBuildingSelect.value = "conveyor";
  els.layoutDirectionSelect.value = nextDirection;
  setPlanSpec(state.selected.x, state.selected.y, {
    type: "conveyor",
    direction: nextDirection,
  });
  setStatus(`Conveyor direction: ${title(nextDirection)}`);
  render();
}

function updateSelectedLayoutSpec() {
  if (!state.selected) return;
  const type = state.layoutDraft.building || els.layoutBuildingSelect.value;
  if (!type) {
    setPlanSpec(state.selected.x, state.selected.y, null);
    render();
    return;
  }
  if (isLockedTile(state.selected.x, state.selected.y)) return;
  const spec = specFromDraft(type, state.layoutDraft);
  if (!spec) return;
  setPlanSpec(state.selected.x, state.selected.y, spec);
  render();
}

function clearSelectedPlanTile() {
  if (!state.selected) return;
  if (isLockedTile(state.selected.x, state.selected.y)) {
    return setStatus("Walls and core tiles are locked", "error");
  }
  setPlanSpec(state.selected.x, state.selected.y, null);
  setStatus("Cleared tile");
  render();
}

function startBridgePick(source) {
  if (!state.selected) return setStatus("Select a bridge tile first", "error");
  state.bridgePick = { source, origin: { ...state.selected } };
  setStatus("Pick a bridge target on the map");
  render();
}

function finishBridgePick(x, y) {
  const pick = state.bridgePick;
  if (!pick) return;
  if (!isBridgeTargetInRange(pick.origin, { x, y })) {
    setStatus("Bridge targets must be within Euclidean distance 3", "error");
    render();
    return;
  }
  state.bridgePick = null;
  if (pick.source === "layout") {
    state.selected = pick.origin;
    state.layoutDraft.building = "bridge";
    state.layoutDraft.bridgeTarget = { x, y };
    els.layoutBuildingSelect.value = "bridge";
    updateSelectedLayoutSpec();
  } else {
    state.overrideDraft.bridgeTarget = { x, y };
    render();
  }
  setStatus("Bridge target set");
}

function addBuildAction(useOverride) {
  if (!state.selected) return setStatus("Select a tile first", "error");
  if (isLockedTile(state.selected.x, state.selected.y)) {
    return setStatus("Walls and core tiles cannot be build targets", "error");
  }
  if (!useOverride && !planSpecAt(state.selected.x, state.selected.y)) {
    return setStatus("No final-plan building on this tile", "error");
  }
  const action = {
    action: "build",
      at: [state.selected.x, state.selected.y],
  };
  if (useOverride) {
    const overrideType = els.overrideBuildingSelect.value;
    if (!overrideType) return setStatus("Choose an override building first", "error");
    const overrideSpec = specFromDraft(overrideType, state.overrideDraft);
    if (!overrideSpec) return;
    action.building = overrideSpec;
  }
  addBuildActionWithImplicitMove(action);
}

function addMoveAction() {
  if (!state.selected) return setStatus("Select a tile first", "error");
  addAction({ action: "move_to", to: [state.selected.x, state.selected.y] });
}

function addDestroyAction() {
  if (!state.selected) return setStatus("Select a tile first", "error");
  addAction({ action: "destroy", at: [state.selected.x, state.selected.y] });
}

function addBuildActionWithImplicitMove(buildAction) {
  const strategy = currentStrategy();
  const turn = insertionTurn(strategy);
  const buildPos = actionPosition(buildAction);
  const currentPos = simulatedPositionBeforeInsertion(turn, true);
  const walkableKeys = walkableTilesBeforeInsertion(turn, true);
  const actions = [];

  if (currentPos && buildPos && distanceSq(currentPos, buildPos) > BUILDER_ACTION_RADIUS_SQ) {
    const stagingPos = implicitBuildStagingTile(currentPos, buildPos, walkableKeys);
    if (stagingPos) {
      actions.push({
        action: "move_to",
        to: [stagingPos.x, stagingPos.y],
        implicit: true,
        reason: "build_range",
      });
    }
  }

  actions.push(buildAction);
  addActions(actions);
}

function applySelectedStrategyAction() {
  if (state.strategyActionMode === "plan_build") {
    addBuildAction(false);
    return;
  }
  if (state.strategyActionMode === "override_build") {
    addBuildAction(true);
    return;
  }
  if (state.strategyActionMode === "move") {
    addMoveAction();
    return;
  }
  if (state.strategyActionMode === "destroy") {
    addDestroyAction();
  }
}

function strategyActionModeLabel(mode) {
  if (mode === "plan_build") return "Build from plan";
  if (mode === "override_build") return "Overwrite build";
  if (mode === "move") return "Move";
  if (mode === "destroy") return "Destroy";
  return "Action";
}

function insertionTurn(strategy) {
  return state.strategyClickMode === "append" ? nextEmptyTurn(strategy) : state.currentTurn;
}

function isReplaceableBuildAction(action) {
  if (normalizeActionName(action.action) === "build") return true;
  return normalizeActionName(action.action) === "move_to" && action.implicit === true && action.reason === "build_range";
}

function addAction(action) {
  addActions([action]);
}

function addActions(actions) {
  const strategy = currentStrategy();
  const turn = insertionTurn(strategy);
  const key = String(turn);
  strategy.turns[key] = strategy.turns[key] || [];
  const includesBuild = actions.some((action) => normalizeActionName(action.action) === "build");
  if (state.strategyClickMode === "current" && includesBuild) {
    strategy.turns[key] = strategy.turns[key].filter((existing) => !isReplaceableBuildAction(existing));
  }
  strategy.turns[key].push(...actions);
  setTurn(turn);
  syncTurnBounds();
  render();
  setStatus(`Added ${actions.map(describeAction).join(" + ")} on turn ${turn}`);
}

function removeActionAtCurrentTurn(index) {
  const actions = currentTurnActions();
  actions.splice(index, 1);
  currentStrategy().turns[String(state.currentTurn)] = actions;
  render();
}

function clearFutureActions() {
  const strategy = currentStrategy();
  let removedTurns = 0;
  let removedActions = 0;
  for (const turn of Object.keys(strategy.turns)) {
    if (Number(turn) <= state.currentTurn) continue;
    removedTurns += 1;
    removedActions += strategy.turns[turn].length;
    delete strategy.turns[turn];
  }
  syncTurnBounds();
  render();
  setStatus(`Cleared ${removedActions} future action${removedActions === 1 ? "" : "s"} from ${removedTurns} turn${removedTurns === 1 ? "" : "s"}`);
}

function addBuilder() {
  const next = Math.max(...builderNumbers()) + 1;
  state.strategies.set(next, normalizeStrategy({ turns: { 1: [] } }));
  ensureSpawnForBuilder(next);
  state.currentBuilder = next;
  renderBuilderSelect();
  syncTurnBounds();
  render();
}

async function savePlan() {
  await putJson("/api/plan", state.plan);
  setStatus("Saved plan.json", "ok");
}

async function saveCurrentStrategy() {
  const strategy = compactStrategy(currentStrategy());
  state.strategies.set(state.currentBuilder, strategy);
  await putJson(`/api/strategy/${state.currentBuilder}`, strategy);
  setStatus(`Saved strategies/${state.currentBuilder}.json`, "ok");
  render();
}

async function saveSpawnSchedule() {
  await putJson("/api/spawns", { spawn_schedule: compactSpawnSchedule() });
  setStatus("Saved spawns.json", "ok");
}

async function putJson(url, payload) {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Save failed: ${response.status}`);
  }
}

function renderBuilderSelect() {
  els.builderSelect.textContent = "";
  for (const builder of builderNumbers()) {
    const option = document.createElement("option");
    option.value = String(builder);
    option.textContent = `Builder ${builder}`;
    els.builderSelect.appendChild(option);
  }
  els.builderSelect.value = String(state.currentBuilder);
}

function builderNumbers() {
  const builders = new Set(state.strategies.keys());
  for (const spawn of state.spawnSchedule) builders.add(Number(spawn.builder));
  if (builders.size === 0) builders.add(1);
  return [...builders].filter(Number.isFinite).sort((a, b) => a - b);
}

function syncTurnBounds() {
  const maxTurn = Math.max(300, maxStrategyTurn(currentStrategy()) + 20, state.currentTurn, 1);
  els.turnSlider.min = "1";
  els.turnSlider.max = String(maxTurn);
  els.turnSlider.value = String(state.currentTurn);
  els.turnNumber.min = "1";
  els.turnNumber.value = String(state.currentTurn);
}

function currentStrategy() {
  ensureStrategy(state.currentBuilder);
  return state.strategies.get(state.currentBuilder);
}

function ensureStrategy(builderNumber) {
  if (!state.strategies.has(builderNumber)) {
    state.strategies.set(builderNumber, normalizeStrategy({ turns: { 1: [] } }));
  }
}

function normalizeSpawnSchedule(spawns) {
  const normalized = [];
  for (const raw of spawns || []) {
    const builder = Number(raw.builder);
    const pos = posFromAny(raw.tile);
    if (!Number.isFinite(builder) || builder <= 0 || !isFinitePos(pos)) continue;
    const turn = Math.max(0, Math.floor(Number(raw.turn) || 0));
    normalized.push({ builder, turn, tile: [pos.x, pos.y] });
  }
  return normalized.sort((a, b) => a.builder - b.builder);
}

function compactSpawnSchedule() {
  for (const builder of builderNumbers()) ensureSpawnForBuilder(builder);
  return normalizeSpawnSchedule(state.spawnSchedule);
}

function currentSpawnEntry() {
  ensureSpawnForBuilder(state.currentBuilder);
  return state.spawnSchedule.find((item) => Number(item.builder) === state.currentBuilder);
}

function ensureSpawnForBuilder(builderNumber) {
  if (state.spawnSchedule.some((item) => Number(item.builder) === builderNumber)) return;
  const pos = defaultSpawnTile();
  state.spawnSchedule.push({
    builder: builderNumber,
    turn: 0,
    tile: [pos.x, pos.y],
  });
  state.spawnSchedule.sort((a, b) => a.builder - b.builder);
}

function defaultSpawnTile() {
  const core = state.map?.cores?.[1]?.center;
  return core ? { x: core.x, y: core.y } : { x: 41, y: 8 };
}

function normalizeStrategy(strategy) {
  const normalized = { ...strategy, turns: { ...(strategy.turns || {}) } };
  for (const [turn, actions] of Object.entries(normalized.turns)) {
    normalized.turns[String(Number(turn))] = Array.isArray(actions) ? actions : [];
    if (String(Number(turn)) !== turn) delete normalized.turns[turn];
  }
  return normalized;
}

function compactStrategy(strategy) {
  const compact = { ...strategy, turns: {} };
  for (const turn of Object.keys(strategy.turns).map(Number).sort((a, b) => a - b)) {
    const actions = strategy.turns[String(turn)] || [];
    if (actions.length > 0) compact.turns[String(turn)] = actions;
  }
  if (Object.keys(compact.turns).length === 0) compact.turns["1"] = [];
  return compact;
}

function currentTurnActions() {
  const strategy = currentStrategy();
  return strategy.turns[String(state.currentTurn)] || [];
}

function maxStrategyTurn(strategy) {
  const turns = Object.keys(strategy.turns || {}).map(Number).filter(Number.isFinite);
  return turns.length ? Math.max(...turns) : 0;
}

function nextEmptyTurn(strategy) {
  let turn = 1;
  while ((strategy.turns[String(turn)] || []).length > 0) turn += 1;
  return turn;
}

function assignedBuildTiles() {
  const result = new Map();
  const builds = strategyBuildActions();
  builds.forEach((entry, index) => {
    result.set(tileKey(entry.pos.x, entry.pos.y), index + 1);
  });
  return result;
}

function visibleBuildTilesAtTurn() {
  const built = new Set();
  const future = new Set();
  for (const entry of strategyBuildActions()) {
    const key = tileKey(entry.pos.x, entry.pos.y);
    if (entry.turn <= state.currentTurn) built.add(key);
    else future.add(key);
  }
  return { built, future };
}

function buildTilesForTurn(turn) {
  const result = new Set();
  for (const action of currentStrategy().turns[String(turn)] || []) {
    if (normalizeActionName(action.action) !== "build") continue;
    const pos = actionPosition(action);
    if (pos) result.add(tileKey(pos.x, pos.y));
  }
  return result;
}

function strategyBuildActions() {
  const entries = [];
  const strategy = currentStrategy();
  for (const turn of Object.keys(strategy.turns).map(Number).sort((a, b) => a - b)) {
    for (const action of strategy.turns[String(turn)] || []) {
      if (normalizeActionName(action.action) !== "build") continue;
      const pos = actionPosition(action);
      if (pos) entries.push({ turn, pos, action });
    }
  }
  return entries;
}

function simulatedPositionBeforeInsertion(turn, replacingBuild) {
  const start = builderSpawnPosition();
  if (!start) return null;

  let current = { ...start };
  const strategy = currentStrategy();
  const turns = Object.keys(strategy.turns).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  for (const existingTurn of turns) {
    if (existingTurn > turn) break;
    if (existingTurn === turn && state.strategyClickMode !== "current") break;

    let actions = strategy.turns[String(existingTurn)] || [];
    if (existingTurn === turn && replacingBuild) {
      actions = actions.filter((action) => !isReplaceableBuildAction(action));
    }
    for (const action of actions) {
      if (normalizeActionName(action.action) !== "move_to") continue;
      const pos = actionPosition(action);
      if (pos && isFinitePos(pos) && isSingleMoveStep(current, pos)) {
        current = { ...pos };
      }
    }
  }
  return current;
}

function walkableTilesBeforeInsertion(turn, replacingBuild) {
  const walkable = new Set(coreFootprintKeys());
  const strategy = currentStrategy();
  const turns = Object.keys(strategy.turns).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  for (const existingTurn of turns) {
    if (existingTurn > turn) break;
    if (existingTurn === turn && state.strategyClickMode !== "current") break;

    let actions = strategy.turns[String(existingTurn)] || [];
    if (existingTurn === turn && replacingBuild) {
      actions = actions.filter((action) => !isReplaceableBuildAction(action));
    }
    for (const action of actions) {
      const name = normalizeActionName(action.action);
      const pos = actionPosition(action);
      if (!pos) continue;
      const key = tileKey(pos.x, pos.y);
      if (name === "build" && isWalkableBuildAction(action, pos)) walkable.add(key);
      if (name === "destroy") walkable.delete(key);
    }
  }
  return walkable;
}

function implicitBuildStagingTile(current, buildPos, walkableKeys) {
  const candidates = [];
  for (let dx = -1; dx <= 1; dx += 1) {
    for (let dy = -1; dy <= 1; dy += 1) {
      if (dx === 0 && dy === 0) continue;
      const candidate = { x: current.x + dx, y: current.y + dy };
      if (!isMovableStrategyTile(candidate, walkableKeys)) continue;
      if (distanceSq(candidate, buildPos) > BUILDER_ACTION_RADIUS_SQ) continue;
      candidates.push(candidate);
    }
  }
  candidates.sort((a, b) => {
    const distanceDelta = distanceSq(a, buildPos) - distanceSq(b, buildPos);
    if (distanceDelta !== 0) return distanceDelta;
    const straightDelta = Math.abs(a.x - current.x) + Math.abs(a.y - current.y)
      - (Math.abs(b.x - current.x) + Math.abs(b.y - current.y));
    if (straightDelta !== 0) return straightDelta;
    const yDelta = a.y - b.y;
    if (yDelta !== 0) return yDelta;
    return a.x - b.x;
  });
  return candidates[0] || null;
}

function impossibleActionWarnings() {
  const warnings = [];
  const start = builderSpawnPosition();
  if (!start) {
    return [`Builder ${state.currentBuilder} has no configured spawn tile`];
  }
  if (!isValidSpawnTile(start)) {
    warnings.push(`Builder ${state.currentBuilder} spawn tile ${formatPos(start)} is not on the right-side core footprint`);
  }

  let current = { ...start };
  let walkable = new Set(coreFootprintKeys());
  const strategy = currentStrategy();
  const turns = Object.keys(strategy.turns).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  for (const turn of turns) {
    const actions = strategy.turns[String(turn)] || [];
    actions.forEach((action, index) => {
      const name = normalizeActionName(action.action);
      const pos = actionPosition(action);
      if (!pos || !isFinitePos(pos)) {
        warnings.push(`Turn ${turn}, action ${index + 1}: ${describeRawAction(action)} has no valid target tile`);
        return;
      }
      if (!isMapPosition(pos)) {
        warnings.push(`Turn ${turn}, action ${index + 1}: ${describeRawAction(action)} targets ${formatPos(pos)}, outside the map`);
        return;
      }

      if (name === "move_to") {
        if (!isSingleMoveStep(current, pos)) {
          warnings.push(
            `Turn ${turn}, action ${index + 1}: move from ${formatPos(current)} to ${formatPos(pos)} is more than one tile`,
          );
          return;
        }
        if (!walkable.has(tileKey(pos.x, pos.y))) {
          warnings.push(
            `Turn ${turn}, action ${index + 1}: move target ${formatPos(pos)} is not walkable yet`,
          );
          return;
        }
        current = { ...pos };
        return;
      }

      if (name === "build") {
        if (distanceSq(current, pos) > BUILDER_ACTION_RADIUS_SQ) {
          warnings.push(
            `Turn ${turn}, action ${index + 1}: build at ${formatPos(pos)} is outside action range from ${formatPos(current)}`,
          );
          return;
        }
        if (isWalkableBuildAction(action, pos)) walkable.add(tileKey(pos.x, pos.y));
        return;
      }

      if (name === "destroy" && distanceSq(current, pos) > BUILDER_ACTION_RADIUS_SQ) {
        warnings.push(
          `Turn ${turn}, action ${index + 1}: destroy at ${formatPos(pos)} is outside action range from ${formatPos(current)}`,
        );
        return;
      }
      if (name === "destroy") walkable.delete(tileKey(pos.x, pos.y));
    });
  }
  return warnings;
}

function builderSpawnPosition() {
  const schedule = currentSpawnEntry();
  if (schedule) return posFromAny(schedule.tile);
  const core = state.map?.cores?.[1]?.center;
  return core ? { x: core.x, y: core.y } : null;
}

function isSingleMoveStep(from, to) {
  return Math.max(Math.abs(to.x - from.x), Math.abs(to.y - from.y)) <= 1;
}

function distanceSq(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  return dx * dx + dy * dy;
}

function isFinitePos(pos) {
  return Number.isFinite(pos.x) && Number.isFinite(pos.y);
}

function isMapPosition(pos) {
  return pos.x >= RIGHT_MIN_X && pos.x < state.map.width && pos.y >= 0 && pos.y < state.map.height;
}

function isMovableStrategyTile(pos, walkableKeys) {
  return isMapPosition(pos)
    && state.map.rows[pos.y][pos.x] !== 1
    && walkableKeys.has(tileKey(pos.x, pos.y));
}

function isWalkableBuildAction(action, pos) {
  const spec = action.building ?? planSpecAt(pos.x, pos.y);
  return WALKABLE_BUILDINGS.has(specType(spec));
}

function isValidSpawnTile(pos) {
  return isMapPosition(pos) && coreFootprintKeys().has(tileKey(pos.x, pos.y));
}

function describeRawAction(action) {
  const name = normalizeActionName(action.action);
  return name || "action";
}

function describeAction(action) {
  const name = normalizeActionName(action.action);
  const pos = actionPosition(action);
  const where = pos ? `${pos.x},${pos.y}` : "";
  if (name === "build") {
    const spec = action.building ?? planSpecAt(pos.x, pos.y);
    return `build ${spec ? specType(spec) : "plan"} at ${where}`;
  }
  if (name === "move_to") {
    if (action.implicit === true && action.reason === "build_range") {
      return `move to ${where} for build range`;
    }
    return `move to ${where}`;
  }
  if (name === "destroy") return `destroy at ${where}`;
  return `${action.action} ${where}`;
}

function normalizeActionName(raw) {
  const name = String(raw || "").toLowerCase();
  if (name === "build at" || name === "build_at") return "build";
  if (name === "move to") return "move_to";
  if (name === "destroy building at" || name === "destroy_at") return "destroy";
  return name;
}

function actionPosition(action) {
  const raw = action.at ?? action.to;
  if (!raw) return null;
  return posFromAny(raw);
}

function specFromDraft(type, draft) {
  if (!type) return null;
  if (type === "conveyor") {
    return { type, direction: cardinalDirection(draft.direction) };
  }
  if (type === "bridge") {
    if (!draft.bridgeTarget) {
      setStatus("Pick a bridge target first", "error");
      return null;
    }
    return { type, target: [draft.bridgeTarget.x, draft.bridgeTarget.y] };
  }
  return type;
}

function selectedBridgeTarget() {
  const selected = state.selected;
  if (!selected) return null;
  const spec = normalizeSpec(planSpecAt(selected.x, selected.y));
  if (spec?.type === "bridge") return posFromAny(spec.target);
  return null;
}

function isBridgeTargetInRange(origin, target) {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  return dx * dx + dy * dy <= BRIDGE_TARGET_RADIUS_SQ;
}

function cardinalDirection(direction) {
  if (CONVEYOR_DIRECTIONS.includes(direction)) return direction;
  return "south";
}

function conveyorRotationDeg(direction) {
  return CONVEYOR_ROTATION_DEG[cardinalDirection(direction)];
}

function planSpecAt(x, y) {
  return state.plan.tiles[tileKey(x, y)] ?? null;
}

function setPlanSpec(x, y, spec) {
  state.plan.tiles[tileKey(x, y)] = spec;
}

function normalizeSpec(spec) {
  if (!spec) return null;
  if (typeof spec === "string") return { type: spec };
  return spec;
}

function specType(spec) {
  return normalizeSpec(spec)?.type ?? "";
}

function isLockedTile(x, y) {
  return state.map.rows[y][x] === 1 || coreFootprintKeys().has(tileKey(x, y));
}

function coreFootprintKeys() {
  const keys = new Set();
  for (const core of state.map.cores) {
    const { x, y } = core.center;
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        keys.add(tileKey(x + dx, y + dy));
      }
    }
  }
  return keys;
}

function posFromAny(raw) {
  if (Array.isArray(raw)) return { x: Number(raw[0]), y: Number(raw[1]) };
  if (typeof raw === "string") {
    const [x, y] = raw.split(",", 2).map(Number);
    return { x, y };
  }
  return { x: Number(raw.x), y: Number(raw.y) };
}

function tileKey(x, y) {
  return `${x},${y}`;
}

function formatPos(pos) {
  return pos ? `${pos.x},${pos.y}` : "none";
}

function title(value) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function setStatus(message, kind = "") {
  els.status.textContent = message;
  els.status.classList.toggle("is-error", kind === "error");
  els.status.classList.toggle("is-ok", kind === "ok");
}
