#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const protobuf = require("protobufjs");

const TEAM_NAME = { 0: "TEAM_A", 1: "TEAM_B" };
const ENV_NAME = {
  0: "EMPTY",
  1: "WALL",
  2: "ORE_TITANIUM",
  3: "ORE_AXIONITE",
};
const DIRECTION_NAME = {
  0: "DIR_CENTRE",
  1: "DIR_NORTH",
  2: "DIR_NORTHEAST",
  3: "DIR_EAST",
  4: "DIR_SOUTHEAST",
  5: "DIR_SOUTH",
  6: "DIR_SOUTHWEST",
  7: "DIR_WEST",
  8: "DIR_NORTHWEST",
};
const RESOURCE_NAME = {
  0: "RESOURCE_NONE",
  1: "RESOURCE_TITANIUM",
  2: "RESOURCE_RAW_AXIONITE",
  3: "RESOURCE_REFINED_AXIONITE",
};
const TRACKED_INSTANCE_KINDS = new Set([
  "builderBot",
  "core",
  "gunner",
  "sentinel",
  "breach",
  "launcher",
]);
const VISION_RADIUS_SQ_BY_KIND = {
  builderBot: 20,
  core: 36,
  gunner: 13,
  sentinel: 32,
  breach: 2,
  launcher: 26,
};
const CORE_INITIAL_HP = 500;
const AMMO_COST_BY_KIND = {
  gunner: 2,
  sentinel: 10,
  breach: 5,
  launcher: 0,
};

function usage() {
  console.log(
    [
      "Usage:",
      "  node parse_replay.js <replay_path> [--out <summary.json>] [--out-dir <dir>] [--schema <visualizer_main.js>] [--top <N>]",
      "",
      "Options:",
      "  --out     Write JSON summary to file instead of stdout.",
      "  --out-dir Write chunked JSON files to a directory for large replays.",
      "  --schema  Explicit path to cambc visualizer bundle (main-*.js).",
      "  --top     Number of top items for large counters (default: 30).",
      "  --turn-chunk-size    Turns per turnsDetailed chunk in --out-dir mode (default: 50).",
      "  --action-chunk-size  Actions per instance chunk in --out-dir mode (default: 50).",
      "",
      "Environment:",
      "  CAMBC_VISUALIZER_JS  Explicit schema JS path (used if --schema is not set).",
    ].join("\n")
  );
}

function parseArgs(argv) {
  let replayPath = null;
  let outPath = null;
  let outDirPath = null;
  let schemaPath = null;
  let topN = 30;
  let turnChunkSize = 50;
  let actionChunkSize = 50;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      usage();
      process.exit(0);
    }
    if (arg === "--out") {
      outPath = argv[++i];
      continue;
    }
    if (arg === "--out-dir") {
      outDirPath = argv[++i];
      continue;
    }
    if (arg === "--schema") {
      schemaPath = argv[++i];
      continue;
    }
    if (arg === "--top") {
      const n = Number(argv[++i]);
      if (!Number.isFinite(n) || n <= 0) {
        throw new Error("--top must be a positive integer");
      }
      topN = Math.floor(n);
      continue;
    }
    if (arg === "--turn-chunk-size") {
      turnChunkSize = parsePositiveInteger(argv[++i], "--turn-chunk-size");
      continue;
    }
    if (arg === "--action-chunk-size") {
      actionChunkSize = parsePositiveInteger(argv[++i], "--action-chunk-size");
      continue;
    }
    if (arg.startsWith("-")) {
      throw new Error(`Unknown option: ${arg}`);
    }
    if (!replayPath) {
      replayPath = arg;
      continue;
    }
    throw new Error(`Unexpected argument: ${arg}`);
  }

  if (!replayPath) {
    usage();
    throw new Error("Missing required <replay_path> argument");
  }
  if (outPath && outDirPath) {
    throw new Error("Use either --out or --out-dir, not both");
  }

  return {
    replayPath: path.resolve(replayPath),
    outPath: outPath ? path.resolve(outPath) : null,
    outDirPath: outDirPath ? path.resolve(outDirPath) : null,
    schemaPath: schemaPath ? path.resolve(schemaPath) : null,
    topN,
    turnChunkSize,
    actionChunkSize,
  };
}

function parsePositiveInteger(rawValue, optionName) {
  const n = Number(rawValue);
  if (!Number.isFinite(n) || n <= 0 || Math.floor(n) !== n) {
    throw new Error(`${optionName} must be a positive integer`);
  }
  return n;
}

function fileExists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function tryResolveVisualizerPathViaPython(cmd) {
  const snippet = [
    "import cambc",
    "from pathlib import Path",
    "base = Path(cambc.__file__).resolve().parent / 'data' / 'visualiser' / 'assets'",
    "files = sorted(base.glob('main-*.js'))",
    "print(files[0] if files else '')",
  ].join("; ");

  try {
    const out = execSync(`${cmd} -c "${snippet}"`, {
      stdio: ["ignore", "pipe", "ignore"],
      encoding: "utf8",
    }).trim();
    if (!out) return null;
    return path.resolve(out);
  } catch {
    return null;
  }
}

function resolveVisualizerPath(explicitPath) {
  if (explicitPath) {
    if (!fileExists(explicitPath)) {
      throw new Error(`Schema JS not found: ${explicitPath}`);
    }
    return explicitPath;
  }

  const fromEnv = process.env.CAMBC_VISUALIZER_JS;
  if (fromEnv) {
    const p = path.resolve(fromEnv);
    if (fileExists(p)) return p;
  }

  const pythonCandidates = ["python", "py -3"];
  for (const cmd of pythonCandidates) {
    const resolved = tryResolveVisualizerPathViaPython(cmd);
    if (resolved && fileExists(resolved)) return resolved;
  }

  throw new Error(
    "Could not locate cambc visualizer schema JS automatically. " +
      "Pass --schema <path_to_main-*.js> or set CAMBC_VISUALIZER_JS."
  );
}

