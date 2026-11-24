"""Keep unit-test credentials independent from the machine that runs the suite."""

from pathlib import Path
from unittest.mock import patch


def credential_env(folder):
    return {
        "DEEPSEEK_API_KEY": "",
        "NH_DEEPSEEK_KEY_FILE": "",
        "NH_PLATFORM_VAULT": str(Path(folder) / "isolated-platform.sqlite3"),
        "NH_PLATFORM_KEY_FILE": "",
    }


def isolate_credentials(case, folder):
    override = patch.dict("os.environ", credential_env(folder))
    override.start()
    case.addCleanup(override.stop)
