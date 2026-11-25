"""The release entry point and ordinary unittest discovery honor the same edition boundary."""

import unittest

from provider_fixture import credential_env
from release_scope import ChineseReleaseLoader, international_only


class ReleaseScopeTests(unittest.TestCase):
    def test_discovery_and_explicit_selection_preserve_only_shared_and_chinese_cases(self):
        class Mixed(unittest.TestCase):
            def test_shared(self):
                pass

            @international_only
            def test_archived(self):
                self.fail("Archived test executed")

        @international_only
        class Archived(Mixed):
            pass

        loader = ChineseReleaseLoader()
        self.assertEqual(loader.getTestCaseNames(Mixed), ["test_shared"])
        self.assertEqual(loader.getTestCaseNames(Archived), [])
        self.assertTrue(Mixed.test_archived.__unittest_skip__)
        self.assertTrue(Archived.__unittest_skip__)
        self.assertEqual(credential_env(".")["NH_DEPLOYMENT_LANGUAGE"], "zh-CN")