function extractAssignedObjectLiteral(jsSource, variableName) {
  const declarationRegex = new RegExp(`\\b${variableName}\\s*=\\s*\\{`);
  const match = declarationRegex.exec(jsSource);
  if (!match) {
    throw new Error(`Could not find schema variable declaration for ${variableName}`);
  }

  const braceStart = jsSource.indexOf("{", match.index);
  if (braceStart === -1) {
    throw new Error(`Could not find opening brace for ${variableName}`);
  }

  let depth = 0;
  let inString = false;
  let quote = "";
  let escaped = false;

  for (let i = braceStart; i < jsSource.length; i++) {
    const ch = jsSource[i];

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === quote) {
        inString = false;
      }
      continue;
    }

    if (ch === "'" || ch === '"' || ch === "`") {
      inString = true;
      quote = ch;
      continue;
    }

    if (ch === "{") {
      depth++;
      continue;
    }
    if (ch === "}") {
      depth--;
      if (depth === 0) {
        return jsSource.slice(braceStart, i + 1);
      }
    }
  }

  throw new Error(`Could not find closing brace for ${variableName}`);
}

function extractReplaySchemaObjectLiteral(jsSource) {
  const replaySchemaRefMatch = jsSource.match(
    /\.Root\.fromJSON\(([_$A-Za-z][_$0-9A-Za-z]*)\)\.lookupType\("battlecode\.Replay"\)/
  );
  if (replaySchemaRefMatch) {
    return extractAssignedObjectLiteral(jsSource, replaySchemaRefMatch[1]);
  }

  let start = jsSource.indexOf("Xt={");
  if (start === -1) start = jsSource.indexOf("Xt = {");
  if (start !== -1) {
    const braceStart = jsSource.indexOf("{", start);
    if (braceStart === -1) {
      throw new Error("Could not find opening brace for Xt schema object");
    }

    let depth = 0;
    let inString = false;
    let quote = "";
    let escaped = false;

    for (let i = braceStart; i < jsSource.length; i++) {
      const ch = jsSource[i];

      if (inString) {
        if (escaped) {
          escaped = false;
        } else if (ch === "\\") {
          escaped = true;
        } else if (ch === quote) {
          inString = false;
        }
        continue;
      }

      if (ch === "'" || ch === '"' || ch === "`") {
        inString = true;
        quote = ch;
        continue;
      }

      if (ch === "{") {
        depth++;
        continue;
      }
      if (ch === "}") {
        depth--;
        if (depth === 0) {
          return jsSource.slice(braceStart, i + 1);
        }
      }
    }
  }

  throw new Error(
    'Could not find replay protobuf schema in visualizer JS for "battlecode.Replay"'
  );
}

function loadReplayType(visualizerPath) {
  const js = fs.readFileSync(visualizerPath, "utf8");
  const schemaLiteral = extractReplaySchemaObjectLiteral(js);
  const schema = eval(`(() => (${schemaLiteral}))()`);
  return protobuf.Root.fromJSON(schema).lookupType("battlecode.Replay");
}

function bump(counterMap, key) {
  counterMap.set(key, (counterMap.get(key) || 0) + 1);
}

