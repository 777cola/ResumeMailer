"""离线自检 — 不联网、不发信，覆盖解析 / 渲染 / MIME / 限速 / 取消

用法：python tests/test_selftest.py
任何一条挂了，说明改坏了真实发送路径。
"""
import io
import smtplib
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

import engine.sender as sender
from engine.excel_parser import parse_table, parse_tsv, generate_template, parse_workbook
from engine.render import render_email, unknown_placeholders, to_html


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_basic_and_vars():
    data = _xlsx([
        ["公司名称", "收件人邮箱", "邮件主题", "岗位"],
        ["华泰资产", "HR@HTAsset.com", "实习申请-{姓名}-{岗位}", "量化研究"],
        ["中信证券", "hr@citics.com", "", "行研"],
    ])
    res = parse_workbook(data, "t.xlsx")
    assert len(res.recipients) == 2, res.errors
    r0 = res.recipients[0]
    assert r0.email == "hr@htasset.com", "邮箱应小写"
    assert r0.vars["岗位"] == "量化研究"
    assert r0.subject.startswith("实习申请")


def test_parse_multi_email_splits():
    data = _xlsx([
        ["公司", "邮箱"],
        ["某公司", "a@x.com；b@y.com、c@z.com"],
    ])
    res = parse_workbook(data, "t.xlsx")
    assert len(res.recipients) == 3, [r.email for r in res.recipients]
    assert len({r.email for r in res.recipients}) == 3


def test_parse_dedupes():
    data = _xlsx([
        ["公司", "邮箱"],
        ["A", "hr@same.com"],
        ["B", "hr@same.com"],
    ])
    res = parse_workbook(data, "t.xlsx")
    assert len(res.recipients) == 1
    assert any("重复" in e for e in res.errors)


def test_parse_header_aliases_and_offset_header():
    data = _xlsx([
        ["2026 秋招投递表"],
        ["单位", "投递邮箱", "标题"],
        ["某基金", "hr@fund.com", "应聘-研究"],
    ])
    res = parse_workbook(data, "t.xlsx")
    assert len(res.recipients) == 1
    assert res.recipients[0].company == "某基金"


def test_parse_tsv_paste():
    res = parse_tsv("公司\t邮箱\nA公司\ta@a.com\nB公司\tb@b.com")
    assert len(res.recipients) == 2


def test_template_downloads():
    content = generate_template()
    assert content[:2] == b"PK"
    wb = openpyxl.load_workbook(io.BytesIO(content))
    assert "填写说明" in wb.sheetnames


def test_render_subject_and_body():
    user = {"姓名": "戚俊皓", "学校": "华东理工", "专业": "金融"}
    r = {"company": "某公司", "email": "a@b.com", "subject": "实习-{姓名}-{岗位}",
         "vars": {"岗位": "量化"}}
    out = render_email(r, user, "你好 {公司名}，我是{姓名}。", "实习申请-{姓名}")
    assert out["subject"] == "实习-戚俊皓-量化", out["subject"]
    assert out["body"] == "你好 某公司，我是戚俊皓。"
    assert "戚俊皓" in out["html"]


def test_render_unknown_kept():
    out = render_email({"company": "A", "email": "a@b.com"}, {},
                       "你好 {不存在的变量}", "{姓名}")
    assert "{不存在的变量}" in out["body"]
    assert unknown_placeholders(out["body"], {}) == ["不存在的变量"]


def test_html_escaping():
    html = to_html("a<b> & c\nd")
    assert "&lt;b&gt;" in html and "&amp;" in html and "<br>" in html


def test_message_headers():
    from config import EmailConfig
    cfg = EmailConfig(email="me@qq.com", sender_name="戚俊皓")
    msg = sender.build_message(cfg, "hr@corp.com", "实习申请-戚俊皓",
                               "正文第一行\n第二行", to_html("正文第一行\n第二行"),
                               [], cc_self=True)
    assert msg["Date"], "缺 Date 头"
    assert msg["Message-ID"], "缺 Message-ID 头"
    assert msg.get_content_type() == "multipart/alternative", msg.get_content_type()
    types = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in types and "text/html" in types
    # 中文主题 / 发件人名必须能被标准库解回来
    import email
    from email import policy
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert parsed["Subject"] == "实习申请-戚俊皓", parsed["Subject"]
    assert "戚俊皓" in str(parsed["From"])
    assert parsed["Cc"] == "me@qq.com"


