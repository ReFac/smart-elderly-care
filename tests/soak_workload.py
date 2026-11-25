"""Run paced, authenticated HTTP reads and writes against the isolated 200-bed Linux fixture."""

from bisect import bisect_left
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPException
import json
from math import ceil
from pathlib import Path
from statistics import median
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from perf_beds import check_snapshot
from perf_workspace import ROUTES, cpu_seconds, request, session_headers

# A fixed histogram keeps the load driver's own memory independent of the request rate.
LATENCY_MS = (5, 10, 20, 50, 100, 150, 200, 250, 500, 1000, 2000, 5000, 15000, 60000)


def read_kib(path):
    return {key: int(rest.split()[0]) for key, rest in
            (line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
            if rest.strip().endswith(' kB')}


def process_identity(proc):
    # Linux /proc/PID/stat: starttime is field 22 (third field starts after comm).
    return (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]


def sample(pid, identity, started):
    proc = Path(f'/proc/{pid}')
    if process_identity(proc) != identity:
        raise RuntimeError('service process changed during the observation window')
    fields = (proc / 'status').read_text().splitlines()
    status = dict(row.split(':', 1) for row in fields if ':' in row)
    rollup = read_kib(proc / 'smaps_rollup')
    vm = read_kib(Path('/proc/meminfo'))
    vmstats = dict(row.split() for row in Path('/proc/vmstat').read_text().splitlines())
    return {
        'at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'elapsed_s': round(monotonic() - started, 3),
        'rss_mib': round(rollup['Rss'] / 1024, 3),
        'pss_mib': round(rollup['Pss'] / 1024, 3),
        'private_mib': round((rollup['Private_Clean'] + rollup['Private_Dirty']) / 1024, 3),
        'anonymous_mib': round(rollup['Anonymous'] / 1024, 3),
        'rss_hwm_mib': round(int(status['VmHWM'].split()[0]) / 1024, 3),
        'threads': int(status['Threads']), 'service_cpu_s': round(cpu_seconds(pid), 3),
        'available_mib': round(vm['MemAvailable'] / 1024, 3),
        'swap_used_mib': round((vm['SwapTotal'] - vm['SwapFree']) / 1024, 3),
        'kernel_oom_kills': int(vmstats['oom_kill']),
    }


def collect_memory(pid, path, started, duration, interval, stop):
    identity = process_identity(Path(f'/proc/{pid}'))
    next_tick = started
    with path.open('x', buffering=1) as out:
        while True:
            timeout = max(0, next_tick - monotonic()) if next_tick < started + duration else None
            stopping = stop.wait(timeout)
            row = sample(pid, identity, started)
            out.write(json.dumps(row) + '\n')
            if stopping:
                break
            next_tick += interval
            if next_tick < monotonic():
                next_tick = monotonic() + interval


def slope(hourly, key):
    # Fit only whole post-warmup hours; a final sample alone is not an extra hour.
    if len(hourly) < 2:
        return None
    x = [row['hour'] for row in hourly]
    y = [row[key] for row in hourly]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    return round(sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) /
                 sum((a - mean_x) ** 2 for a in x), 4)


