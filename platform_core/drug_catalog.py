"""Drug-name suggestions from the public Chinese national reimbursement catalogue."""

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import re
import subprocess
from threading import Lock
import time
from unicodedata import normalize
from urllib.request import urlopen

SOURCE = "国家医保局 · 国家医保药品目录（2025年）"
SOURCE_PAGE = "https://www.nhsa.gov.cn/art/2025/12/7/art_104_18970.html"
PDF = "https://www.nhsa.gov.cn/module/download/downfile.jsp?classid=0&filename=a32f9f2f3fc046afaf08471f87456ce3.pdf"
DIGEST = "82b249771d25f42b372093ab6be76192754ceb67a0b7309f5da0d5e284842dc3"
MAX_SIZE = 6 * 1024 * 1024
# Only extract names that fit the name cell of a single numbered row. Skip wrapped
# cells, prose, and the negotiated-prices appendix with its different table layout.
ROW = re.compile(
    r"^\s*[甲乙]\s+(?:★\s*)?\(?\d{1,4}\)?[ ]{1,10}(?P<drug>\S+?)(?:\s{2,}|\s*$)"
)
NAME = re.compile(r"[\w（）()\-、Ⅰ-Ⅹ·]+")


def _index(raw):
    names = {}
    for page, body in enumerate(raw.split("\f"), 1):
        if any(line.strip() == "协议期内谈判药品部分" for line in body.splitlines()):
            break
        lines = body.splitlines()
        for i, line in enumerate(lines):
            match = ROW.match(line)
            if not match:
                continue
            name = match["drug"]
            if (
                len(name) < 2
                or not NAME.fullmatch(name)
                or not re.search("[\u3400-\u9fff]", name)
            ):
                continue
            col = match.start("drug")
            adjacent = lines[max(i - 1, 0) : i] + lines[i + 1 : i + 2]
            if any(
                abs(len(other) - len(other.lstrip()) - col) <= 1
                and other.strip()
                and other.strip() != name
                and not ROW.match(other)
                for other in adjacent
            ):
                continue
            names.setdefault(name, page)
    return names


def _download():
    # Fixed publication URL: even the search term stays inside the institution.
    with urlopen(PDF, timeout=5) as response:
        pdf = response.read(MAX_SIZE + 1)
    if len(pdf) > MAX_SIZE or hashlib.sha256(pdf).hexdigest() != DIGEST:
        raise ValueError("目录版本已变更")
    raw = subprocess.run(
        ["pdftotext", "-layout", "-", "-"],
        input=pdf,
        capture_output=True,
        check=True,
        timeout=12,
    ).stdout.decode("utf-8")
    names = _index(raw)
    if not {"阿莫西林", "二甲双胍", "阿司匹林"}.issubset(names):
        raise ValueError("药名目录未能解析")
    return names


class Catalogue:
    def __init__(self):
        self._lock = Lock()
        self.names = {}
        self.checked = ""
        self.status = "unavailable"
        self.next_check = 0

    def current(self):
        with self._lock:
            if time.monotonic() >= self.next_check:
                try:
                    self.names = _download()
                except (OSError, ValueError, subprocess.SubprocessError):
                    self.status = "cached" if self.names else "unavailable"
                    self.next_check = time.monotonic() + 60
                else:
                    self.checked = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    self.status = "online"
                    self.next_check = time.monotonic() + 86400
            return self.names, self.status, self.checked


catalogue = Catalogue()


@lru_cache(maxsize=5000)
def _key(text):
    return re.sub(r"[\W_]", "", normalize("NFKC", text).casefold())


def _one_edit(a, b):
    """One insertion, deletion, substitution or adjacent transposition."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    for i, char in enumerate(a):
        if char != b[i]:
            if len(a) != len(b):
                return a[i:] == b[i + 1 :]
            return a[i + 1 :] == b[i + 1 :] or (
                a[i : i + 2] == b[i : i + 2][::-1] and a[i + 2 :] == b[i + 2 :]
            )
    return True


def suggestions(query):
    query = query.strip() if isinstance(query, str) else ""
    if not 2 <= len(query) <= 60 or not _key(query):
        raise ValueError("请填写 2 至 60 字的药名或包装上的名称")
    key = _key(query)
    names, status, checked = catalogue.current()
    results = []
    for name, page in names.items():
        target = _key(name)
        if target == key:
            rank = 0
        elif target.startswith(key):
            rank = 1
        elif key in target:
            rank = 2
        elif len(key) >= 3 and _one_edit(key, target):
            rank = 3
        elif (
            len(target) >= 3
            and key.startswith(target)
            and key[len(target) :] in ("片", "片剂", "胶囊", "颗粒", "注射液")
        ):
            rank = 4
        else:
            continue
        results.append((rank, len(target), name, page))
    matches = [
        {"name": name, "page": page, "match": "相似写法" if rank >= 3 else "目录药名"}
        for rank, _, name, page in sorted(results)[:8]
    ]
    return {
        "status": status,
        "checkedAt": checked,
        "source": SOURCE,
        "matches": matches,
    }
