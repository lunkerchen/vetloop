"""把 record.mjs 的影格序列轉成 30fps H.264，三支影片共用同一個時間原點。

用法：python3 build_clips.py [raw 目錄] [輸出目錄]
輸出：<out>/<page>.mp4 與 <out>/timeline.json（每個事件換算成影片秒數，HyperFrames 用來對時）。
"""
import json
import subprocess
import sys
from pathlib import Path

raw = Path(sys.argv[1] if len(sys.argv) > 1 else "raw").resolve()
out = Path(sys.argv[2] if len(sys.argv) > 2 else "film/assets").resolve()
out.mkdir(parents=True, exist_ok=True)

# 手機頁有大片留白，只留手機與系統紀錄面板（畫格像素）
CROP = {"phone1": "1920:2160:960:0", "phone2": "1920:2160:960:0", "clinic": None}

pages = {p: json.loads((raw / p / "frames.json").read_text()) for p in CROP}
events = json.loads((raw / "events.json").read_text())
origin = min(f["frames"][0]["t"] for f in pages.values())
end = max(e["t"] for e in events) + 2.0

for name, meta in pages.items():
    frames = meta["frames"]
    lines = []
    # 從共同原點開始：較晚開始的頁面先停在第一格
    times = [origin] + [f["t"] for f in frames[1:]] + [end]
    for f, t0, t1 in zip(frames, times, times[1:]):
        lines.append(f"file '{raw / name / f['file']}'\nduration {max(t1 - t0, 0.001):.4f}")
    lines.append(f"file '{raw / name / frames[-1]['file']}'")  # concat demuxer 需要最後一格再列一次
    listfile = out / f"{name}.txt"
    listfile.write_text("\n".join(lines) + "\n")
    vf = "fps=30"
    if CROP[name]:
        vf = f"crop={CROP[name]}," + vf
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-vf", vf + ",format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-g", "30", "-movflags", "+faststart", "-an", str(out / f"{name}.mp4")],
        check=True, timeout=1800)
    listfile.unlink()
    print(name, "ok")

timeline = [{"t": round(e["t"] - origin, 3), **{k: v for k, v in e.items() if k != "t"}} for e in events]
(out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1))
print("duration", round(end - origin, 2))
