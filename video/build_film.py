"""產生 film/index.html：剪輯表、鏡頭運動、字卡全部寫在這裡，改這支再重跑即可。

用法：python3 build_film.py
輸入：film/assets/{phone1,phone2,clinic}.mp4 與 timeline.json（build_clips.py 產生）
配樂不在這裡處理，渲染後由 finish.sh 用 ffmpeg 混入。
"""
import html
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILM = ROOT / "film"
EV = {e["label"]: e for e in json.loads((FILM / "assets/timeline.json").read_text())}

# 配樂對拍：歌曲 92.0s 的重拍落在標題出現，198.5s 的收尾重音落在片尾卡
MUSIC_IN = 87.5
TITLE_AT = 92.0 - MUSIC_IN          # 4.5
END_AT = 198.5 - MUSIC_IN           # 111.0
END_CARD_AT = END_AT - 2.0          # 片尾卡提早 2 秒進場，提示文字停留約 9 秒；重音處標誌再彈一次
TOTAL = END_AT + 8.0                # 119.0
DEMO_AT = 9.0
WAIT_CAP = 3.0                      # 4× 以上的快轉段都是等 LLM；重試拉長的等待也壓在這個秒數內

DISCLAIMER = "本作品提供之資訊僅供輔助參考，不能取代獸醫師之診斷、治療或專業建議。貓犬之健康與營養需求可能因個體狀況而異，如有健康疑慮或需要調整飲食與照護方式，請諮詢合格獸醫師。"

# 舞台（右側）與字卡欄（左側）
VP = dict(x=680, y=40, w=1200, h=1000)
CHROME = 44                          # 診所畫面的視窗標題列
DIMS = {"phone1": (1920, 2160), "phone2": (1920, 2160), "clinic": (3200, 1800)}


def view(page):
    return (VP["w"], VP["h"] - CHROME) if page == "clinic" else (VP["w"], VP["h"])


def bubble(label, pad=40, extra_h=0):
    """手機事件的 rect 是原始畫格座標，片段已裁掉左邊 960px。"""
    r = EV[label]["rect"]
    return (r["x"] - 960 - pad, r["y"] - pad, r["width"] + 2 * pad, r["height"] + 2 * pad + extra_h)


def frame(page, rect, cap=None, fill=0.94):
    W, H = DIMS[page]
    vw, vh = view(page)
    x, y, w, h = rect
    s = min(vw * fill / w, vh * fill / h)
    if cap:
        s = min(s, cap)
    tx = vw / 2 - s * (x + w / 2)
    ty = vh / 2 - s * (y + h / 2)
    if page == "clinic":                # 診所頁不露出頁面外的空白；手機頁四周本來就是白底，置中即可
        tx = min(0, max(vw - s * W, tx)) if s * W >= vw else (vw - s * W) / 2
        ty = min(0, max(vh - s * H, ty)) if s * H >= vh else (vh - s * H) / 2
    return round(tx, 1), round(ty, 1), round(s, 4)


T = lambda label: EV[label]["t"]

PLAN_SHOWN = T("plan") - 1.7          # 照護計畫頁實際出現（plan 事件是偵測到草稿完成的時間）
REMIND_SHOWN = T("remind:received") - 1.6  # 提醒實際出現在手機上的時間
PH_ALL = (20, 40, 1840, 2080)        # 手機＋系統紀錄
PB = lambda h: (0, 1990 - h, 960, h)  # 只看手機，貼齊聊天室底部（新訊息出現的位置）
PT = lambda y, h: (0, y, 960, h)
PHONE_ONLY = 1000                     # 框寬不超過這個值時，蓋掉右側系統紀錄
CL_PAGE = (0, 0, 3200, 1250)
CL_LEFT = (40, 140, 1440, 1660)
CL_ORDER = (1470, 200, 1680, 1600)
CL_PLAN = (80, 200, 3040, 1458)
CL_PLAN_ORDER = (120, 330, 1500, 1000)
CL_PLAN_AI = (1600, 360, 1480, 1250)
CL_Q_ALL = (143, 443, 2914, 997)
CL_Q_LEFT = (143, 500, 1430, 950)
CL_Q_DRAFT = (1628, 597, 1429, 792)
CL_ALERT = (1900, 190, 1240, 580)

