"""把用户丢进来的文件读成文字（或识别成图片），供 AI 提取使用。

支持：图片、PDF、Word(.docx)、Excel(.xlsx/.xlsm)、CSV/TSV、纯文本。
不依赖第三方库的：docx（zipfile+正则）、文本；xlsx 用 openpyxl（已有依赖）；
PDF 用 pypdf（纯 Python，轻量，已加入 requirements）。
"""
import csv
import io
import re
import zipfile
from html import unescape
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".text"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_CHARS = 40000          # 单份文件喂给模型的上限，够放几十家公司的招聘信息


def file_kind(path: Path) -> str:
    """image / pdf / docx / sheet / text / other"""
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext in {".xlsx", ".xlsm"}:
        return "sheet"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def mime_of(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(ext, "image/png")


def read_text(path: Path, max_chars: int = MAX_CHARS) -> str:
    """读成纯文本；读不出来返回空串（调用方据此提示用户）"""
    kind = file_kind(path)
    if kind == "image":
        return ""
    try:
        if kind == "pdf":
            text = _pdf_text(path)
        elif kind == "docx":
            text = _docx_text(path)
        elif kind == "sheet":
            text = _sheet_text(path)
        elif kind == "text":
            text = _plain_text(path)
        else:
            text = _plain_text(path)      # 未知后缀也试着按文本读
    except Exception as e:                # 文件损坏 / 加密 / 依赖缺失
        raise ValueError(f"{path.name} 读不出来：{e}") from e
    text = _tidy(text)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（{path.name} 内容过长，已截断）"
    return text


def _tidy(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _plain_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _docx_text(path: Path) -> str:
    """Word 正文：zip 里的 word/document.xml，按段落切"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = xml.replace("<w:tab/>", "\t").replace("<w:br/>", "\n").replace("</w:p>", "\n")
    xml = re.sub(r"<w:tc[ >]", "\t<w:tc ", xml)          # 表格单元格用 Tab 隔开
    text = re.sub(r"<[^>]+>", "", xml)
    return unescape(text)


def _sheet_text(path: Path) -> str:
    """Excel：每个工作表转成 TSV 段落，保留表头，模型看得懂"""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    chunks = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                rows.append("\t".join(cells).rstrip("\t"))
        if rows:
            chunks.append(f"# 工作表：{ws.title}\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(chunks)


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("缺少 pypdf，无法读取 PDF（pip install pypdf）") from e
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise ValueError("PDF 有密码，读不了") from e
    pages = []
    for page in reader.pages[:40]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def csv_to_text(path: Path) -> str:
    text = _plain_text(path)
    reader = csv.reader(io.StringIO(text))
    return "\n".join("\t".join(r) for r in reader)
