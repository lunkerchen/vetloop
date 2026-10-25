"""呼叫 Claude CLI 取得結構化輸出（逾時與重試都有上限）。"""
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
ATTEMPTS = 2  # 第一次加上最多 1 次重試

# macOS 要 USER/LOGNAME 才找得到 Claude CLI 的登入；其餘環境變數（含金鑰）一律不帶
_ENV_KEYS = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
             "CLAUDE_CONFIG_DIR")
_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class LLMError(RuntimeError):
    pass


def _stdin_message(user_text: str, image_path) -> bytes:
    content = []
    if image_path:
        path = Path(image_path)
        media_type = _MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            raise LLMError("只支援 png / jpg 圖片")
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as e:
            raise LLMError(f"讀不到圖片：{e.strerror}") from None
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": data}})
    content.append({"type": "text", "text": user_text})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")


def _structured_output(stdout: bytes):
    """取最後一個 type == result 事件的 structured_output；沒有就回 None。"""
    result = None
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    if result is None or result.get("is_error"):
        return None
    output = result.get("structured_output")
    return output if isinstance(output, dict) else None


def ask(system: str, user_text: str, schema: dict, image_path: str | None = None,
        timeout: float = 60, *, executable: str = "claude") -> dict:
    """問一次 Claude，回傳符合 schema 的 dict。失敗丟 LLMError。executable 讓測試換成假執行檔。"""
    argv = [
        executable, "--print", "--safe-mode", "--tools", "", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
        "--no-session-persistence", "--no-chrome", "--permission-mode", "dontAsk",
        "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--model", os.environ.get("VETLOOP_MODEL") or DEFAULT_MODEL,
        "--effort", "medium", "--system-prompt", system,
    ]
    stdin = _stdin_message(user_text, image_path)
    env = {k: os.environ[k] for k in _ENV_KEYS if k in os.environ}
    reason = ""
    for _ in range(ATTEMPTS):
        try:
            # 在空的暫存目錄執行，CLI 才不會讀到別的專案的設定
            with tempfile.TemporaryDirectory(prefix="vetloop-llm-") as cwd:
                done = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout,
                                      env=env, cwd=cwd)
        except subprocess.TimeoutExpired:
            reason = f"Claude CLI 逾時（{timeout} 秒）"
            continue
        except OSError as e:
            reason = f"無法執行 Claude CLI：{e.strerror}"
            continue
        if done.returncode != 0:
            reason = f"Claude CLI 結束碼 {done.returncode}"
            continue
        output = _structured_output(done.stdout)
        if output is not None:
            return output
        reason = "Claude CLI 沒有回傳 structured_output"
    raise LLMError(reason)
