"""Run discovery using isolated credentials and simulated provider responses."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from provider_fixture import credential_env


def deny_live_provider(event, args):
    if event == "urllib.Request" and urlsplit(args[0]).hostname in {
        "api.deepseek.com", "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    }:
        raise AssertionError("普通测试须使用本地模拟供应商回执")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.addaudithook(deny_live_provider)
    with TemporaryDirectory() as temp, patch.dict("os.environ", credential_env(temp)):
        unittest.main(
            module=None,
            argv=[sys.argv[0], "discover", "-s", str(root / "tests"), *sys.argv[1:]],
        )
