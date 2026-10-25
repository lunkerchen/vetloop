"""VetLoop 網頁：飼主手機畫面與醫院後台。

只綁 127.0.0.1，沒有登入機制，僅供本機示範。
sqlite3 連線不能跨執行緒：每個 request 用 flask.g 開一條、結束就關；提醒排程 thread 自己開連線。
"""
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, current_app, g, jsonify, render_template, request, send_from_directory, url_for

from . import db, flows
from .guardrail import DISCLAIMER, SHORT_NOTE

ROOT = Path(__file__).resolve().parent.parent
TICK_SECONDS = 30
MAX_IMAGE = 5 * 1024 * 1024
# 副檔名對應檔頭：改了副檔名的執行檔進不來
IMAGE_MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpe?g)$")
STATUS_LABELS = {
    "intake": "問診中", "awaiting_confirm": "等飼主確認", "submitted": "已送出，待開醫囑",
    "ordered": "照護計畫待核可", "in_care": "照護中",
}
KIND_LABELS = {"med": "用藥提醒", "recheck": "回診提醒"}
REVISING_LABEL = "照護中・新醫囑待核可"
RECORDED = "已記錄"  # 手機面板只說有沒有記錄，不顯示 AI 挑出來的值


# ---- 資料庫與格式 ----

def get_db():
    if "db" not in g:
        g.db = db.connect(current_app.config["DB_PATH"])
    return g.db


def _fmt(iso, pattern):
    return datetime.fromisoformat(iso).astimezone(db.TZ).strftime(pattern) if iso else ""


def get_case(conn, case_id):
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise LookupError(f"找不到案例 {case_id}")
    return row


def clinic_status_label(status, revising) -> str:
    """醫院端的狀態標籤。照護中有待核可的新版醫囑時特別標出；飼主端 API 不帶這個資訊。"""
    return REVISING_LABEL if status == "in_care" and revising else STATUS_LABELS.get(status, status)


def pending_count(conn) -> int:
    """待審佇列的數量（只算 reply 與 handoff；照護計畫在案例頁核可）。"""
    return conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'pending' AND kind != 'plan'").fetchone()[0]


def case_state(conn, case_id) -> dict:
    """案例狀態（/api/case/<id>），手機畫面與醫院案例頁共用。

    欄位值是 AI 從飼主訊息挑出來的，沒經獸醫核可，所以飼主端只回「已記錄」，照片描述也不回。
    醫院端要看原值，從案例頁自己的 summary 取，不走這裡。
    """
    case = get_case(conn, case_id)
    fields = json.loads(case["fields"] or "{}")
    messages = [{
        "id": m["id"], "sender": m["sender"], "text": m["text"], "time": _fmt(m["created_at"], "%H:%M"),
        "image": url_for("uploads", name=m["image"]) if m["image"] else None,
        "actions": json.loads(m["actions"] or "[]"),
    } for m in conn.execute("SELECT * FROM messages WHERE case_id = ? ORDER BY id", (case_id,))]
    reminders = [{
        "id": r["id"], "kind": r["kind"], "kind_label": KIND_LABELS.get(r["kind"], r["kind"]),
        "due_at": r["due_at"], "due": _fmt(r["due_at"], "%m/%d %H:%M"), "text": r["text"],
        "sent_at": r["sent_at"], "sent": _fmt(r["sent_at"], "%m/%d %H:%M"),
        "acked_at": r["acked_at"], "acked": _fmt(r["acked_at"], "%H:%M"),
    } for r in conn.execute("SELECT * FROM reminders WHERE case_id = ? ORDER BY due_at, id", (case_id,))]
    photos = [m["image"] for m in messages if m["image"]]
    return {
        "case": {**{k: case[k] for k in ("id", "pet_name", "species", "owner_name", "clinic_name",
                                         "clinic_phone", "vet_name", "status")},
                 "status_label": STATUS_LABELS.get(case["status"], case["status"])},
        "fields": [{"key": k, "label": label, "value": RECORDED if fields.get(k) else None,
                    "required": k in flows.REQUIRED}
                   for k, label in flows.FIELD_LABELS.items() if k in flows.REQUIRED or fields.get(k)],
        # 照片的 AI 描述沒有獸醫核可，只放在醫院端的摘要卡，不給手機
        "photo": photos[-1] if photos else None,
        "messages": messages, "reminders": reminders,
        "notes": [DISCLAIMER, SHORT_NOTE],  # 這兩段提示文字前端會用小字顯示，但一個字都不省略
        # 醫院案例頁用它判斷有沒有新動態
        "sig": f"{case['gen']}|{case['status']}|{len(messages)}|{sum(bool(r['sent_at']) for r in reminders)}"
               f"|{sum(bool(r['acked_at']) for r in reminders)}",
    }