def test_attachment_name_roundtrip():
    import tempfile
    from config import EmailConfig
    tmp = Path(tempfile.mkdtemp()) / "戚俊皓-简历.pdf"
    tmp.write_bytes(b"%PDF-1.4 test")
    msg = sender.build_message(EmailConfig(email="me@qq.com"), "hr@corp.com",
                               "s", "b", "", [str(tmp)])
    import email
    from email import policy
    parsed = email.message_from_bytes(msg.as_bytes(), policy=policy.default)
    names = [p.get_filename() for p in parsed.walk() if p.get_filename()]
    assert names == ["戚俊皓-简历.pdf"], names


def test_imap_utf7():
    assert sender._imap_utf7("Drafts") == "Drafts"
    enc = sender._imap_utf7("草稿箱")
    assert enc.startswith("&") and enc.endswith("-"), enc


def test_send_batch_daily_limit_and_skip():
    class FakeLink:
        sent = []

        def __init__(self, cfg):
            pass

        def send(self, msg):
            FakeLink.sent.append(msg["To"])

        def close(self):
            pass

    orig = sender._SmtpLink
    sender._SmtpLink = FakeLink
    try:
        from config import EmailConfig
        recipients = [{"company": f"C{i}", "email": f"a{i}@x.com"} for i in range(5)]
        out = sender.send_batch(EmailConfig(email="me@qq.com"), recipients,
                                "hi {公司名}", "主题-{公司名}", [],
                                send_mode="send", rate=600, daily_limit=3)
        statuses = [r["status"] for r in out["results"]]
        assert statuses.count("sent") == 3, statuses
        assert statuses.count("skipped") == 2, statuses
        assert "上限" in out["stopped"]
        assert len(FakeLink.sent) == 3
    finally:
        sender._SmtpLink = orig


def test_send_batch_cancel():
    class FakeLink:
        def __init__(self, cfg):
            pass

        def send(self, msg):
            pass

        def close(self):
            pass

    orig = sender._SmtpLink
    sender._SmtpLink = FakeLink
    try:
        from config import EmailConfig
        cancel = threading.Event()
        recipients = [{"company": f"C{i}", "email": f"a{i}@x.com"} for i in range(4)]

        def on_result(r):
            if r["status"] == "sent":
                cancel.set()

        out = sender.send_batch(EmailConfig(email="me@qq.com"), recipients,
                                "hi", "s", [], send_mode="send", rate=600,
                                progress=on_result, cancel=cancel)
        assert out["results"][0]["status"] == "sent"
        assert out["results"][-1]["status"] == "skipped"
        assert out["stopped"] == "已取消"
    finally:
        sender._SmtpLink = orig


def test_dry_run_never_touches_network():
    """试跑只组装消息，不能创建任何连接，也不吃每日额度"""
    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("试跑不应该创建 SMTP/IMAP 连接")

    orig_link, orig_sink = sender._SmtpLink, sender._DraftSink
    sender._SmtpLink = Boom
    sender._DraftSink = Boom
    try:
        from config import EmailConfig
        recs = [{"company": f"C{i}", "email": f"a{i}@x.com"} for i in range(3)]
        out = sender.send_batch(EmailConfig(email="me@qq.com"), recs, "hi {公司名}",
                                "t-{公司名}", [], send_mode="dry", rate=60, daily_limit=1)
        assert [r["status"] for r in out["results"]] == ["dry", "dry", "dry"], out["results"]
        assert all(r["success"] for r in out["results"])
        assert out["stopped"] == ""
    finally:
        sender._SmtpLink, sender._DraftSink = orig_link, orig_sink


