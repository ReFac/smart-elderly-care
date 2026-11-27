"""Recover unreadable report text from a second rendering of the same page."""

from io import BytesIO
import re
from threading import BoundedSemaphore
import unicodedata

from . import ocr_review

_MIN_EDGE = 160
_MAX_EDGE = 1440
_render_slots = BoundedSemaphore(2)
_CT = re.compile(r"(?<![A-Za-z])CT(?![A-Za-z])", re.I)
_NODULE = re.compile(r"(?:肺(?:部|内)?)?结节(?:影|灶)?")
_NEGATED = re.compile(r"未见|未发现|未显示|未检出|无|排除")
_ZERO_NODULES = re.compile(r"结节数量\s*:\s*(?:0\s*枚|0$|无)")
_CLAUSES = re.compile(r"[。；;\n]")
_UNIT_SIZE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d+)?\s*(?:mm|cm|毫米|厘米)(?![A-Za-z])", re.I)
_OTHER_MEASUREMENT = re.compile(r"[，,]\s*(?!结节)(?:胸腔积液|淋巴结|肝脏|主动脉|血管|心脏|气管)")
_SIZE_HEADING = re.compile(r"^\s*(?:[-#]+\s*)?(?:结节(?:大小|尺寸|最大径)|最大(?:直径|径))\s*:", re.M)
_IDENTITY = {
    "name": r"(?:患者姓名|患者名字|姓名)\s*:\s*([a-z\u3400-\u9fff·'-]{2,})",
    "report": r"(?:检查编号|报告编号|检查号|报告号)\s*:\s*([a-z\d]+(?:[-/][a-z\d]+)*)",
    "date": r"(?:检查日期|检查时间)\s*:\s*(\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2})",
}
_CITED_SECTIONS = re.compile(rf"^(?:{'|'.join((*ocr_review.FINDINGS, *ocr_review.IMPRESSION, *ocr_review.OBSERVATIONS))})\s*:")


def _text(lines):
    return unicodedata.normalize("NFKC", "\n".join(line["text"] for line in lines)).replace("**", "").replace("__", "")


def _squash(text):
    return re.sub(r"[\s#*|]", "", text).casefold()


def anchors(lines):
    """Retain only identity anchors from a truncated first receipt for comparison."""
    text = _text(lines[:128])[:16000].casefold()
    result = {}
    for key, pattern in _IDENTITY.items():
        hits = re.findall(pattern, text)
        if key == "date":
            hits = ["-".join(f"{int(part):02}" for part in re.findall(r"\d+", value)) for value in hits]
        if hits:
            result[key] = sorted({_squash(value) for value in hits})
    return result


def _nodule_size(text):
    if not (_CT.search(text) and ocr_review.REPORT_TITLE.search(text)):
        return False, False
    clauses = _CLAUSES.split(text)
    positive = [
        _OTHER_MEASUREMENT.split(clause[match.start():], maxsplit=1)[0] for clause in clauses
        if (match := _NODULE.search(clause)) and not _NEGATED.search(clause[:match.start()])
        and not _ZERO_NODULES.search(clause)
    ]
    size_sections = [clause for clause in clauses if _SIZE_HEADING.match(clause)]
    return bool(positive or size_sections), any(_UNIT_SIZE.search(clause) for clause in (*positive, *size_sections))


def missing_nodule_size(lines):
    present, measured = _nodule_size(_text(lines))
    return present and not measured


def needed(result):
    return any(page["state"] in ("blank", "partial") for page in result["pages"]) or missing_nodule_size(result["lines"])


def preferred(original, enhanced):
    if enhanced["state"] != "recognized" or enhanced["pages"][0]["state"] != "complete":
        return False
    prior_identity = original.get("_recoveryAnchors") or anchors(original["lines"])
    new_identity = anchors(enhanced["lines"])
    if any(values != new_identity.get(key) for key, values in prior_identity.items()):
        return False
    if not original["lines"]:
        return True
    recovered = _text(enhanced["lines"])
    if not _nodule_size(recovered)[1]:
        return False
    # Preserve values already readable from the first pass, including negative findings.
    normalized = _squash(recovered)
    return all(_squash(line.rstrip("。；; ")) in normalized for line in _text(original["lines"]).splitlines()
               if _CITED_SECTIONS.match(line.strip(" #|")))


def enhanced_png(raw):
    """Increase contrast and alter resolution without rotating or cropping the original."""
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return None

    with _render_slots:
        try:
            with Image.open(BytesIO(raw)) as source:
                if min(source.size) < _MIN_EDGE or source.width * source.height > 20_000_000:
                    return None
                gray = source.convert("L")
            low, high = gray.getextrema()
            if low == high:
                return None
            gray = ImageOps.autocontrast(gray, cutoff=1)
            scale = min(2, _MAX_EDGE / max(gray.size))
            size = tuple(max(1, round(edge * scale)) for edge in gray.size)
            gray = gray.resize(size, Image.Resampling.LANCZOS)
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=85, threshold=3))
            output = BytesIO()
            gray.save(output, format="PNG")
            return output.getvalue()
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
