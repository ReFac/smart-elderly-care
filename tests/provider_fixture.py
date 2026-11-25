"""Keep unit-test credentials independent from the machine that runs the suite."""

from pathlib import Path
from unittest.mock import patch


def credential_env(folder):
    return {
        "NH_DEPLOYMENT_LANGUAGE": "zh-CN",
        "DEEPSEEK_API_KEY": "",
        "NH_DEEPSEEK_KEY_FILE": "",
        "NH_PLATFORM_VAULT": str(Path(folder) / "isolated-platform.sqlite3"),
        "NH_PLATFORM_KEY_FILE": "",
        "NH_CHAT_PROVIDER": "deepseek",
        "NH_ASR_PROVIDER": "deepseek",
        "NH_TTS_PROVIDER": "deepseek",
    }


def isolate_credentials(case, folder):
    override = patch.dict("os.environ", credential_env(folder))
    override.start()
    case.addCleanup(override.stop)


def simulate_narration(case):
    """Keep workflow tests deterministic. Cloud billing/dispatch have dedicated transport tests."""
    model = patch(
        "platform_core.provider.generation.summarize",
        return_value="云端测试回执，请核对所列记录。",
    )
    model.start()
    case.addCleanup(model.stop)

    # Test the report workflow with all resident facts, one paragraph per fact.
    editor = patch(
        "platform_core.rounds.narrative.arrange",
        side_effect=lambda store, rid, scope, rows, **_: [
            [i] for i in range(1, len(rows) + 1)
        ],
    )
    editor.start()
    case.addCleanup(editor.stop)
