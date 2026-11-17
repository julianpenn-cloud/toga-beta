#!/usr/bin/env python3
"""Write nfl.json: every Vikings win of the current season, plus the latest settled game.

Runs on a runner, where an ordinary HTTP request works. The page reads the file from its
OWN ORIGIN, so no browser ever calls a sports API and nothing of the reader's leaves
their device.

The file carries the whole season's wins, not just the last game, so the page can colour
any day after a win: tomorrow on the evening of a game, and every past Monday in the month
grid. The page decides which days those are; this script only reports what was settled.

Source: the team schedule endpoint, one call per season type (regular, postseason). Any
failure of the regular-season call leaves the previous file alone rather than writing a
guess. Wins already recorded are kept (union), and pruned once they are a season old.
"""
import datetime
import gzip
import json
import urllib.request

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:                       # tzdata absent: fixed offset, DST-blind but usable
    CT = datetime.timezone(datetime.timedelta(hours=-6))

SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/min/schedule?seasontype=%d"
OUT = "nfl.json"
KEEP_DAYS = 300          # a win older than this belongs to last season
HEARTBEAT_DAYS = 30      # refresh the timestamp monthly so the schedule is never disabled


def get_json(url, timeout=25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def settled_games(payload):
    """Every completed Vikings game in a schedule payload, as {ymd, won, opponent}."""
    out = []
    for event in (payload.get("events") or []):
        comp = (event.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        if not status.get("completed"):
            continue                                    # not played, or still in progress
        teams = comp.get("competitors") or []
        mine = [t for t in teams if (t.get("team") or {}).get("abbreviation") == "MIN"]
        if not mine:
            continue
        others = [t for t in teams if (t.get("team") or {}).get("abbreviation") != "MIN"]
        try:
            kickoff = datetime.datetime.fromisoformat((event.get("date") or "").replace("Z", "+00:00"))
            # The kickoff date in Central time: the day a reader in Minnesota would call it.
            ymd = kickoff.astimezone(CT).date().isoformat()
        except Exception:
            continue                                    # no usable date, no claim
        out.append({
            "ymd": ymd,
            # A tie leaves winner unset or false on both sides: not a win.
            "won": mine[0].get("winner") is True,
            "opponent": ((others[0].get("team") or {}).get("displayName") or "") if others else "",
        })
    return sorted(out, key=lambda g: g["ymd"])


def season_games():
    """Regular season is required; postseason is optional (it 404s or is empty most of the year)."""
    games = settled_games(get_json(SCHEDULE % 2))
    try:
        games += settled_games(get_json(SCHEDULE % 3))
    except Exception:
        pass
    return sorted(games, key=lambda g: g["ymd"])


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(CT).date()
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}

    try:
        games = season_games()
    except Exception as e:
        print("lookup failed (%s) - leaving the file alone" % type(e).__name__)
        return

    cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    wins = {w["ymd"]: w.get("opponent", "") for w in (old.get("wins") or []) if w.get("ymd")}
    for g in games:
        if g["won"]:
            wins[g["ymd"]] = g["opponent"]
    win_list = [{"ymd": d, "opponent": wins[d]} for d in sorted(wins) if d >= cutoff]

    latest = games[-1] if games else None
    new = {
        "wins": win_list,
        "gameYmd": latest["ymd"] if latest else old.get("gameYmd"),
        "won": latest["won"] if latest else (old.get("won") is True),
        "opponent": latest["opponent"] if latest else (old.get("opponent") or ""),
    }

    same = all(new.get(k) == old.get(k) for k in ("wins", "gameYmd", "won", "opponent"))
    stale = True
    if old.get("checked"):
        try:
            when = datetime.datetime.fromisoformat(old["checked"].replace("Z", "+00:00"))
            stale = (now - when).days >= HEARTBEAT_DAYS
        except Exception:
            stale = True
    if same and not stale:
        print("unchanged and checked recently - leaving the file alone")
        return

    new["checked"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2)
        f.write("\n")
    print(("heartbeat (no new result)" if same else "updated") + ": %d wins, latest %s"
          % (len(win_list), json.dumps({k: new[k] for k in ("gameYmd", "won", "opponent")})))


if __name__ == "__main__":
    main()
