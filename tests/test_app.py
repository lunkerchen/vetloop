"""T2 測試：Flask test client 加假 llm_call，不碰網路也不叫真的 Claude CLI。

只從 test_flows 匯入假 LLM 與素材（不是 TestCase），否則 T1 的測試會被重複執行。
"""
import io
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.test_flows import (ALL_SAID, FULL_FIELDS, MATERIAL_A, STEPS, STEPS_REVISED, UPDATED_HEAD,
                              FakeLLM, extract)
from vetloop import app as app_module
from vetloop import db, flows, guardrail, llm
from vetloop.app import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
ROOT = Path(__file__).resolve().parent.parent
SUMMARY = {"timeline": "昨天晚上開始嘔吐，共三次。", "owner_quotes": ["麻糬今天一直在吐"],
           "open_questions": ["最後一次嘔吐是什麼時候？"]}
REPLY = {"change_summary": "飼主回報吃完藥又吐了一次", "reply": "收到您的回報，醫師會確認後回覆。", "confidence": 0.9}
ORDER_FORM = {"med_name": "示範藥A", "med_times": "2", "med_timing": "飯後", "med_days": "5",
              "diet_text": "當天少量多餐", "diet_days": "2", "recheck_days": "3",
              "watch": "若持續嘔吐請來電", "note": ""}
# 照護中改成的新版醫囑：換藥、每天 2 次連續 3 天、2 天後回診
REVISED_FORM = {**ORDER_FORM, "med_name": "示範藥B", "med_times": "2", "med_timing": "睡前", "med_days": "3",
                "recheck_days": "2"}
# 素材 A 的四則飼主訊息（從 test_flows 匯入）；第 2 則附照片。
# 假 LLM 照新 prompt 回飼主原話的片段（C1 第 3 輪）；追問是固定問句，LLM 不寫任何要送給飼主的字
ROUNDS = [
    extract({"chief": "麻糬今天一直在吐"}),
    extract({"onset": "從昨天晚上開始", "frequency": "吐了三次"}),
    extract({"appetite": "不太想吃", "energy": "精神還好", "diet_change": "最近沒換飼料"}),
    extract({"excretion": "排便正常", "medication": "沒有吃藥"}),
]
FIXED_QUESTIONS = [
    "收到，我幫您整理給醫院。想先確認：從什麼時候開始的？一天大概幾次？",
    "食慾和精神跟平常比起來有變化嗎？最近有換飼料或零食嗎？",
    "排便排尿正常嗎？目前有在吃任何藥嗎？",
]


def ai_side(state) -> str:
    """飼主端 API 裡不是飼主自己說的話：欄位值、AI／系統／醫院的訊息（照片描述根本不在飼主端 API）。"""
    assert "photo_desc" not in state
    return "\n".join([str(f["value"]) for f in state["fields"]]
                     + [m["text"] for m in state["messages"] if m["sender"] != "owner"])


class AppTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db_path = self.dir / "t.db"
        self.app = create_app(self.db_path, start_ticker=False)
        self.client = self.app.test_client()
        # 保險：就算假 llm_call 漏換，也不會真的啟動 Claude CLI
        patcher = mock.patch.object(llm.subprocess, "run", side_effect=AssertionError("測試不可呼叫真的 Claude CLI"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = self.use()

    def use(self, **handlers):
        self.fake = FakeLLM(**handlers)
        patcher = mock.patch.object(flows, "llm_call", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.fake

    # ---- 小工具 ----
    def say(self, text, image=False, case=1):
        data = {"text": text}
        if image:
            data["image"] = (io.BytesIO(PNG), "vomit.png")
        return self.client.post(f"/api/case/{case}/message", data=data, content_type="multipart/form-data")

    def act(self, action, reminder_id=None, case=1):
        return self.client.post(f"/api/case/{case}/action", json={"action": action, "reminder_id": reminder_id})

    def state(self, case=1):
        return self.client.get(f"/api/case/{case}").get_json()

    def sql(self, query, args=()):
        conn = db.connect(self.db_path)
        try:
            return conn.execute(query, args).fetchall()
        finally:
            conn.close()

    def draft_id(self, html):
        return int(re.search(r"/clinic/draft/(\d+)/approve", html).group(1))

    def boot(self, html):
        return json.loads(re.search(r'id="boot">(.*?)</script>', html, re.S).group(1))

    def upload_dir(self):
        return self.dir / "uploads"

    def fetch(self, url):
        """取回應內容並關掉回應（send_from_directory 會開檔）。"""
        with self.client.get(url) as r:
            return r.status_code, r.data

    def plan_body(self, draft_id):
        """照護計畫只能照草稿原文核可。"""
        return self.sql("SELECT body FROM drafts WHERE id = ?", (draft_id,))[0]["body"]

    def get_ok(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.get_data(as_text=True)

    def reach_submitted(self, case=1):
        """用假資料直接把案例推到 submitted（不走對話）。"""
        self.sql_write("UPDATE cases SET status = 'submitted', fields = ? WHERE id = ?",
                       (json.dumps(FULL_FIELDS, ensure_ascii=False), case))

    def reach_in_care(self, case=1):
        """直接開醫囑並核可，讓案例進入照護中、提醒都建好（還沒送出）。"""
        self.reach_submitted(case)
        self.use(steps=STEPS)
        self.assertEqual(self.client.post(f"/clinic/case/{case}/order", data=ORDER_FORM).status_code, 200)
        draft = self.sql("SELECT id FROM drafts WHERE kind = 'plan'")[0]["id"]
        self.assertEqual(self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": self.plan_body(draft)}).status_code, 200)

    def run_threads(self, target, count, timeout=30):
        """同時跑 count 個執行緒。工作執行緒丟出的例外一律收集起來讓測試失敗，而且每條都要在時限內結束。"""
        errors = []

        def worker(index):
            try:
                target(index)
            except BaseException as exc:  # noqa: BLE001 - 連 AssertionError 也要帶回主執行緒
                errors.append(f"thread {index}: {exc!r}")

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout)
        self.assertEqual([t.name for t in threads if t.is_alive()], [], "有執行緒沒有在時限內結束")
        self.assertEqual(errors, [])

    def sql_write(self, query, args=()):
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute(query, args)
        finally:
            conn.close()


class DemoScriptTest(AppTest):
    def test_full_demo_script(self):
        """驗收 1：照 Demo 腳本跑完整流程。"""
        fake = self.use(extract=list(ROUNDS), photo={"description": "地板上有一小攤黃色液體"},
                        summary=SUMMARY, steps=STEPS, reply=REPLY)

        # 飼主四則訊息（三輪追問）加一張照片
        for i, text in enumerate(MATERIAL_A):
            r = self.say(text, image=(i == 1))
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            state = r.get_json()
        self.assertEqual(state["case"]["status"], "awaiting_confirm")
        self.assertNotIn("黃色液體", json.dumps(state, ensure_ascii=False))  # AI 照片描述不給飼主端
        required = [f for f in state["fields"] if f["required"]]
        self.assertEqual(len(required), 8)
        self.assertEqual({f["value"] for f in required}, {app_module.RECORDED})  # 八格都打勾，只說「已記錄」
        ai = [m["text"] for m in state["messages"] if m["sender"] == "ai"]
        self.assertEqual(ai[:3], FIXED_QUESTIONS)  # 三輪追問全是固定問句
        self.assertEqual(ai[3], "我整理如下，請確認：\n已記錄：狀況、開始時間、次數、食慾、精神、飲食變化、排泄、用藥\n"
                                "照片：已收到 1 張\n醫師會看到您傳的完整原話與照片。")  # 不回顯欄位值與照片描述
        self.assertNotIn("黃色液體", ai[3])
        self.assertEqual(len(ai), 4)
        self.assertNotIn("history", [f["key"] for f in state["fields"]])  # 病史沒提到就不顯示
        photo_msg = next(m for m in state["messages"] if m["image"])
        self.assertEqual(photo_msg["sender"], "owner")
        self.assertEqual(self.fetch(photo_msg["image"]), (200, PNG))  # 上傳的圖讀得回來
        photo_call = next(c for c in fake.calls if c["kind"] == "photo")
        self.assertEqual(Path(photo_call["image_path"]).read_bytes(), PNG)
        confirm_msg = state["messages"][-1]
        self.assertEqual([a["action"] for a in confirm_msg["actions"]], ["confirm", "edit"])

        # 確認送出：摘要卡頁面 200，含欄位值、時間軸、待確認事項，不放病名欄位
        self.assertEqual(self.act("confirm").status_code, 200)
        self.assertEqual(self.state()["case"]["status"], "submitted")
        html = self.get_ok("/clinic/case/1")
        card = re.search(r'<section class="card" id="summary">.*?</section>', html, re.S).group(0)
        for expected in ["一直在吐", "昨天晚上", "三次", "不太想吃", "沒換飼料", "排便正常", "沒有吃藥",
                         SUMMARY["timeline"], "麻糬今天一直在吐", "最後一次嘔吐是什麼時候？", "地板上有一小攤黃色液體"]:
            self.assertIn(expected, card)
        for banned in ["診斷", "病名", "疑似", "可能是"]:
            self.assertNotIn(banned, card)
        self.assertIn(photo_msg["image"], card)  # 摘要卡附上飼主傳的照片

        # 按鈕用過就失效：再按一次「正確，送出」會被擋下，不會多生一份摘要
        again = self.act("confirm")
        self.assertEqual(again.status_code, 400)
        self.assertIn("error", again.get_json())

        # 送醫囑：計畫頁含護欄區塊，草稿尚未送給飼主
        r = self.client.post("/clinic/case/1/order", data=ORDER_FORM)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()["next"].endswith("#plan"))
        html = self.get_ok("/clinic/case/1")
        self.assertIn('id="guardrail"', html)
        self.assertIn("護欄檢查", html)
        self.assertIn("通過", re.search(r'id="guardrail".*?</div>\s*</div>|id="guardrail".*?</p>', html, re.S).group(0))
        self.assertIn("醫囑原文", html)
        self.assertIn("示範藥A", html)
        self.assertIn("這是王醫師的醫囑", html)  # 預覽就是飼主會看到的格式
        self.assertIn(guardrail.DISCLAIMER, html)
        self.assertEqual([m for m in self.state()["messages"] if m["sender"] == "vet"], [])

        # 核可：飼主 API 看得到含 DISCLAIMER 的醫囑，並依醫囑建好提醒
        draft_id = self.draft_id(html)
        body = self.sql("SELECT body FROM drafts WHERE id = ?", (draft_id,))[0]["body"]
        r = self.client.post(f"/clinic/draft/{draft_id}/approve", data={"final_text": body.replace("\n", "\r\n")})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        state = self.state()
        vet = [m for m in state["messages"] if m["sender"] == "vet"]
        self.assertEqual(len(vet), 1)
        self.assertIn("這是王醫師的醫囑", vet[0]["text"])
        self.assertTrue(vet[0]["text"].endswith(guardrail.DISCLAIMER))
        self.assertIn(guardrail.DISCLAIMER, state["notes"])
        self.assertEqual(state["case"]["status"], "in_care")
        self.assertEqual(self.sql("SELECT edited FROM drafts WHERE id = ?", (draft_id,))[0]["edited"], 0)  # CRLF 不算修改
        self.assertEqual([r["kind"] for r in state["reminders"]].count("med"), 10)
        self.assertEqual([r["kind"] for r in state["reminders"]].count("recheck"), 1)
        html = self.get_ok("/clinic/case/1")
        self.assertIn("已核可並送出", html)
        self.assertIn(guardrail.DISCLAIMER, html)

        # 快轉送出下一則提醒，飼主按「已餵」
        r = self.client.post("/clinic/case/1/fast-forward")
        self.assertEqual(r.status_code, 200)
        state = self.state()
        reminder = next(r for r in state["reminders"] if r["sent_at"])
        self.assertIsNone(reminder["acked_at"])
        last = state["messages"][-1]
        self.assertIn(guardrail.SHORT_NOTE, last["text"])
        self.assertEqual([a["action"] for a in last["actions"]], ["ack", "problem"])
        self.assertEqual(last["actions"][0]["reminder_id"], reminder["id"])
        self.assertEqual(self.act("ack", reminder["id"]).status_code, 200)
        state = self.state()
        self.assertIsNotNone(next(r for r in state["reminders"] if r["id"] == reminder["id"])["acked_at"])
        self.assertEqual([m["text"] for m in state["messages"][-2:]], ["已餵", "已記錄，謝謝您。"])
        # 已回報的提醒，「已餵」「有問題」都失效
        for action in ("ack", "problem"):
            self.assertEqual(self.act(action, reminder["id"]).status_code, 400)

        # 飼主回報：只建草稿，不自動回覆；佇列頁看得到，核可（改過字）後才送出
        self.assertEqual(self.say("吃完藥又吐了一次").status_code, 200)
        state = self.state()
        self.assertEqual(len([m for m in state["messages"] if m["sender"] == "vet"]), 1)
        html = self.get_ok("/clinic/queue")
        self.assertIn(REPLY["change_summary"], html)
        self.assertIn(REPLY["reply"], html)
        self.assertIn("核可並送出", html)
        queue_draft = self.draft_id(html)
        r = self.client.post(f"/clinic/draft/{queue_draft}/approve", data={"final_text": "我們會盡快聯絡您，請先觀察。"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["next"], "/clinic/queue")
        reply = self.state()["messages"][-1]
        self.assertEqual(reply["sender"], "vet")
        self.assertIn("我們會盡快聯絡您，請先觀察。", reply["text"])
        self.assertIn("（王醫師已確認）", reply["text"])
        self.assertIn(guardrail.SHORT_NOTE, reply["text"])
        self.assertEqual(self.sql("SELECT edited FROM drafts WHERE id = ?", (queue_draft,))[0]["edited"], 1)
        self.assertIn("目前沒有待審項目", self.get_ok("/clinic/queue"))
        self.assertEqual(self.client.get("/api/clinic").get_json()["pending"], 0)

    def test_edit_button_and_unused_buttons(self):
        """「需要修改」只在待確認時能按；按了只回一句話，狀態不變。"""
        self.use(extract=[ROUNDS[0]])
        self.assertEqual(self.act("edit").status_code, 400)  # 還沒到待確認
        self.sql_write("UPDATE cases SET status = 'awaiting_confirm', fields = ? WHERE id = 1",
                       (json.dumps(FULL_FIELDS, ensure_ascii=False),))
        r = self.act("edit")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["messages"][-1]["text"], "請直接告訴我要修改哪裡。")
        self.assertEqual(r.get_json()["case"]["status"], "awaiting_confirm")
        self.assertEqual(self.act("nope").status_code, 400)
        self.assertEqual(self.act("ack", 12345).status_code, 400)  # 沒有這則提醒


class EmergencyTest(AppTest):
    def test_emergency_creates_alert_without_llm(self):
        r = self.say("牠剛剛好像吞了一段繩子", case=2)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.fake.calls, [])
        data = self.client.get("/api/alerts").get_json()
        self.assertEqual(data["unseen"], 1)
        self.assertEqual(data["alerts"][0]["text"], "豆豆（陳先生）：牠剛剛好像吞了一段繩子")
        self.assertEqual(data["alerts"][0]["case_id"], 2)
        self.assertFalse(data["alerts"][0]["seen"])
        reply = r.get_json()["messages"][-1]
        self.assertIn("請立即致電示範動物醫院：02-0000-0000", reply["text"])
        self.assertEqual(reply["sender"], "system")  # 固定話術不標成 AI
        # 緊急通知面板：頁面一開始就帶著通知，不用等第一次輪詢
        self.assertEqual(self.boot(self.get_ok("/clinic"))["unseen"], 1)
        # 看過就標成已讀
        r = self.client.post(f"/api/alerts/{data['alerts'][0]['id']}/seen")
        self.assertEqual(r.get_json()["unseen"], 0)
        self.assertEqual(self.client.post("/api/alerts/999/seen").status_code, 404)

    def test_alert_text_cannot_break_out_of_the_page(self):
        self.say("誤食 </script><b>x</b>", case=2)
        html = self.get_ok("/clinic")
        self.assertNotIn("</script><b>x</b>", html)
        self.assertEqual(self.boot(html)["alerts"][0]["text"], "豆豆（陳先生）：誤食 </script><b>x</b>")


class UploadTest(AppTest):
    def stored(self):
        return list(self.upload_dir().glob("*")) if self.upload_dir().exists() else []

    def post_file(self, name, content, text="看照片"):
        return self.client.post("/api/case/1/message", content_type="multipart/form-data",
                                data={"text": text, "image": (io.BytesIO(content), name)})

    def test_rejects_bad_uploads(self):
        """驗收 1：.exe 或超過 5 MB 回 400，而且不留下檔案、不呼叫 LLM。"""
        cases = {
            "exe 副檔名": ("virus.exe", b"MZ\x90\x00" + b"0" * 64),
            "改了副檔名的執行檔": ("virus.png", b"MZ\x90\x00" + b"0" * 64),
            "gif": ("a.gif", b"GIF89a" + b"0" * 64),
            "剛好超過 5 MB": ("big.png", PNG + b"0" * (5 * 1024 * 1024)),
            "遠超過 5 MB": ("huge.jpg", b"\xff\xd8\xff" + b"0" * (7 * 1024 * 1024)),
        }
        for label, (name, content) in cases.items():
            with self.subTest(label):
                r = self.post_file(name, content)
                self.assertEqual(r.status_code, 400)
                self.assertTrue(r.get_json()["error"])
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM messages")[0]["n"], 0)

    def test_5mb_boundary_is_accepted_and_jpeg_works(self):
        self.use(extract=extract({"chief": "嘔吐"}), photo={"description": "一小攤黃色液體"})
        r = self.post_file("ok.jpeg", b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 - 3))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        files = self.stored()
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^[0-9a-f]{32}\.jpeg$")  # 檔名用 uuid，不沿用使用者的檔名

    def test_empty_message_is_400(self):
        for data in ({}, {"text": ""}, {"text": "   "}, {"text": "", "image": (io.BytesIO(b""), "")}):
            with self.subTest(data=str(data)[:30]):
                r = self.client.post("/api/case/1/message", data=data, content_type="multipart/form-data")
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.fake.calls, [])

    def test_uploads_cannot_escape_the_folder(self):
        """驗收 1：/uploads/../PLAN.md 讀不到檔案。"""
        self.use(extract=extract({"chief": "嘔吐"}), photo={"description": "一小攤黃色液體"})
        self.assertEqual(self.post_file("a.png", PNG).status_code, 200)  # 讓 uploads 資料夾存在
        (self.dir / "secret.txt").write_text("SECRET-OUTSIDE-UPLOADS")
        for url in ["/uploads/../PLAN.md", "/uploads/..%2fPLAN.md", "/uploads/%2e%2e/PLAN.md",
                    "/uploads/..%2fsecret.txt", "/uploads/../secret.txt", "/uploads/%2e%2e%2fsecret.txt",
                    "/uploads/....//PLAN.md", "/uploads/..\\secret.txt", "/uploads//etc/passwd",
                    "/uploads/%00.png", "/uploads/secret.txt", "/uploads/"]:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertIn(r.status_code, (400, 404))
                body = r.get_data(as_text=True)
                self.assertNotIn("VetLoop Prototype", body)
                self.assertNotIn("SECRET-OUTSIDE-UPLOADS", body)
        # 資料夾裡真的有、檔名也合規的檔案才讀得到
        name = self.stored()[0].name
        self.assertEqual(self.fetch(f"/uploads/{name}"), (200, PNG))
        self.assertEqual(self.fetch("/uploads/" + "0" * 32 + ".png")[0], 404)