# 字卡（標題沿用簡報第 03 頁流程用字）
STEPS = {
    "01": ["飼主描述狀況", "（可附照片）"],
    "02": ["系統固定問句追問", "AI 整理問診摘要"],
    "03": ["獸醫看摘要", "開立醫囑"],
    "04": ["AI 改寫為白話", "照護計畫"],
    "05": ["獸醫核可後", "送達飼主"],
    "06": ["依醫囑定時提醒", "飼主回報狀況"],
    "07": ["AI 起草回覆", "獸醫審核後送出"],
    "緊急": ["緊急分流"],
}
PILLS = list(STEPS)

# 剪輯表：(頁面, 來源起, 來源迄, 速度, 鏡頭 [(片段內秒數, 框, 上限)], 字卡 [(片段內秒數, 步驟, 說明)], 標籤)
SHOTS = [
    ("phone1", 0.6, T("intake1:sent"), 1, [(0, PH_ALL, None)],
     [(0.3, "01", "飼主像聊天一樣說明狀況，也能附上照片。")], None),
    ("phone1", T("intake1:sent"), T("intake1:replied"), 4, [], [], "快轉 4×"),
    ("phone1", T("intake1:replied"), T("intake2:sent"), 1,
     [(0.1, (40, 330, 1840, 900), None), (2.6, PH_ALL, None)],
     [(0.4, "02", "追問句是固定的；AI 只從飼主原話擷取 8 個欄位。")], None),
    ("phone1", T("intake2:sent"), T("intake2:replied"), 5, [], [], "快轉 5×"),
    ("phone1", T("intake2:replied"), T("intake3:sent"), 2, [], [], "快轉 2×"),
    ("phone1", T("intake3:sent"), T("intake3:replied"), 4, [], [], "快轉 4×"),
    ("phone1", T("intake3:replied"), T("intake4:sent"), 2, [], [], "快轉 2×"),
    ("phone1", T("intake4:sent"), T("intake4:replied"), 4, [], [], "快轉 4×"),
    ("phone1", T("intake4:replied"), T("list") - 0.2, 1, [(0.1, PB(800), 1.175)],
     [(0.3, "02", "整理結果先給飼主確認，才送到醫院。")], None),

    ("clinic", T("list") - 0.6, T("summary:pending"), 1, [(0, CL_PAGE, None)],
     [(0.1, "02", "飼主確認後，摘要與原話、照片一起送到診所後台。")], None),
    ("clinic", T("summary:pending"), T("summary"), 4, [(0.2, CL_LEFT, None)], [], "快轉 4×"),
    ("clinic", T("summary"), T("summary") + 1.5, 0.5, [(0.3, (60, 300, 1400, 1000), None)], [], None),
    ("clinic", T("summary") + 1.5, T("order:start"), 1, [(0.1, CL_LEFT, None)], [], None),
    ("clinic", T("order:start"), T("order:filled"), 2, [(0.05, CL_ORDER, None)],
     [(0.1, "03", "用藥、飲食、回診與觀察重點，都由獸醫填寫。")], "快轉 2×"),
    ("clinic", T("order:filled"), T("order:submitted"), 1, [], [], None),
    ("clinic", T("order:submitted"), PLAN_SHOWN, 4, [], [], "快轉 4×"),
    ("clinic", PLAN_SHOWN, PLAN_SHOWN + 0.2, 1, [(0, CL_PLAN, None)],
     [(0.05, "04", "用藥照醫囑原文；其餘改寫成白話。護欄自動比對藥名、劑量與用語。")], None),
    ("clinic", PLAN_SHOWN + 0.2, PLAN_SHOWN + 1.6, 0.3,
     [(0.3, CL_PLAN_ORDER, None), (2.7, CL_PLAN_AI, None)], [], None),
    ("clinic", PLAN_SHOWN + 1.6, T("plan:approved") + 0.4, 1, [],
     [(T("plan:approved") - PLAN_SHOWN - 2.4, "05", "未經獸醫核可，飼主端不會收到任何健康內容。")], None),

    ("phone1", T("plan:received") - 0.6, REMIND_SHOWN - 0.2, 0.6, [(0, PB(1100), 1.175)],
     [(2.0, "05", "訊息標明「這是王醫師的醫囑」，並附完整提示文字。")], None),
    ("phone1", REMIND_SHOWN - 0.2, T("remind:acked") + 0.8, 1, [(0.3, PB(1000), 1.175)],
     [(0.3, "06", "提醒依醫囑排程；飼主一鍵回覆「已餵」。")], "示範：快轉至提醒時間"),
    ("phone1", T("remind:acked") + 0.8, T("followup:sent"), 1, [(0.05, PB(900), 1.175)],
     [(0.8, "06", "飼主隨時回報新狀況，系統先回覆收到。")], None),
    ("phone1", T("followup:sent"), T("followup:replied"), 4, [], [], "快轉 4×"),
    ("phone1", T("followup:replied"), T("followup:replied") + 2.4, 1, [], [], None),

    ("clinic", T("queue") - 0.5, T("queue"), 0.25, [(0, CL_Q_ALL, None), (0.6, CL_Q_LEFT, None)],
     [(0.1, "07", "AI 起草回覆，放進待審佇列，附變化摘要與護欄檢查。")], None),
    ("clinic", T("queue"), T("queue:approved") - 0.1, 1, [(0.2, CL_Q_DRAFT, None)],
     [(2.1, "07", "獸醫可直接改字，核可後才送出。")], None),
    ("phone1", T("reply:received") - 0.4, T("reply:received") + 4.4, 1, [(0, PB(950), 1.175)],
     [(1.8, "07", "飼主收到的回覆標明「王醫師已確認」。")], None),

    ("phone2", T("emergency:sent") - 1.8, T("emergency:replied") + 2.0, 1,
     [(0, PH_ALL, None), (2.3, PT(470, 760), 1.175)],
     [(0.2, "緊急", "訊息含緊急字眼（例如誤吞異物）時不經 AI，立即請飼主致電醫院。")], None),
    ("clinic", T("emergency:alert") - 0.5, T("emergency:alert") + 5.2, 1,
     [(0, CL_PAGE, None), (0.9, CL_ALERT, None)],
     [(0.4, "緊急", "後台同步轉紅通知，獸醫立即看到。")], None),
]