def test_job_counters_treat_dry_as_success(monkeypatch=None):
    import engine.jobs as jobs

    class FakeJob(dict):
        pass

    job = FakeJob(id="t", status="running", mode="dry", total=2, done=0, success=0,
                  failed=0, skipped=0, started_at="", finished_at="", error="",
                  stopped="", draft_box="", results=[], cancel=threading.Event())
    orig = jobs.send_batch
    rows = [
        {"company": "A", "email": "a@x.com", "status": "dry", "success": True, "error": "", "subject": "s"},
        {"company": "B", "email": "b@x.com", "status": "dry", "success": True, "error": "", "subject": "s"},
    ]

    def fake_send_batch(**kw):
        progress = kw.get("progress")
        for r in rows:
            if progress:
                progress(r)
        return {"results": rows, "stopped": "", "draft_box": ""}

    jobs.send_batch = fake_send_batch
    try:
        jobs._run(job, None, [], "b", "s", [], 60, {}, 0, False)
    finally:
        jobs.send_batch = orig
    assert job["success"] == 2 and job["failed"] == 0, dict(job)


def test_auth_error_stops_batch():
    class FakeLink:
        def __init__(self, cfg):
            pass

        def send(self, msg):
            raise smtplib.SMTPAuthenticationError(535, b"bad auth")

        def close(self):
            pass

    orig = sender._SmtpLink
    sender._SmtpLink = FakeLink
    try:
        from config import EmailConfig
        recipients = [{"company": "A", "email": "a@x.com"},
                      {"company": "B", "email": "b@x.com"}]
        out = sender.send_batch(EmailConfig(email="me@qq.com"), recipients,
                                "hi", "s", [], send_mode="send", rate=600)
        assert all(r["status"] != "sent" for r in out["results"])
        assert "认证" in out["stopped"], out["stopped"]
    finally:
        sender._SmtpLink = orig


def test_header_company_mail_is_email_column():
    """「公司邮箱」是邮箱列，不能因为含「公司」被认成公司名"""
    data = _xlsx([
        ["公司", "公司邮箱", "主题"],
        ["某基金", "hr@fund.com", "应聘"],
    ])
    res = parse_workbook(data, "t.xlsx")
    assert len(res.recipients) == 1, res.errors
    assert res.recipients[0].company == "某基金", res.recipients[0].company
    assert res.recipients[0].email == "hr@fund.com"


def test_split_display_name():
    data = _xlsx([["公司", "邮箱"], ["A", "王女士 <HR@A.com>, li@a.com"]])
    res = parse_workbook(data, "t.xlsx")
    assert [r.email for r in res.recipients] == ["hr@a.com", "li@a.com"]


def test_csv_gbk():
    raw = "公司,邮箱\n某券商,hr@broker.com\n".encode("gbk")
    res = parse_workbook(raw, "t.csv")
    assert len(res.recipients) == 1, res.errors
    assert res.recipients[0].company == "某券商"


def test_old_xls_rejected():
    res = parse_workbook(b"whatever", "old.xls")
    assert res.recipients == [] and "xls" in res.errors[0]


def test_draft_box_detection():
    """Gmail / 163 的草稿箱名字不同，必须按 LIST 结果挑"""
    class FakeConn:
        def list(self):
            return ("OK", [b'(\\HasNoChildren) "/" "Drafts"',
                           b'(\\HasNoChildren) "/" "&XfJT0ZAB-"'])

    sink = sender._DraftSink(type("C", (), {"imap_host": "x", "imap_port": 993,
                                            "email": "a@b.c", "auth_code": "x"})())
    sink.conn = FakeConn()
    boxes = sink._boxes()
    assert boxes[0] == "Drafts", boxes
    assert any(b.startswith("&") for b in boxes), boxes


def test_html_body_plain_fallback():
    out = render_email({"company": "A", "email": "a@b.com"}, {},
                       "<p>你好</p><p>第二段</p>", "主题")
    assert "你好" in out["body"] and "第二段" in out["body"]
    assert "<p>" not in out["body"], out["body"]
    assert out["html"].startswith("<p>你好</p>"), out["html"]


