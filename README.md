# muteki

This is team mutekis bot for Cambridge Battlecode 2026.  
We qualified as international finalists (top 8) with it and placed roughly top 6 on ladder.  
Our motto is "上を見るだけ。" which is japanese and translates to "We only look upwards.".  
If you want to see this bot in action, see [Setup](#setup).  
Also, enjoy this list of... let's call 'em "interesting" commit messages.  

## A few commits

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

## Setup

Our main bot can be found under `/bots/uewomirudake`.  
Quick start:

```bash
pip install cambc # install this globally
git submodule update --init --recursive
cambc run <bot1> <bot2> [--watch] [--map-random]
```

Install the black python formatter - automatic formatting on save is already configured, so try modifying something slightly and saving then to see if the automatic formatting kicks in. 

## Naming Conventions

Methods whose names start with `u_` were initially created by a user.
Methods created by AI should start with `c_`.
This rule does not apply to conventional special method names such as `__init__`.
Methods whose names start with `s_` are strategy submethods.

## Related
- [docs](https://docs.battlecode.cam/getting-started/installation)
- [Reference Table](https://docs.battlecode.cam/spec/reference)
- [matches](https://game.battlecode.cam/matches)
