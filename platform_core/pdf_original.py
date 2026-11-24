"""Read protected PDF originals through bounded Poppler processes over standard input."""

import re
import shutil
import subprocess
from threading import BoundedSemaphore

PAGE_LIMIT = 1000
_workers = BoundedSemaphore(2)


def _poppler(raw, args):
    if not raw.startswith(b"%PDF-") or len(raw) > 8 * 1024 * 1024:
        raise ValueError("请选择 8 MiB 以内的 PDF 原件")
    binary = shutil.which(args[0])
    if not binary:
        raise ValueError(
            "机构服务器缺少 Poppler PDF 组件，请联系管理员安装 poppler-utils"
        )
    command = [binary, *args[1:]]
    limits = shutil.which("prlimit")
    if limits:
        command = [limits, "--as=536870912", "--cpu=12", "--", *command]
    if not _workers.acquire(timeout=2):
        raise ValueError("其他 PDF 正在读取，请稍后重试")
    try:
        result = subprocess.run(
            command,
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            env={"LC_ALL": "C"},
        )
    except (subprocess.TimeoutExpired, OSError):
        raise ValueError("读取 PDF 超时或组件不可用，请检查原件") from None
    finally:
        _workers.release()
    if result.returncode:
        raise ValueError("无法读取 PDF，请核对文件完整性并移除打开密码")
    return result.stdout


def pages(raw):
    info = _poppler(raw, ["pdfinfo", "-"])
    count = re.findall(rb"^Pages:[ \t]+(\d+)[ \t]*$", info, re.M)
    if len(count) != 1 or re.search(rb"^Encrypted:\s+yes", info, re.M):
        raise ValueError("无法核实 PDF 页数，请移除文件加密后重新选择")
    total = int(count[0])
    if not 1 <= total <= PAGE_LIMIT:
        raise ValueError("每份 PDF 支持 1 至 1000 页")
    return total


def render_page(raw, page):
    if not 1 <= page <= PAGE_LIMIT:
        raise ValueError("PDF 页码无效")
    png = _poppler(
        raw,
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            "-scale-to",
            "1200",
            "-png",
            "-",
        ],
    )
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("无法生成该页预览，请下载原件核对")
    return png
