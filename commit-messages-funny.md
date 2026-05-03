# Commit Messages by Funniness

Ordered funniest to least funny. Ratings are subjective, from `10` = funniest to `0` = aggressively normal.  
Total commits: 617

| Rating | Author | LOC Changed | Message |
|---:|---|---:|---|
| 10 | nina | 123 | SELF DESTRUCTION MUHAHAHA |
| 10 | lxorb | 13890 | potato |
| 9 | nina | 2 | praying that no stupid self destruction anymore :( |
| 9 | nina | 176 | dont blindly destroy harvesters pretty pls |
| 9 | nina | 3 | dont be so introverted, mr. core defender! |
| 9 | infinitylooped | 11095 | random okonomiyaki stuff |
| 8 | nina | 177 | i hope this doesnt create a merge conflict :D hehe |
| 8 | lxorb | 70 | matcha chocolate is broken |
| 8 | infinitylooped | 440 | Let Claude cook |
| 8 | nina | 10 | lets not destroy turrets to build turrets |
| 8 | nina | 16 | (core) defender can now actually build missing supply link yippie |
| 8 | nina | 75 | gunners were being stupid |
| 8 | nina | 3 | scavenger >> SORRY |
| 7 | lxorb | 3017 | i like sushi |
| 7 | infinitylooped | 987 | it is indeed sushi time |
| 7 | nina | 8 | lets only self destruct when closing gap possible! |
| 7 | nina | 28 | aggressively kill enemies |
| 7 | nina | 7 | fix: self-destruct when not enough attention |
| 7 | nina | 57 | standing next to you |
| 6 | infinitylooped | 53 | takoyaki (fix submission error related to finally block use) |
| 6 | nina | 42 | ... update_target_zones_building arguments were inconsistent (no logical bug, but it bothered me) |
| 6 | lxorb | 150 | Add harassment yeeter annoyance strategy |
| 6 | nina | 2 | commenting annoying in |
| 6 | lxorb | 416 | semi finished nina obliterate stuff |
| 6 | nina | 15 | redundant computation of in_action_range, affordable_rank, ... for obliterating |
| 6 | nina | 3448481 | change u_get_turret_build_plan(candidate.position) -> compute once per candidate! ---- goal: make obliterating efficient |
| 6 | nina | 2 | aggression turned on |
| 6 | nina | 2 | aggression -- |
| 6 | nina | 2 | prompt 99 |
| 6 | nina | 42 | self-destruct if blocking harv |
| 5 | lxorb | 212 | Reuse action-reachable launcher cache for yeeting |
| 5 | nina | 66 | emil 4th prompt - skipping precomp for harassment / core defender<br><br>Skip the expensive frontier-expand cache population in map preprocessing<br>when the active bot will run as a harassment or core-defender builder.<br><br>- Map: add `skip_frontier_expand_this_turn` flag and guard it inside<br>`u_update_frontier_expand_cache`. Placed after the newly-seen → pending<br>transfer so indices first observed during skipped turns are not lost<br>(they are processed by the next non-skip bot).<br>- Agent: add `u_before_vision_update` hook, reset the flag and call the<br>hook before `u_update_vision` so other agents keep default behavior.<br>- BuilderAgent: infer role from current position relative to the own<br>core center (mirroring `u_infer_strategy_by_spawning_tile`); when the<br>center is not yet known, fall back to the default (no skip).<br><br>Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com> |
| 5 | nina | 15 | PROMPT 7 AGAIN |
| 5 | nina | 27 | self destruct if not fed |
| 4 | lxorb | 281 | Add launcher yeet path planning and target ranking |
| 4 | nina | 39 | PROMPT 6 EMIL<br><br>Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com> |
| 4 | nina | 8 | PROMPT 6 EMIL |
| 4 | nina | 340 | PROMPT 5 |
| 4 | nina | 238 | prompt 9 |
| 4 | nina | 12 | prompt 10 |
| 4 | nina | 93 | prompt 11 |
| 4 | lxorb | 24 | Remove yeeter core proximity gate |
| 4 | lxorb | 13 | Prefer cardinal yeeter launcher spots |
| 4 | lxorb | 73 | Add yeeter-trapped attack strategy |
| 4 | nina | 4761899 | currentbot deleted |
| 4 | nina | 50 | enemy-throw fallback logic |
| 4 | nina | 6 | undo: supply >>, scav. >> |
| 3 | nina | 581 | prompt-generated changes: changing map attributes (lists), indexing |
| 3 | lxorb | 73 | Add berserk harassment trigger |
| 3 | nina | 16 | emil 3 |
| 3 | nina | 78 | rotate |
| 2 | lxorb | 7 | Initial commit |
| 2 | einbocha | 59 | cambc starter |
| 2 | einbocha | 24 | introduced simple structure to the README.md |
| 2 | einbocha | 31 | bot strategy can be selected by inheritance |
| 2 | einbocha | 33 | bot strategy can be selected by inheritance |
| 2 | ninag | 42 | adding map matrix |
| 2 | einbocha | 17 | refactored enums to use StrEnum and added exists() utility function to unit |
| 2 | nina | 0 | fix file structure (merge changed it) |
| 2 | lxorb | 5 | minor changes to README.md |
| 2 | lxorb | 79 | initial formatting pass |
| 2 | einbocha | 79 | expanded README with bot implementation guide and refactored Information and Unit classes |
| 2 | nina | 21 | re-add changes to Bot (lost due to merge) |
| 2 | lxorb | 86 | structural changes to src/bots/__init__.py |
| 2 | lxorb | 16 | fix main Bot import |
| 2 | lxorb | 127 | Restructure bots layout around shared lib |
| 2 | lxorb | 3 | modify .vscode/settings.json |
| 2 | lxorb | 27 | structure builder bot implementations via commenting |
| 2 | lxorb | 2 | docs update |
| 2 | einbocha | 116 | modularized bot strategies by introducing strategy-specific classes for core and builder logic |
| 2 | infinitylooped | 1 | gitignore parsed json replays |
| 2 | infinitylooped | 4 | fix agent error |
| 2 | einbocha | 0 | moved tile module from lib.tile to lib.map.tile |
| 2 | lxorb | 40 | Infer builder strategies from spawn tiles |
| 2 | lxorb | 64 | Fix uewomirudake startup and pathing bugs |
| 2 | lxorb | 50 | Fix supplier targeting in uewomirudake |
| 2 | lxorb | 2 | Fix passable blocker clearing in uewomirudake |
| 2 | lxorb | 2 | Fix enemy core supply link targeting in uewomirudake |
| 2 | lxorb | 20 | some more bugfixes |
| 2 | lxorb | 6 | some more bugfixes |
| 2 | lxorb | 10 | Restrict harvester adjacency placement rules |
| 2 | lxorb | 44 | enhance debug printout |
| 2 | lxorb | 9 | Log builder strategy handler timing |
| 2 | lxorb | 49 | Avoid Position allocation in distance BFS |
| 2 | lxorb | 515 | made attribute updating 5x faster |
| 2 | lxorb | 515 | Revert "made attribute updating 5x faster"<br><br>This reverts commit 0fd89239e1ed6e36cd2b529ad92ebfecf52b439f. |
| 2 | lxorb | 279 | Centralize visible map cache updates |
| 2 | infinitylooped | 12 | Stop tracking actual settings file |
| 2 | infinitylooped | 140 | Improve s_frontier_expand efficiency |
| 2 | infinitylooped | 40 | Unify frontier expand logic methods |
| 2 | infinitylooped | 129 | Generate initial harvester supply link optimization |
| 2 | infinitylooped | 105 | Review harvester supply link optimizations and remove old code |
| 2 | lxorb | 28 | initialize defender bot strategy with stubs |
| 2 | lxorb | 9 | Prioritize harvesters by core distance |
| 2 | lxorb | 39 | enhance chokepoint conveyor placement |
| 2 | lxorb | 8 | fix building walkable on own tile |
| 2 | lxorb | 2 | minor scavenger strategy adjustment |
| 2 | infinitylooped | 216 | Swap foundry and splitter priorities |
| 2 | infinitylooped | 9 | Fix broken raw axionite supply chain core avoidance |
| 2 | infinitylooped | 5 | Fix (small) remove enemy roads counting towards valid foundry supply routes |
| 2 | infinitylooped | 49 | Fix foundries without supply chains forcing supplier waits, resolve foundry candidate tiebreakers by bot distance |
| 2 | lxorb | 7 | Only hold build targets within action range |
| 2 | lxorb | 9 | Step onto newly built conveyors |
| 2 | lxorb | 99 | Weight diagonal core-distance steps as two |
| 2 | lxorb | 67 | Prioritize surrounding harvesters before building |
| 2 | lxorb | 2 | Delay foundry strategy start to turn 150 |
| 2 | lxorb | 18 | improve multi bb conveyor placement |
| 2 | lxorb | 20 | fix healing |
| 2 | lxorb | 27 | some more healing fixes |
| 2 | lxorb | 566 | Revert "Remove map distance fields"<br><br>This reverts commit 4456fcd8e7025e20c1139916d9c301a5d656e53c. |
| 2 | lxorb | 1 | Stop turrets targeting harvesters |
| 2 | lxorb | 557 | Simplify map distance handling and cleanup dead code |
| 2 | lxorb | 24 | Port dev/infinity map tuning flags |
| 2 | infinitylooped | 190 | [Codex] Fix "Port dev/infinity map tuning flags" causing bots to build barriers instead of harvesters |
| 2 | infinitylooped | 75 | [Codex] Add overtime checks in loops with many iterations which have a safe "incomplete state" |
| 2 | infinitylooped | 91 | [Codex] Fix harvesters not being built |
| 2 | infinitylooped | 8 | Prep for next submission |
| 2 | infinitylooped | 104 | [Codex] Add overtime checks for map with resumable state |
| 2 | infinitylooped | 299 | [Codex] Trying to add more overtime checks |
| 2 | infinitylooped | 12 | Undo debug prints |
| 2 | infinitylooped | 6 | Better allocated times |
| 2 | infinitylooped | 9746 | Better overtime checks |
| 2 | infinitylooped | 23 | modify bridge target to only check tiles within bridge radius |
| 2 | infinitylooped | 29 | have round stopwatch print the last couple method names before overtime, make bridge target logic use min instead of sorting |
| 2 | infinitylooped | 84 | reduce loop count in bridge target logic |
| 2 | infinitylooped | 11 | Change RoundStopwatch to always output caller method |
| 2 | lxorb | 37 | fix resignation |
| 2 | lxorb | 46 | minor strategy related constant adjustments |
| 2 | lxorb | 26 | improve sentinel direction logic |
| 2 | infinitylooped | 2 | Catch all exceptions for prevent bot surrender in submissions |
| 2 | infinitylooped | 1 | stop tracking exclude constants |
| 2 | infinitylooped | 101 | gitignore exclude constants |
| 2 | infinitylooped | 2 | set surround harvester type back to road for main |
| 2 | lxorb | 247 | rework sentinel facing logic |
| 2 | lxorb | 115 | surround harvesters with conveyors |
| 2 | lxorb | 106 | improve harvester placement: after building a harvester, a bot will move onto a supply chain tile adjacent to that harvester directly so it can then continue expanding the supply chain in succeeding turns |
| 2 | lxorb | 5 | exclude axionite for move_to helper conveyor placement |
| 2 | lxorb | 368 | rework harassment |
| 2 | lxorb | 29 | fix harassment scouting |
| 2 | lxorb | 16 | fix minor sentinel orientation bug |
| 2 | lxorb | 174 | minor fix for harvester building |
| 2 | lxorb | 55 | further build harvester improvements |
| 2 | lxorb | 221 | tweak builder stuff |
| 2 | lxorb | 280 | tune harvester safety |
| 2 | lxorb | 192 | rework harvester supply logic |
| 2 | lxorb | 7 | fully ignore enemy markers |
| 2 | lxorb | 16 | enhance existing supply chain avoidance |
| 2 | lxorb | 56 | fix map inference |
| 2 | lxorb | 23 | improve printing |
| 2 | lxorb | 398 | axionite farming prototype |
| 2 | lxorb | 200 | Improve builder supply continuation and foundry actions |
| 2 | lxorb | 10 | Separate patrol supply timing from missing link rebuilds |
| 2 | lxorb | 2 | Delay axionite harvester activation |
| 2 | lxorb | 132 | rework axionite farming |
| 2 | lxorb | 22 | Auto-upgrade harvester-adjacent conveyors to armoured |
| 2 | lxorb | 450 | improve harvester defense |
| 2 | lxorb | 534 | Rework builder movement and spawning rules |
| 2 | lxorb | 990 | Expand replay parser turn and entity output |
| 2 | lxorb | 70 | Ensure core center calculation seeds enemy candidates |
| 2 | lxorb | 71 | Prioritize exposed enemy harvesters for turrets |
| 2 | lxorb | 49 | Prune visible enemy core candidates by footprint |
| 2 | lxorb | 35 | improve hijacked supplier rebuilding |
| 2 | infinitylooped | 11 | fix time logging to actually work |
| 2 | infinitylooped | 2 | set log time default to false |
| 2 | infinitylooped | 244 | write results into subfolder |
| 2 | lxorb | 14 | attack enemy harvester supply links |
| 2 | infinitylooped | 26 | prioritize least played maps based on cumulative results file |
| 2 | infinitylooped | 91 | have unrated runner output image files for tables |
| 2 | infinitylooped | 444 | fallback to n/a for unrated runner output when no data available |
| 2 | infinitylooped | 359 | list requested teams first in output |
| 2 | lxorb | 1 | Fix hijack enemy supply chain own team lookup |
| 2 | lxorb | 105 | Fix feeding adjacent core turrets |
| 2 | infinitylooped | 2498 | display number of games next to percentage |
| 2 | lxorb | 28 | Constrain own-building healing to nearby targets |
| 2 | lxorb | 33 | Armour conveyors that feed own turrets |
| 2 | infinitylooped | 200 | final results update |
| 2 | infinitylooped | 3661 | fix webhook and result map names |
| 2 | lxorb | 240 | Generalize harvester turret placement |
| 2 | lxorb | 36 | Propagate harvester resource type into supply chains |
| 2 | lxorb | 162 | Generalize harvester turret integration |
| 2 | infinitylooped | 30680 | gitignore results and requested_teams |
| 2 | lxorb | 31 | Block gunner fire through protected harvesters |
| 2 | lxorb | 40 | Step scavengers off core corners in frontier expand |
| 2 | lxorb | 529 | Rework sentinel target prioritization |
| 2 | lxorb | 83 | extend sentinel direction decision logic |
| 2 | lxorb | 108 | Only compare core centers in symmetry inference |
| 2 | lxorb | 684 | directional frontier expansion prioritization keys for scavenger bots |
| 2 | lxorb | 188 | Persist pending supply-link targets |
| 2 | lxorb | 805 | Reuse vision BFS for builder pathing |
| 2 | lxorb | 14 | enhance frontier expansion |
| 2 | lxorb | 20 | Trim unused vision cache updates |
| 2 | lxorb | 49 | Speed up builder move-to hot path |
| 2 | lxorb | 589807 | Fix map passability refresh and restore conveyor import |
| 2 | lxorb | 6 | Avoid rewriting cached environment codes |
| 2 | lxorb | 78 | move step off core to beginning of strategies |
| 2 | lxorb | 3 | modify strategy |
| 2 | lxorb | 19 | Stop preferring sentinel for enemy supplied turrets |
| 2 | lxorb | 116922 | reparse maps |
| 2 | lxorb | 41 | Broaden healing for titanium-fed gunners |
| 2 | lxorb | 26 | Defer harvester feeder conveyor deletion by one turn |
| 2 | lxorb | 16 | Short-circuit low-hp harvester-adjacent attacks |
| 2 | lxorb | 35 | Respawn missing core defender when out of vision |
| 2 | lxorb | 97 | Fix safe harvester progression around barriers |
| 2 | lxorb | 8 | macro changes |
| 2 | lxorb | 99 | Publish builder intent on markers |
| 2 | lxorb | 107 | Reuse existing launchers in enemy-core harassment |
| 2 | lxorb | 14 | Avoid enemy supply-link targets when enemy builder is reachable |
| 2 | lxorb | 231 | Prepare next-turn reset work in map update |
| 2 | nina | 548133 | save point |
| 2 | nina | 422 | save point |
| 2 | nina | 80 | including emil prompts |
| 2 | nina | 2 | removing 3 |
| 2 | lxorb | 7 | Place symmetry hint markers without targets |
| 2 | nina | 4 | those two discord prompts |
| 2 | nina | 39 | not re-targeting already targeted urgent targets, not removing turrets targeting urgent targets |
| 2 | nina | 3709455 | not s_annoy_with_yeeter if on irrelevant road |
| 2 | nina | 4 | completing supply link is important! |
| 2 | nina | 5 | dont put marker where conveyor to harvester |
| 2 | lxorb | 8 | dont blindly destroy harvesters |
| 2 | lxorb | 1104 | ur runner comparison script |
| 2 | lxorb | 277 | runner fixes |
| 2 | lxorb | 24906 | cleanup redundant files |
| 1 | lxorb | 50 | remove venv |
| 1 | lxorb | 3 | add replay files to gitignore |
| 1 | lxorb | 0 | add custom_map1 |
| 1 | infinitylooped | 91 | Create id map in library |
| 1 | ninag | 7 | add to system path |
| 1 | einbocha | 0 | added map without walls and only two titanium / axionite ores |
| 1 | ninag | 208 | add information class |
| 1 | nina | 86 | add BFS with edge weights 0/1 |
| 1 | lxorb | 57 | add black formatter config |
| 1 | lxorb | 2017 | add docs.txt |
| 1 | lxorb | 4 | Add cambattlecode docs submodule |
| 1 | lxorb | 2017 | Remove docs.txt |
| 1 | lxorb | 1 | Update README.md to include submodule updating |
| 1 | lxorb | 93 | add laning bot |
| 1 | lxorb | 63 | add method to find core center |
| 1 | lxorb | 112 | implement lane direction calculation |
| 1 | lxorb | 1 | add planning to laning bot |
| 1 | lxorb | 236 | feat: instantiate framing bot |
| 1 | lxorb | 209 | feat: improve build_missing_bridge method to move to tile if not in action range |
| 1 | lxorb | 91 | feat: path finding enhancements for resource finding |
| 1 | lxorb | 384 | feat: enhance action radius based path finding |
| 1 | lxorb | 42 | feat: improve new bridge targeting (prefer non-ore tiles) |
| 1 | lxorb | 0 | add new ladder maps |
| 1 | lxorb | 446 | feat: added initial resource finding |
| 1 | lxorb | 199 | feat: core proximity enemy walkable tile attacking |
| 1 | lxorb | 107 | feat: improve path finding using caching |
| 1 | lxorb | 284 | feat: add launcher defense bot |
| 1 | lxorb | 7 | feat: add launcher defense bot |
| 1 | lxorb | 367 | feat: implement launcher throwing logic |
| 1 | lxorb | 146 | feat: improve bridge placement |
| 1 | lxorb | 94 | feat: constrained harvester placement for safety |
| 1 | lxorb | 76 | feat: implement safer bridge placement |
| 1 | lxorb | 62 | feat: optimize titanium holding |
| 1 | lxorb | 82 | fix: initial resource bb bug |
| 1 | lxorb | 568 | feat: expand some bridge-related logic to conveyors |
| 1 | lxorb | 2879 | feat: huge performance improvement |
| 1 | lxorb | 97 | feat: attack enemy supply elements to continue own supply chain |
| 1 | lxorb | 606 | feat: add replay parser |
| 1 | lxorb | 1118 | feat: implement conveyer/bridge decision logic |
| 1 | lxorb | 159 | feat: improve defense mechanisms |
| 1 | lxorb | 264 | feat: implement TLE continuation |
| 1 | lxorb | 20 | remove unassigned builder bot handler |
| 1 | lxorb | 25 | remove maintainer bb |
| 1 | lxorb | 435 | feat: implement expansion scoring system |
| 1 | lxorb | 44 | feat: expand titanium holding prioritization |
| 1 | lxorb | 2 | update docs |
| 1 | einbocha | 1 | removed unused random import from __init__.py |
| 1 | lxorb | 276 | feat: improve harassment bots |
| 1 | lxorb | 1 | remove profiling leftovers |
| 1 | lxorb | 403 | feat: huge performance improvement for harassment bots |
| 1 | lxorb | 168 | feat: improve sentinel positioning |
| 1 | lxorb | 559 | feat: further improve performance |
| 1 | lxorb | 3 | feat: improve initial resource finding |
| 1 | lxorb | 103 | feat: consider barriers for harvester placement |
| 1 | lxorb | 393 | feat: add barrier walling onto titanium tiles for harassment bot |
| 1 | lxorb | 299 | feat: further improve harassment bots |
| 1 | lxorb | 33 | feat: implement marker spamming |
| 1 | lxorb | 85 | feat: improve scavenger expansion |
| 1 | lxorb | 21851 | feat: lategame axionite farming |
| 1 | lxorb | 2 | adjust constants |
| 1 | lxorb | 289 | feat: add enemy core walling with barriers + launchers |
| 1 | lxorb | 126 | feat: minor performance improvements |
| 1 | lxorb | 315 | feat: implement harassment bot enemy launcher avoiding |
| 1 | lxorb | 92 | feat: improve harassment bots for more precise launcher avoidance |
| 1 | lxorb | 1132 | feat: add some more caching for improved performance |
| 1 | lxorb | 28 | feat: improve initial resource bot spawning locations |
| 1 | lxorb | 4 | feat: adjust initial spawning order |
| 1 | lxorb | 11631 | feat: add new documentation strategy |
| 1 | lxorb | 1347 | feat: readd sketch.py |
| 1 | infinitylooped | 87 | Make bot runnable and new directory structure |
| 1 | lxorb | 89 | feat: improve sketch.py |
| 1 | infinitylooped | 12 | create base classes for agents |
| 1 | lxorb | 2 | feat: add strategy class |
| 1 | lxorb | 8 | feat: finalize new file structure |
| 1 | lxorb | 664 | feat: integrate sketch into new structure |
| 1 | lxorb | 267 | feat: remove old libs folder |
| 1 | lxorb | 218 | feat: implement builder bot strategy handler |
| 1 | lxorb | 74 | feat: extend builder bot strategy handler |
| 1 | lxorb | 91 | feat: add builder bot strategy constants |
| 1 | lxorb | 40 | feat: update builder agent bots |
| 1 | lxorb | 3 | feat: update vscode settings.json |
| 1 | lxorb | 16 | feat: expand docstrings of builder agent |
| 1 | lxorb | 626 | Refactor bot agent handling and builder actions |
| 1 | lxorb | 52 | feat: implement block enemy supply chain strategy method |
| 1 | lxorb | 40 | feat: implement block titanium strategy method |
| 1 | lxorb | 174 | feat: add tile filtering and prioritization methods for modularity |
| 1 | lxorb | 99 | feat: implement attack enemy harvester supply link strategy method |
| 1 | lxorb | 116 | feat: implement attack enemy core supply link strategy method |
| 1 | lxorb | 89 | feat: implement build harvester strategy method |
| 1 | lxorb | 149 | Implement builder strategy helpers and actions |
| 1 | lxorb | 42 | Add builder danger avoidance helpers |
| 1 | lxorb | 61 | feat: implement destroy hijacked supplier strategy method |
| 1 | lxorb | 105 | feat: implement build harvester supply link strategy method |
| 1 | lxorb | 89 | feat: implement surround harvester strategy method |
| 1 | lxorb | 16 | Remove unused harvester launcher strategy |
| 1 | lxorb | 79 | remove strategy class |
| 1 | lxorb | 123 | feat: restructure agent methods |
| 1 | lxorb | 275 | feat: add attack turret prioritization logic |
| 1 | lxorb | 173 | feat: implement launcher throwing |
| 1 | lxorb | 95 | feat: filesplit strategies |
| 1 | lxorb | 2025 | feat: file split builder agent |
| 1 | lxorb | 58 | delete old src folder |
| 1 | lxorb | 29 | Wire player agent dispatch and fix agent init order |
| 1 | infinitylooped | 0 | update existing maps |
| 1 | infinitylooped | 64 | Make walls not count to intrinsically passable tiles |
| 1 | lxorb | 46 | implement base version of frontier expansion |
| 1 | lxorb | 165 | implement path finding for bot movement |
| 1 | lxorb | 22 | integrate path finding into relevant strategy methods |
| 1 | lxorb | 87 | implement chokepoint detection logic |
| 1 | lxorb | 90 | implement conveyor orientation decision logic |
| 1 | lxorb | 146 | implement bridge target decision logic |
| 1 | lxorb | 5 | add surrender at turn constant |
| 1 | lxorb | 13 | add some debug output |
| 1 | lxorb | 38 | Refine builder strategy logging and supply gaps |
| 1 | lxorb | 4 | Adjust uewomirudake builder spawn constants |
| 1 | lxorb | 14 | Add map timing diagnostics for uewomirudake |
| 1 | lxorb | 33 | Store map distances in flat arrays |
| 1 | lxorb | 66 | Use dedicated map distance refresh helpers |
| 1 | lxorb | 35 | Precompute map neighbors for distance BFS |
| 1 | lxorb | 100 | Use index queues in map pathfinding |
| 1 | lxorb | 105 | Make core distance updates incremental |
| 1 | lxorb | 242 | Optimize map updates and sync constants |
| 1 | lxorb | 8 | Allow same-turn destroy and build |
| 1 | lxorb | 2 | Allow same-turn road build and move |
| 1 | lxorb | 2 | adjust constants |
| 1 | lxorb | 175 | Optimize map tile attribute updates |
| 1 | lxorb | 190 | Cache map target geometry for tile updates |
| 1 | infinitylooped | 16 | Replace the shared settings with an example template |
| 1 | infinitylooped | 149 | Create debug-friendly Stopwatch class and use it for timing |
| 1 | infinitylooped | 8 | Restore build harvester link docstring |
| 1 | infinitylooped | 218 | Optimize surround harvester and chokepoint detection |
| 1 | lxorb | 84 | optimize symmetry pruning |
| 1 | lxorb | 32 | add stubs for foundry strategy |
| 1 | lxorb | 95 | Use direct builder strategy method references |
| 1 | lxorb | 46 | implement light chokepoint checking |
| 1 | lxorb | 32 | Refine builder passability and spawn mapping |
| 1 | lxorb | 4 | update constants |
| 1 | infinitylooped | 224 | Add supply patrol index updating and defender patrol logic |
| 1 | lxorb | 41 | Optimize map distance hot paths |
| 1 | lxorb | 58 | Optimize exact self-distance refresh |
| 1 | lxorb | 102 | Optimize core distance initialization |
| 1 | infinitylooped | 11 | Add second pass over patrol targets when it is impossible to avoid enemy targets |
| 1 | infinitylooped | 6 | Add todo messages for debug harassment and defender spawning |
| 1 | lxorb | 150 | Optimize first-turn map vision updates |
| 1 | lxorb | 15 | Ignore harvesters in missing supply link cache |
| 1 | lxorb | 39 | Refine core and chokepoint builder handling |
| 1 | nina | 4 | remove last_titanium_onit_turn<br>redundancy |
| 1 | lxorb | 50 | Add configurable further builder spawning |
| 1 | infinitylooped | 47 | Prevent bots from freezing in frontier expand when they start off next to an enemy turret |
| 1 | lxorb | 2 | adjust constants |
| 1 | infinitylooped | 617 | Add basic axionite build plan logic and usage in supply link methods |
| 1 | infinitylooped | 64 | Make axionite supply chains avoid tiles adjacent to titanium ores |
| 1 | infinitylooped | 699 | Clean up build plan methods, make titanium chains avoid axionite chains as well, add a pending target for the last missing supply link |
| 1 | infinitylooped | 411 | Add debug foundry bot spawning, (note: the following changes were not reviewed) implement foundry-splitter site selection and targeting in order to (the following never works) build the pair in the end |
| 1 | infinitylooped | 461 | Add splitter to foundry routing checks |
| 1 | infinitylooped | 119 | Make foundry bot wait if we have a foundry but no routing from splitter to foundry is currently possible, fix circular import by adding builder constants file |
| 1 | infinitylooped | 58 | Add foundry waiting and initial foundry tile reservation |
| 1 | infinitylooped | 123 | Implement more robust supply chain label update logic |
| 1 | infinitylooped | 22 | Added option to build foundry before or after supply chain and documented tradeoffs |
| 1 | infinitylooped | 80 | Allow axionite supply chains to wrap around core without improving own_core_dist, fix axionite routes not being able to target foundry |
| 1 | lxorb | 18 | Add bridge-target empty ore toggle |
| 1 | lxorb | 10 | Add builder build-target debug print |
| 1 | lxorb | 1 | Skip occupied tiles when building harvesters |
| 1 | lxorb | 125 | Refine harvester surround and core axionite behavior |
| 1 | lxorb | 122 | Refine builder strategy switching and constants |
| 1 | lxorb | 27 | Tighten builder supply and titanium blocking rules |
| 1 | infinitylooped | 18 | Add harassment s_move_toward_enemy_core stub |
| 1 | infinitylooped | 33 | Implement harassment moving toward enemy core |
| 1 | lxorb | 106 | implement defender bot healing |
| 1 | lxorb | 566 | Remove map distance fields |
| 1 | lxorb | 95 | Precompute turret attack geometry and add vision timing splits |
| 1 | infinitylooped | 2 | Update docs submodule |
| 1 | infinitylooped | 20 | Prevent early surrenders in submissions (create exclude module) |
| 1 | infinitylooped | 44 | Create GlobalRoundStopwatch to automatically stop bots before they TLE |
| 1 | infinitylooped | 68 | Add overtime break condition to map init distance field |
| 1 | infinitylooped | 6 | Implement GlobalRoundStopwatch update |
| 1 | infinitylooped | 8 | Remove redundant method |
| 1 | infinitylooped | 56 | Implement temp fix for bots unable to place initial supply chains on axionite-heavy maps due to forbidden tile logic |
| 1 | infinitylooped | 8 | Add overtime method check to GlobalRoundStopwatch which always is executed |
| 1 | infinitylooped | 26 | Added an "always check overtime" method which ignores the check interval |
| 1 | infinitylooped | 51 | Handle cambc servers blocking time module with Controller |
| 1 | infinitylooped | 0 | Add new maps |
| 1 | infinitylooped | 9 | Precompute bridge target offsets |
| 1 | infinitylooped | 10 | disable unused and unoptimized get foundry plan method |
| 1 | infinitylooped | 91 | Refactor adjacent position logic to not do an inefficient split, try to optimize build harvester strategy |
| 1 | infinitylooped | 24 | Remove redundant short interval overtime check |
| 1 | lxorb | 150 | add argument for harvester surround enforcal |
| 1 | lxorb | 27 | prevent turrets from attacking own bbs |
| 1 | lxorb | 18 | implement self healing |
| 1 | lxorb | 97 | make time printing more precise |
| 1 | lxorb | 128 | make symmetry calculation 8x faster |
| 1 | lxorb | 6 | adjust constants |
| 1 | infinitylooped | 110 | make harvester surround tile configurable and set it to barrier |
| 1 | infinitylooped | 579 | refactor strategy files to remove circular imports |
| 1 | lxorb | 206 | add fix_conveyor strategy method |
| 1 | lxorb | 249 | make moving to enemy core a lot faster |
| 1 | lxorb | 625 | implement union find supply chain tracking |
| 1 | lxorb | 281 | make harassment bots patrol enemy core |
| 1 | lxorb | 10 | wire new harvester strategy |
| 1 | lxorb | 478 | Refine builder supply-chain and pathing behavior |
| 1 | lxorb | 10 | Clean up commented builder strategy entries |
| 1 | lxorb | 26 | Prefer coreward conveyor targets and enable hard supply-chain avoidance |
| 1 | lxorb | 4 | Treat any harvester-fed best tile as fixable |
| 1 | lxorb | 561 | Add map metadata generation tooling |
| 1 | lxorb | 0 | Remove local custom maps |
| 1 | lxorb | 406684 | Add generated map inference metadata |
| 1 | lxorb | 265353 | Add parsed map inference loading |
| 1 | lxorb | 25 | Store parsed maps as marshal with json sidecars |
| 1 | lxorb | 4386 | Add enemy core checkpoint paths for inferred maps |
| 1 | lxorb | 45 | Make inferred map paths work without __file__ |
| 1 | lxorb | 202 | make map inference faster |
| 1 | lxorb | 8 | disable map inference |
| 1 | lxorb | 685 | Remove obsolete foundry strategy and supply logic |
| 1 | lxorb | 48 | Add gated axionite harvesting for scavengers |
| 1 | lxorb | 9 | Make harassment spawning toggle overrideable |
| 1 | lxorb | 107 | Refine transport supplier planning |
| 1 | lxorb | 11 | Make foundry bridge replacement configurable |
| 1 | lxorb | 154 | Add passing-splitter foundry integration strategy |
| 1 | lxorb | 63 | allow own harvester protect method to build harvester if appropriate |
| 1 | lxorb | 111 | Optimize harvester protection candidate selection |
| 1 | lxorb | 556 | Optimize uewomirudake supply info update |
| 1 | lxorb | 5818 | Update builder supply planning and replay tooling |
| 1 | lxorb | 22 | Reserve axionite for armoured conveyors |
| 1 | lxorb | 464 | Optimize builder pathing and movement diagnostics |
| 1 | lxorb | 101 | Treat armoured conveyors like conveyors |
| 1 | lxorb | 29 | Refine harvester defense targeting |
| 1 | lxorb | 2 | Restore axionite harvester turn threshold |
| 1 | lxorb | 127 | Rewrite foundry integration around core conveyors |
| 1 | lxorb | 73 | replace instead of heal conveyors below certain health |
| 1 | lxorb | 145 | Track full core footprint as core tiles |
| 1 | lxorb | 299 | Refine harassment builders around enemy core |
| 1 | lxorb | 219 | Implement explicit gunner target selection |
| 1 | lxorb | 2 | Prefer A* over bugnav for builder movement |
| 1 | lxorb | 68 | Adjust harassment movement around the enemy core |
| 1 | lxorb | 40 | make move towards enemy core faster |
| 1 | lxorb | 8 | make further bb rotation configurable |
| 1 | lxorb | 173 | Prefer sentinels over harvester safety builds |
| 1 | lxorb | 264 | Integrate sentinel upgrades around harvesters |
| 1 | lxorb | 56 | Cache enemy core proxy movement targets |
| 1 | infinitylooped | 0 | add new maps |
| 1 | lxorb | 0 | add new maps |
| 1 | infinitylooped | 18 | add round stopwatch overtime logging configurable with a flag |
| 1 | infinitylooped | 143 | add unrated runner python script |
| 1 | lxorb | 14 | Relax attack reserve on damaged key suppliers |
| 1 | lxorb | 538 | Add enemy supply chain hijack strategy |
| 1 | infinitylooped | 88 | add win rates to output and remove old table |
| 1 | lxorb | 150 | Refine enemy supplied turret building |
| 1 | infinitylooped | 18622 | update unrated runner output and better team handling |
| 1 | infinitylooped | 2446 | adjust unrated runner params and enable random map selection |
| 1 | infinitylooped | 2 | disable log time from earlier commit |
| 1 | lxorb | 25 | Adjust hijack enemy supply chain usage |
| 1 | lxorb | 79 | Add enemy supply chain blocking strategy |
| 1 | lxorb | 26 | Remove barrier fallback from hijack strategy |
| 1 | lxorb | 18 | Rename enemy core orientation helper |
| 1 | lxorb | 15 | Refine gunner shootable tile helper |
| 1 | lxorb | 18 | Use shootable tiles for gunner coverage |
| 1 | infinitylooped | 18598 | adjust output half life decay |
| 1 | infinitylooped | 492 | add map win color highlighting and update docs |
| 1 | lxorb | 138 | Refine continuable supply chain detection |
| 1 | lxorb | 126 | Refine split supply sentinel replacements |
| 1 | lxorb | 3 | Disable conveyor building during core patrol |
| 1 | lxorb | 16 | Require supplier tile for harvester targets |
| 1 | lxorb | 3312431 | Track joinable supply chains and relax axionite links |
| 1 | lxorb | 118 | Prefer joining compatible axionite supply chains |
| 1 | infinitylooped | 4211 | add configurable results source for output |
| 1 | lxorb | 85 | Refine transport supply chain bridge planning |
| 1 | lxorb | 2 | Skip occupied conveyors in foundry integration |
| 1 | lxorb | 15 | Skip splitter targets for foundry placement |
| 1 | infinitylooped | 4921 | add compare script and fix redundant map in results |
| 1 | infinitylooped | 835 | add compare docs |
| 1 | lxorb | 81 | Remove initres builder strategy |
| 1 | lxorb | 85 | Replace low-HP buildings during healing |
| 1 | lxorb | 20 | Prefer titanium-chain bridge joins for pure axionite |
| 1 | lxorb | 49 | add core defender bot |
| 1 | lxorb | 35 | Reserve titanium after harassment road builds |
| 1 | lxorb | 64 | Refine hijacked supplier cleanup |
| 1 | lxorb | 39 | Limit sentinel harvester swaps to titanium |
| 1 | lxorb | 25 | Adjust core defender and expansion controls |
| 1 | infinitylooped | 3375 | add runner webhook functionality |
| 1 | infinitylooped | 197 | add output cutoff to prevent old results from influencing output |
| 1 | lxorb | 77 | Refine sentinel harassment target setup |
| 1 | lxorb | 20 | add flag to explicitly enable printing in exclude.py |
| 1 | lxorb | 32 | Allow hijacks on mixed titanium chains |
| 1 | lxorb | 46 | Gate turret rebuilds on titanium supply |
| 1 | lxorb | 22 | Adjust core healing priority |
| 1 | lxorb | 7 | Document integrate own sentinel strategy |
| 1 | lxorb | 389 | Refine gunner planning near harvesters |
| 1 | lxorb | 15 | Introduce sentinel orientation helper |
| 1 | lxorb | 19 | Add barrier fallback for hijacked supplier rebuild |
| 1 | lxorb | 64 | Refine missing supply link target priority |
| 1 | lxorb | 147 | Allow gunners to rotate toward better targets |
| 1 | lxorb | 19 | Ignore parsed replay artifact |
| 1 | infinitylooped | 2 | adjust cutoff hours in unrated runner output |
| 1 | lxorb | 33 | Prefer existing walkable first steps in move_to |
| 1 | lxorb | 88 | Refine gunner firing safety rules |
| 1 | lxorb | 30 | Use strategy tile order for builder spawn ties |
| 1 | lxorb | 255 | Add parsed replay comparison script |
| 1 | lxorb | 70 | Handle more hijacked supplier rebuild targets |
| 1 | lxorb | 274 | Remove unused bugnav movement path |
| 1 | lxorb | 265 | Add gunner-aware harassment and sentinel targeting |
| 1 | infinitylooped | 1805 | add filters for generating ladder top teams |
| 1 | lxorb | 72 | Refine step-off-core strategy handling |
| 1 | lxorb | 3 | Allow road building for step-off-core |
| 1 | lxorb | 50 | Prefer gunners near enemy harvester lanes |
| 1 | lxorb | 2053355 | adjust initial bb |
| 1 | lxorb | 3 | Skip redundant patrol fallback without enemy turret targets |
| 1 | lxorb | 162551 | Add in-vision BFS caching and replay snapshots |
| 1 | lxorb | 14 | Use cached BFS steps for road-building moves |
| 1 | infinitylooped | 19407 | add graphs to unrated runner |
| 1 | lxorb | 48 | remove road preference for performance |
| 1 | lxorb | 94 | make it faster |
| 1 | lxorb | 48 | make own core field 50% faster |
| 1 | lxorb | 69 | make own core field faster |
| 1 | lxorb | 175 | Cache titanium harvester turret candidates |
| 1 | lxorb | 46 | Use array-backed visible entity caches |
| 1 | lxorb | 102 | Use touched arrays for supply target caches |
| 1 | lxorb | 6118142 | remove stale parsed replays |
| 1 | lxorb | 1 | Add another initial scavenger slot |
| 1 | lxorb | 13 | Adjust builder strategy and turret integration |
| 1 | lxorb | 11 | Add hold toggle for key supply chain attacks |
| 1 | lxorb | 291 | implement information gain scout |
| 1 | lxorb | 163 | optimize information gain scout |
| 1 | lxorb | 167 | Adjust scavenger priorities and supply link continuation |
| 1 | lxorb | 115 | Adjust harvester targeting and core defender trigger |
| 1 | lxorb | 141 | Add enemy supply chain patrol strategy |
| 1 | lxorb | 203 | Require core coverage for harvester sentinels |
| 1 | lxorb | 8 | Require seen enemy core for enemy supply patrol |
| 1 | lxorb | 36 | Adjust builder strategy hooks and resource accessibility |
| 1 | lxorb | 4 | Treat markers as empty map tiles |
| 1 | lxorb | 47 | Adjust own building heal priorities |
| 1 | lxorb | 145 | Add marker payload decoding and map cache |
| 1 | lxorb | 154 | Rewrite launcher behavior around marker targets |
| 1 | lxorb | 141 | Cache in-vision action-range reachability |
| 1 | lxorb | 2 | Limit harvester turret shortcut to titanium |
| 1 | lxorb | 635 | Optimize enemy core movement and builder spawn gating |
| 1 | lxorb | 5 | Adjust further builder spawn rotation and threshold |
| 1 | lxorb | 12 | Handle legacy enemy-bot visibility flag in navigation |
| 1 | lxorb | 41 | Optimize tile clear state resets |
| 1 | lxorb | 16 | Optimize building target equality check |
| 1 | lxorb | 70 | Optimize supply info cache updates |
| 1 | lxorb | 257 | Use turn stamps for hot map caches |
| 1 | lxorb | 26 | Optimize harvester conveyor target checks |
| 1 | lxorb | 1 | Ignore replay parser output JSON files |
| 1 | lxorb | 67 | Adjust builder harvester targeting and bot tuning |
| 1 | lxorb | 123 | Add simple harvester build strategy |
| 1 | lxorb | 45 | Tighten harvester target tile validation |
| 1 | lxorb | 21 | Gate core distance estimates by action reachability |
| 1 | lxorb | 339 | Add enemy builder follow coordination |
| 1 | lxorb | 28 | Refine enemy builder follow behavior |
| 1 | lxorb | 139 | Remove builder debug output |
| 1 | lxorb | 8 | Update builder navigation and strategy files |
| 1 | lxorb | 3 | Track core defender spawns centrally |
| 1 | lxorb | 83 | update unrated runner enemy teams |
| 1 | lxorb | 558956 | Add bundled maps |
| 1 | lxorb | 2 | Skip self heal in enemy attack range |
| 1 | lxorb | 199 | Add initial scavenger self-patrol mode |
| 1 | lxorb | 38 | Adjust builder defender patrol and logging |
| 1 | nina | 2 | add cheap exit: definitely not possible to build turret if self.in_own_resource-range == 0 |
| 1 | lxorb | 7455461 | remove unnecessary parsed replays |
| 0 | einbocha | 0 | Merge remote-tracking branch 'origin/main' |
| 0 | einbocha | 0 | Merge remote-tracking branch 'origin/main' |
| 0 | ninag | 0 | Merge remote-tracking branch 'origin/main' |
| 0 | ninag | 9 | Merge remote-tracking branch 'origin/main'<br><br># Conflicts:<br>#	src/lib/information/direction.py |
| 0 | einbocha | 25 | Merge remote-tracking branch 'origin/main'<br><br># Conflicts:<br>#	src/bots/__init__.py |
| 0 | lxorb | 7510 | Merge branch 'dev-lxorb' |
| 0 | lxorb | 54 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | einbocha | 42274 | Merge remote-tracking branch 'origin/main'<br><br># Conflicts:<br>#	src/bots/__init__.py |
| 0 | lxorb | 85 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | lxorb | 12 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | einbocha | 186 | Merge remote-tracking branch 'origin/main' |
| 0 | einbocha | 10 | Merge remote-tracking branch 'origin/main' |
| 0 | einbocha | 664 | Merge remote-tracking branch 'origin/main' |
| 0 | lxorb | 58 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | lxorb | 1186 | merge with dev/daisy |
| 0 | lxorb | 141 | merge dev/einbocha into main |
| 0 | infinitylooped | 15038 | Merge branch 'main' into dev/infinity |
| 0 | Emil Vinu | 100 | Merge pull request #1 from lxorb/dev/infinity<br><br>More efficient frontier expand |
| 0 | Emil Vinu | 360 | Merge pull request #2 from lxorb/dev/infinity<br><br>Improve 1. build harvester supply link efficiency 2. surround harvester and chokepoint efficiency |
| 0 | lxorb | 199 | Merge branch 'dev/emil'<br><br># Conflicts:<br>#	bots/uewomirudake/lib/agent/builder/strategy_methods.py |
| 0 | infinitylooped | 269 | Merge branch 'dev/infinity' into main |
| 0 | lxorb | 99 | Merge branch 'dev/emil' into main<br><br># Conflicts:<br>#	bots/uewomirudake/lib/agent/builder/strategy_methods.py |
| 0 | Emil Vinu | 1666 | Merge pull request #5 from lxorb/dev/infinity<br><br>Part 1/2 of Axionite logic - Axionite routing towards foundry |
| 0 | nina | 46 | Merge remote-tracking branch 'origin/dev/daisy' into dev/daisy |
| 0 | lxorb | 27 | Merge origin/dev/infinity into main |
| 0 | lxorb | 686 | Merge origin/dev/daisy into main |
| 0 | infinitylooped | 0 | Merge branch 'main' into dev/infinity-nan |
| 0 | Emil Vinu | 2866 | Merge pull request #8 from lxorb/dev/infinity-nan<br><br>Time limit exceeded prevention, minor optimizations and bug fixes |
| 0 | infinitylooped | 771 | Merge pull request #10 from lxorb/dev/infinity<br><br>minor fixes and import refactoring to remove need for imports inside methods |
| 0 | infinitylooped | 49 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | lxorb | 46757 | Merge origin/main and keep local bots state |
| 0 | infinitylooped | 1175 | Merge branch 'main' of https://github.com/lxorb/cbc-muteki |
| 0 | lxorb | 2054276 | Merge branch 'dev/lxorb' |
| 0 | lxorb | 218 | Merge visible tile classification into vision update |
| 0 | lxorb | 5369093 | Merge branch 'dev/lxorb' |
| 0 | lxorb | 759 | Merge branch 'main' into dev/lxorb |
