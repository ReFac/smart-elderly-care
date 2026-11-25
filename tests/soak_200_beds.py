"""Run a real-time, isolated 200-bed endurance test on Linux.

python3 tests/soak_200_beds.py /private/new-result-directory --source-revision GIT_SHA
The directory must be new. It will hold a synthetic database and its recovery key.
Only the aggregate results are intended for publication.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import time
import traceback
from unittest.mock import patch

from perf_beds import seed_beds
from perf_workspace import server
from provider_fixture import credential_env
from soak_schedule import seed_schedule, verify_schedule
from soak_workload import run as run_workload

DAY = 24 * 3600


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def hardware():
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "cpus": len(os.sched_getaffinity(0)),
        "mem_total_kib": int(memory["MemTotal"].split()[0]),
        "swap_total_kib": int(memory["SwapTotal"].split()[0]),
        "kernel": platform.release(),
        "python": platform.python_version(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--seconds", type=int, default=DAY, help="shorter runs are smoke tests")
    args = parser.parse_args()
    if not 1 <= args.seconds <= DAY or not re.fullmatch("[a-f0-9]{40}", args.source_revision):
        parser.error("provide a 40-character Git revision and 1–86400 real seconds")
    host = hardware()
    if args.seconds == DAY and not (host["cpus"] == 2 and 1800 * 1024 <= host["mem_total_kib"] <= 2048 * 1024
                                    and host["swap_total_kib"] == 0):
        parser.error("the 24-hour acceptance run requires 2 CPUs, 2 GiB RAM and no swap")
    os.umask(0o077)
    directory = args.directory.resolve()
    directory.mkdir(mode=0o700, exist_ok=False)
    fixture = directory / "private"
    fixture.mkdir()
    manifest = None

    def seed(store):
        nonlocal manifest
        seed_beds(store)
        manifest = seed_schedule(store)
        save(fixture / "schedule-manifest.json", manifest)

    original_boot = boot_id()
    record = {"source_revision": args.source_revision, "requested_seconds": args.seconds, "hardware": host}
    with server(fixture, seed=seed) as (pid, port):
        started_mono = time.monotonic()
        record["started_epoch"] = time.time()
        save(directory / "progress.json", {**record, "phase": "load", "service_pid": pid})
        try:
            workload = run_workload(pid, port, directory, duration_s=args.seconds, sample_s=min(60, args.seconds))
        except Exception as error:
            # Preserve the measured interval and reconcile deliveries even if the
            # service exits unexpectedly. Never count a restarted interval as continuous.
            workload = {"ok": False, "problems": [type(error).__name__]}
            traceback.print_exc()
        record.update(ended_epoch=time.time(), monotonic_seconds=time.monotonic() - started_mono,
                      boot_unchanged=original_boot == boot_id(), workload=workload)
        save(directory / "progress.json", {**record, "phase": "scheduler_grace"})
        # One last polling cycle can complete after the cut-off. Keep its due time
        # inside the observation window and report dispatch lateness separately.
        time.sleep(60)

    try:
        with patch.dict(os.environ, credential_env(fixture)):
            record["schedule"] = verify_schedule(fixture / "fixture.sqlite3", manifest,
                                                 record["started_epoch"], record["ended_epoch"], restore=True)
    except Exception as error:
        record["schedule"] = {"ok": False, "problems": [type(error).__name__]}
        traceback.print_exc()
    save(directory / "run.json", record)
    save(directory / "progress.json", {"phase": "finished", "ended_epoch": record["ended_epoch"]})
    return int(not (record["boot_unchanged"] and record["monotonic_seconds"] >= args.seconds
                    and workload.get("ok") and record["schedule"].get("ok")))


if __name__ == "__main__":
    raise SystemExit(main())
