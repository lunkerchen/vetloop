"""護欄：純函式，不碰資料庫。AI 自己寫的內容都要先過這裡。"""
import re
import unicodedata

DISCLAIMER = (
    "本作品提供之資訊僅供輔助參考，不能取代獸醫師之診斷、治療或專業建議。"
    "貓犬之健康與營養需求可能因個體狀況而異，如有健康疑慮或需要調整飲食與照護方式，請諮詢合格獸醫師。"
)
SHORT_NOTE = "提醒內容來自獸醫師醫囑，僅供照護參考；有疑慮請洽獸醫師。"

# 緊急字眼寧可誤報（例如「沒有誤食」也會觸發），不可漏報。
_FOREIGN = "繩子|線|骨頭|塑膠|巧克力|葡萄|百合"
_EMERGENCY = re.compile("|".join([
    "誤食", "誤吞", "吞了", "吞下", "吞到", "吞進",
    # 「吃了／吃下／吃到藥」是正常的用藥回報，只有「偷吃」接藥才算
    f"(?:吃到|吃下|吃了).{{0,6}}(?:{_FOREIGN})", f"偷吃.{{0,6}}(?:{_FOREIGN}|藥)",
    # 毒物：這幾種單獨出現就算；人吃的藥與百合要看動作
    "老鼠藥", "殺蟲劑", "除草劑", "農藥",
    "(?:吃到|吃了|吃下|舔).{0,6}(?:我的藥|人的藥|人吃的|普拿疼|感冒藥|止痛藥|安眠藥)",
    "(?:舔|咬|吃).{0,6}百合",
    "吞食", "呼吸困難", "喘不過氣", "張口呼吸", "抽搐", "抽筋", "癲癇", "痙攣", "昏倒", "休克",
    "沒有意識", "叫不醒", "大量出血", "流血不止", "一直流血", "吐血", "尿不出", "中毒", "車禍", "癱",
]))

# 數量：5、2.5、1/4、1 / 2、四分之一、半、一
_NUM = r"\d+(?:\.\d+)?"
_ZH = "一二兩三四五六七八九十百"
_AMOUNT = rf"(?:{_NUM}(?:\s*/\s*{_NUM})?|[{_ZH}]+分之[{_ZH}]+|[{_ZH}半]+)"
_DOSE = re.compile(_AMOUNT + r"\s*(?:mg|ml|cc|毫克|毫升|錠|顆)", re.I)

# 病名字尾。「症」不擋「症狀」；「病」不擋病史、病歷、病情、病況、生病、生過病、看病、毛病
_DISEASE = (r"(?:炎|症(?!狀)|癌|腫瘤|衰竭|結石|感染|中暑|寄生蟲|過敏"
            r"|(?<![生看過毛])病(?![史歷情況])|瘟|潰瘍|阻塞|癲癇)")
_RULES = (
    # 推測句型要放在單獨的病名字尾前面，同一段只報一次
    ("診斷或推測", re.compile(
        r"可能是|疑似|診斷|確診|罹患|(?:應該是|或許是|大概是|看起來像).{0,8}?" + _DISEASE
        + "|" + _DISEASE)),
    ("嚴重度分級", re.compile(r"嚴重度|嚴重程度|輕症|重症|危險等級|分級|不嚴重|沒什麼大礙|高風險|低風險|風險等級")),
    ("用藥建議", re.compile(r"建議(?:服用|吃|給).{0,12}藥|止吐藥|抗生素|類固醇|胃藥|益生菌|禁食|加倍|減半|停藥|加量|減量")),
    ("劑量", _DOSE),
    ("產品或品牌", re.compile(r"飼料品牌|處方飼料|royal\s*canin|皇家|推薦.{0,10}(?:飼料|罐頭|產品|品牌)", re.I)),
)