def test_draft_append_falls_back_to_second_folder():
    """第一个候选箱名不存在时，要接着试下一个，并记住成功的那个"""
    class FakeConn:
        def __init__(self):
            self.calls = []

        def list(self):
            return ("OK", [b'(\\HasNoChildren) "/" "Drafts"',
                           ('(\\HasNoChildren) "/" "%s"' % sender._imap_utf7("草稿箱")).encode()])

        def append(self, name, flags, date, raw):
            self.calls.append(name)
            return ("OK", [b"ok"]) if name.strip('"') == sender._imap_utf7("草稿箱") else ("NO", [b"nope"])

        def logout(self):
            pass

    from config import EmailConfig
    sink = sender._DraftSink(EmailConfig(email="a@b.c", auth_code="x"))
    sink.conn = FakeConn()
    msg = sender.build_message(EmailConfig(email="a@b.c"), "hr@c.com", "s", "b", "", [])
    sink.append(msg)
    assert sink.box == sender._imap_utf7("草稿箱"), sink.box
    assert len(sink.conn.calls) == 2, sink.conn.calls
    # 第二次应直接用缓存成功的箱名
    sink.append(msg)
    assert len(sink.conn.calls) == 3, sink.conn.calls


def test_empty_attachment_list_does_not_fall_back():
    """显式传空附件 = 不发附件，不能回退到上次的简历"""
    import server
    cfg = type("C", (), {"last_attachments": ["/tmp/should_not_be_used.pdf"]})()
    assert server._requested_attachments({"attachments": []}, cfg) == []
    # 缺失字段时才沿用上次选择，并且要校验文件确实存在
    try:
        server._requested_attachments({}, cfg)
    except Exception as e:
        assert "不存在" in str(getattr(e, "detail", e)) or "非法" in str(getattr(e, "detail", e))
    else:
        raise AssertionError("沿用的附件不存在时必须报错，而不是静默发一封没有附件的信")


DSN_RAW = b"""From: Mail Delivery Subsystem <MAILER-DAEMON@qq.com>
To: me@qq.com
Subject: Undelivered Mail Returned to Sender
Date: Wed, 21 Oct 2026 10:00:00 +0800
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset=utf-8

\u4f60\u7684\u90ae\u4ef6\u65e0\u6cd5\u6295\u9012\u3002
--BOUND
Content-Type: message/delivery-status

Reporting-MTA: dns; qq.com
Final-Recipient: rfc822; HR@OldCompany.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 User unknown

--BOUND
Content-Type: text/rfc822-headers

Subject: test
--BOUND--
"""


def _parse(raw):
    from email import policy
    from email.parser import BytesParser
    return BytesParser(policy=policy.default).parsebytes(raw)


def test_parse_dsn():
    from engine.bounce import parse_dsn, looks_like_bounce
    msg = _parse(DSN_RAW)
    assert looks_like_bounce(str(msg["From"]), str(msg["Subject"]))
    rows = parse_dsn(msg)
    assert len(rows) == 1, rows
    assert rows[0]["email"] == "hr@oldcompany.com"
    assert rows[0]["status"] == "5.1.1"
    assert "550" in rows[0]["reason"]


def test_parse_bounce_text_fallback():
    from engine.bounce import parse_bounce_message
    raw = """From: postmaster@163.com
Subject: 无法投递
Content-Type: text/plain; charset=utf-8

\u60a8\u7684\u90ae\u4ef6\u65e0\u6cd5\u6295\u9012\u5230 dead@nowhere.com\uff0c\u8bf7\u68c0\u67e5\u5730\u5740\u3002
""".encode("utf-8")
    rows = parse_bounce_message(_parse(raw), "me@163.com")
    assert [r["email"] for r in rows] == ["dead@nowhere.com"], rows


