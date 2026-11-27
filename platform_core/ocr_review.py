"""Review cues based on OCR text and receipt status, without interpreting a scan."""

import re
import unicodedata


REPORT_TITLE = re.compile(r"(?:CT|MRI?|磁共振|放射|影像)[^\n。；:：]{0,14}报告", re.I)
FINDINGS = ("检查所见", "影像所见", "影像表现", "检查描述", "影像描述", "扫描所见", "扫描描述", "所见")
IMPRESSION = ("影像结论", "影像诊断", "放射学诊断", "诊断意见", "影像学印象", "影像印象", "影像提示",
              "检查结论", "印象", "结论", "诊断")
# These count as findings when the original uses labelled measurements instead of prose.
OBSERVATIONS = ("结节数量", "最大直径", "结节大小", "病灶位置", "病灶大小", "胸腔积液", "测量值", "CT值")
ADMIN = ("检查日期", "检查编号", "检查方式", "检查部位", "检查项目", "检查方法", "报告日期",
         "报告医师", "审核医师", "患者姓名", "姓名", "性别", "年龄")
LABELS = "|".join((*FINDINGS, *IMPRESSION, *OBSERVATIONS, *ADMIN))
HEADINGS = re.compile(rf"({LABELS})[ \t]*:|^[#| \t]*({LABELS})[ \t]*$", re.I | re.M)
EMPTY = {"", "待核对", "待填写", "未填写", "待补充", "不详", "待核实"}


def _report_gaps(lines, incomplete):
    if not any(REPORT_TITLE.search(unicodedata.normalize("NFKC", line["text"])) for line in lines):
        return []
    readable = "\n".join(line["text"] for line in lines if line.get("page") not in incomplete)
    text = unicodedata.normalize("NFKC", readable)
    text = text.replace("**", "").replace("__", "")
    headings = list(HEADINGS.finditer(text))
    filled, empty = set(), set()
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        value = text[heading.end():end].strip(" \n\t|#_*:：-—.…/[]")
        (empty if value in EMPTY else filled).add(heading[1] or heading[2])
    missing = []
    if not filled.intersection((*FINDINGS, *OBSERVATIONS)):
        missing.append("检查所见")
    if not filled.intersection(IMPRESSION):
        missing.append("影像结论")
    missing.extend(label for label in OBSERVATIONS if label in empty)
    return missing


def quality(result, image_size=None):
    warnings = []
    if image_size and min(image_size) < 480:
        width, height = image_size
        warnings.append(f"原图为 {width} × {height} 像素，细小文字可能漏读。请放大核对，必要时上传清晰原件。")
    for state, issue in (("partial", "识别中断"), ("blank", "未读到文字")):
        pages = [str(page["page"]) for page in result.get("pages", ()) if page["state"] == state]
        if pages:
            listed = "、".join(pages[:12]) + (" 等" if len(pages) > 12 else "")
            warnings.append(f"第 {listed} 页{issue}，请对照这些页的原件手工补录。")
    incomplete = {page["page"] for page in result.get("pages", ()) if page["state"] != "complete"}
    missing = _report_gaps(result.get("lines", ()), incomplete)
    if missing:
        labels = "、".join(f"「{label}」" for label in missing)
        warnings.append(f"影像报告的{labels}未读到可核对的文字。请对照原报告手工摘录。")
    return {"reviewWarnings": warnings, "manualReportReview": bool(missing)}