TAGS = {"phone1": "飼主手機畫面", "phone2": "飼主手機畫面", "clinic": "診所後台畫面"}


def build():
    vids, chips, cams, beats, tags = [], [], [], [], []
    t = DEMO_AT
    prev_page = None
    switches = []                     # (時間, 離開的舞台, 進入的舞台)
    for i, (page, a, b, rate, camk, capk, chip) in enumerate(SHOTS):
        if rate >= 4 and (b - a) / rate > WAIT_CAP:
            rate = math.ceil((b - a) / WAIT_CAP)
            chip = f"快轉 {rate}×"
        if rate > 1 and (b - a) / rate < 0.6:   # 短到放不下快轉標示，就用原速播
            rate, chip = 1, None
        dur = (b - a) / rate
        assert dur > 0, (i, a, b)
        vids.append(dict(id=f"s{i}", page=page, start=t, dur=dur, ms=a, rate=rate))
        for off, rect, cap in camk:
            cams.append((page, t + off, frame(page, rect, cap), off == 0, rect))
        for off, step, desc in capk:
            beats.append((t + off, step, desc))
        if prev_page != page:
            switches.append((t, prev_page, page))
            tags.append((t, TAGS[page]))
        if chip:
            chips.append((t + 0.15, min(dur, 3.0 if "示範" in chip else dur) - 0.3, chip))
        prev_page = page
        t += dur
    return vids, chips, cams, beats, tags, switches, t


def esc(s):
    return html.escape(s, quote=True)


