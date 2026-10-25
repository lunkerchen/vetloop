"""SQLite 資料表與示範資料。"""
import os
import secrets
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(
    id INTEGER PRIMARY KEY, pet_name TEXT, species TEXT, owner_name TEXT,
    clinic_name TEXT, clinic_phone TEXT, vet_name TEXT,
    status TEXT,
    fields TEXT DEFAULT '{}',
    photo_desc TEXT,
    summary TEXT,
    order_json TEXT,     -- 現行醫囑：提醒和照護中回覆都用它
    revision_json TEXT,  -- 照護中修改、還沒核可的新版醫囑；核可時才換進 order_json
    created_at TEXT,
    gen TEXT);  -- 世代：每次 Demo 重設都換新值，等完 AI 才寫入的地方要比對，舊請求的結果才不會寫進新案例
-- messages 用 AUTOINCREMENT：重設後訊息 id 不重用，手機畫面靠 id 判斷要不要重畫
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER REFERENCES cases(id),
    sender TEXT CHECK(sender IN ('owner','ai','vet','system')),
    text TEXT, image TEXT, actions TEXT DEFAULT '[]', created_at TEXT);
-- reminders、alerts 也用 AUTOINCREMENT：Demo 重設後 id 不重用，背景排程或舊頁面拿著舊 id 不會動到新資料
CREATE TABLE IF NOT EXISTS reminders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER REFERENCES cases(id), kind TEXT,
    due_at TEXT, text TEXT, sent_at TEXT, acked_at TEXT);
-- AUTOINCREMENT：草稿刪掉後 id 也不會被新草稿重用，舊頁面的 id 不會核可到別份草稿
CREATE TABLE IF NOT EXISTS drafts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER REFERENCES cases(id),
    kind TEXT CHECK(kind IN ('plan','reply','handoff')),
    summary TEXT, body TEXT, flags TEXT DEFAULT '[]',
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','sent')),
    edited INTEGER DEFAULT 0, created_at TEXT, sent_at TEXT,
    order_json TEXT);  -- plan 草稿：產生它的那一版醫囑，核可時要和案例目前的醫囑一致
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER REFERENCES cases(id), text TEXT,
    created_at TEXT, seen INTEGER DEFAULT 0);
"""

# 子表在前，清空時才不會違反外鍵
_TABLES = ("messages", "reminders", "drafts", "alerts", "cases")


def now() -> datetime:
    return datetime.now(TZ)


def iso(dt: datetime) -> str:
    """所有時間欄位都存這個格式（含 +08:00，秒為單位）。"""
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def connect(path) -> sqlite3.Connection:
    path = os.fspath(path)
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def reset_demo(conn: sqlite3.Connection) -> None:
    """清空全部資料，重建兩筆模擬案例。"""
    with conn:
        for table in _TABLES:
            conn.execute(f"DELETE FROM {table}")
        for case_id, pet, species, owner in ((1, "麻糬", "貓", "林小姐"), (2, "豆豆", "狗", "陳先生")):
            conn.execute(
                "INSERT INTO cases(id, pet_name, species, owner_name, clinic_name, clinic_phone,"
                " vet_name, status, created_at, gen) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (case_id, pet, species, owner, "示範動物醫院", "02-0000-0000", "王醫師",
                 "intake", iso(now()), secrets.token_hex(8)))
