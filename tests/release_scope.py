"""Chinese release tests. Mark archived other-edition classes or methods with @international_only."""

import unittest


ARCHIVED_REASON = "当前仅测试中文版，其他语言用例保留存档"
international_only = unittest.skip(ARCHIVED_REASON)


class ChineseReleaseLoader(unittest.TestLoader):
    """Omit archived cases before running fixtures; ordinary unittest still honors their skip."""

    def getTestCaseNames(self, testCaseClass):
        if getattr(testCaseClass, "__unittest_skip_why__", None) == ARCHIVED_REASON:
            return []
        return [
            name for name in super().getTestCaseNames(testCaseClass)
            if getattr(getattr(testCaseClass, name), "__unittest_skip_why__", None) != ARCHIVED_REASON
        ]