function topEntries(counterMap, n) {
  return [...counterMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

function entityKind(entity) {
  const keys = [
    "builderBot",
    "conveyor",
    "splitter",
    "armouredConveyor",
    "bridge",
    "harvester",
    "foundry",
    "road",
    "barrier",
    "marker",
    "core",
    "gunner",
    "sentinel",
    "breach",
    "launcher",
  ];
  for (const key of keys) {
    if (entity[key] != null) return key;
  }
  return "unknown";
}

function parseTypeAndAction(line) {
  const m = line.match(
    /^Unit\s+(\d+)\s+type:\s*(.+?)\s+action:\s*(.+?)(?:\s+turn took|$)/i
  );
  if (!m) return null;
  return {
    unitId: m[1],
    type: m[2].trim().toLowerCase(),
    action: m[3].trim().toLowerCase(),
  };
}

function cloneJsonLike(value) {
  if (value == null) return value;
  return JSON.parse(JSON.stringify(value));
}

function clonePosition(pos) {
  return pos ? { x: pos.x, y: pos.y } : null;
}

function normalizeDirection(direction) {
  if (direction == null) return null;
  return DIRECTION_NAME[direction] || String(direction);
}

function normalizeResourceType(resourceType) {
  if (resourceType == null) return null;
  return RESOURCE_NAME[resourceType] || String(resourceType);
}

function getOccupiedTilesForKind(kind, position) {
  if (!position) return [];
  if (kind === "core") {
    return coreFootprintPositions(position);
  }
  return [clonePosition(position)];
}

function normalizeEntity(entity) {
  const kind = entityKind(entity);
  const normalized = {
    id: entity.id,
    team: entity.team,
    teamName: TEAM_NAME[entity.team] || String(entity.team),
    kind,
    position: clonePosition(entity.position),
    occupiedTiles: getOccupiedTilesForKind(kind, entity.position),
    hp: entity.hp ?? null,
    maxHp: entity.maxHp ?? null,
  };

  if (entity.builderBot) {
    normalized.actionCooldown = entity.builderBot.actionCooldown ?? null;
    normalized.moveCooldown = entity.builderBot.moveCooldown ?? null;
  }
  if (entity.conveyor) {
    normalized.direction = normalizeDirection(entity.conveyor.direction);
    normalized.storedResource = normalizeResourceType(entity.conveyor.stored);
  }
  if (entity.splitter) {
    normalized.direction = normalizeDirection(entity.splitter.direction);
    normalized.storedResource = normalizeResourceType(entity.splitter.stored);
  }
  if (entity.armouredConveyor) {
    normalized.direction = normalizeDirection(entity.armouredConveyor.direction);
    normalized.storedResource = normalizeResourceType(entity.armouredConveyor.stored);
  }
  if (entity.bridge) {
    normalized.bridgeTarget = clonePosition(entity.bridge.target);
    normalized.storedResource = normalizeResourceType(entity.bridge.stored);
  }
  if (entity.harvester) {
    normalized.harvesterCooldown = entity.harvester.cooldown ?? null;
    normalized.harvesterResourceType = normalizeResourceType(
      entity.harvester.resourceType
    );
  }
  if (entity.foundry) {
    normalized.storedResource = normalizeResourceType(entity.foundry.stored);
  }
  if (entity.marker) {
    normalized.markerValue = entity.marker.value ?? null;
  }
  if (entity.core) {
    normalized.actionCooldown = entity.core.actionCooldown ?? null;
  }
  if (entity.gunner) {
    normalized.direction = normalizeDirection(entity.gunner.direction);
    normalized.ammoType = normalizeResourceType(entity.gunner.ammoType);
    normalized.ammoAmount = entity.gunner.ammoAmount ?? null;
  }
  if (entity.sentinel) {
    normalized.direction = normalizeDirection(entity.sentinel.direction);
    normalized.ammoType = normalizeResourceType(entity.sentinel.ammoType);
    normalized.ammoAmount = entity.sentinel.ammoAmount ?? null;
  }
  if (entity.breach) {
    normalized.direction = normalizeDirection(entity.breach.direction);
    normalized.ammoType = normalizeResourceType(entity.breach.ammoType);
    normalized.ammoAmount = entity.breach.ammoAmount ?? null;
  }
  if (entity.launcher) {
    normalized.ammoType = normalizeResourceType(entity.launcher.ammoType);
    normalized.ammoAmount = entity.launcher.ammoAmount ?? null;
  }

  return normalized;
}

function normalizeCoreEntity(core) {
  return {
    id: core.id,
    team: core.team,
    teamName: TEAM_NAME[core.team] || String(core.team),
    kind: "core",
    position: clonePosition(core.position),
    occupiedTiles: getOccupiedTilesForKind("core", core.position),
    hp: CORE_INITIAL_HP,
    maxHp: CORE_INITIAL_HP,
    actionCooldown: 0,
  };
}

function isTrackedInstanceKind(kind) {
  return TRACKED_INSTANCE_KINDS.has(kind);
}

function makeMissingAction(turn) {
  return {
    turn,
    exists: false,
    position: null,
    visionRadiusSq: null,
    startState: null,
    endState: null,
    visibleTiles: [],
    visibleTileCount: 0,
    visibleEntities: [],
    visibleEntityCount: 0,
    stdoutLines: [],
    execTimeUs: 0,
    tled: false,
    selfEventIndices: [],
  };
}

function finalizeTurnOutput(outputState) {
  const stdout = outputState.stdoutParts.join("\n");
  return {
    stdoutLines: stdout
      ? stdout
          .split(/\r?\n/)
          .map((line) => line.trimEnd())
          .filter((line) => line.length > 0)
      : [],
    execTimeUs: outputState.execTimeUs,
    tled: outputState.tled,
  };
}

function mergeTurnOutputIntoAction(action, turnOutput) {
  if (!turnOutput) return action;
  action.stdoutLines = turnOutput.stdoutLines;
  action.execTimeUs = turnOutput.execTimeUs;
  action.tled = turnOutput.tled;
  return action;
}

function coreFootprintPositions(centerPos) {
  const positions = [];
  for (let dy = -1; dy <= 1; dy++) {
    for (let dx = -1; dx <= 1; dx++) {
      positions.push({ x: centerPos.x + dx, y: centerPos.y + dy });
    }
  }
  return positions;
}

function getOccupiedPositionKeys(entity) {
  if (!entity.position) return [];
  if (entity.kind === "core") {
    return coreFootprintPositions(entity.position).map((pos) => `${pos.x},${pos.y}`);
  }
  return [`${entity.position.x},${entity.position.y}`];
}

function buildPositionEntityIndex(entities) {
  const index = new Map();
  for (const entity of entities.values()) {
    for (const key of getOccupiedPositionKeys(entity)) {
      index.set(key, entity);
    }
  }
  return index;
}

function getVisionOrigins(entity) {
  if (entity.kind === "core" && entity.position) {
    return coreFootprintPositions(entity.position);
  }
  return entity.position ? [entity.position] : [];
}

function summarizeEntityCounts(entities) {
  const counts = {};
  for (const entity of entities.values()) {
    const team = entity.teamName || "UNKNOWN";
    if (!counts[team]) counts[team] = {};
    counts[team][entity.kind] = (counts[team][entity.kind] || 0) + 1;
  }
  return counts;
}

function clonePlayers(players) {
  return {
    TEAM_A: { ...players.TEAM_A },
    TEAM_B: { ...players.TEAM_B },
  };
}

function getVisibleTilesForEntity(
  entity,
  mapWidth,
  mapHeight,
  environmentRows,
  positionEntityIndex
) {
  const radiusSq = VISION_RADIUS_SQ_BY_KIND[entity.kind];
  if (radiusSq == null || !entity.position) {
    return [];
  }

  const maxDelta = Math.floor(Math.sqrt(radiusSq));
  const seen = new Set();

  for (const origin of getVisionOrigins(entity)) {
    for (let dy = -maxDelta; dy <= maxDelta; dy++) {
      for (let dx = -maxDelta; dx <= maxDelta; dx++) {
        if (dx * dx + dy * dy > radiusSq) continue;
        const x = origin.x + dx;
        const y = origin.y + dy;
        if (x < 0 || y < 0 || x >= mapWidth || y >= mapHeight) continue;
        seen.add(`${x},${y}`);
      }
    }
  }

  return [...seen]
    .map((key) => {
      const [x, y] = key.split(",").map(Number);
      return {
        x,
        y,
      };
    })
    .sort((a, b) => a.y - b.y || a.x - b.x);
}

function makeExistingAction(
  turn,
  entity,
  mapWidth,
  mapHeight,
  environmentRows,
  positionEntityIndex
) {
  const visibleTiles = getVisibleTilesForEntity(
    entity,
    mapWidth,
    mapHeight,
    environmentRows,
    positionEntityIndex
  );
  const visibleEntities = [];
  const visibleEntityIds = new Set();
  for (const tile of visibleTiles) {
    const visibleEntity = positionEntityIndex.get(`${tile.x},${tile.y}`);
    if (visibleEntity && !visibleEntityIds.has(visibleEntity.id)) {
      visibleEntityIds.add(visibleEntity.id);
      visibleEntities.push(cloneJsonLike(visibleEntity));
    }
  }

  return {
    turn,
    exists: true,
    position: clonePosition(entity.position),
    visionRadiusSq: VISION_RADIUS_SQ_BY_KIND[entity.kind] ?? null,
    startState: cloneJsonLike(entity),
    endState: null,
    visibleTiles,
    visibleTileCount: visibleTiles.length,
    visibleEntities,
    visibleEntityCount: visibleEntities.length,
    stdoutLines: [],
    execTimeUs: 0,
    tled: false,
    selfEventIndices: [],
  };
}

function ensureTrackedInstanceRecord(instanceRecords, entity, fillThroughTurn) {
  let record = instanceRecords.get(entity.id);
  if (!record) {
    record = {
      id: entity.id,
      team: entity.teamName,
      kind: entity.kind,
      spawnTurn: null,
      despawnTurn: null,
      actions: [],
    };
    instanceRecords.set(entity.id, record);
  }

  while (record.actions.length < fillThroughTurn) {
    record.actions.push(makeMissingAction(record.actions.length + 1));
  }

  return record;
}

function buildEnvironmentRows(map) {
  return (map.rows || []).map((row) =>
    (row.tiles || []).map((tile) => ENV_NAME[tile] || "EMPTY")
  );
}

function getStoredLikeResource(entity) {
  if (!entity) return null;
  if (entity.storedResource) return entity.storedResource;
  if (entity.ammoType) return entity.ammoType;
  if (entity.harvesterResourceType) return entity.harvesterResourceType;
  return null;
}

function isTurretLikeKind(kind) {
  return (
    kind === "gunner" ||
    kind === "sentinel" ||
    kind === "breach" ||
    kind === "launcher"
  );
}

function applyResourceToDestination(entity, resourceTypeName) {
  if (!entity || !resourceTypeName || entity.kind === "core") return;

  if (isTurretLikeKind(entity.kind)) {
    entity.storedResource = null;
    if (entity.kind === "launcher" || resourceTypeName === "RESOURCE_RAW_AXIONITE") {
      entity.ammoType = null;
      entity.ammoAmount = 0;
      return;
    }
    entity.ammoType = resourceTypeName;
    entity.ammoAmount = 10;
    return;
  }

  if (entity.kind === "foundry") {
    const existing = entity.storedResource;
    if (
      (resourceTypeName === "RESOURCE_TITANIUM" &&
        existing === "RESOURCE_RAW_AXIONITE") ||
      (resourceTypeName === "RESOURCE_RAW_AXIONITE" &&
        existing === "RESOURCE_TITANIUM")
    ) {
      entity.storedResource = "RESOURCE_REFINED_AXIONITE";
      return;
    }
  }

  entity.storedResource = resourceTypeName;
}

function consumeTurretAmmo(entity) {
  if (!entity || !isTurretLikeKind(entity.kind)) return;
  const ammoCost = AMMO_COST_BY_KIND[entity.kind] ?? 0;
  if (ammoCost <= 0) return;
  const currentAmmo = entity.ammoAmount ?? 0;
  const nextAmmo = Math.max(0, currentAmmo - ammoCost);
  entity.ammoAmount = nextAmmo;
  if (nextAmmo === 0) {
    entity.ammoType = null;
  }
}

function normalizeTurnEvent(event) {
  return cloneJsonLike(event);
}

function sortNormalizedEntities(entities) {
  return [...entities.values()]
    .map((entity) => cloneJsonLike(entity))
    .sort((a, b) => a.id - b.id);
}

function getChangedEntityIds(events) {
  return [...new Set(events.flatMap((event) => event.relatedEntityIds || []))].sort(
    (a, b) => a - b
  );
}

function getEntitySnapshotsById(entityIds, entityMap) {
  return entityIds
    .map((id) => entityMap.get(id))
    .filter((entity) => entity != null)
    .map((entity) => cloneJsonLike(entity))
    .sort((a, b) => a.id - b.id);
}

function analyzeReplay(decodedReplay, replayPath, visualizerPath, topN) {
  const map = decodedReplay.map;
  const turns = decodedReplay.turns || [];
  const bytes = fs.readFileSync(replayPath);
  const environmentRows = buildEnvironmentRows(map);

  const currentEntities = new Map();
  const instanceRecords = new Map();
  const turnDetails = [];
  const builtByKindTeam = new Map();
  const removedByKindTeam = new Map();
  const botActionCounts = new Map();
  const botTypeCounts = new Map();
  const unitLogCounts = new Map();
  const rawOutputCounts = new Map();
  const eventCounts = {
    turretFires: 0,
    builderAttacks: 0,
    botOutputEvents: 0,
    tledBotOutputs: 0,
    maxExecUs: 0,
  };

  let players = {
    TEAM_A: {
      titanium: 1000,
      axionite: 0,
      resourcesCollected: 0,
      titaniumCollected: 0,
      axioniteCollected: 0,
    },
    TEAM_B: {
      titanium: 1000,
      axionite: 0,
      resourcesCollected: 0,
      titaniumCollected: 0,
      axioniteCollected: 0,
    },
  };
  const firstTitaniumCollectedTurn = { TEAM_A: null, TEAM_B: null };

  for (const core of map.cores || []) {
    const coreEntity = normalizeCoreEntity(core);
    currentEntities.set(coreEntity.id, coreEntity);
    const record = ensureTrackedInstanceRecord(instanceRecords, coreEntity, 0);
    record.spawnTurn = 1;
  }

  const initialEntities = sortNormalizedEntities(currentEntities);

  for (let turnIdx = 0; turnIdx < turns.length; turnIdx++) {
    const turnNumber = turnIdx + 1;
    const updates = turns[turnIdx].updates || [];
    const startOfTurnActions = new Map();
    const playersStart = clonePlayers(players);
    const aliveTrackedInstanceIdsStart = [];
    const entitiesStartSnapshot = new Map(
      [...currentEntities.entries()].map(([id, entity]) => [id, cloneJsonLike(entity)])
    );
    const positionEntityIndexStart = buildPositionEntityIndex(currentEntities);

    for (const entity of currentEntities.values()) {
      if (!isTrackedInstanceKind(entity.kind)) continue;
      const record = ensureTrackedInstanceRecord(instanceRecords, entity, turnIdx);
      if (record.spawnTurn == null || turnNumber < record.spawnTurn) {
        record.spawnTurn = turnNumber;
      }
      aliveTrackedInstanceIdsStart.push(entity.id);
      startOfTurnActions.set(
        entity.id,
        makeExistingAction(
          turnNumber,
          entity,
          map.width,
          map.height,
          environmentRows,
          positionEntityIndexStart
        )
      );
    }

    const turnOutputById = new Map();
    const normalizedTurnEvents = [];
    for (const update of updates) {
      if (update.placeEntity) {
        const entity = normalizeEntity(update.placeEntity.entity);
        currentEntities.set(entity.id, entity);
        bump(builtByKindTeam, `${entity.teamName}:${entity.kind}`);
        if (isTrackedInstanceKind(entity.kind)) {
          const record = ensureTrackedInstanceRecord(instanceRecords, entity, turnIdx);
          if (record.spawnTurn == null || record.spawnTurn > turnNumber + 1) {
            record.spawnTurn = turnNumber + 1;
          }
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "place_entity",
            relatedEntityIds: [entity.id],
            entity: cloneJsonLike(entity),
          })
        );
        continue;
      }

      if (update.moveBuilderBot) {
        const entity = currentEntities.get(update.moveBuilderBot.id);
        const from = entity ? clonePosition(entity.position) : null;
        if (entity) {
          entity.position = clonePosition(update.moveBuilderBot.to);
          entity.occupiedTiles = getOccupiedTilesForKind(entity.kind, entity.position);
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "move_builder_bot",
            relatedEntityIds: [update.moveBuilderBot.id],
            actorId: update.moveBuilderBot.id,
            actorKind: entity?.kind ?? null,
            actorTeam: entity?.teamName ?? null,
            from,
            to: clonePosition(update.moveBuilderBot.to),
          })
        );
        continue;
      }

      if (update.removeEntity) {
        const entity = currentEntities.get(update.removeEntity.id);
        if (entity) {
          bump(removedByKindTeam, `${entity.teamName}:${entity.kind}`);
          if (isTrackedInstanceKind(entity.kind)) {
            const record = ensureTrackedInstanceRecord(
              instanceRecords,
              entity,
              turnIdx
            );
            if (record.despawnTurn == null) {
              record.despawnTurn = turnNumber;
            }
          }
          currentEntities.delete(update.removeEntity.id);
        } else {
          bump(removedByKindTeam, "UNKNOWN:unknown");
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "remove_entity",
            relatedEntityIds: [update.removeEntity.id],
            entityId: update.removeEntity.id,
            entity: entity ? cloneJsonLike(entity) : null,
          })
        );
        continue;
      }

      if (update.updateHp) {
        const entity = currentEntities.get(update.updateHp.id);
        const hpBefore = entity?.hp ?? null;
        if (entity) {
          entity.hp = (entity.hp ?? 0) + update.updateHp.delta;
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "update_hp",
            relatedEntityIds: [update.updateHp.id],
            entityId: update.updateHp.id,
            delta: update.updateHp.delta,
            hpBefore,
            hpAfter: entity?.hp ?? null,
          })
        );
        continue;
      }

      if (update.distributeResources && update.distributeResources.moves) {
        const positionEntityIndex = buildPositionEntityIndex(currentEntities);
        const moves = [];
        for (const move of update.distributeResources.moves) {
          const from = clonePosition(move.from);
          const to = clonePosition(move.to);
          const sourceEntity =
            from == null ? null : positionEntityIndex.get(`${from.x},${from.y}`) || null;
          const targetEntity =
            to == null ? null : positionEntityIndex.get(`${to.x},${to.y}`) || null;
          const resourceType =
            normalizeResourceType(move.resourceId) ||
            getStoredLikeResource(sourceEntity) ||
            null;

          if (sourceEntity && sourceEntity.kind === "harvester") {
            sourceEntity.harvesterCooldown = 3;
          }
          if (sourceEntity) {
            sourceEntity.storedResource = null;
          }
          if (targetEntity) {
            applyResourceToDestination(targetEntity, resourceType);
          }

          moves.push({
            from,
            to,
            resourceType,
            sourceEntityId: sourceEntity?.id ?? null,
            sourceEntityKind: sourceEntity?.kind ?? null,
            targetEntityId: targetEntity?.id ?? null,
            targetEntityKind: targetEntity?.kind ?? null,
          });
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "distribute_resources",
            relatedEntityIds: [
              ...new Set(
                moves.flatMap((move) =>
                  [move.sourceEntityId, move.targetEntityId].filter(
                    (id) => id != null
                  )
                )
              ),
            ],
            moves,
          })
        );
        continue;
      }

      if (update.updatePlayers && update.updatePlayers.players) {
        const p = update.updatePlayers.players;
        if (p.a) {
          players.TEAM_A = {
            titanium: p.a.titanium,
            axionite: p.a.axionite,
            resourcesCollected: p.a.resourcesCollected || 0,
            titaniumCollected: p.a.titaniumCollected || 0,
            axioniteCollected: p.a.axioniteCollected || 0,
          };
          if (
            firstTitaniumCollectedTurn.TEAM_A == null &&
            players.TEAM_A.titaniumCollected > 0
          ) {
            firstTitaniumCollectedTurn.TEAM_A = turnNumber;
          }
        }
        if (p.b) {
          players.TEAM_B = {
            titanium: p.b.titanium,
            axionite: p.b.axionite,
            resourcesCollected: p.b.resourcesCollected || 0,
            titaniumCollected: p.b.titaniumCollected || 0,
            axioniteCollected: p.b.axioniteCollected || 0,
          };
          if (
            firstTitaniumCollectedTurn.TEAM_B == null &&
            players.TEAM_B.titaniumCollected > 0
          ) {
            firstTitaniumCollectedTurn.TEAM_B = turnNumber;
          }
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "update_players",
            relatedEntityIds: [],
            players: clonePlayers(players),
          })
        );
        continue;
      }

      if (update.setActionCooldown) {
        const entity = currentEntities.get(update.setActionCooldown.id);
        const value = update.setActionCooldown.value;
        if (entity) {
          entity.actionCooldown = value;
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "set_action_cooldown",
            relatedEntityIds: [update.setActionCooldown.id],
            entityId: update.setActionCooldown.id,
            entityKind: entity?.kind ?? null,
            entityTeam: entity?.teamName ?? null,
            value,
          })
        );
        continue;
      }

      if (update.setMoveCooldown) {
        const entity = currentEntities.get(update.setMoveCooldown.id);
        const value = update.setMoveCooldown.value;
        if (entity) {
          entity.moveCooldown = value;
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "set_move_cooldown",
            relatedEntityIds: [update.setMoveCooldown.id],
            entityId: update.setMoveCooldown.id,
            entityKind: entity?.kind ?? null,
            entityTeam: entity?.teamName ?? null,
            value,
          })
        );
        continue;
      }

      if (update.fireTurret) {
        eventCounts.turretFires++;
        const positionEntityIndex = buildPositionEntityIndex(currentEntities);
        const from = clonePosition(update.fireTurret.from);
        const to = clonePosition(update.fireTurret.to);
        const turret =
          from == null ? null : positionEntityIndex.get(`${from.x},${from.y}`) || null;
        const ammoBefore = turret?.ammoAmount ?? null;
        if (turret) {
          consumeTurretAmmo(turret);
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "fire_turret",
            relatedEntityIds: turret ? [turret.id] : [],
            actorId: turret?.id ?? null,
            actorKind: turret?.kind ?? null,
            actorTeam: turret?.teamName ?? null,
            from,
            to,
            ammoBefore,
            ammoAfter: turret?.ammoAmount ?? null,
          })
        );
        continue;
      }

      if (update.builderAttack) {
        eventCounts.builderAttacks++;
        const entity = currentEntities.get(update.builderAttack.id);
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "builder_attack",
            relatedEntityIds: [update.builderAttack.id],
            actorId: update.builderAttack.id,
            actorKind: entity?.kind ?? null,
            actorTeam: entity?.teamName ?? null,
            from: entity ? clonePosition(entity.position) : null,
          })
        );
        continue;
      }

      if (update.botOutput) {
        const o = update.botOutput;
        eventCounts.botOutputEvents++;
        eventCounts.maxExecUs = Math.max(eventCounts.maxExecUs, o.execTimeUs || 0);
        if (o.tled) eventCounts.tledBotOutputs++;

        let turnOutput = turnOutputById.get(o.id);
        if (!turnOutput) {
          turnOutput = { stdoutParts: [], execTimeUs: 0, tled: false };
          turnOutputById.set(o.id, turnOutput);
        }
        if (o.stdout && o.stdout.trim()) {
          turnOutput.stdoutParts.push(o.stdout.trimEnd());
          const lines = o.stdout
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter(Boolean);
          for (const line of lines) {
            bump(rawOutputCounts, line);
            const parsed = parseTypeAndAction(line);
            if (parsed) {
              bump(botActionCounts, parsed.action);
              bump(botTypeCounts, parsed.type);
              bump(unitLogCounts, parsed.unitId);
            }
          }
        }
        turnOutput.execTimeUs = Math.max(turnOutput.execTimeUs, o.execTimeUs || 0);
        turnOutput.tled = turnOutput.tled || !!o.tled;

        const entity = currentEntities.get(o.id);
        if (entity && isTrackedInstanceKind(entity.kind)) {
          const record = ensureTrackedInstanceRecord(instanceRecords, entity, turnIdx);
          if (record.spawnTurn == null) {
            record.spawnTurn = turnNumber;
          }
        }
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "bot_output",
            relatedEntityIds: [o.id],
            entityId: o.id,
            entityKind: entity?.kind ?? null,
            entityTeam: entity?.teamName ?? null,
            stdoutLineCount: (o.stdout || "")
              .split(/\r?\n/)
              .map((line) => line.trimEnd())
              .filter((line) => line.length > 0).length,
            execTimeUs: o.execTimeUs || 0,
            tled: !!o.tled,
          })
        );
        continue;
      }

      if (update.indicatorLine) {
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "indicator_line",
            relatedEntityIds: [update.indicatorLine.id],
            entityId: update.indicatorLine.id,
            from: clonePosition(update.indicatorLine.posA),
            to: clonePosition(update.indicatorLine.posB),
            color: {
              r: update.indicatorLine.r,
              g: update.indicatorLine.g,
              b: update.indicatorLine.b,
            },
          })
        );
        continue;
      }

      if (update.indicatorDot) {
        normalizedTurnEvents.push(
          normalizeTurnEvent({
            type: "indicator_dot",
            relatedEntityIds: [update.indicatorDot.id],
            entityId: update.indicatorDot.id,
            position: clonePosition(update.indicatorDot.pos),
            color: {
              r: update.indicatorDot.r,
              g: update.indicatorDot.g,
              b: update.indicatorDot.b,
            },
          })
        );
        continue;
      }
    }

    for (const record of instanceRecords.values()) {
      let action = startOfTurnActions.get(record.id) || makeMissingAction(turnNumber);
      action = mergeTurnOutputIntoAction(
        action,
        finalizeTurnOutput(
          turnOutputById.get(record.id) || {
            stdoutParts: [],
            execTimeUs: 0,
            tled: false,
          }
        )
      );
      const endEntity = currentEntities.get(record.id);
      action.endState = endEntity ? cloneJsonLike(endEntity) : null;
      action.selfEventIndices = normalizedTurnEvents
        .map((event, index) =>
          (event.relatedEntityIds || []).includes(record.id) ? index : -1
        )
        .filter((index) => index >= 0);
      record.actions.push(action);
    }

    const changedEntityIds = getChangedEntityIds(normalizedTurnEvents);
    turnDetails.push({
      turn: turnNumber,
      playersStart,
      playersEnd: clonePlayers(players),
      trackedInstanceIdsAliveStart: aliveTrackedInstanceIdsStart.sort((a, b) => a - b),
      trackedInstanceIdsAliveEnd: [...currentEntities.values()]
        .filter((entity) => isTrackedInstanceKind(entity.kind))
        .map((entity) => entity.id)
        .sort((a, b) => a - b),
      entityCountsStart: summarizeEntityCounts(entitiesStartSnapshot),
      entityCountsEnd: summarizeEntityCounts(currentEntities),
      changedEntityIds,
      changedEntitiesStart: getEntitySnapshotsById(
        changedEntityIds,
        entitiesStartSnapshot
      ),
      changedEntitiesEnd: getEntitySnapshotsById(changedEntityIds, currentEntities),
      events: normalizedTurnEvents,
    });
  }

  const tileCounts = { EMPTY: 0, WALL: 0, ORE_TITANIUM: 0, ORE_AXIONITE: 0 };
  for (const row of environmentRows) {
    for (const tile of row) {
      tileCounts[tile] = (tileCounts[tile] || 0) + 1;
    }
  }

  const instances = [...instanceRecords.values()]
    .sort((a, b) => {
      if (a.team !== b.team) return a.team.localeCompare(b.team);
      if (a.kind !== b.kind) return a.kind.localeCompare(b.kind);
      return a.id - b.id;
    })
    .map((record) => ({
      id: record.id,
      team: record.team,
      kind: record.kind,
      spawnTurn: record.spawnTurn,
      despawnTurn: record.despawnTurn,
      actions: record.actions,
    }));
  const finalEntities = sortNormalizedEntities(currentEntities);

  return {
    replayPath: path.resolve(replayPath),
    visualizerSchemaPath: path.resolve(visualizerPath),
    generatedAt: new Date().toISOString(),
    sizeBytes: bytes.length,
    turns: turns.length,
    winner: decodedReplay.winner == null ? null : TEAM_NAME[decodedReplay.winner],
    map: {
      width: map.width,
      height: map.height,
      rows: environmentRows,
      cores: (map.cores || []).map((core) => ({
        id: core.id,
        team: TEAM_NAME[core.team],
        x: core.position.x,
        y: core.position.y,
        occupiedTiles: coreFootprintPositions(core.position),
      })),
      tileCounts,
    },
    initialEntities,
    finalEntities,
    finalResources: players,
    firstTitaniumCollectedTurn,
    eventCounts,
    builtByKindTeam: topEntries(builtByKindTeam, topN),
    removedByKindTeam: topEntries(removedByKindTeam, topN),
    botActionCounts: topEntries(botActionCounts, topN),
    botTypeCounts: topEntries(botTypeCounts, topN),
    unitLogCounts: topEntries(unitLogCounts, topN),
    topOutputLines: topEntries(rawOutputCounts, topN),
    turnsDetailed: turnDetails,
    instances,
  };
}

