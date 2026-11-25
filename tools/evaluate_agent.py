"""Exercise Chinese release and shared agent scenarios through the release test runner."""
import argparse
from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "chat": ("test_assistant_chat", "test_chat_web_search", "test_chat_capacity", "test_chat_provider_failure"),
    "workflow": ("test_agent_runtime", "test_brief_workflow", "test_agent_audit"),
    "tools": ("test_mcp_plugins", "test_community_skills", "test_agent_protocol", "test_resident_workbook"),
    "documents": ("test_assistant_documents", "test_deployment_language"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=tuple(GROUPS), action="append")
    args = parser.parse_args()
    selected = list(dict.fromkeys(args.group or GROUPS))
    if "tools" in selected:
        missing = [name for name in ("a2a", "mcp", "excel_mcp", "openpyxl", "xlrd", "yaml") if find_spec(name) is None]
        if missing:
            parser.exit(2, "Install requirements-harness.txt and requirements-a2a.txt. Missing: " + ", ".join(missing) + "\n")
    started = monotonic()
    failed = []
    for group in selected:
        for scenario in GROUPS[group]:
            print(f"[{group}] {scenario}", flush=True)
            result = subprocess.run([sys.executable, str(ROOT / "tests/run.py"), "-p", scenario + ".py", "-q"],
                                    cwd=ROOT)
            if result.returncode:
                failed.append(scenario)
    print(f"{sum(len(GROUPS[g]) for g in selected)} suites in {monotonic()-started:.1f}s. Failures: {failed}", flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