def test_scan_inbox_with_fake_conn():
    from engine.bounce import scan_inbox
    from config import EmailConfig

    headers = {
        b"1": b"From: HR Wang <hr@good.com>\nSubject: \u9762\u8bd5\u9080\u8bf7\nDate: Wed, 21 Oct 2026 09:00:00 +0800\n\n",
        b"2": DSN_RAW[:600],
        b"3": b"From: Newsletter <news@spam.com>\nSubject: weekly\n\n",
    }

    class FakeConn:
        def select(self, *a, **k):
            return ("OK", [b"1"])

        def search(self, charset, crit):
            return ("OK", [b"1 2 3"])

        def fetch(self, uid, what):
            body = DSN_RAW if uid == b"2" else headers.get(uid, b"")
            return ("OK", [(("x (BODY %d" % len(body)).encode(), body), b")"])

        def logout(self):
            pass

    out = scan_inbox(EmailConfig(email="me@qq.com", auth_code="x"),
                     {"hr@good.com"}, days=14, conn=FakeConn())
    assert out["scanned"] == 3, out
    assert [r["email"] for r in out["replies"]] == ["hr@good.com"], out["replies"]
    assert [b["email"] for b in out["bounces"]] == ["hr@oldcompany.com"], out["bounces"]


def test_scan_detects_reply_by_message_id():
    """HR 换了邮箱回信，靠 In-Reply-To 也能认出来"""
    from engine.bounce import scan_inbox
    from config import EmailConfig
    hdr = (b"From: HR Assistant <hr-other@corp.com>\n"
           b"Subject: Re: \xe5\xae\x9e\xe4\xb9\xa0\xe7\x94\xb3\xe8\xaf\xb7\n"
           b"In-Reply-To: <abc123@qq.com>\n"
           b"Date: Wed, 21 Oct 2026 11:00:00 +0800\n\n")

    class FakeConn:
        def select(self, *a, **k): return ("OK", [b"1"])
        def search(self, charset, crit): return ("OK", [b"9"])
        def fetch(self, uid, what):
            return ("OK", [(("x (BODY %d" % len(hdr)).encode(), hdr), b")"])
        def logout(self): pass

    out = scan_inbox(EmailConfig(email="me@qq.com", auth_code="x"),
                     {"hr@target.com"}, conn=FakeConn(),
                     msgids={"<abc123@qq.com>": "hr@target.com"})
    assert [r["email"] for r in out["replies"]] == ["hr@target.com"], out["replies"]


def test_delivery_store_priority():
    import tempfile
    import engine.delivery as d

    old = d.FILE
    d.FILE = Path(tempfile.mkdtemp()) / "delivery.json"
    try:
        d.apply_scan([{"email": "dead@x.com", "reason": "550", "status": "5.1.1",
                       "date": "2026-10-20"}],
                     [{"email": "hr@good.com", "subject": "面试邀请", "date": "2026-10-21"}])
        assert "dead@x.com" in d.dead_emails()
        logs = [{"success": True, "email": "hr@good.com", "company": "好公司",
                 "time": "2026-10-19T10:00:00", "mode": "send"}]
        view = {r["email"]: r for r in d.contacts_view(logs)}
        assert view["hr@good.com"]["status"] == "replied"
        assert view["dead@x.com"]["status"] == "bounced"
        # 退信后又收到回复，不应再算作退信
        d.apply_scan([], [{"email": "dead@x.com", "subject": "误报", "date": "2026-10-22"}])
        assert "dead@x.com" not in d.dead_emails()
    finally:
        d.FILE = old


def test_send_batch_skips_flagged_rows():
    class FakeLink:
        sent = []

        def __init__(self, cfg):
            pass

        def send(self, msg):
            FakeLink.sent.append(msg["To"])

        def close(self):
            pass

    from config import EmailConfig
    orig = sender._SmtpLink
    sender._SmtpLink = FakeLink
    try:
        recs = [{"company": "A", "email": "a@x.com"},
                {"company": "B", "email": "b@x.com", "skip_reason": "退信地址，已自动跳过"}]
        out = sender.send_batch(EmailConfig(email="me@qq.com"), recs, "hi", "s", [],
                                send_mode="send", rate=600)
        assert [r["status"] for r in out["results"]] == ["sent", "skipped"], out["results"]
        assert FakeLink.sent == ["a@x.com"]
        assert "退信" in out["results"][1]["error"]
    finally:
        sender._SmtpLink = orig


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
