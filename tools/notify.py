"""Send a notification to the Windows desktop and/or a phone (via ntfy).

Standard library only. Configure in tools/notify.config.json (copy the
.example file). Test with:  python tools/notify.py --test
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE / "notify.config.json"

# Windows only shows toasts from a registered app id; PowerShell's is always present.
PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
PS_SCRIPT = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:NOTIFY_XML)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:NOTIFY_APP_ID).Show($toast)
"""


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_toast_xml(title, message, click_url):
    """Modern ToastGeneric; optionally clickable (protocol activation)."""
    texts = f"<text>{esc(title)}</text><text>{esc(message)}</text>"
    if click_url:
        url = esc(click_url)
        return (
            f'<toast activationType="protocol" launch="{url}" scenario="default">'
            f'<visual><binding template="ToastGeneric">{texts}</binding></visual>'
            f'<actions>'
            f'<action activationType="protocol" arguments="{url}" content="Open assistant"/>'
            f'<action activationType="system" arguments="dismiss" content="Dismiss"/>'
            f'</actions></toast>'
        )
    return (
        f'<toast scenario="default">'
        f'<visual><binding template="ToastGeneric">{texts}</binding></visual></toast>'
    )


def load_config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {"desktop": True, "ntfy_server": "https://ntfy.sh", "ntfy_topic": ""}


def send_desktop(title, message, click_url=None):
    if sys.platform != "win32":
        print(f"[desktop] {title}: {message}  (toasts only on Windows; printed instead)")
        return True
    env = dict(os.environ, NOTIFY_XML=build_toast_xml(title, message, click_url),
               NOTIFY_APP_ID=PS_APP_ID)
    # Windows PowerShell 5.1 (powershell.exe), not pwsh: only it can load these WinRT types.
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
        env=env, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("[desktop] failed:", result.stderr.strip(), file=sys.stderr)
        return False
    print("[desktop] sent")
    return True


def send_phone(cfg, title, message, priority, tags):
    topic = cfg.get("ntfy_topic", "").strip()
    if not topic:
        print("[phone] skipped: set ntfy_topic in tools/notify.config.json")
        return True
    payload = {"topic": topic, "title": title, "message": message, "priority": priority}
    if tags:
        payload["tags"] = tags
    req = urllib.request.Request(
        cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[phone] sent (HTTP {resp.status})")
            return True
    except Exception as exc:  # network down, bad server, etc.
        print(f"[phone] failed: {exc}", file=sys.stderr)
        return False


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--title", default="Assistant")
    p.add_argument("--message", default="")
    p.add_argument("--priority", type=int, default=3, choices=[1, 2, 3, 4, 5])
    p.add_argument("--tags", default="", help="comma-separated ntfy tags, e.g. calendar,warning")
    p.add_argument("--desktop-only", action="store_true")
    p.add_argument("--phone-only", action="store_true")
    p.add_argument("--test", action="store_true", help="send a test notification")
    p.add_argument("--click-url", default=None,
                   help="make the desktop toast clickable: opens this URL (button + body click)")
    a = p.parse_args()

    if a.test:
        a.title, a.message = "Assistant test", "If you can read this, notifications work."
    if not a.message:
        p.error("--message is required (or use --test)")

    cfg = load_config()
    tags = [t.strip() for t in a.tags.split(",") if t.strip()]
    ok = True
    if cfg.get("desktop", True) and not a.phone_only:
        ok &= send_desktop(a.title, a.message, a.click_url)
    if not a.desktop_only:
        ok &= send_phone(cfg, a.title, a.message, a.priority, tags)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