function padNumber(value, width = 4) {
  return String(value).padStart(width, "0");
}

function writeJsonFile(outDir, relativePath, payload, writtenFiles) {
  const fullPath = path.join(outDir, relativePath);
  fs.mkdirSync(path.dirname(fullPath), { recursive: true });
  fs.writeFileSync(fullPath, JSON.stringify(payload, null, 2) + "\n", "utf8");
  if (writtenFiles) {
    writtenFiles.push({
      path: relativePath.replaceAll(path.sep, "/"),
      bytes: fs.statSync(fullPath).size,
    });
  }
}

function writeChunkedOutput(summary, outDir, options) {
  const turnChunkSize = options.turnChunkSize;
  const actionChunkSize = options.actionChunkSize;
  const writtenFiles = [];

  fs.mkdirSync(outDir, { recursive: true });

  writeJsonFile(outDir, "map.json", summary.map, writtenFiles);
  writeJsonFile(outDir, "initial_entities.json", summary.initialEntities, writtenFiles);
  writeJsonFile(outDir, "final_entities.json", summary.finalEntities, writtenFiles);

  const turnChunks = [];
  for (let index = 0; index < summary.turnsDetailed.length; index += turnChunkSize) {
    const chunk = summary.turnsDetailed.slice(index, index + turnChunkSize);
    const startTurn = chunk[0]?.turn ?? index + 1;
    const endTurn = chunk[chunk.length - 1]?.turn ?? startTurn;
    const relativePath = `turns/turns_${padNumber(startTurn)}_${padNumber(endTurn)}.json`;
    writeJsonFile(
      outDir,
      relativePath,
      {
        startTurn,
        endTurn,
        count: chunk.length,
        turnsDetailed: chunk,
      },
      writtenFiles
    );
    turnChunks.push({
      path: relativePath,
      startTurn,
      endTurn,
      count: chunk.length,
    });
  }

  const instanceIndex = [];
  for (const instance of summary.instances) {
    const chunks = [];
    for (let index = 0; index < instance.actions.length; index += actionChunkSize) {
      const chunk = instance.actions.slice(index, index + actionChunkSize);
      const startTurn = chunk[0]?.turn ?? index + 1;
      const endTurn = chunk[chunk.length - 1]?.turn ?? startTurn;
      const relativePath =
        `instances/instance_${padNumber(instance.id)}_actions_` +
        `${padNumber(startTurn)}_${padNumber(endTurn)}.json`;
      writeJsonFile(
        outDir,
        relativePath,
        {
          id: instance.id,
          team: instance.team,
          kind: instance.kind,
          spawnTurn: instance.spawnTurn,
          despawnTurn: instance.despawnTurn,
          startTurn,
          endTurn,
          count: chunk.length,
          actions: chunk,
        },
        writtenFiles
      );
      chunks.push({
        path: relativePath,
        startTurn,
        endTurn,
        count: chunk.length,
      });
    }

    instanceIndex.push({
      id: instance.id,
      team: instance.team,
      kind: instance.kind,
      spawnTurn: instance.spawnTurn,
      despawnTurn: instance.despawnTurn,
      actionCount: instance.actions.length,
      chunks,
    });
  }
  writeJsonFile(outDir, "instances/index.json", instanceIndex, writtenFiles);

  const index = {
    schemaVersion: 2,
    replayPath: summary.replayPath,
    visualizerSchemaPath: summary.visualizerSchemaPath,
    generatedAt: summary.generatedAt,
    sizeBytes: summary.sizeBytes,
    turns: summary.turns,
    winner: summary.winner,
    finalResources: summary.finalResources,
    firstTitaniumCollectedTurn: summary.firstTitaniumCollectedTurn,
    eventCounts: summary.eventCounts,
    builtByKindTeam: summary.builtByKindTeam,
    removedByKindTeam: summary.removedByKindTeam,
    botActionCounts: summary.botActionCounts,
    botTypeCounts: summary.botTypeCounts,
    unitLogCounts: summary.unitLogCounts,
    topOutputLines: summary.topOutputLines,
    files: {
      map: "map.json",
      initialEntities: "initial_entities.json",
      finalEntities: "final_entities.json",
      instances: "instances/index.json",
    },
    turnsDetailed: {
      chunkSize: turnChunkSize,
      chunkCount: turnChunks.length,
      chunks: turnChunks,
    },
    instances: {
      count: instanceIndex.length,
      actionChunkSize,
      index: "instances/index.json",
    },
    writtenFiles,
  };
  writeJsonFile(outDir, "index.json", index, null);
  return index;
}

