#!/usr/bin/env python3
"""Look up the most recent settled Vikings result and write nfl.json.

This runs on a runner, where an ordinary HTTP request works. The page then reads the file
from its OWN ORIGIN, so no browser ever calls a sports API and nothing of the reader's
leaves their device.

The file always holds the MOST RECENT settled game, not yesterday's. The page decides
whether that was yesterday - so a missed run can make the easter egg late, never wrong.

No ESPN parsing assumptions beyond the documented field names, and any failure leaves the
previous file in place rather than writing a guess: a wrong result would be worse than a
stale one.
"""
import datetime
import json
import urllib.request

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:                       # tzdata absent: fixed offset, DST-blind but usable
    CT = datetime.timezone(datetime.timedelta(hours=-6))

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=%s"
OUT = "nfl.json"
LOOKBACK_DAYS = 12
HEARTBEAT_DAYS = 30


def get_json(url, timeout=25):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def latest_result(today):
    """The most recent completed Vikings game, or None. Walks back day by day: cheap, and it
    needs no knowledge of the schedule, byes, or which week it is."""
    for back in range(LOOKBACK_DAYS):
        day = today - datetime.timedelta(days=back)
        try:
            payload = get_json(SCOREBOARD % day.strftime("%Y%m%d"))
        except Exception:
            continue
        for event in (payload.get("events") or []):
            comp = (event.get("competitions") or [{}])[0]
            status = (comp.get("status") or {}).get("type") or {}
            if status.get("state") != "post" and not status.get("completed"):
                continue                                   # not settled yet
            teams = comp.get("competitors") or []
            mine = [t for t in teams if (t.get("team") or {}).get("abbreviation") == "MIN"]
            if not mine:
                continue                                   # no Vikings game that day
            others = [t for t in teams if (t.get("team") or {}).get("abbreviation") != "MIN"]
            # The game's own kickoff date in Central time - the day the reader would call it.
            when = event.get("date") or ""
            try:
                kickoff = datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
                game_ymd = kickoff.astimezone(CT).date().isoformat()
            except Exception:
                game_ymd = day.isoformat()
            return {
                "gameYmd": game_ymd,
                # A tie leaves winner unset on both sides, so this is False - correct: a tie
                # is not a win.
                "won": mine[0].get("winner") is True,
                "opponent": ((others[0].get("team") or {}).get("displayName") or "") if others else "",
            }
    return None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today_ct = now.astimezone(CT).date()
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}

    found = latest_result(today_ct)
    if found is None:
        print("no settled Vikings game in the last %d days" % LOOKBACK_DAYS)
        found = {k: old.get(k) for k in ("gameYmd", "won", "opponent")}
        if not found.get("gameYmd"):
            found = {"gameYmd": None, "won": False, "opponent": ""}

    same = all(found.get(k) == old.get(k) for k in ("gameYmd", "won", "opponent"))
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

    new = dict(found)
    new["checked"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2)
        f.write("\n")
    print(("heartbeat (no new result): " if same else "new result: ") + json.dumps(found))


if __name__ == "__main__":
    main()
