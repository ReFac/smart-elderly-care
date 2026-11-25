"""Translate one registration worksheet into reviewable drafts or produce an editable XLSX."""

import asyncio
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import sys
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from zipfile import BadZipFile, ZipFile

from .. import access, profile_fields
from . import document_intake, resident_profile_intake

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_FILE = 8 * 1024 * 1024
MAX_ROWS = 500
MAX_COLUMNS = 64
_SHEET = "长辈登记"
_COLUMNS = {
    "name": ("姓名", "长辈姓名", "老人姓名"),
    "birthDate": ("出生日期", "生日", "出生年月日"),
    "phone": ("联系电话", "手机号", "手机号码", "电话"),
    "language": ("常用语言", "语言"),
    "maritalStatus": ("婚姻状况", "婚姻状态"),
    "education": ("文化程度", "学历"),
    "occupation": ("原职业", "职业"),
    "addressRegion": ("现住址", "现居住址", "现居地址"),
    "birthRegion": ("出生地", "出生地点"),
    "nativeRegion": ("籍贯",),
}
_EN_COLUMNS = {
    "name":"Full name", "birthDate":"Date of birth", "phone":"Phone number",
    "language":"Preferred language", "maritalStatus":"Marital status", "education":"Education",
    "occupation":"Occupation", "address":"Postal address", "birthplace":"Place of birth", "nativePlace":"Place of origin",
}
_ALIASES = {name.casefold(): key for key, labels in _COLUMNS.items() for name in (*labels, key)}
_ALIASES.update({label.casefold(): key for key, label in _EN_COLUMNS.items()})
_SHEETS = (_SHEET, "Resident registration")
_ENUMS = {"Mandarin":"普通话","English":"英语","French":"法语","Spanish":"西班牙语","Married":"已婚",
          "Single":"未婚","Widowed":"丧偶","Divorced":"离异","Other":"其他","Pending verification":"待核实",
          "Primary school":"小学","Bachelor's degree":"本科","Retired":"已退休"}
_SLOTS = BoundedSemaphore(2)


def authorize(store, token):
    with closing(store.connect()) as db:
        actor = document_intake.authorize(store, db, token)
        access.require(actor, "intake")
        if not {"dossier", "residents"}.intersection(actor["routes"]):
            raise PermissionError("当前账号没有长辈档案入口")


def _value(key, raw, *, international=False):
    if isinstance(raw, (datetime, date)):
        raw = raw.strftime("%Y-%m-%d")
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    value = str(raw).strip()
    if not value:
        return ""
    if len(value) > 120 or value.startswith(("=", "@", "-")) or any(ord(c) < 32 for c in value):
        raise ValueError("请填写普通文本")
    if key.endswith("Region"):
        value = resident_profile_intake.region(value, birthplace=key != "addressRegion")
        if not value:
            raise ValueError("请核对行政区划")
        return value
    if key == "birthDate":
        return date.fromisoformat(value.replace("/", "-")).isoformat()
    if key == "phone":
        value = profile_fields.phone_number(value, mobile=True)
        if not value:
            raise ValueError("请核对手机号码")
    elif value.startswith("+"):
        raise ValueError("请填写普通文本")
    if international:
        value = _ENUMS.get(value, value) if key in ("language", "maritalStatus", "education", "occupation") else value
    if key in ("language", "maritalStatus", "education", "occupation") and value not in profile_fields.catalog("dossier-choices")[key]:
        raise ValueError("请在档案选项中核对")
    return value


def _xlsx_rows(raw):
    from openpyxl import load_workbook

    with ZipFile(BytesIO(raw)) as package:
        entries = package.infolist()
        if len(entries) > 256 or sum(item.file_size for item in entries) > 24 * 1024 * 1024:
            raise ValueError("表格内容过大，请拆分后再上传")
        if any("vbaproject" in item.filename.lower() or "externallinks/" in item.filename.lower()
               or item.flag_bits & 1 or ".." in PurePosixPath(item.filename).parts for item in entries):
            raise ValueError("请选择普通的无宏工作簿")
    book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    try:
        sheets = [sheet for sheet in book.worksheets if sheet.sheet_state == "visible"]
        sheet = next((s for s in sheets if s.title in _SHEETS), None)
        if sheet is None:
            if len(sheets) != 1:
                raise ValueError("多工作表文件请把登记页命名为「长辈登记」或「Resident registration」")
            sheet = sheets[0]
        if (sheet.max_row or 0) > MAX_ROWS+1 or (sheet.max_column or 0) > MAX_COLUMNS:
            raise ValueError("请移除多余行列，或分批导入登记表")
        sheet.reset_dimensions()  # Some non-Excel writers declare an empty or incorrect used range.
        for row in sheet.iter_rows(max_col=MAX_COLUMNS+1):
            if row[-1].value is not None:
                raise ValueError("登记表列数过多")
            yield [cell.value for cell in row[:-1]]
    finally:
        book.close()