function main() {
  const {
    replayPath,
    outPath,
    outDirPath,
    schemaPath,
    topN,
    turnChunkSize,
    actionChunkSize,
  } = parseArgs(
    process.argv.slice(2)
  );

  if (!fileExists(replayPath)) {
    throw new Error(`Replay file not found: ${replayPath}`);
  }

  const visualizerPath = resolveVisualizerPath(schemaPath);
  const ReplayType = loadReplayType(visualizerPath);
  const replayBytes = fs.readFileSync(replayPath);
  const decodedReplay = ReplayType.decode(replayBytes);
  const summary = analyzeReplay(decodedReplay, replayPath, visualizerPath, topN);

  if (outDirPath) {
    const index = writeChunkedOutput(summary, outDirPath, {
      turnChunkSize,
      actionChunkSize,
    });
    console.log(
      [
        `Wrote chunked replay output to ${outDirPath}`,
        `Index: ${path.join(outDirPath, "index.json")}`,
        `Turn chunks: ${index.turnsDetailed.chunkCount}`,
        `Instances: ${index.instances.count}`,
      ].join("\n")
    );
    return;
  }

  const summaryJson = JSON.stringify(summary, null, 2);

  if (outPath) {
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, summaryJson + "\n", "utf8");
  } else {
    process.stdout.write(summaryJson + "\n");
  }
}

try {
  main();
} catch (err) {
  console.error(
    `[replay_parser] ${err && err.message ? err.message : String(err)}`
  );
  process.exit(1);
}
