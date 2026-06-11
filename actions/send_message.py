import time
import pyautogui
from pathlib import Path

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

try:
    from actions.open_app import open_app as _open_app_module
    _HAS_OPEN_APP = True
except ImportError:
    _HAS_OPEN_APP = False


# ---------------------------------------------------------------------------
# WhatsApp — keyed exactly on what the debug showed
# ---------------------------------------------------------------------------

_WA_PROCESS = "whatsapp.root.exe"   # exact name psutil sees
_WA_HWND_PID = None                 # cached after first focus


def _is_whatsapp_running() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"].lower() == _WA_PROCESS:
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _get_whatsapp_hwnd():
    """
    Returns (hwnd, title) for the real WhatsApp Desktop window.
    Matches by:
      - process name == WhatsApp.Root.exe   (exact, from debug output)
      - window is visible and has a non-empty title
    Excludes msedgewebview2 / chrome / anything not WhatsApp.Root.exe.
    """
    try:
        import win32gui
        import win32process
        import psutil

        result = [None, ""]

        def _cb(hwnd, _):
            if result[0]:           # already found
                return
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            try:
                _, pid  = win32process.GetWindowThreadProcessId(hwnd)
                pname   = psutil.Process(pid).name().lower()
                if pname == _WA_PROCESS:          # exact match only
                    result[0] = hwnd
                    result[1] = title
            except Exception:
                pass

        win32gui.EnumWindows(_cb, None)
        return result[0], result[1]

    except ImportError:
        return None, ""


def _focus_whatsapp() -> tuple:
    """Force-focus the WhatsApp window. Returns (hwnd, title)."""
    try:
        import win32gui
        import win32con

        hwnd, title = _get_whatsapp_hwnd()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.7)
            # re-read title after focus (chat title may now be visible)
            title = win32gui.GetWindowText(hwnd).strip()
        return hwnd, title

    except Exception as e:
        print(f"[SendMessage] focus error: {e}")
        return None, ""


def _send_whatsapp(receiver: str, message: str) -> str:
    try:
        if not _is_whatsapp_running():
            print("[SendMessage] WhatsApp not running → launching")
            if _HAS_OPEN_APP:
                _open_app_module({"app_name": "whatsapp"})
            else:
                pyautogui.press("win")
                time.sleep(0.4)
                pyautogui.write("WhatsApp", interval=0.04)
                time.sleep(0.5)
                pyautogui.press("enter")
            time.sleep(2.5)

        hwnd, title = _focus_whatsapp()
        print(f"[SendMessage] HWND={hwnd} title='{title}'")

        if not hwnd:
            return "Could not find or focus WhatsApp window."

        # Determine if already in the right chat
        # Title is either "WhatsApp" (home) or "<Name> - WhatsApp" (in chat)
        if " - WhatsApp" in title:
            open_contact = title.replace(" - WhatsApp", "").strip().lower()
        else:
            open_contact = ""

        already_in_chat = open_contact == receiver.strip().lower()

        if already_in_chat:
            print(f"[SendMessage] Already in {receiver}'s chat — skipping search")
        else:
            print(f"[SendMessage] Searching for: {receiver}")
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.write(receiver, interval=0.04)
            time.sleep(1.0)
            pyautogui.press("enter")
            time.sleep(0.8)

        pyautogui.write(message, interval=0.03)
        time.sleep(0.2)
        pyautogui.press("enter")

        return f"Message sent to {receiver} via WhatsApp."

    except Exception as e:
        return f"WhatsApp error: {e}"


# ---------------------------------------------------------------------------
# Other platforms
# ---------------------------------------------------------------------------

def _open_app(app_name: str):
    if _HAS_OPEN_APP:
        _open_app_module({"app_name": app_name})
    else:
        pyautogui.press("win")
        time.sleep(0.4)
        pyautogui.write(app_name, interval=0.04)
        time.sleep(0.5)
        pyautogui.press("enter")
        time.sleep(2.5)


def _send_instagram(receiver: str, message: str) -> str:
    try:
        import webbrowser
        webbrowser.open("https://www.instagram.com/direct/new/")
        time.sleep(3.5)
        pyautogui.write(receiver, interval=0.05)
        time.sleep(1.5)
        pyautogui.press("down")
        time.sleep(0.3)
        pyautogui.press("enter")
        time.sleep(0.5)
        for _ in range(3):
            pyautogui.press("tab")
            time.sleep(0.1)
        pyautogui.press("enter")
        time.sleep(1.5)
        pyautogui.write(message, interval=0.04)
        time.sleep(0.2)
        pyautogui.press("enter")
        return f"Message sent to {receiver} via Instagram."
    except Exception as e:
        return f"Instagram error: {e}"


def _send_telegram(receiver: str, message: str) -> str:
    try:
        _open_app("telegram")
        time.sleep(1.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.write(receiver, interval=0.04)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)
        pyautogui.write(message, interval=0.03)
        time.sleep(0.2)
        pyautogui.press("enter")
        return f"Message sent to {receiver} via Telegram."
    except Exception as e:
        return f"Telegram error: {e}"


def _send_generic(platform: str, receiver: str, message: str) -> str:
    try:
        _open_app(platform)
        time.sleep(1.5)
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.4)
        pyautogui.write(receiver, interval=0.04)
        time.sleep(1.0)
        pyautogui.press("enter")
        time.sleep(0.8)
        pyautogui.write(message, interval=0.03)
        time.sleep(0.2)
        pyautogui.press("enter")
        return f"Message sent to {receiver} via {platform}."
    except Exception as e:
        return f"{platform} error: {e}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    params       = parameters or {}
    receiver     = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform     = params.get("platform", "whatsapp").strip().lower()

    if not receiver:
        return "Please specify who to send the message to, sir."
    if not message_text:
        return "Please specify what message to send, sir."

    print(f"[SendMessage] 📨 {platform} → {receiver}: {message_text[:40]}")
    if player:
        player.write_log(f"[msg] Sending to {receiver} via {platform}...")

    if "whatsapp" in platform or "wp" in platform or "wapp" in platform:
        result = _send_whatsapp(receiver, message_text)
    elif "instagram" in platform or "ig" in platform or "insta" in platform:
        result = _send_instagram(receiver, message_text)
    elif "telegram" in platform or "tg" in platform:
        result = _send_telegram(receiver, message_text)
    else:
        result = _send_generic(platform, receiver, message_text)

    print(f"[SendMessage] ✅ {result}")
    if player:
        player.write_log(f"[msg] {result}")

    return result
