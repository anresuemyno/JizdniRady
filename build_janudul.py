#!/usr/bin/env python3
"""
Generuje janudul.json z GTFS DPMLJ.
- respektuje calendar + calendar_dates (aktivní service_id pro dnešek),
- filtruje jen linky s GTFS route_type == 0 (tram),
- bere všechny stop_id, jejichž stop_name obsahuje "Janův důl",
- vrací nejbližší odjezdy od aktuálního času (Europe/Prague).
"""

import io, zipfile, csv, json, urllib.request
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

GTFS_URL = "https://www.dpmlj.cz/gtfs.zip"
STOP_NAME = "Janův důl"      # citlivé na diakritiku; porovnáváme case-insensitive
ONLY_TRAM = True             # GTFS route_type 0 = tram/light rail
MAX_RESULTS = 14             # kolik nejbližších odjezdů vracet
TZ = ZoneInfo("Europe/Prague")

def read_csv_from_zip(z, name):
    with z.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))

def to_seconds(hhmmss):
    """GTFS může mít hodiny > 24 (např. 25:10:00)."""
    h, m, s = map(int, hhmmss.split(":"))
    return h*3600 + m*60 + s

def active_service_ids(calendar, calendar_dates, today):
    """
    Vrať množinu service_id aktivních pro 'today' dle calendar + výjimek.
    """
    # 1) základ z calendar
    weekday = today.weekday()  # Mon=0..Sun=6
    weekday_cols = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    active = set()
    for row in calendar:
        start = datetime.strptime(row["start_date"], "%Y%m%d").date()
        end   = datetime.strptime(row["end_date"], "%Y%m%d").date()
        if start <= today <= end and row[weekday_cols[weekday]] == "1":
            active.add(row["service_id"])

    # 2) aplikuj výjimky z calendar_dates (1=add, 2=remove)
    for cd in calendar_dates:
        d = datetime.strptime(cd["date"], "%Y%m%d").date()
        if d == today:
            sid = cd["service_id"]
            if cd["exception_type"] == "1":
                active.add(sid)
            elif cd["exception_type"] == "2" and sid in active:
                active.remove(sid)
    return active

def main():
    now = datetime.now(TZ)
    today = now.date()

    # stáhni GTFS
    data = urllib.request.urlopen(GTFS_URL).read()
    z = zipfile.ZipFile(io.BytesIO(data))

    stops      = read_csv_from_zip(z, "stops.txt")
    stop_times = read_csv_from_zip(z, "stop_times.txt")
    trips      = read_csv_from_zip(z, "trips.txt")
    routes     = read_csv_from_zip(z, "routes.txt")
    calendar   = read_csv_from_zip(z, "calendar.txt") if "calendar.txt" in z.namelist() else []
    cal_dates  = read_csv_from_zip(z, "calendar_dates.txt") if "calendar_dates.txt" in z.namelist() else []

    # stop_id pro "Janův důl" (všechna nástupiště)
    stop_ids = {s["stop_id"] for s in stops if STOP_NAME.lower() in s["stop_name"].lower()}
    if not stop_ids:
        raise SystemExit(f"Nenalezeny žádné stop_id pro '{STOP_NAME}'.")

    # mapy pro rychlý přístup
    trips_by_id = {t["trip_id"]: t for t in trips}
    routes_by_id = {r["route_id"]: r for r in routes}

    # aktivní služby dnes
    active_sids = active_service_ids(calendar, cal_dates, today)

    # případné filtrování jen tramvají
    allowed_route_ids = None
    if ONLY_TRAM:
        allowed_route_ids = {r["route_id"] for r in routes if r.get("route_type") == "0"}

    # posbírej odjezdy od "teď"
    results = []
    midnight = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=TZ)

    for st in stop_times:
        if st["stop_id"] not in stop_ids:
            continue

        trip = trips_by_id.get(st["trip_id"])
        if not trip:
            continue

        # filtruj podle active service_id
        if active_sids and trip["service_id"] not in active_sids:
            continue

        # filtruj route_type (tram)
        route = routes_by_id.get(trip["route_id"], {})
        if allowed_route_ids is not None and trip["route_id"] not in allowed_route_ids:
            continue

        dep_str = st["departure_time"]
        if len(dep_str) != 8 or ":" not in dep_str:
            continue
        dep_sec = to_seconds(dep_str)

        # GTFS "25:10:00" => dnes 01:10:00 následujícího kalendářního dne (ale stále stejný service day)
        dep_dt = midnight + timedelta(seconds=dep_sec)

        if dep_dt >= now:
            results.append({
                "time": dep_dt.strftime("%H:%M"),
                "timestamp": dep_dt.isoformat(),
                "route_short_name": route.get("route_short_name", ""),
                "route_long_name": route.get("route_long_name", ""),
                "headsign": trip.get("trip_headsign", ""),
                "direction_id": trip.get("direction_id", ""),
                "stop_id": st["stop_id"],
                "stop_sequence": st.get("stop_sequence", ""),
            })

    # seřadit, zkrátit
    results.sort(key=lambda r: r["timestamp"])
    results = results[:MAX_RESULTS]

    # zabalit do JSON
    out = {
        "generated_at": now.isoformat(),
        "stop_name_query": STOP_NAME,
        "only_tram": ONLY_TRAM,
        "departures": results
    }
    with open("janudul.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"OK, napsáno {len(results)} položek do janudul.json")

if __name__ == "__main__":
    main()