def main():
    vids, chips, cams, beats, tags, switches, demo_end = build()
    recap_dur = END_CARD_AT - demo_end
    print(f"demo {DEMO_AT:.1f}–{demo_end:.2f}s, recap {recap_dur:.2f}s, total {TOTAL:.1f}s")
    assert 6.0 <= recap_dur <= 9.5, "recap 長度不對，調整剪輯表"

    out = []
    js = []
    w = out.append

    # 舞台
    for page in ("clinic", "phone1", "phone2"):
        W, H = DIMS[page]
        chrome = page == "clinic"
        w(f'<div class="stage{" win" if chrome else ""}" id="st-{page}">')
        if chrome:
            w('<div class="chrome"><i></i><i></i><i></i><span>示範動物醫院 後台（VetLoop Prototype）</span></div>')
        w(f'<div class="vp"><div class="cam" id="cam-{page}" style="width:{W}px;height:{H}px">')
        if not chrome:
            w(f'<div class="cover" id="cover-{page}"></div>')
        for v in vids:
            if v["page"] != page:
                continue
            w(f'<video id="{v["id"]}" class="vid" src="assets/{page}.mp4" muted playsinline '
              f'data-start="{v["start"]:.3f}" data-duration="{v["dur"]:.3f}" data-media-start="{v["ms"]:.3f}" '
              f'data-playback-rate="{v["rate"]}" data-track-index="1" style="width:{W}px;height:{H}px"></video>')
        w("</div></div></div>")

    # 鏡頭
    seen = set()
    for page, at, (x, y, s), cut, rect in cams:
        targets = [(f"#cam-{page}", f"x:{x},y:{y},scale:{s}")]
        if page != "clinic":
            targets.append((f"#cover-{page}", f"opacity:{1 if rect[2] <= PHONE_ONLY else 0}"))
        for sel, props in targets:
            if page not in seen or cut:
                js.append(f'tl.set("{sel}",{{{props}}},{at:.3f});')
            else:
                js.append(f'tl.to("{sel}",{{{props},duration:1.0,ease:"power2.inOut"}},{at:.3f});')
        seen.add(page)

    # 舞台切換：淡出 → 白 → 淡入
    for at, old, new in switches:
        if old:
            js.append(f'tl.to("#st-{old}",{{opacity:0,duration:0.25,ease:"power1.in"}},{at - 0.25:.3f});')
        js.append(f'tl.to("#st-{new}",{{opacity:1,duration:0.35,ease:"power1.out"}},{at:.3f});')
    js.append(f'tl.to(".stage",{{opacity:0,duration:0.4}},{demo_end - 0.4:.3f});')

    # 左欄常駐元素
    demo_dur = demo_end - DEMO_AT
    w(f'<div id="ui" class="clip" data-start="{DEMO_AT}" data-duration="{demo_dur:.3f}" data-track-index="2">'
      '<div class="brand"><i class="ring"></i>VetLoop<span>Prototype 實機操作</span></div>'
      '<div class="badge">模擬案例｜醫院、醫師、飼主與寵物皆為虛構</div>'
      '<div class="pills">' + "".join(f'<b id="pill{i}">{esc(p)}</b>' for i, p in enumerate(PILLS)) + "</div>"
      f'<p class="foot">{DISCLAIMER}</p></div>')
    js.append(f'tl.fromTo("#ui > *",{{opacity:0,y:16}},{{opacity:1,y:0,duration:0.6,stagger:0.08,ease:"power2.out"}},{DEMO_AT:.3f});')
    js.append(f'tl.to("#ui > *",{{opacity:0,duration:0.4}},{demo_end - 0.4:.3f});')

    def window(items, end):
        return [(a, (items[i + 1][0] if i + 1 < len(items) else end) - a, *rest) for i, (a, *rest) in enumerate(items)]

    # 頁面標籤
    for i, (a, d, text) in enumerate(window(tags, demo_end)):
        w(f'<div id="tag{i}" class="clip tag" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="3">{esc(text)}</div>')
        js.append(f'tl.fromTo("#tag{i}",{{opacity:0,x:-12}},{{opacity:1,x:0,duration:0.4}},{a + 0.05:.3f});')
        js.append(f'tl.to("#tag{i}",{{opacity:0,duration:0.2}},{a + d - 0.2:.3f});')

    # 步驟標題（同一步驟只進場一次）
    steps = []
    for a, step, _ in beats:
        if not steps or steps[-1][1] != step:
            steps.append((a, step))
    for i, (a, d, step) in enumerate(window(steps, demo_end)):
        lines = "".join(f"<span>{esc(l)}</span>" for l in STEPS[step])
        num = step if step != "緊急" else "!"
        w(f'<div id="step{i}" class="clip step{" urgent" if step == "緊急" else ""}" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="4">'
          f'<div class="num">{esc(num)}</div><h2>{lines}</h2></div>')
        js.append(f'tl.fromTo("#step{i} .num",{{opacity:0,y:30}},{{opacity:1,y:0,duration:0.5,ease:"power3.out"}},{a:.3f});')
        js.append(f'tl.fromTo("#step{i} h2 span",{{opacity:0,y:24}},{{opacity:1,y:0,duration:0.5,stagger:0.08,ease:"power3.out"}},{a + 0.08:.3f});')
        js.append(f'tl.to("#step{i}",{{opacity:0,duration:0.25}},{a + d - 0.25:.3f});')
        k = PILLS.index(step)
        js.append(f'tl.to("#pill{k}",{{backgroundColor:"#D7263D",color:"#fff",borderColor:"#D7263D",duration:0.3}},{a:.3f});')
        if i + 1 < len(steps):
            js.append(f'tl.to("#pill{k}",{{backgroundColor:"#FDECEE",color:"#B01E31",borderColor:"#FDECEE",duration:0.3}},{a + d:.3f});')

    # 說明文字
    for i, (a, d, _step, desc) in enumerate(window(beats, demo_end)):
        w(f'<p id="desc{i}" class="clip desc" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="5">{esc(desc)}</p>')
        js.append(f'tl.fromTo("#desc{i}",{{opacity:0,y:18}},{{opacity:1,y:0,duration:0.5,ease:"power2.out"}},{a + 0.2:.3f});')
        js.append(f'tl.to("#desc{i}",{{opacity:0,duration:0.2}},{a + d - 0.2:.3f});')

    # 快轉標籤
    for i, (a, d, text) in enumerate(chips):
        w(f'<div id="chip{i}" class="clip chip" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="6">{esc(text)}</div>')
        js.append(f'tl.fromTo("#chip{i}",{{opacity:0,scale:0.9}},{{opacity:1,scale:1,duration:0.2}},{a:.3f});')
        js.append(f'tl.to("#chip{i}",{{opacity:0,duration:0.15}},{a + d - 0.15:.3f});')

    # 開場：問題
    w(f'<div id="hook" class="clip card" data-start="0" data-duration="{TITLE_AT:.3f}" data-track-index="7">'
      '<p class="h1">看完診，照護才剛開始。</p>'
      '<p class="h2">飼主回報分散、醫囑易漏，獸醫難以即時掌握。</p></div>')
    js += [
        'tl.fromTo("#hook .h1",{scale:1.04},{scale:1,duration:1.6,ease:"power2.out"},0);',
        'tl.fromTo("#hook .h2",{opacity:0,y:20},{opacity:1,y:0,duration:0.7,ease:"power2.out"},0.9);',
        f'tl.to("#hook p",{{opacity:0,y:-10,duration:0.35,ease:"power1.in"}},{TITLE_AT - 0.4:.3f});',
    ]

    # 標題
    ring = ('<svg class="mark" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="none" stroke="#D7263D" '
            'stroke-width="15" stroke-dasharray="188.5 251.3" transform="rotate(10 50 50)"/></svg>')
    w(f'<div id="title" class="clip card" data-start="{TITLE_AT:.3f}" data-duration="{DEMO_AT - TITLE_AT:.3f}" data-track-index="7">'
      f'<div class="logo">{ring}<span>VetLoop</span></div>'
      '<p class="sub">獸醫在環的照護助手</p>'
      '<p class="tagline">AI 整理<i></i>獸醫核可<i></i>才送到飼主手上</p>'
      '<p class="meta">主題：獸醫照護　｜　團隊：金橘守醫</p></div>')
    js += [
        f'tl.fromTo("#title circle",{{strokeDashoffset:188.5}},{{strokeDashoffset:0,duration:0.9,ease:"power3.out"}},{TITLE_AT:.3f});',
        f'tl.fromTo("#title .logo span",{{opacity:0,x:-24}},{{opacity:1,x:0,duration:0.7,ease:"power3.out"}},{TITLE_AT + 0.15:.3f});',
        f'tl.fromTo("#title .sub",{{opacity:0,y:16}},{{opacity:1,y:0,duration:0.6}},{TITLE_AT + 0.6:.3f});',
        f'tl.fromTo("#title .tagline",{{opacity:0,y:16}},{{opacity:1,y:0,duration:0.6}},{TITLE_AT + 1.0:.3f});',
        f'tl.fromTo("#title .meta",{{opacity:0}},{{opacity:1,duration:0.6}},{TITLE_AT + 1.5:.3f});',
        f'tl.to("#title > *",{{opacity:0,y:-12,duration:0.35,ease:"power1.in"}},{DEMO_AT - 0.4:.3f});',
    ]

    # 收尾：三道護欄
    cards = [
        ("AI 只整理與起草", "產出經規則比對：不得含病名、診斷、劑量建議或品牌。"),
        ("健康內容都經獸醫核可", "照護計畫與回覆，獸醫核可後才送到飼主手上。"),
        ("緊急字眼不經 AI", "直接請飼主致電醫院，後台同步轉紅通知。"),
    ]
    w(f'<div id="recap" class="clip card" data-start="{demo_end:.3f}" data-duration="{recap_dur:.3f}" data-track-index="7">'
      '<p class="kicker">三道護欄</p><p class="head">AI 整理，獸醫核可，才送到飼主手上</p><div class="cards">'
      + "".join(f'<div><b>{i + 1}</b><h3>{esc(h)}</h3><p>{esc(p)}</p></div>' for i, (h, p) in enumerate(cards))
      + '</div><p class="proof">可執行的 Prototype　·　171 個自動化測試通過（測試使用假的 LLM）　·　全部為模擬案例</p></div>')
    js += [
        f'tl.fromTo("#recap .kicker, #recap .head",{{opacity:0,y:20}},{{opacity:1,y:0,duration:0.6,stagger:0.12,ease:"power2.out"}},{demo_end + 0.1:.3f});',
        f'tl.fromTo("#recap .cards > div",{{opacity:0,y:30}},{{opacity:1,y:0,duration:0.6,stagger:0.25,ease:"power3.out"}},{demo_end + 0.7:.3f});',
        f'tl.fromTo("#recap .proof",{{opacity:0}},{{opacity:1,duration:0.6}},{demo_end + 1.8:.3f});',
        f'tl.fromTo("#recap .cards",{{scale:1}},{{scale:1.035,duration:{recap_dur:.3f},ease:"none"}},{demo_end:.3f});',
        f'tl.to("#recap > *",{{opacity:0,duration:0.35,ease:"power1.in"}},{END_CARD_AT - 0.4:.3f});',
    ]

    # 片尾
    w(f'<div id="end" class="clip card" data-hold data-start="{END_CARD_AT:.3f}" data-duration="{TOTAL - END_CARD_AT:.3f}" data-track-index="7">'
      f'<div class="logo">{ring}<span>VetLoop</span></div>'
      '<p class="sub">獸醫在環的照護助手</p>'
      '<p class="links">github.com/lunkerchen/vetloop　｜　團隊：金橘守醫</p>'
      f'<p class="legal">{DISCLAIMER}</p>'
      '<p class="credit">影片中的醫院、醫師、飼主與寵物皆為模擬案例，不含真實診療資料。<br>'
      '音樂：Corporate Explainer Video（alex-morgan，Pixabay Content License）　字型：思源黑體（SIL Open Font License）</p></div>')
    js += [
        f'tl.fromTo("#end .mark",{{scale:0.6,opacity:0}},{{scale:1,opacity:1,duration:0.6,ease:"back.out(2)"}},{END_CARD_AT:.3f});',
        f'tl.fromTo("#end circle",{{strokeDashoffset:188.5}},{{strokeDashoffset:0,duration:0.8,ease:"power3.out"}},{END_CARD_AT:.3f});',
        f'tl.fromTo("#end .logo span, #end .sub",{{opacity:0,y:16}},{{opacity:1,y:0,duration:0.6,stagger:0.12}},{END_CARD_AT + 0.2:.3f});',
        f'tl.fromTo("#end .links, #end .legal, #end .credit",{{opacity:0}},{{opacity:1,duration:0.6,stagger:0.15}},{END_CARD_AT + 0.6:.3f});',
        f'tl.to("#end .mark",{{scale:1.12,duration:0.12,ease:"power2.out",yoyo:true,repeat:1}},{END_AT:.3f});',
        f'tl.to("#end > *",{{opacity:0,duration:0.6}},{TOTAL - 0.7:.3f});',
    ]

    body = "\n".join(out)
    page = (ROOT / "film.template.html").read_text()
    page = page.replace("{{TOTAL}}", f"{TOTAL:.3f}").replace("{{BODY}}", body).replace("{{JS}}", "\n".join(js))
    (FILM / "index.html").write_text(page)
    subset_fonts(page)


def subset_fonts(page):
    """字型只留用到的字，渲染時少載 50MB。"""
    text = "".join(sorted(set(page))) + "0123456789"
    (FILM / "assets/fonts").mkdir(parents=True, exist_ok=True)
    (FILM / "assets/fonts/chars.txt").write_text(text)
    for wt in ("Regular", "Medium", "Bold"):
        src = Path.home() / f"Library/Fonts/SourceHanSansTC-{wt}.otf"
        subprocess.run(["pyftsubset", str(src), f"--text-file={FILM / 'assets/fonts/chars.txt'}",
                        f"--output-file={FILM / f'assets/fonts/shs-{wt}.otf'}"], check=True, timeout=300)


if __name__ == "__main__":
    main()