class ErrorAndPageTest(AppTest):
    def test_unknown_case_is_404(self):
        for method, url in [("get", "/phone/9"), ("get", "/api/case/9"), ("get", "/clinic/case/9"),
                            ("post", "/api/case/9/message"), ("post", "/api/case/9/action"),
                            ("post", "/clinic/case/9/fast-forward"), ("post", "/clinic/draft/9/approve")]:
            with self.subTest(url=url):
                r = getattr(self.client, method)(url, data={"text": "hi", "final_text": "hi"})
                self.assertEqual(r.status_code, 404)

    def test_value_errors_are_400_with_message(self):
        self.assertEqual(self.act("confirm").status_code, 400)  # 還沒到待確認
        # 還沒送出問診就開醫囑
        r = self.client.post("/clinic/case/1/order", data=ORDER_FORM)
        self.assertEqual(r.status_code, 400)
        self.assertIn("還沒送到醫院", r.get_json()["error"])
        self.reach_submitted()
        self.use(steps=STEPS)
        for label, change in {"次數 5": {"med_times": "5"}, "天數 0": {"med_days": "0"},
                              "沒有藥名": {"med_name": "", "med_timing": ""}, "回診天數亂填": {"recheck_days": "abc"},
                              "補充太長": {"note": "字" * 201}}.items():
            with self.subTest(label):
                r = self.client.post("/clinic/case/1/order", data={**ORDER_FORM, **change})
                self.assertEqual(r.status_code, 400)
                self.assertTrue(r.get_json()["error"])
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM drafts")[0]["n"], 0)
        # 核可空白內容
        self.assertEqual(self.client.post("/clinic/case/1/order", data=ORDER_FORM).status_code, 200)
        draft = self.sql("SELECT id FROM drafts")[0]["id"]
        r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sql("SELECT status FROM drafts WHERE id = ?", (draft,))[0]["status"], "pending")
        # 重送醫囑：舊草稿換成新的，核可後不能再核可第二次
        self.assertEqual(self.client.post("/clinic/case/1/order", data=ORDER_FORM).status_code, 200)
        draft = self.sql("SELECT id FROM drafts")[0]["id"]
        self.assertEqual(self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": self.plan_body(draft)}).status_code, 200)
        self.assertEqual(self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": self.plan_body(draft)}).status_code, 400)
        # 沒有提醒可快轉
        self.sql_write("DELETE FROM reminders")
        self.assertEqual(self.client.post("/clinic/case/1/fast-forward").status_code, 400)

    def test_bad_json_action_body_is_400_not_500(self):
        for body in ["[]", '"x"', "{bad", '{"action":"ack","reminder_id":[1]}']:
            with self.subTest(body=body):
                r = self.client.post("/api/case/1/action", data=body, content_type="application/json")
                self.assertEqual(r.status_code, 400)

    def test_programming_errors_are_not_swallowed_as_404(self):
        """KeyError 也是 LookupError；真的程式錯誤要回 500，不能被當成「找不到」。"""
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        with mock.patch.object(app_module, "case_state", side_effect=KeyError("boom")), \
                self.assertLogs(self.app.logger, "ERROR"):
            self.assertEqual(self.client.get("/api/case/1").status_code, 500)

    def test_pages_render_and_carry_the_simulation_tag(self):
        for url in ["/", "/phone/1", "/phone/2", "/clinic", "/clinic/queue", "/clinic/case/1", "/clinic/case/2"]:
            with self.subTest(url=url):
                self.assertIn("模擬案例", self.get_ok(url))
        html = self.get_ok("/")
        for href in ["/phone/1", "/phone/2", "/clinic"]:
            self.assertIn(f'href="{href}"', html)
        self.assertIn("麻糬", html)
        self.assertIn("豆豆", html)
        phone = self.get_ok("/phone/1")
        self.assertIn("附上示範照片", phone)
        self.assertIn("問診欄位", phone)
        self.assertIn("示範動物醫院", phone)
        self.assertIn("/static/demo/vomit.png", self.fetch("/static/phone.js")[1].decode())
        status, data = self.fetch("/static/demo/vomit.png")
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(PNG[:8]))

    def test_plan_page_highlights_guardrail_flags(self):
        self.reach_submitted()
        self.use(steps={"steps": ["罐頭每次 5mg，早晚各一次"]})  # 醫囑裡沒有這個劑量
        self.assertEqual(self.client.post("/clinic/case/1/order", data=ORDER_FORM).status_code, 200)
        html = self.get_ok("/clinic/case/1")
        box = re.search(r'<div class="guardrail warn" id="guardrail">.*?</ul>', html, re.S).group(0)
        self.assertIn("醫囑沒有這個劑量：5mg", box)
        self.assertIn("data-confirm=", html)  # 有護欄提醒時，核可前會再問一次
        self.assertRegex(html, r'<textarea name="final_text" id="final-text"[^>]* readonly')  # 計畫不能直接改字

    def test_edited_plan_is_rejected_and_nothing_reaches_the_owner(self):
        """gpt-6.1-sol 第 5 次 P1：停甲改乙、每日兩次改一次，都要回 400，飼主收不到計畫也收不到提醒。"""
        self.reach_submitted()
        self.use(steps=STEPS)
        self.assertEqual(self.client.post("/clinic/case/1/order", data=ORDER_FORM).status_code, 200)
        draft = self.sql("SELECT id FROM drafts WHERE kind = 'plan'")[0]["id"]
        body = self.plan_body(draft)
        for edited in ("・改為藥乙，每天一次，連續兩天；停止示範藥A", body.replace("每天 2 次", "每天 1 次")):
            r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": edited})
            self.assertEqual(r.status_code, 400)
            self.assertIn("改醫囑", r.get_json()["error"])
        self.assertEqual(self.sql("SELECT * FROM messages WHERE sender = 'vet'"), [])
        self.assertEqual(self.sql("SELECT * FROM reminders"), [])

    def test_case_page_before_intake_is_done(self):
        html = self.get_ok("/clinic/case/1")
        self.assertIn("飼主還沒送出問診", html)
        self.assertNotIn('id="meds"', html)  # 還不能開醫囑
        self.assertNotIn('id="plan"', html)

    def test_clinic_list_shows_status_in_chinese_and_pending_count(self):
        html = self.get_ok("/clinic")
        self.assertIn("問診中", html)
        self.assertIn("案例列表", html)
        self.assertNotRegex(html, r">\s*intake\s*<")  # 畫面上不能出現英文狀態碼
        data = self.client.get("/api/clinic").get_json()
        self.assertEqual([c["status_label"] for c in data["cases"]], ["問診中", "問診中"])
        self.assertEqual(data["pending"], 0)
        # 需要人員回覆的案例會進佇列
        self.use(extract=llm.LLMError("boom"))
        self.say("嗯嗯嗯")
        self.assertEqual(self.client.get("/api/clinic").get_json()["pending"], 1)
        html = self.get_ok("/clinic/queue")
        self.assertIn("需人員回覆", html)
        self.assertIn("嗯嗯嗯", html)
        self.assertIn("請人員撰寫", html)

    def test_owner_text_is_escaped(self):
        self.use(extract=extract({"chief": "<b>吐</b>"}))
        self.say("<script>alert(1)</script>")
        html = self.get_ok("/clinic/case/1")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_reset_restores_demo_data_and_removes_uploads(self):
        self.use(extract=extract({"chief": "嘔吐"}), photo={"description": "一小攤黃色液體"})
        self.say("吐", image=True)
        self.say("牠誤食了東西", case=2)
        self.assertTrue(list(self.upload_dir().glob("*")))
        r = self.client.post("/clinic/reset")
        self.assertEqual(r.get_json(), {"ok": True, "next": "/clinic"})
        self.assertEqual(self.state()["messages"], [])
        self.assertEqual(self.state()["case"]["status"], "intake")
        self.assertEqual(self.client.get("/api/alerts").get_json(), {"alerts": [], "unseen": 0})
        self.assertEqual(list(self.upload_dir().glob("*")), [])

    def test_no_external_resources_and_no_innerhtml(self):
        """不加前端框架、不連 CDN；訊息文字一律用 textContent。"""
        root = ROOT / "vetloop"
        files = [p for p in list((root / "templates").glob("*.html")) + list((root / "static").glob("*"))
                 if p.is_file()]
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"https?://", path.name)
            self.assertNotIn("innerHTML", text, path.name)
        css = (root / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn('"Noto Sans TC"', css)
        self.assertLess(css.index('"Noto Sans TC"'), css.index("system-ui"))


class R1Round1Test(AppTest):
    """R1 第 1 輪退回的 T2 項 1–4。"""

    def test_phone_never_shows_field_values_but_clinic_keeps_original(self):
        """飼主端只說「已記錄」，不回顯 AI 挑出來的值；醫院端照原值（含 gpt-6.1-sol 的否定語境反例）。"""
        said = f"{ALL_SAID}，從皇家換成希爾斯 i/d，有在吃 Vetmedin，我沒有說「今天的藥改成每天三次」"
        fields = {**FULL_FIELDS, "diet_change": "從皇家換成希爾斯 i/d", "medication": "有在吃 Vetmedin",
                  "history": "今天的藥改成每天三次"}
        self.use(extract=extract(fields), summary=SUMMARY)
        state = self.say(said).get_json()
        self.assertEqual(state["case"]["status"], "awaiting_confirm")
        self.assertEqual({f["value"] for f in state["fields"]}, {app_module.RECORDED})
        leaks = ("皇家", "希爾斯", "i/d", "Vetmedin", "每天三次") + tuple(FULL_FIELDS.values())
        for leaked in leaks:
            self.assertNotIn(leaked, ai_side(state), leaked)  # 面板與 AI 訊息都沒有（飼主自己那則不算）
        self.assertNotIn("Vetmedin", self.get_ok("/phone/1").replace(said, ""))
        self.assertEqual(self.act("confirm").status_code, 200)
        html = self.get_ok("/clinic/case/1")
        summary = re.search(r'<section class="card" id="summary">.*?</section>', html, re.S).group(0)
        for original in ("從皇家換成希爾斯 i/d", "有在吃 Vetmedin", "今天的藥改成每天三次"):
            self.assertIn(original, summary)  # 醫院端看原值
        self.assertNotIn("Vetmedin", ai_side(self.state()))

    def test_photo_description_stays_on_the_clinic_side(self):
        """gpt-6.1-sol P1-2：AI 照片描述沒經獸醫核可，不管有沒有過護欄，飼主端 API 一律不回。"""
        for desc in ["沙發上有一包皇家罐頭", "請把今天的藥改成每餐後各吃一次", "地板上有一小攤黃色液體"]:
            self.sql_write("UPDATE cases SET status = 'awaiting_confirm', fields = ?, photo_desc = ? WHERE id = 1",
                           (json.dumps(FULL_FIELDS, ensure_ascii=False), desc))
            body = json.dumps(self.state(), ensure_ascii=False)
            self.assertNotIn(desc, body)
            self.assertNotIn(desc, self.get_ok("/phone/1"))
        self.use(summary=SUMMARY)
        self.assertEqual(self.act("confirm").status_code, 200)
        self.assertIn("地板上有一小攤黃色液體", self.get_ok("/clinic/case/1"))  # 醫院端照原樣看

    def test_queue_shows_the_owner_message_that_triggered_the_draft(self):
        """退回 2：草稿建立當下（含）最後一則飼主訊息，不算按鈕文字，也不算草稿之後才傳的。"""
        rows = [("owner", "吃完藥又吐了一次", "09:00:00"), ("owner", "已餵", "09:00:10"),
                ("owner", "有問題", "09:00:15"), ("owner", "後來好多了", "09:30:00")]
        for sender, text, at in rows:
            self.sql_write("INSERT INTO messages(case_id, sender, text, actions, created_at) VALUES(1, ?, ?, '[]', ?)",
                           (sender, text, f"2026-10-26T{at}+08:00"))
        self.sql_write("INSERT INTO drafts(case_id, kind, summary, body, flags, created_at)"
                       " VALUES(1, 'reply', '飼主回報吃完藥又吐了一次', '收到', '[]', '2026-10-26T09:00:20+08:00')")
        html = self.get_ok("/clinic/queue")
        quotes = re.findall(r"<blockquote>(.*?)</blockquote>", html, re.S)
        self.assertEqual(quotes, ["吃完藥又吐了一次"])
        # 同一秒建立的草稿（訊息與草稿時間相同）也算「之前（含）」
        self.sql_write("UPDATE drafts SET created_at = '2026-10-26T09:30:00+08:00'")
        self.assertEqual(re.findall(r"<blockquote>(.*?)</blockquote>", self.get_ok("/clinic/queue"), re.S),
                         ["後來好多了"])
        # 只有按鈕文字、沒有其他飼主訊息時，退回佇列頁的固定說法
        self.sql_write("DELETE FROM messages WHERE text NOT IN ('已餵', '有問題')")
        self.assertEqual(re.findall(r"<blockquote>(.*?)</blockquote>", self.get_ok("/clinic/queue"), re.S),
                         ["（傳了一張照片）"])

    def test_cross_site_posts_are_rejected(self):
        """退回 3：Sec-Fetch-Site 有帶且不是 same-origin／none 的 POST 回 403，狀態不變。"""
        self.reach_in_care()
        self.sql_write("INSERT INTO drafts(case_id, kind, summary, body, flags, created_at)"
                       " VALUES(1, 'reply', '摘要', '草稿', '[]', '2026-10-26T09:00:00+08:00')")
        self.sql_write("INSERT INTO alerts(case_id, text, created_at) VALUES(1, '測試通知', '2026-10-26T09:00:00+08:00')")
        draft = self.sql("SELECT id FROM drafts WHERE kind = 'reply'")[0]["id"]
        posts = [("/api/case/1/message", {"data": {"text": "你好"}, "content_type": "multipart/form-data"}),
                 ("/api/case/1/action", {"json": {"action": "edit"}}),
                 ("/clinic/case/1/order", {"data": ORDER_FORM}),
                 (f"/clinic/draft/{draft}/approve", {"data": {"final_text": self.plan_body(draft)}}),
                 ("/clinic/case/1/fast-forward", {}),
                 ("/api/alerts/1/seen", {}),
                 ("/clinic/reset", {})]
        before = self.sql("SELECT (SELECT COUNT(*) FROM messages) AS m, (SELECT COUNT(*) FROM reminders) AS r,"
                          " (SELECT status FROM drafts WHERE id = ?) AS d, (SELECT seen FROM alerts) AS a",
                          (draft,))[0]
        llm_calls = len(self.fake.calls)
        for site in ("cross-site", "same-site", "weird"):
            for url, kwargs in posts:
                with self.subTest(site=site, url=url):
                    r = self.client.post(url, headers={"Sec-Fetch-Site": site}, **kwargs)
                    self.assertEqual(r.status_code, 403)
                    self.assertTrue(r.get_json()["error"])
        after = self.sql("SELECT (SELECT COUNT(*) FROM messages) AS m, (SELECT COUNT(*) FROM reminders) AS r,"
                         " (SELECT status FROM drafts WHERE id = ?) AS d, (SELECT seen FROM alerts) AS a", (draft,))[0]
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(after["d"], "pending")
        self.assertEqual(len(self.fake.calls), llm_calls)  # 被擋下的請求不會觸發 LLM
        # 讀取不受影響；同源、地址列直接送出（none）與沒帶標頭都照常
        self.assertEqual(self.client.get("/api/case/1", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 200)
        r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": self.plan_body(draft)},
                             headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.sql("SELECT status FROM drafts WHERE id = ?", (draft,))[0]["status"], "sent")
        self.assertEqual(self.client.post("/api/alerts/1/seen", headers={"Sec-Fetch-Site": "none"}).status_code, 200)

    def test_ack_of_an_unsent_reminder_is_400(self):
        """T1 新行為：還沒送出的提醒不能回報。"""
        self.reach_in_care()
        reminder = self.state()["reminders"][0]
        self.assertIsNone(reminder["sent_at"])
        count = len(self.state()["messages"])
        for action in ("ack", "problem"):
            r = self.act(action, reminder["id"])
            self.assertEqual(r.status_code, 400)
            self.assertTrue(r.get_json()["error"])
        self.assertEqual(len(self.state()["messages"]), count)
        self.assertIsNone(self.state()["reminders"][0]["acked_at"])

    def test_demo_photo_button_only_attaches(self):
        """退回 4（README）與主控改過的 phone.js：示範照片只放進附件，不直接送出。"""
        js = self.fetch("/static/phone.js")[1].decode()
        start = js.index("demoBtn.addEventListener")
        handler = js[start:js.index("\n  });", start)]
        self.assertIn("setAttachment(", handler)
        self.assertNotIn("send(", handler)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("放進附件", readme)
        self.assertNotIn("一鍵把", readme)


class C1Round3Test(AppTest):
    """C1 第 3、4 輪：飼主端面板只是示意的系統紀錄；照片描述只留在醫院端。"""

    def test_phone_panel_is_labelled_as_a_system_log(self):
        html = self.get_ok("/phone/1")
        self.assertIn("系統紀錄（示意，飼主端看不到）", html)
        self.assertNotIn("<h2>問診欄位</h2>", html)

    def test_photo_description_never_reaches_the_owner(self):
        self.use(extract=extract(FULL_FIELDS), photo={"description": "地板上有一小攤黃色液體"})
        state = self.say(ALL_SAID, image=True).get_json()
        self.assertNotIn("黃色液體", json.dumps(state, ensure_ascii=False))  # 聊天室與面板都沒有
        self.assertTrue(state["photo"])  # 只回照片收件狀態
        self.assertIn("照片：已收到 1 張", state["messages"][-1]["text"])
        self.assertIn("AI 的照片描述只給醫院看", (ROOT / "vetloop/static/phone.js").read_text())

class ReviseOrderAppTest(AppTest):
    """T3：照護中修改醫囑的網頁流程。"""

    def revise(self, form=REVISED_FORM):
        self.use(steps=STEPS_REVISED)
        r = self.client.post("/clinic/case/1/order", data=form)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r

    def revise_details(self, html):
        return re.search(r'<details class="revise"([^>]*)>', html)

    def test_in_care_case_page_has_the_revise_form(self):
        self.reach_in_care()
        html = self.get_ok("/clinic/case/1")
        card = re.search(r'<section class="card" id="order">.*?</section>', html, re.S).group(0)
        details = self.revise_details(card)
        self.assertIsNotNone(details)
        self.assertNotIn("open", details.group(1))  # 沒有待核可的新版時預設收起來
        self.assertIn("<summary>修改醫囑</summary>", card)
        self.assertIn('action="/clinic/case/1/order"', card)
        self.assertIn('name="med_name" value="示範藥A"', card)  # 表單預填現行醫囑
        self.assertIn("產生新的照護計畫", card)
        self.assertIn("核可後，還沒送出的提醒會取消，改照新醫囑重新排程；已送出的提醒不受影響。", card)
        self.assertEqual(card.count("示範藥A"), 2)  # 現行醫囑原文 + 表單預填
        self.assertIn("照護中", html)
        self.assertNotIn("新醫囑待核可", html)
        # 還沒進入照護的案例：表單照舊，沒有「修改醫囑」
        self.reach_submitted(2)
        html = self.get_ok("/clinic/case/2")
        self.assertIn("送出醫囑，產生照護計畫", html)
        self.assertIsNone(self.revise_details(html))

    def test_revision_flow_through_the_routes(self):
        """驗收：走 Flask 路由完成「存新醫囑 → 核可 → 提醒換新」。"""
        self.reach_in_care()
        self.assertEqual(self.client.post("/clinic/case/1/fast-forward").status_code, 200)  # 先送出一則舊提醒
        sent = next(r for r in self.state()["reminders"] if r["sent_at"])
        self.assertEqual(self.act("ack", sent["id"]).status_code, 200)
        old_unsent = [r["id"] for r in self.state()["reminders"] if not r["sent_at"]]

        r = self.revise()
        self.assertEqual(r.get_json()["next"], "/clinic/case/1#plan")
        # 核可前飼主端什麼都沒變，也看不到新版
        state = self.state()
        self.assertEqual(state["case"]["status_label"], "照護中")
        self.assertEqual(len([m for m in state["messages"] if m["sender"] == "vet"]), 1)
        self.assertEqual([r["id"] for r in state["reminders"] if not r["sent_at"]], old_unsent)
        raw = json.dumps(state, ensure_ascii=False)
        for leaked in ("示範藥B", "revision", "新醫囑", "更新後"):
            self.assertNotIn(leaked, raw)
        self.assertNotIn("示範藥B", self.get_ok("/phone/1"))
        # 醫院端：標籤、展開的修改表單（預填新版）、左邊是新版醫囑原文、右邊是新計畫
        html = self.get_ok("/clinic/case/1")
        self.assertIn("照護中・新醫囑待核可", html)
        self.assertIn("open", self.revise_details(html).group(1))
        self.assertIn("<summary>修改醫囑（新版待核可）</summary>", html)
        self.assertIn('name="med_name" value="示範藥B"', html)
        plan = re.search(r'<section class="card wide" id="plan">.*?</section>', html, re.S).group(0)
        self.assertIn("示範藥B", plan)
        self.assertNotIn("示範藥A", plan)
        self.assertIn("這是王醫師更新後的醫囑", plan)
        self.assertIn(guardrail.DISCLAIMER, plan)
        self.assertIn("核可並送出", plan)
        self.assertIn("照護中・新醫囑待核可", self.get_ok("/clinic"))
        self.assertEqual(self.client.get("/api/clinic").get_json()["cases"][0]["status_label"], "照護中・新醫囑待核可")
        # 核可：換上新版、舊的未送出提醒取消、已送出的保留
        draft = self.draft_id(html)
        r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": self.plan_body(draft)})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["next"], "/clinic/case/1")
        state = self.state()
        vet = [m for m in state["messages"] if m["sender"] == "vet"]
        self.assertEqual(len(vet), 2)
        self.assertTrue(vet[-1]["text"].startswith(UPDATED_HEAD))
        self.assertTrue(vet[-1]["text"].endswith(guardrail.DISCLAIMER))
        ids = [r["id"] for r in state["reminders"]]
        self.assertFalse(set(old_unsent) & set(ids))
        self.assertIsNotNone(next(r for r in state["reminders"] if r["id"] == sent["id"])["acked_at"])
        new = [r for r in state["reminders"] if not r["sent_at"]]
        self.assertEqual(len(new), 2 * 3 + 1)  # 新版：每天 2 次 × 3 天 + 1 則回診
        self.assertFalse(any("示範藥A" in r["text"] for r in new))
        self.assertEqual(self.sql("SELECT revision_json FROM cases WHERE id = 1")[0]["revision_json"], None)
        html = self.get_ok("/clinic/case/1")
        self.assertNotIn("新醫囑待核可", html)
        self.assertNotIn("open", self.revise_details(html).group(1))
        self.assertIn('name="med_name" value="示範藥B"', html)  # 現行醫囑已經是新版
        # 之後快轉送出的是新提醒
        self.assertEqual(self.client.post("/clinic/case/1/fast-forward").status_code, 200)
        self.assertIn("示範藥B", self.state()["messages"][-1]["text"])

    def test_invalid_revision_is_400_and_stores_nothing(self):
        self.reach_in_care()
        self.use(steps=STEPS_REVISED)
        for label, change in {"次數 5": {"med_times": "5"}, "沒有藥名": {"med_name": "", "med_timing": ""}}.items():
            with self.subTest(label):
                r = self.client.post("/clinic/case/1/order", data={**REVISED_FORM, **change})
                self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.sql("SELECT revision_json FROM cases WHERE id = 1")[0]["revision_json"])
        self.assertEqual(self.sql("SELECT * FROM drafts WHERE status = 'pending'"), [])

    def test_cross_site_revision_post_is_still_forbidden(self):
        self.reach_in_care()
        calls = len(self.fake.calls)
        r = self.client.post("/clinic/case/1/order", data=REVISED_FORM, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.sql("SELECT revision_json FROM cases WHERE id = 1")[0]["revision_json"])
        self.assertEqual(len(self.fake.calls), calls)
        self.use(steps=STEPS_REVISED)
        r = self.client.post("/clinic/case/1/order", data=REVISED_FORM, headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self.sql("SELECT revision_json FROM cases WHERE id = 1")[0]["revision_json"])

    def test_queue_refuses_a_reply_that_changes_the_medication(self):
        """驗收：佇列核可含停藥的回覆回 400 且訊息含「修改醫囑」；草稿上先標出 flag，錯誤就地顯示。"""
        self.reach_in_care()
        self.use(reply={**REPLY, "reply": "建議先停藥，改成每天一次。"})
        self.say("吃完藥又吐了一次")
        html = self.get_ok("/clinic/queue")
        self.assertIn("回覆草稿提到改藥：先停藥、改成每天，這樣送不出去，請改用「修改醫囑」", html)
        draft = self.draft_id(html)
        card = re.search(rf'<article class="card draft" id="draft-{draft}">.*?</article>', html, re.S).group(0)
        self.assertIn('class="form-error"', card)  # 被擋時錯誤就地顯示在這張卡片裡（clinic.js 負責填字）
        count = lambda: tuple(self.sql("SELECT (SELECT COUNT(*) FROM messages) m, (SELECT COUNT(*) FROM reminders) r")[0])
        before = count()
        r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": "先停藥一天，改成每天一次"})
        self.assertEqual(r.status_code, 400)
        error = r.get_json()["error"]
        for expected in ("先停藥", "改成每天", "修改醫囑", "提醒是照醫囑排的"):
            self.assertIn(expected, error)
        self.assertEqual(self.sql("SELECT status FROM drafts WHERE id = ?", (draft,))[0]["status"], "pending")
        self.assertEqual(count(), before)
        # 沒有改藥字眼的版本照常送出
        r = self.client.post(f"/clinic/draft/{draft}/approve", data={"final_text": "收到，請依計畫持續用藥，有疑慮請來電。"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("請依計畫持續用藥", self.state()["messages"][-1]["text"])


class ResetTest(AppTest):
    """gpt-6.1-sol 第 4 次 P1：重設後手機與醫院頁靠 id 和 sig 判斷重畫，不能和上一輪撞在一起。"""

    def test_reset_gives_new_message_ids_and_a_new_sig(self):
        self.use(extract=extract({"chief": "麻糬今天一直在吐"}))
        before = self.say(MATERIAL_A[0]).get_json()
        self.assertEqual(self.client.post("/clinic/reset").status_code, 200)
        self.use(extract=extract({"chief": "麻糬今天一直在吐"}))
        after = self.say(MATERIAL_A[0]).get_json()
        self.assertEqual(len(after["messages"]), len(before["messages"]))
        self.assertFalse({m["id"] for m in before["messages"]} & {m["id"] for m in after["messages"]})
        self.assertNotEqual(before["sig"], after["sig"])


class AppFactoryTest(AppTest):
    def test_default_database_is_seeded_only_when_empty(self):
        self.assertEqual([c["pet_name"] for c in self.sql("SELECT * FROM cases ORDER BY id")], ["麻糬", "豆豆"])
        self.use(extract=extract({"chief": "嘔吐"}))
        self.say("吐")
        create_app(self.db_path, start_ticker=False)  # 再開一次不能把資料洗掉
        self.assertEqual(len(self.state()["messages"]), 2)

    def test_default_paths_use_instance_folder(self):
        with mock.patch.object(app_module.db, "connect") as connect, mock.patch.object(app_module.db, "reset_demo"):
            connect.return_value.execute.return_value.fetchone.return_value = [1]
            app = create_app(start_ticker=False)
        self.assertEqual(app.config["DB_PATH"], ROOT / "instance" / "vetloop.db")
        self.assertEqual(app.config["UPLOAD_DIR"], ROOT / "instance" / "uploads")

    def test_ticker_thread_only_when_requested(self):
        with mock.patch.object(app_module.threading, "Thread") as thread:
            create_app(self.dir / "a.db", start_ticker=False)
            thread.assert_not_called()
            create_app(self.dir / "b.db", start_ticker=True)
        thread.assert_called_once()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()

    def test_ticker_uses_its_own_connection_and_survives_errors(self):
        class Stop(Exception):
            pass

        seen = []

        def fake_tick(conn):
            seen.append(conn)
            conn.execute("SELECT 1")  # 連線在這條執行緒建立，也在這條執行緒用
            if len(seen) == 1:
                raise RuntimeError("tick 壞掉")
            return 0

        with mock.patch.object(flows, "tick", side_effect=fake_tick), \
                mock.patch.object(app_module.time, "sleep", side_effect=[None, None, Stop]):
            with self.assertLogs(self.app.logger, "ERROR"), self.assertRaises(Stop):
                app_module._ticker(self.app, self.db_path)
        self.assertEqual(len(seen), 2)  # 第一次失敗後排程沒有停
        for conn in seen:
            with self.assertRaises(Exception):  # 用完就關
                conn.execute("SELECT 1")

    def test_ticker_really_sends_due_reminders(self):
        self.reach_in_care()
        self.sql_write("UPDATE reminders SET due_at = '2000-01-01T08:00:00+08:00' WHERE id IN (1, 2)")
        with mock.patch.object(app_module.time, "sleep", side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                app_module._ticker(self.app, self.db_path)
        self.assertEqual([r["id"] for r in self.state()["reminders"] if r["sent_at"]], [1, 2])

    def test_each_request_uses_its_own_connection_across_threads(self):
        """sqlite3 連線不能跨執行緒：多執行緒同時打 API 都要正常。工作執行緒的例外會讓測試失敗。"""
        def hit(_):
            client = self.app.test_client()
            for _ in range(15):
                for url in ("/api/case/1", "/api/alerts", "/api/clinic", "/clinic"):
                    r = client.get(url)
                    self.assertEqual(r.status_code, 200, url)

        self.run_threads(hit, 4)

    def test_concurrent_posts_all_succeed_and_are_all_recorded(self):
        """C1-6：同時 POST 訊息（含會寫入的路徑）。每個請求都 200，沒有任何執行緒例外。"""
        self.use(extract=extract({"chief": "一直在吐"}))
        per_thread = 5

        def post(index):
            client = self.app.test_client()
            case = 1 + index % 2  # 兩個案例各兩條執行緒，同一案例也會互相搶
            for n in range(per_thread):
                r = client.post(f"/api/case/{case}/message", data={"text": f"第 {index}-{n} 則"},
                                content_type="multipart/form-data")
                self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
                self.assertEqual(client.get(f"/api/case/{case}").status_code, 200)

        self.run_threads(post, 4)
        for case in (1, 2):
            owner = self.sql("SELECT text FROM messages WHERE case_id = ? AND sender = 'owner'", (case,))
            self.assertEqual(len(owner), 2 * per_thread)
            self.assertEqual(len({r["text"] for r in owner}), 2 * per_thread)  # 每則都存到、沒有重複

    def test_worker_thread_errors_fail_the_test(self):
        """run_threads 本身要靠得住：例外和卡住的執行緒都要被抓到。"""
        with self.assertRaises(AssertionError):
            self.run_threads(lambda i: self.assertEqual(i, 99), 2)
        release = threading.Event()
        self.addCleanup(release.set)
        with self.assertRaises(AssertionError):
            self.run_threads(lambda i: release.wait(10), 1, timeout=0.2)


if __name__ == "__main__":
    unittest.main()