def alerts_state(conn) -> dict:
    rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 20").fetchall()
    alerts = [{"id": a["id"], "case_id": a["case_id"], "text": a["text"],
               "time": _fmt(a["created_at"], "%m/%d %H:%M"), "seen": bool(a["seen"])} for a in rows]
    return {"alerts": alerts, "unseen": sum(not a["seen"] for a in alerts)}


def clinic_state(conn) -> dict:
    cases = [{"id": c["id"], "pet_name": c["pet_name"], "status": c["status"],
              "status_label": clinic_status_label(c["status"], c["revision_json"])}
             for c in conn.execute("SELECT id, pet_name, status, revision_json FROM cases ORDER BY id")]
    return {"cases": cases, "pending": pending_count(conn)}


def _save_image(file) -> Path:
    ext = Path(file.filename).suffix.lower()
    if ext not in IMAGE_MAGIC:
        raise ValueError("圖片只收 png、jpg、jpeg")
    data = file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ValueError("圖片不可超過 5 MB")
    if not data.startswith(IMAGE_MAGIC[ext]):
        raise ValueError("檔案內容不是 png 或 jpg 圖片")
    folder = current_app.config["UPLOAD_DIR"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return path


def _form_text(name) -> str:
    """瀏覽器送出 textarea 會把換行變成 \r\n；統一成 \n，免得沒改字也被算成「已修改」。"""
    return request.form.get(name, "").replace("\r\n", "\n")


def _error(message, status):
    if request.method == "GET" and not request.path.startswith("/api/"):
        return message, status, {"Content-Type": "text/plain; charset=utf-8"}
    return jsonify(error=message), status


def _ok(next_url):
    return jsonify(ok=True, next=next_url)


# ---- 提醒排程 ----

def _ticker(app, path):
    while True:
        time.sleep(TICK_SECONDS)
        try:
            conn = db.connect(path)
            try:
                flows.tick(conn)
            finally:
                conn.close()
        except Exception:
            app.logger.exception("提醒排程失敗")


def create_app(db_path=None, start_ticker=True) -> Flask:
    app = Flask(__name__)
    path = Path(db_path) if db_path else ROOT / "instance" / "vetloop.db"
    # 上傳的圖放在資料庫旁邊，測試用暫存資料庫時也不會弄髒專案目錄
    app.config.update(DB_PATH=path, UPLOAD_DIR=path.parent / "uploads", MAX_CONTENT_LENGTH=MAX_IMAGE + 1024 * 1024)

    conn = db.connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # 輪詢讀取不擋寫入
        if conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
            db.reset_demo(conn)
    finally:
        conn.close()

    @app.teardown_appcontext
    def close_db(_):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def reject_cross_site_writes():
        # 瀏覽器會自己帶 Sec-Fetch-Site；本機示範沒有登入，至少擋掉別的網站對這裡送出的表單。
        # 沒帶標頭的（curl、測試）照常放行。
        site = request.headers.get("Sec-Fetch-Site")
        if request.method not in ("GET", "HEAD", "OPTIONS") and site not in (None, "same-origin", "none"):
            return _error("不接受跨站送出的請求", 403)

    @app.errorhandler(ValueError)
    def bad_request(e):
        return _error(str(e), 400)

    @app.errorhandler(LookupError)
    def not_found(e):
        if isinstance(e, (KeyError, IndexError)):  # 這是程式錯誤，不要被當成 404 吞掉
            raise e
        return _error(str(e), 404)

    @app.errorhandler(413)
    def too_large(_):
        return _error("圖片不可超過 5 MB", 400)

    @app.template_filter("hm")
    def hm(iso):
        return _fmt(iso, "%H:%M")

    def render_clinic(template, **context):
        return render_template(template, pending=pending_count(get_db()), **context)

    # ---- 首頁與飼主手機 ----

    @app.get("/")
    def index():
        return render_template("index.html", cases=get_db().execute("SELECT * FROM cases ORDER BY id").fetchall())

    @app.get("/phone/<int:case_id>")
    def phone(case_id):
        return render_template("phone.html", case=get_case(get_db(), case_id))

    @app.get("/api/case/<int:case_id>")
    def api_case(case_id):
        return jsonify(case_state(get_db(), case_id))

    @app.post("/api/case/<int:case_id>/message")
    def post_message(case_id):
        conn = get_db()
        get_case(conn, case_id)
        text = _form_text("text")
        image = request.files.get("image")
        if image is not None and not image.filename:  # 沒選檔案時瀏覽器會送空的欄位
            image = None
        if not text.strip() and image is None:
            raise ValueError("訊息不可空白")
        path = _save_image(image) if image else None
        flows.owner_message(conn, case_id, text, str(path) if path else None)  # 同步呼叫 LLM，要 5–12 秒
        return jsonify(case_state(conn, case_id))

    @app.post("/api/case/<int:case_id>/action")
    def post_action(case_id):
        conn = get_db()
        case = get_case(conn, case_id)
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        action, reminder_id = data.get("action"), data.get("reminder_id")
        if reminder_id is not None and not isinstance(reminder_id, int):
            raise ValueError("reminder_id 必須是整數")
        if action in ("confirm", "edit") and case["status"] != "awaiting_confirm":
            raise ValueError("目前沒有待確認的整理")
        if action in ("ack", "problem"):
            reminder = conn.execute("SELECT acked_at FROM reminders WHERE id = ? AND case_id = ?",
                                    (reminder_id, case_id)).fetchone()
            if reminder is not None and reminder["acked_at"]:
                raise ValueError("這則提醒已經回報過了")
        flows.owner_action(conn, case_id, action, reminder_id)
        return jsonify(case_state(conn, case_id))

    @app.get("/uploads/<name>")
    def uploads(name):
        if not UPLOAD_NAME.match(name):
            raise LookupError("找不到檔案")
        return send_from_directory(current_app.config["UPLOAD_DIR"], name)

    # ---- 醫院後台 ----

    @app.get("/api/alerts")
    def api_alerts():
        return jsonify(alerts_state(get_db()))

    @app.post("/api/alerts/<int:alert_id>/seen")
    def alert_seen(alert_id):
        conn = get_db()
        if conn.execute("UPDATE alerts SET seen = 1 WHERE id = ?", (alert_id,)).rowcount == 0:
            raise LookupError("找不到這則通知")
        conn.commit()
        return jsonify(alerts_state(conn))

    @app.get("/api/clinic")
    def api_clinic():
        return jsonify(clinic_state(get_db()))

    @app.get("/clinic")
    def clinic():
        conn = get_db()
        cases = conn.execute(
            "SELECT c.*, (SELECT MAX(created_at) FROM messages WHERE case_id = c.id) AS last_at"
            " FROM cases c ORDER BY c.id").fetchall()
        rows = [{**dict(c), "status_label": clinic_status_label(c["status"], c["revision_json"]),
                 "last": _fmt(c["last_at"], "%m/%d %H:%M") or "—"} for c in cases]
        return render_clinic("clinic.html", cases=rows, boot=alerts_state(conn))

    @app.get("/clinic/case/<int:case_id>")
    def clinic_case(case_id):
        conn = get_db()
        state = case_state(conn, case_id)
        case = get_case(conn, case_id)
        plan = conn.execute("SELECT * FROM drafts WHERE case_id = ? AND kind = 'plan' ORDER BY id DESC LIMIT 1",
                            (case_id,)).fetchone()
        order = json.loads(case["order_json"]) if case["order_json"] else None
        revision = json.loads(case["revision_json"]) if case["revision_json"] else None
        # 計畫左邊的「醫囑原文」要是產生這份草稿的那一版：照護中的新版計畫對的是 revision，不是現行醫囑
        plan = {**dict(plan), "flags": json.loads(plan["flags"] or "[]"), "sent": _fmt(plan["sent_at"], "%m/%d %H:%M"),
                "order": json.loads(plan["order_json"]) if plan["order_json"] else order} if plan else None
        return render_clinic(
            "clinic_case.html", case=case, state=state, plan=plan, field_labels=flows.FIELD_LABELS,
            summary=json.loads(case["summary"]) if case["summary"] else None, order=order, revision=revision,
            status_label=clinic_status_label(case["status"], revision), disclaimer=DISCLAIMER)

    @app.post("/clinic/case/<int:case_id>/order")
    def post_order(case_id):
        form = request.form
        meds = [{"name": name, "times_per_day": times, "timing": timing, "days": days}
                for name, times, timing, days in zip(form.getlist("med_name"), form.getlist("med_times"),
                                                     form.getlist("med_timing"), form.getlist("med_days"))
                if name.strip() or timing.strip()]  # 整列空白的跳過
        order = {"meds": meds, "diet": {"text": form.get("diet_text", ""), "days": form.get("diet_days") or "0"},
                 "recheck_days": form.get("recheck_days") or "0",
                 "watch": _form_text("watch"), "note": _form_text("note")}
        flows.save_order(get_db(), case_id, order)  # 同步呼叫 LLM
        return _ok(url_for("clinic_case", case_id=case_id, _anchor="plan"))

    @app.post("/clinic/draft/<int:draft_id>/approve")
    def approve(draft_id):
        conn = get_db()
        draft = conn.execute("SELECT case_id, kind FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if draft is None:
            raise LookupError(f"找不到草稿 {draft_id}")
        flows.approve_draft(conn, draft_id, _form_text("final_text"))
        if draft["kind"] == "plan":
            return _ok(url_for("clinic_case", case_id=draft["case_id"]))
        return _ok(url_for("queue"))

    @app.post("/clinic/case/<int:case_id>/fast-forward")
    def fast_forward(case_id):
        conn = get_db()
        get_case(conn, case_id)
        if not flows.fast_forward(conn, case_id):
            raise ValueError("沒有尚未送出的提醒")
        return _ok(url_for("clinic_case", case_id=case_id))

    @app.post("/clinic/reset")
    def reset():
        db.reset_demo(get_db())
        for f in current_app.config["UPLOAD_DIR"].glob("*"):
            if UPLOAD_NAME.match(f.name):
                f.unlink(missing_ok=True)
        return _ok(url_for("clinic"))

    @app.get("/clinic/queue")
    def queue():
        conn = get_db()
        # 「飼主最近說」：草稿建立當下（含）最後一則飼主訊息，不算「已餵」這類按鈕文字
        labels = tuple(flows.ACTION_LABELS.values())
        rows = conn.execute(
            "SELECT d.*, c.pet_name, c.owner_name, c.vet_name,"
            " (SELECT text FROM messages WHERE case_id = d.case_id AND sender = 'owner'"
            f"  AND created_at <= d.created_at AND text NOT IN ({','.join('?' * len(labels))})"
            "  ORDER BY id DESC LIMIT 1) AS owner_text"
            " FROM drafts d JOIN cases c ON c.id = d.case_id"
            " WHERE d.status = 'pending' AND d.kind != 'plan' ORDER BY d.id", labels).fetchall()
        drafts = [{**dict(r), "flags": json.loads(r["flags"] or "[]"), "time": _fmt(r["created_at"], "%m/%d %H:%M")}
                  for r in rows]
        return render_clinic("queue.html", drafts=drafts, short_note=SHORT_NOTE)

    if start_ticker:
        threading.Thread(target=_ticker, args=(app, path), daemon=True, name="vetloop-ticker").start()
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # 不開 reloader：它會多開一個行程，也就多一條提醒排程
    create_app().run(host="127.0.0.1", port=5050, threaded=True, debug=False, use_reloader=False)
