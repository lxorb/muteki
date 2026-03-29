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

function usage() {
  console.log(
    [
      "Usage:",
      "  node parse_replay.js <replay_path> [--out <summary.json>] [--schema <visualizer_main.js>] [--top <N>]",
      "",
      "Options:",
      "  --out     Write JSON summary to file instead of stdout.",
      "  --schema  Explicit path to cambc visualizer bundle (main-*.js).",
      "  --top     Number of top items for large counters (default: 30).",
      "",
      "Environment:",
      "  CAMBC_VISUALIZER_JS  Explicit schema JS path (used if --schema is not set).",
    ].join("\n")
  );
}

function parseArgs(argv) {
  let replayPath = null;
  let outPath = null;
  let schemaPath = null;
  let topN = 30;

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

  return {
    replayPath: path.resolve(replayPath),
    outPath: outPath ? path.resolve(outPath) : null,
    schemaPath: schemaPath ? path.resolve(schemaPath) : null,
    topN,
  };
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

function extractXtObject(jsSource) {
  let start = jsSource.indexOf("Xt={");
  if (start === -1) start = jsSource.indexOf("Xt = {");
  if (start === -1) {
    throw new Error("Could not find Xt schema assignment in visualizer JS");
  }

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

  throw new Error("Could not find closing brace for Xt schema object");
}

function loadReplayType(visualizerPath) {
  const js = fs.readFileSync(visualizerPath, "utf8");
  const xtObjectLiteral = extractXtObject(js);
  const schema = eval(`(() => { const Xt = ${xtObjectLiteral}; return Xt; })()`);
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
  const m = line.match(/^Unit\s+(\d+)\s+type:\s*(.+?)\s+action:\s*(.+?)(?:\s+turn took|$)/i);
  if (!m) return null;
  return {
    unitId: m[1],
    type: m[2].trim().toLowerCase(),
    action: m[3].trim().toLowerCase(),
  };
}

function analyzeReplay(decodedReplay, replayPath, visualizerPath, topN) {
  const map = decodedReplay.map;
  const turns = decodedReplay.turns || [];
  const bytes = fs.readFileSync(replayPath);

  const entities = new Map();
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
    TEAM_A: { titanium: 1000, axionite: 0, resourcesCollected: 0, titaniumCollected: 0, axioniteCollected: 0 },
    TEAM_B: { titanium: 1000, axionite: 0, resourcesCollected: 0, titaniumCollected: 0, axioniteCollected: 0 },
  };
  let firstTitaniumCollectedTurn = { TEAM_A: null, TEAM_B: null };

  for (let turnIdx = 0; turnIdx < turns.length; turnIdx++) {
    const updates = turns[turnIdx].updates || [];

    for (const update of updates) {
      if (update.placeEntity) {
        const e = update.placeEntity.entity;
        const kind = entityKind(e);
        entities.set(e.id, { id: e.id, team: e.team, kind, pos: e.position });
        bump(builtByKindTeam, `${TEAM_NAME[e.team]}:${kind}`);
        continue;
      }

      if (update.moveBuilderBot) {
        const it = entities.get(update.moveBuilderBot.id);
        if (it) it.pos = update.moveBuilderBot.to;
        continue;
      }

      if (update.removeEntity) {
        const id = update.removeEntity.id;
        const known = entities.get(id);
        if (known) {
          bump(removedByKindTeam, `${TEAM_NAME[known.team]}:${known.kind}`);
          entities.delete(id);
        } else {
          bump(removedByKindTeam, "UNKNOWN:unknown");
        }
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
            firstTitaniumCollectedTurn.TEAM_A = turnIdx + 1;
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
            firstTitaniumCollectedTurn.TEAM_B = turnIdx + 1;
          }
        }
        continue;
      }

      if (update.fireTurret) {
        eventCounts.turretFires++;
        continue;
      }

      if (update.builderAttack) {
        eventCounts.builderAttacks++;
        continue;
      }

      if (update.botOutput) {
        const o = update.botOutput;
        eventCounts.botOutputEvents++;
        eventCounts.maxExecUs = Math.max(eventCounts.maxExecUs, o.execTimeUs || 0);
        if (o.tled) eventCounts.tledBotOutputs++;

        if (o.stdout && o.stdout.trim()) {
          const lines = o.stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
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
      }
    }
  }

  const tileCounts = { EMPTY: 0, WALL: 0, ORE_TITANIUM: 0, ORE_AXIONITE: 0 };
  for (const row of map.rows || []) {
    for (const tile of row.tiles || []) {
      const key = ENV_NAME[tile] || "EMPTY";
      tileCounts[key] = (tileCounts[key] || 0) + 1;
    }
  }

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
      cores: (map.cores || []).map((core) => ({
        id: core.id,
        team: TEAM_NAME[core.team],
        x: core.position.x,
        y: core.position.y,
      })),
      tileCounts,
    },
    finalResources: players,
    firstTitaniumCollectedTurn,
    eventCounts,
    builtByKindTeam: topEntries(builtByKindTeam, topN),
    removedByKindTeam: topEntries(removedByKindTeam, topN),
    botActionCounts: topEntries(botActionCounts, topN),
    botTypeCounts: topEntries(botTypeCounts, topN),
    unitLogCounts: topEntries(unitLogCounts, topN),
    topOutputLines: topEntries(rawOutputCounts, topN),
  };
}

function main() {
  const { replayPath, outPath, schemaPath, topN } = parseArgs(process.argv.slice(2));

  if (!fileExists(replayPath)) {
    throw new Error(`Replay file not found: ${replayPath}`);
  }

  const visualizerPath = resolveVisualizerPath(schemaPath);
  const ReplayType = loadReplayType(visualizerPath);
  const replayBytes = fs.readFileSync(replayPath);
  const decodedReplay = ReplayType.decode(replayBytes);
  const summary = analyzeReplay(decodedReplay, replayPath, visualizerPath, topN);
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
  console.error(`[replay_parser] ${err && err.message ? err.message : String(err)}`);
  process.exit(1);
}