# 追蹤回覆裡的改藥字眼。提醒是照醫囑排的，在回覆裡寫「停藥」「改成每天一次」只會讓飼主收到互相矛盾的指示，
# 所以核可前擋下，請獸醫改走「修改醫囑」。
# ponytail: 這是 regex 經驗法則，不是語意判斷。上限：擋不到沒出現這些字眼的改藥說法（例如「晚上那一次不用吃」）；
# 也會誤擋少數正常句子（例如「劑量」「藥量」單獨出現、「幫傷口換藥」，寧可請獸醫換個寫法）。
# 要真的杜絕，只能把追蹤回覆限定成固定模板。
_CLAUSE = r"[^，。,.；;！!？?\n]"  # 同一句之內
_STOP = r"[暫先]?停(?:止|用|掉)?(?:給|吃|餵|服|使用|用)?藥"
_MED_CHANGE = re.compile("|".join([
    _STOP,
    r"(?:不用|不必|不需要?|不要|先別|勿|(?<![特分])別)再?(?:給|吃|餵|服用?)藥",
    r"(?:給藥|餵藥|用藥|吃藥|服藥)的?次數|次數(?:改|調整|增加|減少)",  # 單獨的「次數」太常見（嘔吐次數），不算
    r"改(?:成|為|到)?(?:每天|每日|每次|每餐|一天|一日|早晚)", r"(?:每天|每日|一天|一日)改",
    "加量|減量|加倍|減半|劑量|藥量",
    rf"[多少]給{_CLAUSE}{{0,4}}(?:藥|顆|錠|粒|包|cc|ml|mg|毫升)",  # 「多給麻糬喝水」不算
    rf"(?:增加|減少){_CLAUSE}{{0,4}}[次藥]",
    rf"換{_CLAUSE}{{0,6}}藥", rf"改(?:給|用|吃|服|餵){_CLAUSE}{{0,6}}藥",
    r"改(?:成|為|給|用)?\s*" + _DOSE.pattern,  # 「改給半顆」沒提到藥字也算
]), re.I)
# 「請不要自行停藥」「請勿自行調整劑量」是在勸阻，不算
_SELF = re.compile(rf"(?:自行|擅自){_CLAUSE}{{0,4}}?(?:{_MED_CHANGE.pattern})", re.I)


def is_emergency(text: str) -> bool:
    return bool(_EMERGENCY.search(text or ""))


def check_ai_text(text: str, allowed=()) -> list[str]:
    """回傳違規原因；空 list 代表通過。allowed 是獸醫醫囑原文，先從 text 移除再檢查。"""
    # 全形英數轉半形，免得「５ｍｇ」躲過劑量規則
    text = unicodedata.normalize("NFKC", text or "")
    allowed = {unicodedata.normalize("NFKC", a) for a in allowed if isinstance(a, str) and a}
    # 用 \0 取代而不是刪掉，避免前後文接在一起湊出新的違規字串
    for s in sorted(allowed, key=len, reverse=True):
        text = text.replace(s, "\0")
    reasons = []
    for label, pattern in _RULES:
        for m in pattern.finditer(text):
            reason = f"{label}：「{m.group(0)}」"
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def med_change(text: str, med_names=()) -> list[str]:
    """回覆文字裡提到停藥、改次數、改劑量或換藥的片段（不重複，依出現順序）；空 list 代表沒有。

    med_names 是這個案例醫囑裡的藥名，比對前先換成「藥」，「停掉示範藥A」才會被當成「停掉藥」。
    """
    text = unicodedata.normalize("NFKC", text or "")
    for name in sorted({unicodedata.normalize("NFKC", n) for n in med_names if n}, key=len, reverse=True):
        text = text.replace(name, "藥")
    text = _SELF.sub("\0", text)
    hits = []
    for m in _MED_CHANGE.finditer(text):
        if m.group(0) not in hits:
            hits.append(m.group(0))
    return hits


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


# 醫囑自己寫了這幾個字，計畫就可以用（它們在 check_ai_text 裡是照護建議）
_ADVICE_WORDS = ("禁食", "益生菌", "胃藥")


def _norm(s: str) -> str:
    """去空白、全形轉半形、轉小寫，拿來比對藥名與劑量。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).lower()


def _doses(text: str) -> list[str]:
    return [_norm(m.group(0)) for m in _DOSE.finditer(unicodedata.normalize("NFKC", text))]


def check_plan(text: str, order: dict) -> list[str]:
    """照護計畫草稿要忠於醫囑：藥名不能漏、劑量不能憑空出現，其餘照 check_ai_text。"""
    flags = []
    text_n = _norm(text)
    for med in order.get("meds", []):
        name = med.get("name", "")
        if name and _norm(name) not in text_n:
            flags.append(f"漏掉醫囑藥名：{name}")
    order_strings = list(_strings(order))
    # 醫囑裡的劑量也用同一個運算式抽出來，正規化後逐一完全比對（2.5mg 不能放行 5mg）
    ordered = {d for s in order_strings for d in _doses(s)}
    shown = []
    for m in _DOSE.finditer(unicodedata.normalize("NFKC", text)):
        if m.group(0) not in shown:
            shown.append(m.group(0))
            if _norm(m.group(0)) not in ordered:
                flags.append(f"醫囑沒有這個劑量：{m.group(0)}")
    # 劑量已在上面逐一判斷，這裡一併放行，避免同一個劑量被標兩次
    order_text = unicodedata.normalize("NFKC", " ".join(order_strings))
    advice = [w for w in _ADVICE_WORDS if w in order_text]
    return flags + check_ai_text(text, allowed=order_strings + shown + advice)
