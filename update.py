"""Scarica dati NBA (API pubbliche non ufficiali di ESPN) e scrive data.json."""
import json, os, datetime as dt, requests
from collections import defaultdict

B = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"

def get(url, **p):
    try:
        r = S.get(url, params=p, timeout=25); r.raise_for_status(); return r.json()
    except Exception as e:
        print("ERRORE", url, e); return {}

today = dt.date.today()
finished, upcoming, perf = [], [], []
for i in range(-14, 4):
    d = (today + dt.timedelta(days=i)).strftime("%Y%m%d")
    for e in get(B + "/scoreboard", dates=d).get("events", []):
        c = e["competitions"][0]
        t = {x["homeAway"]: x for x in c["competitors"]}
        h, a = t["home"], t["away"]
        g = {"date": e["date"], "state": e["status"]["type"]["state"],
             "home": h["team"]["abbreviation"], "away": a["team"]["abbreviation"],
             "homeName": h["team"]["displayName"], "awayName": a["team"]["displayName"],
             "hs": int(h.get("score") or 0), "as": int(a.get("score") or 0)}
        if g["state"] == "post":
            finished.append(g)
            for x in (h, a):
                for l in x.get("leaders", []):
                    if l.get("name") == "points" and l.get("leaders"):
                        ld = l["leaders"][0]
                        perf.append({"player": ld["athlete"]["displayName"],
                                     "team": x["team"]["abbreviation"],
                                     "pts": int(float(ld["value"])), "date": e["date"]})
        else:
            upcoming.append(g)

# difesa: punti subiti a partita
al = defaultdict(list)
for g in finished:
    al[g["home"]].append(g["as"]); al[g["away"]].append(g["hs"])
defense = sorted(({"team": k, "allowed": round(sum(v)/len(v), 1), "games": len(v)} for k, v in al.items()),
                 key=lambda x: x["allowed"])
for i, x in enumerate(defense): x["rank"] = i + 1

# giocatori in forma: miglior marcatore di squadra in almeno 2 partite recenti
byp = defaultdict(list)
for p in perf: byp[(p["player"], p["team"])].append(p["pts"])
upcoming.sort(key=lambda g: g["date"])
dmap = {x["team"]: x for x in defense}
hot = []
for (name, team), v in byp.items():
    if len(v) < 2: continue
    nxt = next((g for g in upcoming if team in (g["home"], g["away"])), None)
    opp = None
    if nxt:
        o = nxt["away"] if nxt["home"] == team else nxt["home"]
        opp = {"team": o, "date": nxt["date"], "rank": dmap.get(o, {}).get("rank"),
               "allowed": dmap.get(o, {}).get("allowed"), "home": nxt["home"] == team}
    hot.append({"player": name, "team": team, "avg": round(sum(v)/len(v), 1), "games": len(v), "last": v[-5:], "next": opp})
hot.sort(key=lambda x: -x["avg"]); hot = hot[:10]

# classifiche
standings = []
for conf in get("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings").get("children", []):
    rows = []
    for en in conf.get("standings", {}).get("entries", []):
        st = {s["name"]: s.get("value") for s in en.get("stats", [])}
        rows.append({"team": en["team"]["displayName"], "abbr": en["team"].get("abbreviation"),
                     "w": int(st.get("wins") or 0), "l": int(st.get("losses") or 0)})
    rows.sort(key=lambda r: -(r["w"] / max(1, r["w"] + r["l"])))
    standings.append({"conf": conf.get("name"), "rows": rows})

# ---- probabilità di vittoria: record + forma + back-to-back + infortuni ----
import math
def add_probabilities(upcoming, finished, standings, injuries, perf, games_played):
    wp, n2a = {}, {}
    for c in standings:
        for r in c["rows"]:
            wp[r["abbr"]] = (r["w"] + 5) / (r["w"] + r["l"] + 10)   # record con regressione verso 50%
            n2a[r["team"]] = r["abbr"]
    pd = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    allg = sorted(finished + upcoming, key=lambda g: g["date"])
    margins = defaultdict(list)                       # margine punti, ultime partite
    for g in finished:
        margins[g["home"]].append(g["hs"] - g["as"]); margins[g["away"]].append(g["as"] - g["hs"])
    form = {t: sum(m[-5:]) / len(m[-5:]) for t, m in margins.items()}
    tops = defaultdict(int)                           # quante volte è stato il miglior marcatore
    for p in perf: tops[(p["player"], p["team"])] += 1
    W = {"out": 1.0, "doubtful": 0.75}
    miss = defaultdict(list)                          # assenze pesate per squadra
    for i in injuries:
        t = n2a.get(i["team"]); 
        if not t: continue
        share = tops.get((i["player"], t), 0) / max(1, games_played.get(t, 1))
        if share < 0.15: continue                     # conta solo chi segna davvero
        w = W.get((i["status"] or "").lower(), 0.4)
        miss[t].append((i["player"], i["status"], min(0.7, share * 0.6) * w))
    for g in upcoming:
        h, a = g["home"], g["away"]
        if h not in wp or a not in wp: continue
        lo = math.log(wp[h] / (1 - wp[h])) - math.log(wp[a] / (1 - wp[a])) + 0.32
        why = []
        if h in form and a in form:
            lo += max(-0.5, min(0.5, 0.03 * (form[h] - form[a])))
        for t, sign in ((h, -1), (a, 1)):
            prev = next((x for x in reversed(allg) if t in (x["home"], x["away"]) and x["date"] < g["date"]), None)
            if prev and (pd(g["date"]) - pd(prev["date"])).total_seconds() < 30 * 3600:
                lo += sign * 0.25; why.append("Back-to-back: " + t)
            for name, st, imp in miss.get(t, []):
                lo += sign * imp; why.append(f"{name} ({st}, {t})")
        g["pHome"] = round(100 / (1 + math.exp(-lo)), 1); g["why"] = why

# infortuni + novita rispetto all'ultimo aggiornamento
injuries = []
for t in get(B + "/injuries").get("injuries", []):
    for i in t.get("injuries", []):
        injuries.append({"player": i["athlete"]["displayName"], "team": t.get("displayName"),
                         "status": i.get("status"), "note": i.get("shortComment") or "", "date": i.get("date")})
old = {}
if os.path.exists("data.json"):
    try: old = {(x["player"], x["team"]): x["status"] for x in json.load(open("data.json"))["injuries"]}
    except Exception: pass
changes = []
for x in injuries:
    prev = old.get((x["player"], x["team"]))
    if old and prev != x["status"]:
        changes.append({"player": x["player"], "team": x["team"], "from": prev or "nuovo", "to": x["status"]})

add_probabilities(upcoming, finished, standings, injuries, perf, {k: len(v) for k, v in al.items()})

out = {"updated": dt.datetime.utcnow().isoformat() + "Z", "finished": finished[-20:][::-1],
       "upcoming": upcoming[:20], "defense": defense, "hot": hot,
       "standings": standings, "injuries": injuries, "changes": changes}
json.dump(out, open("data.json", "w"), ensure_ascii=False, indent=1)
print("OK:", len(injuries), "infortuni,", len(finished), "partite,", len(changes), "novita")