def memory_summary(path, duration, interval):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows:
        hour = min(int(row['elapsed_s'] // 3600) + 1, ceil(duration / 3600))
        groups[hour].append(row)
    hourly = []
    for hour, readings in sorted(groups.items()):
        hourly.append({
            'hour': hour, 'samples': len(readings),
            **{field + '_median_mib': round(median(r[field + '_mib'] for r in readings), 3)
               for field in ('rss', 'pss', 'private')},
            'rss_max_mib': max(r['rss_mib'] for r in readings),
        })
    valid_hours = [h for h in hourly if 1 < h['hour'] <= duration // 3600
                   and h['samples'] >= max(1, int(3600 / interval) - 1)]
    return {
        'sample_count': len(rows), 'first_at': rows[0]['at'], 'last_at': rows[-1]['at'],
        'observed_s': round(rows[-1]['elapsed_s'] - rows[0]['elapsed_s'], 3),
        'max_gap_s': round(max((b['elapsed_s'] - a['elapsed_s'] for a, b in zip(rows, rows[1:])), default=0), 3),
        'rss_peak_mib': max(max(r['rss_hwm_mib'], r['rss_mib']) for r in rows),
        'min_available_mib': min(r['available_mib'] for r in rows),
        'swap_used_peak_mib': max(r['swap_used_mib'] for r in rows),
        'oom_kills': rows[-1]['kernel_oom_kills'] - rows[0]['kernel_oom_kills'],
        'service_cpu_s': round(rows[-1]['service_cpu_s'] - rows[0]['service_cpu_s'], 3),
        'max_threads': max(r['threads'] for r in rows), 'hourly': hourly, 'warmup_hours': 1,
        'trend_hours': len(valid_hours), 'rss_slope_mib_per_hour': slope(valid_hours, 'rss_median_mib'),
        'pss_slope_mib_per_hour': slope(valid_hours, 'pss_median_mib'),
    }


def json_file(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def issue(port, auth, route, payload=None):
    start = monotonic()
    try:
        code, _, body = request(port, route, headers=auth, payload=payload)
    except (OSError, HTTPException) as error:
        return route, type(error).__name__, None, (monotonic() - start) * 1000
    return route, str(code), body, (monotonic() - start) * 1000


class Traffic:
    def __init__(self):
        self.statuses = defaultdict(Counter)
        self.latencies = defaultdict(lambda: [0] * (len(LATENCY_MS) + 1))
        self.problems = Counter()

    def observe(self, response, allowed=('200',)):
        route, code, body, ms = response
        self.statuses[route][code] += 1
        self.latencies[route][bisect_left(LATENCY_MS, ms)] += 1
        if code not in allowed:
            self.problems[f'{route} {code}'] += 1
        return code, body

    def summary(self):
        result = {}
        for route, counts in self.statuses.items():
            count = sum(counts.values())
            cumulative = 0
            bound = None
            for ms, observations in zip(LATENCY_MS, self.latencies[route]):
                cumulative += observations
                if cumulative >= ceil(count * .95):
                    bound = ms
                    break
            result[route] = {'count': count, 'statuses': counts, 'p95_upper_ms': bound}
        return result


def record_vital(port, auth, resident_id, marker, version, traffic):
    for _ in range(4):
        command = {'action': 'care.vital', 'revision': version, 'payload': {
            'residentId': resident_id, 'metric': '体温', 'value': '36.5', 'unit': '℃',
            'note': marker,
        }}
        code, _ = traffic.observe(issue(port, auth, '/api/commands', command), ('200', '409'))
        if code != '409':
            return code == '200'
        code, body = traffic.observe(issue(port, auth, '/api/version'))
        if code != '200':
            return False
        version = json.loads(body)['revision']
    traffic.problems['vital edit conflicts exhausted'] += 1
    return False


def run(pid, port, output_dir, duration_s=86400, sample_s=60, read_s=4, write_s=180):
    """The server must already be running on loopback using seed_beds and PASSWORD."""
    if not __debug__ or min(duration_s, sample_s, read_s, write_s) <= 0:
        raise ValueError('use positive intervals and enable assertions for census validation')
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'telemetry.jsonl'
    if path.exists():
        raise FileExistsError(f'{path} already exists; use a fresh result directory')
    auth = session_headers(port, 'owner')
    traffic = Traffic()
    _, initial_body = traffic.observe(issue(port, auth, '/api/state'))
    initial = json.loads(initial_body)
    occupied, beds = check_snapshot(initial)
    # Never register synthetic vitals unless the distinctive isolated fixture is present.
    if 'mixed-bed-200-1' not in beds or 'mixed-person-180' not in occupied:
        raise ValueError('expected the isolated perf_beds.seed_beds fixture')
    resident_ids = sorted(occupied)
    del occupied, beds, initial, initial_body
    marker_prefix = 'soak-' + uuid4().hex + '-'
    expected = {}
    checks = 1
    started = monotonic()
    next_read = next_write = next_check = started
    renew_at = started + 8 * 3600
    next_progress = started
    deadline = started + duration_s
    cycles = missed_reads = missed_writes = writes_ok = renewals = 0
    stop = Event()
    with ThreadPoolExecutor(max_workers=4) as pool:
        telemetry = pool.submit(collect_memory, pid, path, started, duration_s, sample_s, stop)
        try:
            while monotonic() < deadline:
                if telemetry.done():
                    telemetry.result()
                    raise RuntimeError('telemetry ended prematurely')
                now = monotonic()
                if now < next_read:
                    sleep(max(0, min(next_read, deadline) - now))
                    continue
                if now >= renew_at:
                    auth = session_headers(port, 'owner')
                    renew_at = monotonic() + 8 * 3600
                    renewals += 1
                cycles += 1
                next_read += read_s
                reads = [pool.submit(issue, port, auth, route) for route in ROUTES]
                version = None
                for future in reads:
                    response = future.result()
                    route = response[0]
                    code, body = traffic.observe(response)
                    if code == '401':
                        renew_at = 0
                    if code != '200':
                        continue
                    if route == '/api/state' and now >= next_check:
                        try:
                            check_snapshot(json.loads(body))
                            checks += 1
                        except (ValueError, KeyError, AssertionError, TypeError) as error:
                            traffic.problems['invalid census ' + type(error).__name__] += 1
                        next_check += sample_s
                    if route == '/api/version':
                        version = json.loads(body)['revision']
                if now >= next_write:
                    index = len(expected)
                    marker = marker_prefix + str(index)
                    rid = resident_ids[index % len(resident_ids)]
                    expected[marker] = rid
                    if version is not None and record_vital(port, auth, rid, marker, version, traffic):
                        writes_ok += 1
                    next_write += write_s
                    while next_write < now:
                        missed_writes += 1
                        next_write += write_s
                while next_read < monotonic():
                    missed_reads += 1
                    next_read += read_s
                if now >= next_progress:
                    json_file(output / 'workload-progress.json', {
                        'elapsed_s': round(now - started, 2), 'cycles': cycles, 'writes_ok': writes_ok,
                        'snapshot_checks': checks, 'missed_reads': missed_reads, 'missed_writes': missed_writes,
                        'http': traffic.summary(), 'problems': traffic.problems,
                    })
                    next_progress = now + sample_s
        finally:
            stop.set()
            telemetry.result()
    elapsed = monotonic() - started
    code, body = traffic.observe(issue(port, auth, '/api/state'))
    final = json.loads(body) if code == '200' else {}
    if code == '200':
        check_snapshot(final)
        checks += 1
    observed = [v for v in final.get('data', {}).get('vitals', ()) if str(v.get('note', '')).startswith(marker_prefix)]
    counts = Counter(v['note'] for v in observed)
    planned_writes = ceil(duration_s / write_s)
    integrity = {
        'snapshot_checks': checks, 'expected_writes': len(expected), 'acknowledged_writes': writes_ok,
        'persisted_writes': len(observed), 'missing_writes': len(expected.keys() - counts.keys()),
        'duplicate_writes': sum(n - 1 for n in counts.values()),
        'unexpected_writes': len(counts.keys() - expected.keys()),
        'wrong_resident_writes': sum(v['residentId'] != expected.get(v['note']) for v in observed),
    }
    memory = memory_summary(path, duration_s, sample_s)
    integrity_ok = not any(integrity[k] for k in ('missing_writes', 'duplicate_writes', 'unexpected_writes', 'wrong_resident_writes'))
    ok = (elapsed >= duration_s and memory['sample_count'] >= 2 and memory['max_gap_s'] <= 2 * sample_s
          and not memory['oom_kills'] and integrity_ok and not traffic.problems
          and writes_ok == len(expected) == planned_writes and not missed_writes and not missed_reads)
    result = {
        'elapsed_s': round(elapsed, 3), 'duration_s': duration_s, 'ok': ok, 'memory': memory,
        'http': traffic.summary(), 'integrity': integrity, 'problems': traffic.problems, 'session_renewals': renewals,
        'cadence': {'sample_s': sample_s, 'read_s': read_s, 'write_s': write_s, 'read_cycles': cycles,
                    'missed_read_cycles': missed_reads, 'missed_write_slots': missed_writes,
                    'planned_write_slots': planned_writes},
    }
    json_file(output / 'workload.json', result)
    return result
