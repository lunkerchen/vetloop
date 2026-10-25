"""把 Python 版護欄與純函式對大量輸入的結果存成 JSON，給 JS 版對照。輸入取自既有測試裡的中文字串。"""
import ast, json, re, sys
from datetime import datetime
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from vetloop import guardrail, flows  # noqa: E402

texts = set()
for f in ["tests/test_flows.py", "tests/test_app.py", "vetloop/flows.py", "vetloop/guardrail.py"]:
    for node in ast.walk(ast.parse((root / f).read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"[一-鿿]", node.value):
            texts.add(node.value)
texts |= {"５ｍｇ", "1 / 2 顆", "四分之一錠", "改給半顆", "Royal Canin 飼料", "吃了😀😀繩子", "偷吃😀😀😀😀😀藥",
          "請勿自行調整劑量", "示範藥A加強錠一天兩次", "停掉示範藥A", "不要再給示範藥B", "特別給藥", "分別給藥",
          "2.5mg 和 5mg", "每天改成一次", "增加 一次", "看起來像是腸胃炎", "生病了", "毛病", "病史", "症狀", "炎症"}
names = ["示範藥A", "示範藥B", "示範藥A加強錠"]
orders = [
    {"meds": [{"name": "示範藥A", "times_per_day": 2, "timing": "飯後 2.5mg", "days": 5}],
     "diet": {"text": "當天少量多餐", "days": 2}, "recheck_days": 3, "watch": "若持續嘔吐請來電", "note": ""},
    {"meds": [{"name": "示範藥B", "times_per_day": 1, "timing": "半顆", "days": 3}],
     "diet": {"text": "禁食 12 小時", "days": 1}, "recheck_days": 0, "watch": "", "note": "可給益生菌"},
]
cases = []
for t in sorted(texts):
    cases.append({"t": t, "e": guardrail.is_emergency(t), "a": guardrail.check_ai_text(t),
                  "aa": guardrail.check_ai_text(t, allowed=["示範藥A", "飯後", "2.5mg"]),
                  "m": guardrail.med_change(t, names), "m0": guardrail.med_change(t),
                  "p": [guardrail.check_plan(t, o) for o in orders], "n": guardrail._norm(t)})

nows = ["2026-10-26T07:59:00+08:00", "2026-10-26T08:00:00+08:00", "2026-10-26T13:30:00+08:00",
        "2026-10-26T20:00:01+08:00", "2026-10-31T23:59:00+08:00", "2026-12-31T21:00:00+08:00"]
rem = [{"now": n, "tpd": tpd, "days": days,
        "out": [x.isoformat(timespec="seconds") for x in flows._reminder_times(tpd, days, datetime.fromisoformat(n))]}
       for n in nows for tpd in (1, 2, 3) for days in (1, 2, 5)]

order_inputs = [
    {"meds": [{"name": " 示範藥A ", "times_per_day": "2", "timing": "飯後", "days": "5"}], "diet": {"text": "少量多餐", "days": "2"},
     "recheck_days": "3", "watch": "若持續嘔吐請來電", "note": ""},
    {"meds": []}, {"meds": [{"name": "", "times_per_day": "2", "timing": "", "days": "5"}]},
    {"meds": [{"name": "A", "times_per_day": "4", "timing": "", "days": "5"}]},
    {"meds": [{"name": "A", "times_per_day": "2", "timing": "", "days": ""}]},
    {"meds": [{"name": "A", "times_per_day": "2", "timing": "", "days": "61"}]},
    {"meds": [{"name": "A" * 201, "times_per_day": "2", "timing": "", "days": "6"}]},
    {"meds": [{"name": "A", "times_per_day": "１", "timing": "", "days": "６"}], "diet": {"text": "", "days": "0"},
     "recheck_days": "0", "watch": "", "note": "多喝水"},
]
orders_out = []
for o in order_inputs:
    try:
        v = flows._validate_order(o)
        orders_out.append({"in": o, "ok": v, "med": flows._med_steps(v), "other": flows._other_steps(v)})
    except ValueError as e:
        orders_out.append({"in": o, "err": str(e)})

q = [{"f": f, "q": flows._question(f, {"pet_name": "麻糬"})} for f in (
    {}, {"chief": "x"}, {"chief": "x", "onset": "y"}, {"chief": "x", "onset": "y", "frequency": "z"},
    {"chief": "x", "onset": "y", "frequency": "z", "appetite": "a"},
    {"chief": "x", "onset": "y", "frequency": "z", "appetite": "a", "energy": "b", "diet_change": "c"})]
json.dump({"cases": cases, "rem": rem, "orders": orders_out, "q": q}, sys.stdout, ensure_ascii=False)
