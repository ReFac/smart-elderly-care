"""Render the public aggregate report from a private endurance-test directory."""

import argparse
import csv
from datetime import date, datetime
import json
import math
from pathlib import Path
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
DAY = 86_400
TELEMETRY = ("elapsed_s", "rss_mib", "pss_mib", "private_mib", "available_mib",
             "swap_used_mib", "threads", "kernel_oom_kills")


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def fmt(value, digits=0):
    return f"{value:,.{digits}f}" if numeric(value) else "—"


def stamp(epoch):
    if numeric(epoch):
        return datetime.fromtimestamp(epoch, ZONE).strftime("%Y-%m-%d %H:%M:%S")
    return "—"


def disposition(value):
    return {True: "通过", False: "未通过"}.get(value, "待核验")


def safe_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return "—"


def export_samples(source, target):
    """CSV has numerical measurements only. Empty cells represent unavailable values."""
    temporary = target.with_suffix(".csv.tmp")
    count = 0
    with source.open(encoding="utf-8") as samples, temporary.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(TELEMETRY)
        for line in samples:
            record = json.loads(line)
            if not numeric(record.get("elapsed_s")):
                raise ValueError("Telemetry row without an elapsed time")
            writer.writerow(record[key] if numeric(record.get(key)) else "" for key in TELEMETRY)
            count += 1
    temporary.replace(target)
    return count


