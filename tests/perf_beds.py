"""Validate concurrent transfers with 200 beds and 180 residents over authenticated HTTP.

Run python3 tests/perf_beds.py > bed-results.json on Linux. Uses a temporary encrypted
database and four clients sharing a synthetic Owner session.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from time import monotonic

from perf_workspace import ROUTES, cpu_seconds, peak_rss, percentiles, request, server, session_headers
from platform_core.care.residency import move

BED_COUNT = 200
OCCUPIED = 180
ROUNDS = 20


def seed_beds(store):
    with closing(store.connect()) as db, db:
        state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
        # The demo already has 24 beds. The new room numbers avoid its rooms 201–204.
        for number in [200, *range(205, 292)]:
            room_id = f"mixed-room-{number}"
            ward = "混合测试区"
            db.execute(
                "INSERT INTO facility_rooms(id,floorId,number,ward) VALUES(?,?,?,?)",
                (room_id, "floor-2", str(number), ward),
            )
            for slot in (1, 2):
                bed_id = f"mixed-bed-{number}-{slot}"
                db.execute("INSERT INTO facility_beds VALUES(?,?)", (bed_id, room_id))
                state["beds"].append({
                    "id": bed_id, "label": f"{number}-{slot:02}", "ward": ward,
                    "dailyRate": 65, "residentId": "", "status": "空闲",
                })
        free_beds = (bed for bed in state["beds"] if not bed["residentId"])
        today = store.now().date().isoformat()
        for index in range(len(state["residents"]) + 1, OCCUPIED + 1):
            resident = {
                **state["residents"][0], "name": f"混合测试{index}", "id": f"mixed-person-{index}",
                "bedId": "", "stayType": "formal", "summary": "合成测试档案",
            }
            state["residents"].append(resident)
            move(state, resident, today, "入住", new_bed=next(free_beds))
        db.execute("UPDATE workspace SET data=? WHERE id=1", (json.dumps(state, ensure_ascii=False),))


def check_snapshot(snapshot):
    data = snapshot["data"]
    beds = {bed["id"]: bed for bed in data["beds"]}
    residents = {p["id"]: p for p in data["residents"] if p["status"] == "在住"}
    occupied = {bid: bed["residentId"] for bid, bed in beds.items() if bed["residentId"]}
    directory = data["bedDirectory"]
    assert len(beds) == BED_COUNT and beds.keys() == directory.keys()
    assert len(residents) == len(occupied) == OCCUPIED
    assert occupied == {p["bedId"]: rid for rid, p in residents.items()}
    for resident_id, person in residents.items():
        bed_id = person["bedId"]
        room = beds[bed_id]["label"].split("-")[0]
        assert data["residentRooms"][resident_id] == directory[bed_id]["roomNumber"] == room
    return residents, beds


def fetch(port, auth, path, payload=None, *, expected=200):
    start = monotonic()
    status, _, body = request(port, path, headers=auth, payload=payload)
    data = json.loads(body)
    elapsed_ms = (monotonic() - start) * 1000
    assert status in ((expected,) if isinstance(expected, int) else expected), (path, status, data.get("error"))
    return status, data, elapsed_ms


def transfer(call, revision, resident, old_bed, target, expected, barrier=None):
    if barrier is not None:
        barrier.wait(timeout=10)
    return call("/api/commands", {
        "action": "care.transfer", "revision": revision,
        "payload": {"residentId": resident, "fromBedId": old_bed, "bedId": target},
    }, expected=expected)


def read_during_transfers(call, offset):
    readings = []
    for index in range(ROUNDS * len(ROUTES)):
        path = ROUTES[(index + offset) % len(ROUTES)]
        _, data, ms = call(path)
        if path == "/api/state":
            check_snapshot(data)
        readings.append((path, ms))
    return readings


def timings(samples):
    grouped = defaultdict(list)
    for key, ms in samples:
        grouped[key].append(ms)
    return {key: {"count": len(times), **percentiles(times)} for key, times in grouped.items()}


def run(pid, port):
    call = partial(fetch, port, session_headers(port, "owner"))
    _, initial, _ = call("/api/state")
    residents, beds = check_snapshot(initial)
    occupants = [beds[bed_id]["residentId"] for bed_id in ("mixed-bed-200-1", "mixed-bed-209-1")]
    assigned = {rid: residents[rid]["bedId"] for rid in occupants}
    free = {bid for bid, bed in beds.items() if not bed["residentId"]}
    revision = initial["revision"]
    writes = []
    refreshes = []
    cpu_start = cpu_seconds(pid)
    start = monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        readers = [pool.submit(read_during_transfers, call, offset) for offset in (0, 1)]
        for _ in range(ROUNDS):
            target, alternate = sorted(free)[:2]
            barrier = Barrier(2)
            calls = {
                rid: pool.submit(transfer, call, revision, rid, assigned[rid], target, (200, 409), barrier)
                for rid in occupants
            }
            results = {rid: future.result() for rid, future in calls.items()}
            assert sorted(code for code, _, _ in results.values()) == [200, 409]
            winner, loser = sorted(occupants, key=lambda rid: results[rid][0])
            writes.extend((code, ms) for code, _, ms in results.values())

            _, current, ms = call("/api/version")
            refreshes.append(ms)
            revision = current["revision"]
            assert revision == results[winner][1]["revision"]
            code, denied, ms = transfer(call, revision, loser, assigned[loser], target, 400)
            assert "占用" in denied["error"]
            writes.append((code, ms))
            code, accepted, ms = transfer(call, revision, loser, assigned[loser], alternate, 200)
            writes.append((code, ms))
            assert accepted["revision"] == revision + 1
            revision = accepted["revision"]

            free.difference_update((target, alternate))
            free.update(assigned.values())
            assigned.update({winner: target, loser: alternate})
        reads = [sample for future in readers for sample in future.result()]
    wall = monotonic() - start
    cpu = cpu_seconds(pid) - cpu_start
    _, final, _ = call("/api/state")
    residents, beds = check_snapshot(final)
    transfers = [m for m in final["data"]["bedMoves"] if m["kind"] == "转床" and m["residentId"] in occupants]
    assert final["revision"] - initial["revision"] == len(transfers) == 2 * ROUNDS
    assert all(residents[rid]["bedId"] == bid for rid, bid in assigned.items())
    assert free == {bid for bid, bed in beds.items() if not bed["residentId"]}
    requests = len(reads) + len(writes) + len(refreshes)
    return {
        "beds": len(beds), "occupied": len(residents), "vacant": len(free), "concurrent_clients_max": 4,
        "reader_calls": timings(reads), "transfer_statuses": timings(writes),
        "race_rounds": ROUNDS, "version_refreshes": len(refreshes), "successful_transfers": len(transfers),
        "bidirectional_integrity_checks": 2 + sum(path == "/api/state" for path, _ in reads),
        "total_timed_requests": requests, "service_cpu_s": round(cpu, 2), "wall_s": round(wall, 3),
        "requests_per_s": round(requests / wall, 2), "service_lifetime_peak_rss_mib": round(peak_rss(pid), 2),
    }


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run with Python assertions enabled to validate concurrency and bed assignments")
    with TemporaryDirectory(prefix="eldercare-bed-benchmark-") as scratch:
        with server(Path(scratch), seed_beds) as (pid, port):
            print(json.dumps(run(pid, port), indent=2))
