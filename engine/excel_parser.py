"""Excel / CSV 收件人解析 + 模板生成

设计要点：
- 四列是核心（序号/公司名称/收件人邮箱/邮件主题），其余任意列都变成变量，
  例如加一列「岗位」，正文里就能写 {岗位}。
- 一个单元格写多个邮箱（逗号/分号/顿号分隔）会拆成多封独立邮件，
  而不是塞进同一个 To —— 两个 HR 不该互相看到对方地址。
- 支持 .xlsx/.xlsm/.csv，CSV 自动识别 UTF-8 / GBK 与分隔符。
"""
import csv
import io
import re
from dataclasses import dataclass, field
from typing import List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# 表头别名 → 核心列。用户表格五花八门，认宽一点比报错强。
ALIASES = {
    "序号":       {"序号", "编号", "no", "no.", "#"},
    "公司名称":   {"公司名称", "公司", "公司名", "企业名称", "企业", "单位", "单位名称", "雇主"},
    "收件人邮箱": {"收件人邮箱", "邮箱", "邮件", "email", "e-mail", "收件邮箱", "投递邮箱", "邮件地址"},
    "邮件主题":   {"邮件主题", "主题", "标题", "subject", "邮件标题"},
}

# 邮箱：宽松但要求有域名点和合法字符；同时接受 "张三 <a@b.com>"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_ANGLE = re.compile(r"<([^<>]+)>")
_SPLIT = re.compile(r"[,;、，；/\s]+")

MAX_ROWS = 2000  # 一次投递超过这个数量基本是爬来的名单，防止误操作

thin_border = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin'),
)
header_fill = PatternFill(start_color="1A4B8C", end_color="1A4B8C", fill_type="solid")
header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
body_font = Font(name="微软雅黑", size=10)


@dataclass
class Recipient:
    seq: int
    company: str
    email: str
    subject: str = ""
    vars: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"seq": self.seq, "company": self.company, "email": self.email,
                "subject": self.subject, "vars": self.vars}


@dataclass
class ParseResult:
    recipients: List[Recipient]
    errors: List[str]
    warnings: List[str] = field(default_factory=list)