def _xls_rows(raw):
    import xlrd

    book = xlrd.open_workbook(file_contents=raw, on_demand=True)
    try:
        names = book.sheet_names()
        title = next((s for s in names if s in _SHEETS), None)
        if title is None and len(names) != 1:
            raise ValueError("多工作表文件请把登记页命名为「长辈登记」或「Resident registration」")
        sheet = book.sheet_by_name(title) if title else book.sheet_by_index(0)
        if sheet.nrows > MAX_ROWS+1 or sheet.ncols > MAX_COLUMNS:
            raise ValueError("请移除多余行列，或分批导入登记表")
        for i in range(sheet.nrows):
            yield [xlrd.xldate_as_datetime(cell.value, book.datemode) if cell.ctype == xlrd.XL_CELL_DATE
                   else cell.value for cell in sheet.row(i)]
    finally:
        book.release_resources()


def preview(raw, *, international=False):
    if len(raw) > MAX_FILE:
        raise ValueError("请选择 8 MiB 以内的工作簿")
    if raw.startswith(b"PK\x03\x04"):
        rows = _xlsx_rows(raw)
    elif raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        rows = _xls_rows(raw)
    else:
        raise ValueError("请选择真实的 XLS 或 XLSX 工作簿")
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("工作表正在处理，请稍后重试")
    try:
        header = next(rows, [])
        keys = [_ALIASES.get(str(v).strip().casefold()) for v in header]
        supported = _EN_COLUMNS if international else _COLUMNS
        keys = [key if key in supported else None for key in keys]
        known = [key for key in keys if key]
        if not known or len(set(known)) != len(known):
            raise ValueError("第一行需包含唯一的登记字段，例如姓名、出生日期、联系电话")
        records = []
        for n, row in enumerate(rows, start=2):
            if n > MAX_ROWS+1:
                raise ValueError("请将登记表拆分为每次最多 500 行")
            fields, ambiguous = {}, []
            for key, value in zip(keys, row):
                if key and value is not None and str(value).strip():
                    try:
                        fields[key] = _value(key, value, international=international)
                    except (ValueError, OverflowError):
                        ambiguous.append(key)
            if fields or ambiguous:
                labels = {key: profile_fields.address_fields(value, birthplace=key != "addressRegion")[1]
                          for key, value in fields.items() if key.endswith("Region")}
                records.append({"row": n, "fields": fields, "ambiguous": ambiguous, "labels": labels})
        return {"category": "电子表格", "records": records, "note": f"读到 {len(records)} 行长辈资料，请逐位核对。"}
    except ImportError as err:
        raise ValueError("机构尚未安装表格服务组件") from err
    except ValueError:
        raise
    except Exception as err:
        raise ValueError("工作簿无法读取，请检查格式或另存为 XLSX") from err
    finally:
        rows.close()
        _SLOTS.release()


async def _fill(folder, values, sheet_name=_SHEET):
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import excel_mcp

    runtime = str(Path(excel_mcp.__file__).resolve().parent.parent)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "excel_mcp", "stdio", "--allow-dir", folder, "--tools", "workbooks,data",
              "--max-file-mb", "8", "--max-cells", "1024"],
        cwd=folder,
        env={"PYTHONPATH": runtime, "HOME": folder, "PATH": os.defpath,
             "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"},
    )
    filename = "registration.xlsx"
    with open(os.devnull, "w") as errors:
        async with asyncio.timeout(20), Client(
            stdio_client(params, errlog=errors), read_timeout_seconds=15, cache=None,
        ) as client:
            for tool, args in (
                ("create_workbook", {"path": filename, "sheets": [sheet_name]}),
                ("write_range", {"path": filename, "sheet": sheet_name, "at": "A1", "rows": values}),
            ):
                result = await client.call_tool(tool, args)
                if result.is_error:
                    raise ValueError("工作表生成失败，请重新尝试")
    return (Path(folder) / filename).read_bytes()


def export(fields, *, international=False):
    columns = _EN_COLUMNS if international else {k: v[0] for k,v in _COLUMNS.items()}
    if not isinstance(fields, dict) or fields.keys() - columns.keys():
        raise ValueError("工作表包含未支持的字段")
    values = [list(columns.values())]
    if fields:
        row = []
        for key in columns:
            raw = fields.get(key)
            if raw and key.endswith("Region"):
                region, _ = profile_fields.address_fields(raw, birthplace=key != "addressRegion")
                parent, parts = "CN", []
                for code in region["codes"]:
                    parts.append(profile_fields.region_children(parent)[code])
                    parent = code
                row.append(" · ".join(filter(None, [*parts, region.get("unlisted"), region["detail"]])))
            elif raw and not isinstance(raw, str):
                raise ValueError("工作表字段格式错误")
            else:
                value = _value(key, raw, international=international) if raw else None
                if international and key in ("language","maritalStatus","education","occupation"):
                    value = next((en for en, stored in _ENUMS.items() if value == stored), value)
                row.append(value)
        values.append(row)
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("工作表正在处理，请稍后重试")
    try:
        memory_dir = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None
        with TemporaryDirectory(prefix="nh-sheet-", dir=memory_dir) as folder:
            return asyncio.run(_fill(folder, values, _SHEETS[1] if international else _SHEET))
    except (ImportError, OSError, TimeoutError, ExceptionGroup) as err:
        raise ValueError("Excel MCP 服务暂不可用，请检查机构表格组件") from err
    finally:
        _SLOTS.release()
