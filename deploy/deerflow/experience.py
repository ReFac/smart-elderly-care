"""Review a detached, non-executable writing skill with DeerFlow's mutation validator."""

from importlib.metadata import version
from re import fullmatch

from deerflow.skills.mutations.validation import validate_candidate
from deerflow.skills.review.analyzer import analyze_skill_package
from deerflow.skills.review.readers import build_inline_snapshot
from deerflow.skills.review.renderer import build_static_report

from capabilities import read_skill


def review(value):
    name, baseline, candidate = (value[key] for key in ("name", "baseline", "candidate"))
    if not fullmatch(r"careops-(?:meals|handover|visit|observations)", name):
        raise ValueError("未登记的经验技能")
    validate_candidate(baseline, candidate, name)
    snapshot = build_inline_snapshot(candidate, name_hint=name)
    facts = analyze_skill_package(snapshot, profile="deerflow")
    summary = facts["summary"]
    if summary["blockers"] or summary["errors"] or not facts["completeness"]["text_content_complete"]:
        raise ValueError("DeerFlow 未通过候选技能检查")
    report = build_static_report(facts, scope=["static"])
    if report["readiness"] != "publish_candidate":
        raise ValueError("候选技能需要修订")
    return {"engine": "DeerFlow", "version": version("deerflow-harness"),
            "digest": facts["subject"]["package_digest"], "report": report,
            "body": read_skill(candidate, name)["instructions"]}