def generate_template() -> bytes:
    """生成 Excel 模板（含示例行 + 说明页）"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "收件人列表"

    cols = ["序号", "公司名称", "收件人邮箱", "邮件主题", "应聘岗位"]
    widths = [8, 26, 32, 42, 20]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    for col_idx, name in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    example = [1, "示例公司", "hr@example.com", "实习申请-{姓名}-{学校}-{应聘岗位}", "数据分析实习生"]
    for col_idx, val in enumerate(example, 1):
        cell = ws.cell(row=2, column=col_idx, value=val)
        cell.font = body_font
        cell.alignment = Alignment(horizontal="center" if col_idx == 1 else "left", vertical="center")
        cell.border = thin_border

    guide = wb.create_sheet("填写说明")
    lines = [
        ("必填 / 选填", "列名"),
        ("必填", "公司名称、收件人邮箱"),
        ("选填", "序号（可留空，自动编号）、邮件主题（留空则用「正文」页的主题模板）"),
        ("自由扩展", "右侧任何额外的列都会变成变量。例如加一列「HR」，正文和主题里就能写 {HR}。"),
        ("多个邮箱", "一个单元格写多个邮箱请用逗号分隔，程序会拆成多封独立邮件，不会互相看到地址。"),
        ("变量写法", "{公司名} {姓名} {学校} {专业} {年级} {电话} {邮箱} {应聘岗位} {HR} ..."),
        ("提示", "先点「发送」页的「测试发给自己」，确认排版无误再群发。"),
    ]
    for r, (a, b) in enumerate(lines, 1):
        for c, val in enumerate((a, b), 1):
            cell = guide.cell(row=r, column=c, value=val)
            cell.font = header_font if r == 1 else body_font
            if r == 1:
                cell.fill = header_fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    guide.column_dimensions["A"].width = 14
    guide.column_dimensions["B"].width = 90

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _norm_header(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _match_core(header: str):
    h = _norm_header(header)
    # 顺序很重要：邮箱/主题优先于公司，否则「公司邮箱」会被认成公司名称列
    priority = ["收件人邮箱", "邮件主题", "序号", "公司名称"]
    for core in priority:
        if h in {n.lower() for n in ALIASES[core]}:
            return core
    # 带「邮箱 / email / 邮件地址」字样的列一律是邮箱列
    if any(k in h for k in ("邮箱", "email", "e-mail", "邮件地址")):
        return "收件人邮箱"
    for core in priority:
        if any(n.lower() in h for n in ALIASES[core] if len(n) >= 2):
            return core
    return None


def _split_emails(raw: str):
    """从单元格里取出所有邮箱，允许 `张三 <a@b.com>` 和多种分隔符"""
    found = []
    if not raw:
        return found
    for token in _SPLIT.split(str(raw).replace("\n", ",")):
        token = token.strip().strip("<>()（）[]【】")
        if not token:
            continue
        m = _ANGLE.search(token)
        if m:
            token = m.group(1).strip()
        if "@" not in token:
            continue
        token = token.lower()
        if _EMAIL.match(token):
            found.append(token)
        else:
            found.append(f"!{token}")  # ! 前缀 = 非法，交给上层记错误
    return found


def _read_rows(file_bytes: bytes, filename: str):
    """返回 (rows, 错误列表)；rows 是 list[list[str]]"""
    name = (filename or "").lower()
    if name.endswith(".xls") and not name.endswith(".xlsx"):
        return [], ["旧版 .xls 不支持，请在 Excel 里「另存为」.xlsx 或 .csv 后再上传"]
    if name.endswith(".csv") or name.endswith(".txt"):
        text = None
        for enc in ("utf-8-sig", "gb18030", "utf-16"):
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return [], ["CSV 编码无法识别，请另存为 UTF-8 或 xlsx"]
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [row for row in csv.reader(io.StringIO(text), dialect)], []

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        return [], [f"无法打开 Excel 文件：{e}"]
    ws = wb.active
    if ws is None:
        return [], ["Excel 里没有工作表"]
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(["" if v is None else str(v) for v in row])
    wb.close()
    return rows, []


def parse_table(rows, filename: str = "") -> ParseResult:
    errors, warnings, recipients = [], [], []
    seen = {}          # email -> 公司名，用于批内去重

    if not rows:
        return ParseResult([], ["文件是空的"])

    # 找表头：前 10 行里第一行能认出「邮箱」列的
    header_idx, col_map = None, {}
    for i, row in enumerate(rows[:10]):
        mapping = {}
        for idx, cell in enumerate(row):
            core = _match_core(cell)
            if core and core not in mapping:
                mapping[core] = idx
        if "收件人邮箱" in mapping:
            header_idx, col_map = i, mapping
            break

    if header_idx is None:
        return ParseResult([], [
            "找不到表头。第一行需要包含「公司名称」和「收件人邮箱」；"
            "列名支持：公司/单位/企业、邮箱/邮件/email。"
        ])

    if "公司名称" not in col_map:
        warnings.append("没有识别到「公司名称」列，公司名将留空（正文里的 {公司名} 会是空）")

    header_row = rows[header_idx]
    # 其余列 → 自定义变量
    extra_cols = {}
    for idx, cell in enumerate(header_row):
        name = str(cell or "").strip()
        if not name or idx in col_map.values():
            continue
        if name in extra_cols:          # 同名列只保留第一列
            continue
        extra_cols[name] = idx

    data_rows = rows[header_idx + 1:]
    if len([r for r in data_rows if any(str(c).strip() for c in r)]) == 0:
        return ParseResult([], ["表头下面没有数据行"])

    def cell(row, idx):
        return str(row[idx]).strip() if idx is not None and idx < len(row) else ""

    for row_no, row in enumerate(data_rows, header_idx + 2):
        if row_no - header_idx - 1 > MAX_ROWS:
            warnings.append(f"数据超过 {MAX_ROWS} 行，只解析了前 {MAX_ROWS} 行")
            break
        if not any(str(c).strip() for c in row):
            continue

        company = cell(row, col_map.get("公司名称"))
        email_raw = cell(row, col_map.get("收件人邮箱"))
        subject = cell(row, col_map.get("邮件主题"))

        if not company and not email_raw:
            continue
        if not email_raw:
            errors.append(f"第{row_no}行：{company or '（无公司名）'} 没有填邮箱，已跳过")
            continue

        emails = _split_emails(email_raw)
        bad = [e[1:] for e in emails if e.startswith("!")]
        good = [e for e in emails if not e.startswith("!")]
        for b in bad:
            errors.append(f"第{row_no}行：邮箱「{b}」格式不正确，已跳过该地址")
        if not good:
            errors.append(f"第{row_no}行：{company or '（无公司名）'} 没有可用邮箱，已跳过")
            continue

        vars_ = {}
        for name, idx in extra_cols.items():
            val = cell(row, idx)
            if val:
                vars_[name] = val

        for addr in good:
            if addr in seen:
                errors.append(
                    f"第{row_no}行：{addr} 与「{seen[addr]}」重复，已忽略（避免重复投递）")
                continue
            seen[addr] = company or "上一行"

            seq_raw = cell(row, col_map.get("序号"))
            try:
                seq = int(float(seq_raw))
            except (ValueError, TypeError):
                seq = len(recipients) + 1

            recipients.append(Recipient(seq, company, addr, subject, dict(vars_)))

    return ParseResult(recipients, errors, warnings)


def parse_workbook(file_bytes: bytes, filename: str = "") -> ParseResult:
    rows, errs = _read_rows(file_bytes, filename)
    if errs:
        return ParseResult([], errs)
    return parse_table(rows, filename)


def parse_tsv(text: str) -> ParseResult:
    """从 Excel 直接复制粘贴（制表符分隔）或手打的一列邮箱"""
    lines = [l for l in (text or "").replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        return ParseResult([], ["粘贴的内容是空的"])
    rows = []
    for line in lines:
        if "\t" in line:
            rows.append(line.split("\t"))
        else:
            # 只有邮箱的一行：公司名留空
            rows.append(["", line.strip()])
    # 没有表头时补一个
    if not any(_match_core(c) for c in rows[0]):
        rows.insert(0, ["公司名称", "收件人邮箱"] if len(rows[0]) >= 2 else ["收件人邮箱"])
    return parse_table(rows, "paste.tsv")