def render(record, sample_count=None):
    hardware = record.get("hardware", {})
    load = record.get("workload", {})
    schedule = record.get("schedule", {})
    memory = load.get("memory", {})
    work = schedule.get("work", {})
    cadence = load.get("cadence", {})
    backups = schedule.get("backups", [])
    restores = [b for b in backups if b.get("restored")]
    elapsed = record.get("monotonic_seconds")
    full = numeric(elapsed) and elapsed >= DAY and record.get("requested_seconds") == DAY
    hours = {r["hour"]: r for r in memory.get("hourly", []) if type(r.get("hour")) is int}
    valid_hours = [h for h in range(1, 25) if numeric(hours.get(h, {}).get("rss_median_mib"))]
    max_gap = memory.get("max_gap_s")
    observed = memory.get("observed_s")
    sample_ok = (len(valid_hours) == 24 and numeric(max_gap) and max_gap <= 120
                 and numeric(observed) and observed >= DAY - 60
                 and (sample_count is None or sample_count == memory.get("sample_count")))
    hardware_ok = (hardware.get("cpus") == 2 and hardware.get("swap_total_kib") == 0
                   and 1800 * 1024 <= hardware.get("mem_total_kib", 0) <= 2048 * 1024)
    if not full:
        verdict = "本次运行未覆盖完整的 24 小时。"
    elif not (hardware_ok and record.get("boot_unchanged") and sample_ok):
        verdict = "连续性、硬件或采样证据未满足 24 小时验收条件。"
    elif load.get("ok") is not True or schedule.get("ok") is not True:
        verdict = "已运行满 24 小时，业务或资源校验发现异常。"
    else:
        verdict = "连续 24 小时的业务、采样和恢复校验通过。"
    sha = record.get("source_revision", "")
    revision = sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "未记录"
    start, end = record.get("started_epoch"), record.get("ended_epoch")
    lines = [
        "# 200 床医养工作台持续负载测试", "", f"**{verdict}**", "",
        f"北京时间 {stamp(start)} 至 {stamp(end)}，单调时钟实测 {fmt(elapsed, 2)} 秒。"
        f"测试使用 200 张床、180 位合成长辈，应用源码为 `{revision}`。",
        "",
        f"客体可用逻辑 CPU 数为 {fmt(hardware.get('cpus'))}，内核可见内存 "
        f"{fmt(hardware.get('mem_total_kib'))} KiB，交换空间 {fmt(hardware.get('swap_total_kib'))} KiB。"
        f"启动标识连续性校验{disposition(record.get('boot_unchanged'))}。", "",
        "## 内存变化", "",
        f"服务峰值 RSS 为 {fmt(memory.get('rss_peak_mib'), 2)} MiB，客体最低可用内存 "
        f"{fmt(memory.get('min_available_mib'), 2)} MiB。客体 OOM 终止事件增量为 "
        f"{fmt(memory.get('oom_kills'))}，交换空间峰值使用 {fmt(memory.get('swap_used_peak_mib'), 2)} MiB。", "",
        f"从负载开始按 {fmt(cadence.get('sample_s'))} 秒间隔采样。实际采集 {fmt(memory.get('sample_count'))} 次，"
        f"首末样本相距 {fmt(observed, 2)} 秒，最大间隔 {fmt(max_gap, 2)} 秒，覆盖 {len(valid_hours)} 个小时段。"
        "24 小时验收要求首末样本至少相距 86,340 秒、每小时有数据且最大间隔不超过 120 秒。",
    ]
    if sample_count is not None:
        lines[-1] += f" 随报告发布的 CSV 包含 {fmt(sample_count)} 行数值。"
        if sample_count != memory.get("sample_count"):
            lines[-1] += " CSV 行数与汇总计数不一致。"
    if full and len(valid_hours) == 24:
        early = hours[2]["rss_median_mib"]
        late = hours[24]["rss_median_mib"]
        medians = [hours[i]["rss_median_mib"] for i in range(2, 25)]
        increases = sum(b > a for a, b in zip(medians, medians[1:]))
        lines += ["", f"跳过第 1 小时预热后，第 2 小时和第 24 小时的 RSS 中位数分别为 "
                  f"{early:.2f} 和 {late:.2f} MiB，净变化 {late - early:+.2f} MiB。"
                  f"22 次相邻小时比较中有 {increases} 次上升。RSS 和 PSS 的拟合斜率分别为 "
                  f"{fmt(memory.get('rss_slope_mib_per_hour'), 3)} 和 "
                  f"{fmt(memory.get('pss_slope_mib_per_hour'), 3)} MiB/小时。"
                  "这些数值描述本次工作量下的变化，长期泄漏需要进一步做分配跟踪。"]
    lines += ["", "| 负载小时 | 样本 | RSS 中位 MiB | RSS 峰值 MiB | PSS 中位 MiB | 私有内存中位 MiB |",
              "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for h in (range(1, 25) if full else sorted(hours)):
        row = hours.get(h, {})
        lines.append("| " + " | ".join([str(h), fmt(row.get("samples"))] +
                     [fmt(row.get(k), 2) for k in ("rss_median_mib", "rss_max_mib", "pss_median_mib",
                                                   "private_median_mib")]) + " |")
    lines += ["", "## 定时派单", "",
              f"派单核验{disposition(work.get('ok'))}。应派 {fmt(work.get('expected_runs'))} 批，"
              f"实际收到 {fmt(work.get('receipts'))} 批回执。应生成 {fmt(work.get('expected_tasks'))} 项，"
              f"实际生成 {fmt(work.get('issued_tasks'))} 项。每批核对接收名单、床号房号、回执关联，餐单另查菜品。",
              "", "| 预定时间（北京时间） | 项目 | 应派 | 实派 | 漏派 | 重复 | 名单外 | 延迟秒 |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in sorted(work.get("occurrences", []), key=lambda row: row["due"]):
        when = datetime.fromisoformat(r["due"]).astimezone(ZONE).strftime("%m-%d %H:%M")
        name = r.get("name")
        if name not in ("早间巡查", "早餐", "午餐", "晚餐", "晚间巡查"):
            name = "小时巡查"
        lines.append("| " + " | ".join([when, name] +
                     [fmt(r.get(k)) for k in ("expected", "issued", "missing", "duplicates", "unexpected", "delay_s")])
                     + " |")
    lines += ["", "## 备份与独立恢复", "",
              "按北京时间的自然日核对每日自动备份。启动当天核对补建，此后核对零点到期的快照。"
              "每份快照在单独目录解密还原，核对修订号、床位及其人员、派单规则、已到期工单及回执。",
              "", f"应有 {len(backups) if 'backups' in schedule else '—'} 个备份槽，"
              f"就绪 {sum(b.get('state') == 'ready' for b in backups) if 'backups' in schedule else '—'} 个，"
              f"成功冷恢复 {len(restores) if 'backups' in schedule else '—'} 个。"
              f"备份校验{disposition(schedule.get('restore_verified'))}。", "",
              "| 计划日期 | 就绪情况 | 冷恢复 | 快照时间（北京时间） | 延迟秒 | 大小（字节） | 尝试次数 | 恢复床位 / 在住 | 恢复回执 / 工单 |",
              "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |"]
    for b in backups:
        restore = b.get("restored", {})
        state = {"ready": "就绪", "missing": "缺失"}.get(b.get("state"), "未就绪")
        lines.append(f"| {safe_day(b.get('day'))} | {state} | {'通过' if restore else '未验证成功'} | "
                     f"{stamp(b.get('captured'))} | {fmt(b.get('delay_s'), 2)} | "
                     f"{fmt(b.get('bytes'))} | {fmt(b.get('attempts'))} | "
                     f"{fmt(restore.get('beds'))} / {fmt(restore.get('occupied'))} | "
                     f"{fmt(restore.get('verified_receipts'))} / {fmt(restore.get('verified_tasks'))} |")
    integrity = load.get("integrity", {})
    routes = list(load.get("http", {}).values())
    total = sum(r["count"] for r in routes) if routes else None
    successes = sum(n for r in routes for code, n in r["statuses"].items() if re.fullmatch(r"2[0-9]{2}", code))
    lines += ["", "## HTTP 负载与写入核对", "",
              f"每 {fmt(cadence.get('read_s'))} 秒并发读取工作台、数据版本和助理导航版本，每 "
              f"{fmt(cadence.get('write_s'))} 秒轮流为一位在住长辈写入一条合成体温记录。"
              f"读取完成 {fmt(cadence.get('read_cycles'))} 轮，跳过 {fmt(cadence.get('missed_read_cycles'))} 轮，"
              f"错过 {fmt(cadence.get('missed_write_slots'))} 个写入时点。", "",
              f"测得 {fmt(total)} 次请求，其中 {fmt(successes if routes else None)} 次返回 2xx。"
              f"工作台快照校验 {fmt(integrity.get('snapshot_checks'))} 次。"
              f"计划写入 {fmt(integrity.get('expected_writes'))} 条，确认持久化 {fmt(integrity.get('persisted_writes'))} 条，"
              f"缺少 {fmt(integrity.get('missing_writes'))} 条，重复 {fmt(integrity.get('duplicate_writes'))} 条，"
              f"多余 {fmt(integrity.get('unexpected_writes'))} 条，关联长辈错误 {fmt(integrity.get('wrong_resident_writes'))} 条。", "",
              "| 入口 | 请求数 | 成功 | 修订冲突 | 其他响应或连接错误 | P95 上界（毫秒） |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for path, label in (("/api/state", "工作台"), ("/api/version", "数据版本"),
                        ("/api/assistant/navigation-version", "导航版本"), ("/api/commands", "照护记录写入")):
        if path in load.get("http", {}):
            entry = load["http"][path]
            ok = entry["statuses"].get("200", 0)
            conflict = entry["statuses"].get("409", 0)
            other = entry["count"] - ok - conflict
            lines.append(f"| {label} | {fmt(entry['count'])} | {fmt(ok)} | {fmt(conflict)} | {fmt(other)} | "
                         f"{fmt(entry.get('p95_upper_ms'))} |")
    lines.extend(["", "延迟取固定直方图桶的上界。遇到修订冲突时，写入端重新取版本后重试。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".md":
        parser.error("expected a Markdown output (.md)")
    record = json.loads((args.directory / "run.json").read_text(encoding="utf-8"))
    source = args.directory / "telemetry.jsonl"
    samples = export_samples(source, args.output.with_suffix(".csv")) if source.exists() else None
    content = render(record, samples)
    if samples is not None:
        csv_name = quote(args.output.with_suffix(".csv").name, safe="-._")
        content += f"\n[下载逐次内存采样 CSV]({csv_name})\n"
    args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
