"""F.L.I.N.T desktop shell — MISSION CONTROL edition.

A complete UI redesign: left navigation sidebar, central AI core with
animated orb, right intelligence feed, mission timeline, agent cards,
system monitor, memory insights, LLM status, and bottom voice bar.

Public surface (kept stable for main.py and every actions/ module):

    ui = FlintUI("face.png")
    ui.on_text_command = callback            # text commands from the user
    ui.set_state("LISTENING"|"THINKING"|"SPEAKING"|"PROCESSING")
    ui.write_log("Flint: hello")
    ui.muted / ui.current_file
    ui.wait_for_api_key()
    ui.start_speaking() / ui.stop_speaking()
    ui.root.mainloop()
    ui.set_link_clients(n)                   # remote phone clients online
    ui.attach_pipeline(pipeline)             # show live worker activity
    ui.show_toast(msg, level)
    ui.update_task_state(goal, text, active)
    ui.toggle_compact_mode()
    ui.wake_up()
"""

from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient, QShortcut, QTextCursor, QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget,
)

# ── Optional memory import ────────────────────────────────────────────────────
try:
    from memory.memory_manager import load_memory as _load_memory
    _HAS_MEMORY = True
except Exception:
    _HAS_MEMORY = False

    def _load_memory() -> dict:
        return {}


# ── Paths ─────────────────────────────────────────────────────────────────────
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1320, 840
_MIN_W,     _MIN_H     = 1060, 700

_OS            = platform.system()
_MONO          = "Cascadia Mono" if _OS == "Windows" else "Menlo"
_MONO_FALLBACK = "Consolas"
_UI_FONT       = "Segoe UI" if _OS == "Windows" else "SF Pro Text"


# ── Fonts ─────────────────────────────────────────────────────────────────────
def F(size: int, bold: bool = False) -> QFont:
    """UI font (Segoe UI / Arial fallback)."""
    f = QFont(_UI_FONT, size,
              QFont.Weight.Bold if bold else QFont.Weight.Normal)
    if not f.exactMatch():
        f = QFont("Arial", size,
                  QFont.Weight.Bold if bold else QFont.Weight.Normal)
    return f


def M(size: int, bold: bool = False) -> QFont:
    """Monospace font for terminal / log text."""
    f = QFont(_MONO, size,
              QFont.Weight.Bold if bold else QFont.Weight.Normal)
    if not f.exactMatch():
        f = QFont(_MONO_FALLBACK, size,
                  QFont.Weight.Bold if bold else QFont.Weight.Normal)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


# ── Theme: Mission Control ─────────────────────────────────────────────────────
class T:
    BG        = "#030811"       # void black
    SIDEBAR   = "#060c18"       # sidebar
    PANEL     = "#090f1c"       # glass panel
    PANEL2    = "#0d1525"       # slightly lighter panel
    INSET     = "#050a14"       # input inset
    BORDER    = "#0e1c33"       # subtle border
    BORDER_HI = "#1a3060"       # highlighted border

    CYAN      = "#00e5ff"       # primary neon
    CYAN_DIM  = "#0d6a82"
    CYAN_GHO  = "#061c26"
    VIOLET    = "#7c4dff"       # purple
    VIOLET_D  = "#1a0836"
    EMERALD   = "#00e676"       # green
    EMERALD_D = "#0a3a28"
    AMBER     = "#ffb300"       # orange/warning
    MAGENTA   = "#ff2d78"       # pink/muted
    RED       = "#ff1744"       # error

    TEXT      = "#7ab0c8"       # main text
    TEXT_DIM  = "#253a52"       # dim text
    TEXT_MED  = "#426882"       # medium text
    WHITE     = "#e0f8ff"       # bright text


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


_STATE_COLORS = {
    "LISTENING":    T.EMERALD,
    "SPEAKING":     T.AMBER,
    "THINKING":     T.CYAN,
    "PROCESSING":   T.VIOLET,
    "MUTED":        T.MAGENTA,
    "INITIALISING": T.CYAN,
}

_STATE_LABEL = {
    "LISTENING":    "● LISTENING",
    "SPEAKING":     "◉ SPEAKING",
    "THINKING":     "◌ THINKING...",
    "PROCESSING":   "◌ PROCESSING...",
    "MUTED":        "⊘ MUTED",
    "INITIALISING": "◌ INITIALISING...",
}


# ── System metrics (background thread) ────────────────────────────────────────
class _SysMetrics:
    def __init__(self):
        self.cpu = self.mem = self.net = 0.0
        self.gpu = self.tmp = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        threading.Thread(target=self._loop, daemon=True,
                         name="FlintMetrics").start()

    def _loop(self):
        while True:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        nc, now = psutil.net_io_counters(), time.time()
        dt = now - self._last_net_t
        net = (((nc.bytes_sent - self._last_net.bytes_sent)
                + (nc.bytes_recv - self._last_net.bytes_recv)) / dt
               / (1024 * 1024)) if dt > 0 else 0.0
        self._last_net, self._last_net_t = nc, now
        gpu, tmp = self._gpu(), self._temp()
        with self._lock:
            self.cpu, self.mem, self.net, self.gpu, self.tmp = cpu, mem, net, gpu, tmp

    @staticmethod
    def _gpu() -> float:
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                vals = [float(v) for v in r.stdout.split() if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass
        return -1.0

    @staticmethod
    def _temp() -> float:
        try:
            temps = psutil.sensors_temperatures()
            for name in ("coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "zenpower", "it8688"):
                if temps.get(name):
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {"cpu": self.cpu, "mem": self.mem, "net": self.net,
                    "gpu": self.gpu, "tmp": self.tmp}


_metrics = _SysMetrics()


# ── NeonPanel: animated glowing border panel ──────────────────────────────────
class NeonPanel(QFrame):
    _shared_phase = 0.0
    _phase_timer: QTimer | None = None
    _instances: list["NeonPanel"] = []

    def __init__(self, glow: str = T.CYAN, radius: int = 10,
                 sweep: bool = True, parent=None):
        super().__init__(parent)
        self._glow = glow
        self._radius = radius
        self._sweep = sweep
        self._intensity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        NeonPanel._instances.append(self)
        if NeonPanel._phase_timer is None:
            NeonPanel._phase_timer = QTimer()
            NeonPanel._phase_timer.timeout.connect(NeonPanel._advance)
            NeonPanel._phase_timer.start(33)

    @classmethod
    def _advance(cls):
        cls._shared_phase = (cls._shared_phase + 0.006) % 1.0
        for w in cls._instances:
            if w.isVisible():
                w.update()

    def set_glow(self, color: str, intensity: float = 1.0):
        self._glow = color
        self._intensity = intensity
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        r = QRectF(1.5, 1.5, W - 3, H - 3)

        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, QBrush(qcol(T.PANEL, 240)))

        for wd, al in [(3.5, 14), (2.0, 36), (1.0, 90)]:
            p.setPen(QPen(qcol(self._glow, int(al * self._intensity)), wd))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        if self._sweep:
            per = 2 * (W + H)
            pos = (NeonPanel._shared_phase * per) % per
            grad = QLinearGradient(0, 0, W, 0)
            seg = max(0.06, 90.0 / max(per, 1))
            t0 = pos / per
            g = QColor(self._glow)
            for k in range(-2, 3):
                tt = t0 + k * seg * 0.5
                if 0.0 <= tt <= 1.0:
                    g.setAlpha(max(0, 150 - abs(k) * 55))
                    grad.setColorAt(tt, g)
            p.setPen(QPen(QBrush(grad), 1.4))
            p.drawPath(path)


# ── Spinner ────────────────────────────────────────────────────────────────────
class Spinner(QWidget):
    def __init__(self, color: str = T.CYAN, size: int = 18, parent=None):
        super().__init__(parent)
        self._color = color
        self._angle = 0
        self.setFixedSize(size, size)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._spin)

    def start(self):
        self._tmr.start(16)
        self.show()

    def stop(self):
        self._tmr.stop()
        self.hide()

    def set_color(self, color: str):
        self._color = color

    def _spin(self):
        self._angle = (self._angle + 7) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(qcol(self._color, 45), 2))
        p.drawEllipse(rect)
        p.setPen(QPen(qcol(self._color), 2.2))
        p.drawArc(rect, int(-self._angle * 16), 100 * 16)
        p.setPen(QPen(qcol(self._color, 110), 1.4))
        p.drawArc(rect, int((-self._angle - 140) * 16), 50 * 16)


# ── HudCanvas: animated AI core orb ───────────────────────────────────────────
class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick = 0
        self._scale, self._tgt_scale = 1.0, 1.0
        self._halo,  self._tgt_halo  = 55.0, 55.0
        self._last_t  = time.time()
        self._scan,  self._scan2     = 0.0, 180.0
        self._rings  = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 60.0]
        self._loader_angle = 0.0
        self._blink        = True
        self._blink_tick   = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _col(self) -> str:
        if self.muted:    return T.MAGENTA
        if self.speaking: return T.AMBER
        return _STATE_COLORS.get(self.state, T.CYAN)

    def _busy(self) -> bool:
        return self.state in ("THINKING", "PROCESSING") and not self.speaking

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.10 if self.speaking else 0.45):
            if self.speaking:
                self._tgt_scale = random.uniform(1.05, 1.13)
                self._tgt_halo  = random.uniform(130, 180)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(12, 24)
            else:
                self._tgt_scale = random.uniform(1.001, 1.007)
                self._tgt_halo  = random.uniform(44, 62)
            self._last_t = now

        sp = 0.36 if self.speaking else 0.14
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.1, -0.75, 1.8] if self.speaking else [0.45, -0.28, 0.75]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan  = (self._scan  + (2.8 if self.speaking else 1.1))  % 360
        self._scan2 = (self._scan2 + (-1.8 if self.speaking else -0.65)) % 360
        self._loader_angle = (self._loader_angle + 5.5) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 3.8 if self.speaking else 1.8
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.065 if self.speaking else 0.022):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.24:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.27
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.8, 2.2),
                math.sin(ang) * random.uniform(0.8, 2.2) - 0.35, 1.0])
        self._particles = [
            [pt[0] + pt[2], pt[1] + pt[3], pt[2] * 0.97, pt[3] * 0.97, pt[4] - 0.026]
            for pt in self._particles if pt[4] > 0]

        self._blink_tick += 1
        if self._blink_tick >= 34:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw  = min(W, H)
        col = self._col()

        bg = QRadialGradient(cx, cy, max(W, H) * 0.75)
        bg.setColorAt(0.0, qcol("#071019"))
        bg.setColorAt(1.0, qcol(T.BG))
        p.fillRect(self.rect(), QBrush(bg))

        # perspective grid
        p.setPen(QPen(qcol(T.BORDER, 60), 0.6))
        horizon = cy + fw * 0.30
        for i in range(1, 9):
            y = horizon + (i ** 1.7) * 9
            if y < H:
                p.drawLine(QPointF(0, y), QPointF(W, y))
        for i in range(-12, 13):
            p.drawLine(QPointF(cx + i * 26, horizon),
                       QPointF(cx + i * 110, H))

        r_face = fw * 0.30

        # halo rings
        for i in range(8):
            r = r_face * (1.9 - i * 0.085)
            a = max(0, min(255, int(self._halo * 0.07 * (1.0 - i / 8))))
            p.setPen(QPen(qcol(col, a), 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # expanding pulses
        for pr in self._pulses:
            a = max(0, int(200 * (1.0 - pr / (fw * 0.74))))
            p.setPen(QPen(qcol(col, a), 1.1))
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # orbital arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
                [(0.485, 2.4, 110, 80), (0.405, 1.7, 72, 58), (0.33, 1.1, 50, 44)]):
            ring_r = fw * r_frac
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            p.setPen(QPen(qcol(col, a_val), w_r))
            rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            ang  = self._rings[idx]
            while ang < self._rings[idx] + 360:
                p.drawArc(rect, int(ang * 16), int(arc_l * 16))
                ang += arc_l + gap

        # scanners
        sr    = fw * 0.50
        sa    = min(255, int(self._halo * 1.4))
        ex    = 70 if self.speaking else 40
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.setPen(QPen(qcol(T.WHITE, sa), 2.0))
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(T.VIOLET, sa // 3), 1.1))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # busy loader ring
        if self._busy():
            lr    = fw * 0.55
            lrect = QRectF(cx - lr, cy - lr, lr * 2, lr * 2)
            p.setPen(QPen(qcol(col, 55), 3))
            p.drawEllipse(lrect)
            p.setPen(QPen(qcol(col, 225), 3))
            p.drawArc(lrect, int(-self._loader_angle * 16), 80 * 16)
            p.setPen(QPen(qcol(T.WHITE, 150), 1.5))
            p.drawArc(lrect, int((-self._loader_angle - 130) * 16), 30 * 16)

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.472
        for deg in range(0, 360, 6):
            rad  = math.radians(deg)
            is_m = deg % 30 == 0
            inn  = t_in if is_m else t_in + (8 if deg % 15 == 0 else 12)
            p.setPen(QPen(qcol(T.WHITE if is_m else col, 170 if is_m else 60),
                          1.0 if is_m else 0.5))
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)))

        # face / orb
        if self._face_px:
            fsz    = int(fw * 0.60 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.26 * self._scale)
            base  = QColor(col)
            for i in range(8, 0, -1):
                frc = i / 8
                a   = max(0, min(255, int(self._halo * frc)))
                oc  = QColor(int(base.red() * frc * 0.4),
                             int(base.green() * frc * 0.4),
                             int(base.blue() * frc * 0.4), a)
                p.setBrush(QBrush(oc))
                p.setPen(Qt.PenStyle.NoPen)
                r2 = int(orb_r * frc)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(T.WHITE, min(255, int(self._halo * 2))), 1))
            p.setFont(M(13, True))
            p.drawText(QRectF(cx - 80, cy - 14, 160, 28),
                       Qt.AlignmentFlag.AlignCenter, "F.L.I.N.T")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(T.WHITE, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.2, 2.2)

        # waveform at bottom of canvas
        wy = H - 26
        N, bw = 42, 7
        wx0   = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(T.MAGENTA, 110)
            elif self.speaking:
                hgt = random.randint(2, 18)
                cl  = qcol(T.WHITE if hgt > 10 else T.AMBER, 190)
            elif self._busy():
                hgt = int(3 + 6 * abs(math.sin(self._tick * 0.11 + i * 0.4)))
                cl  = qcol(col, 140)
            else:
                hgt = int(2 + 2 * math.sin(self._tick * 0.08 + i * 0.55))
                cl  = qcol(T.BORDER_HI, 150)
            p.setBrush(QBrush(cl))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(wx0 + i * bw, wy + 18 - hgt, bw - 1, hgt), 1, 1)


# ── LogWidget: typewriter conversation log ────────────────────────────────────
class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    _COLORS = {
        "you":  T.WHITE,
        "ai":   T.CYAN,
        "err":  T.RED,
        "file": T.EMERALD,
        "sys":  T.AMBER,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(M(9))
        self.setFrameStyle(QFrame.Shape.NoFrame.value)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {T.TEXT};
                border: none; padding: 6px;
                selection-background-color: {T.CYAN_GHO};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 5px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {T.BORDER_HI}; border-radius: 2px; min-height: 14px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._queue: list[str] = []
        self._typing = False
        self._text, self._pos, self._tag = "", 0, "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        if tl.startswith("you:"):       self._tag = "you"
        elif tl.startswith("flint:"):   self._tag = "ai"
        elif tl.startswith("file:"):    self._tag = "file"
        elif "err" in tl:               self._tag = "err"
        else:                           self._tag = "sys"
        self._tmr.start(4)

    def _step(self):
        if self._pos < len(self._text):
            cur = self.textCursor()
            fmt = cur.charFormat()
            fmt.setForeground(QBrush(qcol(self._COLORS.get(self._tag, T.TEXT))))
            cur.movePosition(QTextCursor.MoveOperation.End)
            cur.insertText(self._text[self._pos], fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(14, self._next)


# ── TerminalWidget: live stdout mirror ────────────────────────────────────────
class TerminalWidget(QPlainTextEdit):
    _sig = pyqtSignal(str, str)

    _LEVEL_COLORS = {
        "info": T.TEXT_MED, "ok": T.EMERALD,
        "warn": T.AMBER,    "error": T.RED,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(M(8))
        self.setMaximumBlockCount(1200)
        self.setFrameStyle(QFrame.Shape.NoFrame.value)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {T.INSET}; color: {T.TEXT_MED};
                border: none; padding: 6px;
            }}
            QScrollBar:vertical {{
                background: transparent; width: 5px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {T.BORDER_HI}; border-radius: 2px; min-height: 14px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._sig.connect(self._append)
        self._attach_hub()

    def _attach_hub(self):
        try:
            from core.log_interceptor import get_hub
            hub = get_hub()
            for _, line, level, _stream in hub.snapshot()[-200:]:
                self._append(line, level)
            hub.subscribe(self._on_line)
        except Exception:
            self._append("log interceptor unavailable", "warn")

    def _on_line(self, line: str, level: str, _stream: str):
        self._sig.emit(line, level)

    def _append(self, line: str, level: str):
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        ts_fmt = QTextCharFormat()
        ts_fmt.setForeground(QBrush(qcol(T.TEXT_DIM)))
        cur.insertText(time.strftime("%H:%M:%S "), ts_fmt)
        ln_fmt = QTextCharFormat()
        ln_fmt.setForeground(QBrush(qcol(self._LEVEL_COLORS.get(level, T.TEXT_MED))))
        cur.insertText(line + "\n", ln_fmt)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── File handling ─────────────────────────────────────────────────────────────
_FILE_ICONS = {
    "image":   ("🖼", T.CYAN),    "video":   ("🎬", T.AMBER),
    "audio":   ("🎵", T.VIOLET),  "pdf":     ("📄", T.RED),
    "word":    ("📝", T.VIOLET),  "excel":   ("📊", T.EMERALD),
    "code":    ("💻", T.AMBER),   "archive": ("📦", "#fb923c"),
    "pptx":   ("📊", T.MAGENTA), "text":    ("📃", T.TEXT_MED),
    "data":   ("🔧", T.CYAN),    "unknown": ("📎", T.TEXT_DIM),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"], "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"], "audio"),
    **dict.fromkeys(["pdf"], "pdf"),
    **dict.fromkeys(["doc","docx"], "word"),
    **dict.fromkeys(["xls","xlsx","ods"], "excel"),
    **dict.fromkeys(["ppt","pptx"], "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c",
                     "cpp","cs","go","rs","rb","php","swift","kt","sh",
                     "sql","lua"], "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"], "archive"),
    **dict.fromkeys(["txt","md","rst","log"], "text"),
    **dict.fromkeys(["csv","tsv","json","xml"], "data"),
}


def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")


def _fmt_size(size: int) -> str:
    if size < 1024:      return f"{size} B"
    if size < 1024**2:   return f"{size/1024:.1f} KB"
    if size < 1024**3:   return f"{size/1024**2:.1f} MB"
    return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(70)
        self._current_file: str | None = None
        self._hovering = self._drag_over = False
        self._dash_offset = 0.0
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._animate)
        self._anim.start(35)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.7) % 20
        self.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            self.update()

    def dragLeaveEvent(self, _):
        self._drag_over = False
        self.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self.update()

    def enterEvent(self, _):
        self._hovering = True
        self.update()

    def leaveEvent(self, _):
        self._hovering = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._current_file and e.pos().x() > self.width() - 28:
            self.clear_file()
        else:
            self._browse()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None
        self.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for FLINT", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Audio (*.mp3 *.wav *.m4a *.flac);;Video (*.mp4 *.mov *.mkv);;"
            "Archives (*.zip *.rar *.7z)")
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self.update()
        self.file_selected.emit(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        rect = QRectF(3, 3, W - 6, H - 6)

        bg = (qcol("#0a1a2e") if self._drag_over
              else qcol("#081120") if self._hovering else qcol(T.INSET))
        path = QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        p.fillPath(path, QBrush(bg))

        border = (qcol(T.EMERALD, 180) if self._current_file
                  else qcol(T.WHITE, 210) if self._drag_over
                  else qcol(T.CYAN, 160) if self._hovering
                  else qcol(T.BORDER_HI, 130))
        pen = QPen(border, 1.1, Qt.PenStyle.DashLine)
        pen.setDashOffset(self._dash_offset)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 7, 7)

        if self._current_file:
            ph = Path(self._current_file)
            icon, icon_col = _FILE_ICONS.get(_file_category(ph), _FILE_ICONS["unknown"])
            try:
                size_str = _fmt_size(ph.stat().st_size)
            except OSError:
                size_str = "?"
            p.setFont(QFont("Segoe UI Emoji", 14) if _OS == "Windows" else QFont("Arial", 14))
            p.setPen(QPen(qcol(icon_col), 1))
            p.drawText(QRectF(8, 0, 38, H), Qt.AlignmentFlag.AlignCenter, icon)
            p.setFont(M(8, True))
            p.setPen(QPen(qcol(T.WHITE), 1))
            name = ph.name if len(ph.name) <= 28 else ph.name[:25] + "…"
            p.drawText(QRectF(50, H * 0.22, W - 86, 15), Qt.AlignmentFlag.AlignLeft, name)
            p.setFont(M(7))
            p.setPen(QPen(qcol(T.TEXT_MED), 1))
            p.drawText(QRectF(50, H * 0.22 + 16, W - 86, 12),
                       Qt.AlignmentFlag.AlignLeft,
                       f"{ph.suffix.upper().lstrip('.') or 'FILE'}  ·  {size_str}")
            p.setFont(M(9, True))
            p.setPen(QPen(qcol(T.RED, 170), 1))
            p.drawText(QRectF(W - 26, 0, 22, H), Qt.AlignmentFlag.AlignCenter, "✕")
        elif self._drag_over:
            p.setFont(F(12))
            p.setPen(QPen(qcol(T.WHITE), 1))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "⬇  Release to load")
        else:
            p.setFont(F(8))
            p.setPen(QPen(qcol(T.CYAN if self._hovering else T.TEXT_DIM), 1))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter,
                       "📎  Drop a file  or  Click to browse")


# ── Boot overlay ──────────────────────────────────────────────────────────────
class BootOverlay(QWidget):
    _BOOT_LINES = [
        "NEURAL CORE ............ ONLINE",
        "MEMORY MATRIX .......... LOADED",
        "VOICE ENGINE ........... ARMED",
        "ASYNC PIPELINE ......... 4 WORKERS",
        "REMOTE LISTENER ........ STANDBY",
        "AUDIO SUBSYSTEM ........ CALIBRATED",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._progress = 0.0
        self._line_idx = 0
        self._done     = False
        self._tmr      = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(28)

    def _step(self):
        if self._progress < 100:
            self._progress = min(100.0, self._progress + random.uniform(0.6, 2.4))
            self._line_idx = int(self._progress / 100 * len(self._BOOT_LINES))
            self.update()

    def finish(self):
        if self._done:
            return
        self._done     = True
        self._progress = 100.0
        self._tmr.stop()
        eff  = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(650)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self.hide)
        anim.start()
        self._fade_anim = anim

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), qcol(T.BG, 240))
        cx, cy = W / 2, H / 2

        p.setFont(F(26, True))
        p.setPen(QPen(qcol(T.CYAN), 1))
        p.drawText(QRectF(0, cy - 120, W, 46),
                   Qt.AlignmentFlag.AlignCenter, "F L I N T")
        p.setFont(F(9))
        p.setPen(QPen(qcol(T.TEXT_DIM), 1))
        p.drawText(QRectF(0, cy - 74, W, 18), Qt.AlignmentFlag.AlignCenter,
                   "MISSION CONTROL  ·  INITIALISING")

        bw, bh = min(420, W * 0.5), 5
        bx, by = cx - bw / 2, cy - 20
        p.setPen(QPen(qcol(T.BORDER_HI), 1))
        p.setBrush(QBrush(qcol(T.INSET)))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 2.5, 2.5)
        fw2 = bw * self._progress / 100
        if fw2 > 2:
            grad = QLinearGradient(bx, 0, bx + bw, 0)
            grad.setColorAt(0, qcol(T.CYAN))
            grad.setColorAt(1, qcol(T.VIOLET))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(bx, by, fw2, bh), 2.5, 2.5)
            glow = QRadialGradient(bx + fw2, by + bh / 2, 10)
            glow.setColorAt(0, qcol(T.CYAN, 200))
            glow.setColorAt(1, qcol(T.CYAN, 0))
            p.setBrush(QBrush(glow))
            p.drawEllipse(QPointF(bx + fw2, by + bh / 2), 10, 10)

        p.setFont(F(9, True))
        p.setPen(QPen(qcol(T.CYAN), 1))
        p.drawText(QRectF(0, by + 13, W, 18), Qt.AlignmentFlag.AlignCenter,
                   f"{self._progress:3.0f}%")
        p.setFont(M(8))
        for i, line in enumerate(self._BOOT_LINES[:self._line_idx]):
            p.setPen(QPen(qcol(T.EMERALD if i < self._line_idx - 1 else T.TEXT), 1))
            p.drawText(QRectF(cx - 170, by + 42 + i * 16, 360, 14),
                       Qt.AlignmentFlag.AlignLeft, line)


# ── Setup overlay (API keys) ──────────────────────────────────────────────────
class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(3, 8, 17, 252);
                border: 1px solid {T.BORDER_HI};
                border-radius: 12px;
            }}
        """)
        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = detected

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(9)

        def _lbl(txt, size=9, bold=False, color=T.CYAN,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(F(size, bold))
            w.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            return w

        lay.addWidget(_lbl("INITIALISATION REQUIRED", 14, True,
                           align=Qt.AlignmentFlag.AlignLeft))
        lay.addWidget(_lbl("Configure F.L.I.N.T before first boot.", 9,
                           color=T.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))

        def _field(placeholder, focus=T.CYAN):
            e = QLineEdit()
            e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setPlaceholderText(placeholder)
            e.setFont(F(10))
            e.setFixedHeight(34)
            e.setStyleSheet(f"""
                QLineEdit {{
                    background: {T.INSET}; color: {T.TEXT};
                    border: 1px solid {T.BORDER_HI}; border-radius: 6px;
                    padding: 5px 10px;
                }}
                QLineEdit:focus {{ border: 1px solid {focus}; }}
            """)
            return e

        lay.addWidget(_lbl("GEMINI API KEY", 8, color=T.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = _field("AIza…", T.CYAN)
        lay.addWidget(self._key_input)

        lay.addWidget(_lbl("OPENROUTER API KEY", 8, color=T.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = _field("sk-or-…", T.EMERALD)
        lay.addWidget(self._or_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("OPERATING SYSTEM", 8, color=T.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))
        os_row = QHBoxLayout()
        os_row.setSpacing(7)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows", "⊞  Windows"), ("mac", "  macOS"),
                            ("linux", "🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(F(9, True))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        lay.addLayout(os_row)
        self._sel(detected)

        lay.addSpacing(6)
        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(F(10, True))
        init_btn.setFixedHeight(38)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.CYAN_GHO}; color: {T.CYAN};
                border: 1px solid {T.CYAN_DIM}; border-radius: 6px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: #0a3340; border: 1px solid {T.CYAN};
                color: {T.WHITE};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        lay.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows": (T.CYAN, "#06222e"),
               "mac":     (T.EMERALD, "#03241a"),
               "linux":   (T.AMBER, "#241a03")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(
                    f"QPushButton {{ background: {bg}; color: {fg};"
                    f" border: 1px solid {fg}; border-radius: 6px; }}")
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {T.PANEL}; color: {T.TEXT_DIM};
                        border: 1px solid {T.BORDER}; border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        color: {T.TEXT}; border: 1px solid {T.BORDER_HI};
                    }}
                """)

    def _submit(self):
        key    = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        for val, field in [(key, self._key_input), (or_key, self._or_input)]:
            if not val:
                field.setStyleSheet(
                    field.styleSheet()
                    + f" QLineEdit {{ border: 1px solid {T.RED}; }}")
                return
        self.done.emit(key, or_key, self._sel_os)


# ── Toast notification ────────────────────────────────────────────────────────
class ToastWidget(QWidget):
    def __init__(self, message: str, level: str = "info", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(34)
        cmap = {
            "info":    (T.CYAN,    T.CYAN_GHO),
            "ok":      (T.EMERALD, "#03241a"),
            "success": (T.EMERALD, "#03241a"),
            "warn":    (T.AMBER,   "#241a03"),
            "memory":  (T.VIOLET,  T.VIOLET_D),
            "error":   (T.RED,     "#360814"),
        }
        fg, bg = cmap.get(level.lower(), (T.CYAN, T.CYAN_GHO))
        lay    = QHBoxLayout(self)
        lay.setContentsMargins(14, 4, 14, 4)
        lbl = QLabel(message)
        lbl.setFont(F(8, True))
        lbl.setStyleSheet(f"color: {fg}; background: transparent; border: none;")
        lay.addWidget(lbl)
        self.setStyleSheet(f"""
            QWidget {{ background: {bg}; border: 1px solid {fg}; border-radius: 6px; }}
        """)
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)

    def fade_in_and_out(self):
        anim = QPropertyAnimation(self.eff, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._in = anim
        QTimer.singleShot(2800, self._fade_out)

    def _fade_out(self):
        anim = QPropertyAnimation(self.eff, b"opacity", self)
        anim.setDuration(400)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()
        self._out = anim


# ═══════════════════════════════════════════════════════════════════════════════
#  NEW DASHBOARD COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _card_style(border_col: str = T.BORDER, bg: str = T.PANEL) -> str:
    return f"""
        QWidget {{
            background: {bg};
            border: 1px solid {border_col};
            border-radius: 10px;
        }}
    """


def _label(text: str, size: int = 9, bold: bool = False,
           color: str = T.TEXT, parent=None) -> QLabel:
    lbl = QLabel(text, parent)
    lbl.setFont(F(size, bold))
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(F(7, True))
    lbl.setStyleSheet(f"""
        color: {T.TEXT_DIM}; background: transparent; border: none;
        border-bottom: 1px solid {T.BORDER};
        padding-bottom: 3px; letter-spacing: 2px;
    """)
    return lbl


# ── Nav sidebar ───────────────────────────────────────────────────────────────
_NAV_ITEMS = [
    ("◉", "AI CORE",        0),
    ("🤖", "AGENTS",         0),
    ("📋", "TASKS",          4),
    ("📅", "CALENDAR",       4),
    ("🧠", "MEMORY",         3),
    ("💬", "CONVERSATIONS",  1),
    ("📚", "KNOWLEDGE BASE", 4),
    ("🔧", "TOOLS",          4),
    ("⚡", "WORKFLOWS",      4),
    ("⚙", "SETTINGS",       4),
]


class NavItem(QWidget):
    clicked = pyqtSignal(int)       # page index

    def __init__(self, icon: str, label: str, page: int, parent=None):
        super().__init__(parent)
        self._page   = page
        self._active = False
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(10)

        self._indicator = QWidget()
        self._indicator.setFixedSize(2, 20)
        self._indicator.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self._indicator)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(F(11))
        icon_lbl.setFixedWidth(20)
        icon_lbl.setStyleSheet("color: #426882; background: transparent; border: none;")
        self._icon = icon_lbl
        lay.addWidget(icon_lbl)

        text_lbl = QLabel(label)
        text_lbl.setFont(F(8, False))
        text_lbl.setStyleSheet(f"color: {T.TEXT_DIM}; background: transparent; border: none;")
        self._text = text_lbl
        lay.addWidget(text_lbl)
        lay.addStretch()

        self.setStyleSheet("QWidget { background: transparent; border: none; }")

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._indicator.setStyleSheet(
                f"background: {T.CYAN}; border: none; border-radius: 1px;")
            self._icon.setStyleSheet(
                f"color: {T.CYAN}; background: transparent; border: none;")
            self._text.setStyleSheet(
                f"color: {T.WHITE}; background: transparent; border: none;")
            self.setStyleSheet(
                f"QWidget {{ background: {T.CYAN_GHO}; border: none; border-radius: 6px; }}")
        else:
            self._indicator.setStyleSheet("background: transparent; border: none;")
            self._icon.setStyleSheet(
                f"color: {T.TEXT_MED}; background: transparent; border: none;")
            self._text.setStyleSheet(
                f"color: {T.TEXT_DIM}; background: transparent; border: none;")
            self.setStyleSheet("QWidget { background: transparent; border: none; }")

    def enterEvent(self, _):
        if not self._active:
            self.setStyleSheet(
                f"QWidget {{ background: {T.PANEL2}; border: none; border-radius: 6px; }}")

    def leaveEvent(self, _):
        if not self._active:
            self.setStyleSheet("QWidget { background: transparent; border: none; }")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._page)


class NavSidebar(QWidget):
    nav_changed = pyqtSignal(int)   # page index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet(f"""
            QWidget#NavSidebar {{
                background: {T.SIDEBAR};
                border-right: 1px solid {T.BORDER};
            }}
        """)
        self.setObjectName("NavSidebar")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 20, 10, 16)
        lay.setSpacing(2)

        # Branding
        brand = QVBoxLayout()
        brand.setSpacing(2)
        logo = _label("FLINT", 20, True, T.WHITE)
        logo.setStyleSheet(
            f"color: {T.WHITE}; background: transparent; border: none; letter-spacing: 4px;")
        sub  = _label("AI ASSISTANT", 7, False, T.CYAN_DIM)
        sub.setStyleSheet(
            f"color: {T.CYAN_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        brand.addWidget(logo)
        brand.addWidget(sub)
        lay.addLayout(brand)
        lay.addSpacing(12)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {T.BORDER}; border: none;")
        lay.addWidget(div)
        lay.addSpacing(8)

        # Section header
        sec = _label("COMMAND CENTER", 7, True, T.TEXT_DIM)
        sec.setStyleSheet(
            f"color: {T.TEXT_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        lay.addWidget(sec)
        lay.addSpacing(4)

        # Nav items
        self._items: list[NavItem] = []
        for icon, label, page in _NAV_ITEMS:
            item = NavItem(icon, label, page)
            item.clicked.connect(self._on_nav_click)
            lay.addWidget(item)
            self._items.append(item)

        lay.addStretch()

        # Bottom status
        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {T.BORDER}; border: none;")
        lay.addWidget(div2)
        lay.addSpacing(6)

        self._status_dot = _label("● SYSTEM OPTIMAL", 7, True, T.EMERALD)
        self._status_dot.setStyleSheet(
            f"color: {T.EMERALD}; background: transparent; border: none;")
        lay.addWidget(self._status_dot)

        ver = _label("MISSION CONTROL  v3.0", 7, False, T.TEXT_DIM)
        ver.setStyleSheet(
            f"color: {T.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(ver)

        # Activate first item
        if self._items:
            self._items[0].set_active(True)

    def _on_nav_click(self, page: int):
        for item in self._items:
            item.set_active(False)
        sender = self.sender()
        if isinstance(sender, NavItem):
            sender.set_active(True)
        self.nav_changed.emit(page)

    def set_status(self, text: str, color: str = T.EMERALD):
        self._status_dot.setText(text)
        self._status_dot.setStyleSheet(
            f"color: {color}; background: transparent; border: none;")


# ── Top bar ───────────────────────────────────────────────────────────────────
class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.SIDEBAR};
                border-bottom: 1px solid {T.BORDER};
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)

        # Left: FLINT + system status
        left = QHBoxLayout()
        left.setSpacing(12)

        logo = _label("F·L·I·N·T", 13, True, T.CYAN)
        logo.setStyleSheet(
            f"color: {T.CYAN}; background: transparent; border: none; letter-spacing: 3px;")
        left.addWidget(logo)

        self._status_badge = QLabel("● SYSTEM OPTIMAL")
        self._status_badge.setFont(F(8, True))
        self._status_badge.setStyleSheet(f"""
            color: {T.EMERALD};
            background: {T.EMERALD_D};
            border: 1px solid #1a5a3a;
            border-radius: 4px;
            padding: 2px 10px;
        """)
        left.addWidget(self._status_badge)

        self._link_badge = QLabel("LINK  OFFLINE")
        self._link_badge.setFont(F(7, True))
        self._link_badge.setStyleSheet(f"""
            color: {T.TEXT_DIM};
            background: {T.PANEL};
            border: 1px solid {T.BORDER};
            border-radius: 4px;
            padding: 2px 8px;
        """)
        left.addWidget(self._link_badge)

        self._spinner = Spinner(T.CYAN, 16)
        self._spinner.hide()
        left.addWidget(self._spinner)

        self._jobs_lbl = _label("", 7, True, T.VIOLET)
        left.addWidget(self._jobs_lbl)

        lay.addLayout(left)
        lay.addStretch()

        # Center: clock + date
        center = QVBoxLayout()
        center.setSpacing(1)
        center.setContentsMargins(0, 0, 0, 0)
        self._clock = _label("00:00:00", 16, True, T.WHITE)
        self._clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clock.setStyleSheet(
            f"color: {T.WHITE}; background: transparent; border: none; letter-spacing: 2px;")
        self._date = _label("", 7, False, T.TEXT_DIM)
        self._date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._date.setStyleSheet(
            f"color: {T.TEXT_DIM}; background: transparent; border: none; letter-spacing: 1px;")
        center.addWidget(self._clock)
        center.addWidget(self._date)
        lay.addLayout(center)
        lay.addStretch()

        # Right: compact mode + hotkeys hint
        right = QHBoxLayout()
        right.setSpacing(8)

        compact_btn = QPushButton("❐  COMPACT")
        compact_btn.setFont(F(7, True))
        compact_btn.setFixedHeight(26)
        compact_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        compact_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.PANEL2}; color: {T.TEXT_DIM};
                border: 1px solid {T.BORDER}; border-radius: 5px;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                color: {T.CYAN}; border: 1px solid {T.CYAN_DIM};
                background: {T.CYAN_GHO};
            }}
        """)
        self._compact_btn = compact_btn
        right.addWidget(compact_btn)

        hotkey = _label("[Ctrl+Space] Wake  [F4] Mute  [F10] Compact", 7, False, T.TEXT_DIM)
        right.addWidget(hotkey)

        lay.addLayout(right)

        # Clock timer
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(1000)
        self._tick()

    def _tick(self):
        self._clock.setText(time.strftime("%H:%M:%S"))
        self._date.setText(time.strftime("%A   %d %b %Y"))

    def set_link_clients(self, n: int):
        if n > 0:
            self._link_badge.setText(f"LINK  {n} CLIENT{'S' if n != 1 else ''}")
            self._link_badge.setStyleSheet(f"""
                color: {T.EMERALD};
                background: {T.EMERALD_D};
                border: 1px solid #1a5a3a;
                border-radius: 4px;
                padding: 2px 8px;
            """)
        else:
            self._link_badge.setText("LINK  OFFLINE")
            self._link_badge.setStyleSheet(f"""
                color: {T.TEXT_DIM};
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 4px;
                padding: 2px 8px;
            """)

    def set_state_badge(self, state: str):
        col = _STATE_COLORS.get(state, T.CYAN)
        if state in ("LISTENING", "SPEAKING"):
            self._status_badge.setText("● SYSTEM OPTIMAL")
            self._status_badge.setStyleSheet(f"""
                color: {T.EMERALD}; background: {T.EMERALD_D};
                border: 1px solid #1a5a3a; border-radius: 4px; padding: 2px 10px;
            """)
        elif state in ("THINKING", "PROCESSING"):
            self._status_badge.setText("◌ PROCESSING")
            self._status_badge.setStyleSheet(f"""
                color: {col}; background: {T.CYAN_GHO};
                border: 1px solid {T.CYAN_DIM}; border-radius: 4px; padding: 2px 10px;
            """)
        elif state == "MUTED":
            self._status_badge.setText("⊘ MICROPHONE MUTED")
            self._status_badge.setStyleSheet(f"""
                color: {T.MAGENTA}; background: #260a18;
                border: 1px solid {T.MAGENTA}; border-radius: 4px; padding: 2px 10px;
            """)


# ── Agent cards ────────────────────────────────────────────────────────────────
_AGENTS_DEF = [
    ("🖥", "Coding",   "code_helper"),
    ("🔍", "Research", "web_search"),
    ("🧠", "Memory",   "save_memory"),
    ("🌐", "Browser",  "browser_control"),
    ("📱", "WhatsApp", "send_message"),
    ("📄", "Files",    "file_processor"),
    ("🖱", "Desktop",  "desktop_control"),
    ("✈", "Flights",  "flight_finder"),
]


class AgentCard(QWidget):
    def __init__(self, icon: str, name: str, tool_key: str, parent=None):
        super().__init__(parent)
        self._tool_key = tool_key
        self.setFixedSize(80, 68)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL2};
                border: 1px solid {T.BORDER};
                border-radius: 8px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(3)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFont(F(16))
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self._icon_lbl)

        self._name_lbl = _label(name, 7, True, T.TEXT_MED)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._name_lbl)

        self._status_lbl = _label("STANDBY", 6, False, T.TEXT_DIM)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._status_lbl)

    def set_active(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QWidget {{
                    background: {T.CYAN_GHO};
                    border: 1px solid {T.CYAN};
                    border-radius: 8px;
                }}
            """)
            self._name_lbl.setStyleSheet(
                f"color: {T.WHITE}; background: transparent; border: none;")
            self._status_lbl.setText("● ACTIVE")
            self._status_lbl.setStyleSheet(
                f"color: {T.EMERALD}; background: transparent; border: none;")
        else:
            self.setStyleSheet(f"""
                QWidget {{
                    background: {T.PANEL2};
                    border: 1px solid {T.BORDER};
                    border-radius: 8px;
                }}
            """)
            self._name_lbl.setStyleSheet(
                f"color: {T.TEXT_MED}; background: transparent; border: none;")
            self._status_lbl.setText("STANDBY")
            self._status_lbl.setStyleSheet(
                f"color: {T.TEXT_DIM}; background: transparent; border: none;")

    @property
    def tool_key(self) -> str:
        return self._tool_key


class AgentsStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setStyleSheet("background: transparent; border: none;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        hdr = QHBoxLayout()
        hdr.addWidget(_section_header("ACTIVE AGENTS"))
        hdr.addStretch()
        outer.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(68)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
        """)

        inner = QWidget()
        inner.setStyleSheet("background: transparent; border: none;")
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._cards: dict[str, AgentCard] = {}
        for icon, name, key in _AGENTS_DEF:
            card = AgentCard(icon, name, key)
            row.addWidget(card)
            self._cards[key] = card
        row.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def set_active_tool(self, tool_key: str | None):
        for key, card in self._cards.items():
            card.set_active(key == tool_key)


# ── Mission timeline ──────────────────────────────────────────────────────────
class MissionTimeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_section_header("MISSION TIMELINE"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; border: none; }
            QScrollBar::handle:vertical { background: #1a3060; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent; border: none;")
        self._vlay = QVBoxLayout(self._content)
        self._vlay.setContentsMargins(0, 0, 0, 0)
        self._vlay.setSpacing(4)
        self._vlay.addStretch()

        self._idle_lbl = _label("● Ready for requests", 8, False, T.TEXT_DIM)
        self._vlay.insertWidget(0, self._idle_lbl)

        scroll.setWidget(self._content)
        lay.addWidget(scroll, stretch=1)
        self._scroll = scroll
        self._events: list[tuple[str, str, bool]] = []

    def add_event(self, goal: str, text: str, active: bool):
        # Remove idle label
        self._idle_lbl.hide()

        ts   = time.strftime("%H:%M")
        col  = T.CYAN if active else T.EMERALD
        dot  = "◌" if active else "✓"

        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        ts_lbl = _label(ts, 7, False, T.TEXT_DIM)
        ts_lbl.setFixedWidth(34)
        row.addWidget(ts_lbl)

        dot_lbl = _label(dot, 8, True, col)
        dot_lbl.setFixedWidth(14)
        row.addWidget(dot_lbl)

        txt = text if text else (goal[:40] + ("…" if len(goal) > 40 else ""))
        row.addWidget(_label(txt, 8, False, T.TEXT if active else T.TEXT_MED))
        row.addStretch()

        container = QWidget()
        container.setStyleSheet("background: transparent; border: none;")
        container.setLayout(row)
        container.setFixedHeight(22)

        # Insert before stretch
        idx = self._vlay.count() - 1
        self._vlay.insertWidget(idx, container)

        # Keep last 8 events
        if self._vlay.count() > 10:
            item = self._vlay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        QTimer.singleShot(50, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def reset(self):
        while self._vlay.count() > 1:
            item = self._vlay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._idle_lbl.show()


# ── Quick commands ────────────────────────────────────────────────────────────
class QuickCommandsPanel(QWidget):
    command_triggered = pyqtSignal(str)

    _CMDS = [
        ("🎙", "Start Voice",     ""),
        ("📅", "Open Calendar",   "open calendar"),
        ("🌐", "Open Browser",    "open browser"),
        ("🧠", "Show Memory",     "show memory summary"),
        ("📱", "WhatsApp",        "open whatsapp"),
        ("💻", "Code Editor",     "open code editor"),
        ("📁", "File Explorer",   "open file explorer"),
        ("⚡", "New Task",        "start a new task"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lay.addWidget(_section_header("QUICK COMMANDS"))

        grid = QWidget()
        grid.setStyleSheet("background: transparent; border: none;")
        grid_lay = QVBoxLayout(grid)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setSpacing(5)

        for i in range(0, len(self._CMDS), 2):
            row = QHBoxLayout()
            row.setSpacing(5)
            for j in range(2):
                if i + j < len(self._CMDS):
                    icon, label, cmd = self._CMDS[i + j]
                    btn = QPushButton(f"{icon}  {label}")
                    btn.setFont(F(8))
                    btn.setFixedHeight(28)
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background: {T.PANEL2}; color: {T.TEXT};
                            border: 1px solid {T.BORDER}; border-radius: 6px;
                            padding: 2px 6px; text-align: left;
                        }}
                        QPushButton:hover {{
                            background: {T.CYAN_GHO}; color: {T.CYAN};
                            border: 1px solid {T.CYAN_DIM};
                        }}
                    """)
                    btn.clicked.connect(
                        lambda _, c=cmd: self.command_triggered.emit(c) if c else None)
                    row.addWidget(btn, stretch=1)
            grid_lay.addLayout(row)

        lay.addWidget(grid, stretch=1)


# ── System monitor strip ───────────────────────────────────────────────────────
class SystemMonitorStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 8px;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(0)

        self._stats: list[tuple[QLabel, QLabel]] = []
        items = [
            ("CPU",  T.CYAN),
            ("MEM",  T.EMERALD),
            ("NET",  T.VIOLET),
            ("GPU",  T.AMBER),
            ("TEMP", T.MAGENTA),
        ]
        for i, (name, col) in enumerate(items):
            if i > 0:
                sep = QFrame()
                sep.setFixedSize(1, 28)
                sep.setStyleSheet(f"background: {T.BORDER}; border: none;")
                lay.addWidget(sep)

            cell = QWidget()
            cell.setStyleSheet("background: transparent; border: none;")
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(14, 4, 14, 4)
            cell_lay.setSpacing(1)

            name_lbl = _label(name, 7, True, T.TEXT_DIM)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet(
                f"color: {T.TEXT_DIM}; background: transparent; border: none;")

            val_lbl = _label("--", 9, True, col)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(
                f"color: {col}; background: transparent; border: none;")

            cell_lay.addWidget(name_lbl)
            cell_lay.addWidget(val_lbl)
            self._stats.append((name_lbl, val_lbl))
            lay.addWidget(cell, stretch=1)

        lay.addStretch()

        # Uptime / process count
        sep2 = QFrame()
        sep2.setFixedSize(1, 28)
        sep2.setStyleSheet(f"background: {T.BORDER}; border: none;")
        lay.addWidget(sep2)

        right_cell = QWidget()
        right_cell.setStyleSheet("background: transparent; border: none;")
        rc_lay = QVBoxLayout(right_cell)
        rc_lay.setContentsMargins(14, 4, 8, 4)
        rc_lay.setSpacing(1)

        self._uptime_lbl = _label("UPTIME  --:--", 7, False, T.TEXT_MED)
        self._procs_lbl  = _label("PROCS  --",     7, False, T.TEXT_DIM)
        rc_lay.addWidget(self._uptime_lbl)
        rc_lay.addWidget(self._procs_lbl)
        lay.addWidget(right_cell)

    def update_metrics(self, snap: dict):
        cpu = snap.get("cpu", 0)
        mem = snap.get("mem", 0)
        net = snap.get("net", 0)
        gpu = snap.get("gpu", -1)
        tmp = snap.get("tmp", -1)

        vals = [
            f"{cpu:.0f}%",
            f"{mem:.0f}%",
            (f"{net*1024:.0f}KB/s" if net < 1.0 else f"{net:.1f}MB/s"),
            (f"{gpu:.0f}%" if gpu >= 0 else "N/A"),
            (f"{tmp:.0f}°C" if tmp >= 0 else "N/A"),
        ]
        for (_nl, vl), val in zip(self._stats, vals):
            vl.setText(val)

        try:
            elapsed = time.time() - psutil.boot_time()
            h, m = int(elapsed // 3600), int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UPTIME  {h:02d}:{m:02d}")
            self._procs_lbl.setText(f"PROCS  {len(psutil.pids())}")
        except Exception:
            pass


# ── Intelligence feed (right panel) ────────────────────────────────────────────
class IntelFeedItem(QWidget):
    _CAT_COLORS = {
        "AI":       (T.CYAN,    "◉"),
        "MEMORY":   (T.VIOLET,  "🧠"),
        "SYSTEM":   (T.AMBER,   "⚡"),
        "AGENT":    (T.EMERALD, "🤖"),
        "ERROR":    (T.RED,     "✕"),
        "WHATSAPP": (T.EMERALD, "💬"),
        "FILE":     (T.AMBER,   "📄"),
        "YOU":      (T.WHITE,   "👤"),
    }

    def __init__(self, category: str, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL2};
                border: 1px solid {T.BORDER};
                border-radius: 6px;
            }}
        """)

        col, dot = self._CAT_COLORS.get(category.upper(), (T.TEXT, "●"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(2)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        cat_lbl = _label(f"{dot}  {category.upper()}", 7, True, col)
        ts_lbl  = _label(time.strftime("%H:%M"), 7, False, T.TEXT_DIM)
        hdr.addWidget(cat_lbl)
        hdr.addStretch()
        hdr.addWidget(ts_lbl)
        lay.addLayout(hdr)

        body_text = text[:120] + ("…" if len(text) > 120 else "")
        body = _label(body_text, 8, False, T.TEXT)
        body.setWordWrap(True)
        lay.addWidget(body)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.adjustSize()


class IntelligenceFeed(QWidget):
    _sig = pyqtSignal(str, str)     # category, text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        lay.addWidget(_section_header("INTELLIGENCE FEED"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; border: none; }
            QScrollBar::handle:vertical { background: #1a3060; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent; border: none;")
        self._ilay  = QVBoxLayout(self._inner)
        self._ilay.setContentsMargins(0, 0, 0, 0)
        self._ilay.setSpacing(5)
        self._ilay.addStretch()

        scroll.setWidget(self._inner)
        lay.addWidget(scroll, stretch=1)
        self._scroll = scroll
        self._count  = 0

        self._sig.connect(self._add_item)

    def add_event(self, category: str, text: str):
        self._sig.emit(category, text)

    def _add_item(self, category: str, text: str):
        item = IntelFeedItem(category, text)
        idx  = max(0, self._ilay.count() - 1)
        self._ilay.insertWidget(idx, item)
        self._count += 1
        # Cap at 50 items
        if self._count > 50:
            w = self._ilay.takeAt(0)
            if w and w.widget():
                w.widget().deleteLater()
            self._count -= 1
        QTimer.singleShot(50, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Memory insights (right panel) ─────────────────────────────────────────────
class MemoryInsightsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        lay.addWidget(_section_header("MEMORY INSIGHTS"))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)

        self._stat_widgets: dict[str, QLabel] = {}
        for key, label, col in [
            ("total",   "MEMORIES", T.VIOLET),
            ("recent",  "RECENT",   T.CYAN),
            ("cats",    "CATEGORIES", T.EMERALD),
        ]:
            cell = QWidget()
            cell.setStyleSheet(f"""
                QWidget {{
                    background: {T.PANEL2};
                    border: 1px solid {T.BORDER};
                    border-radius: 7px;
                }}
            """)
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(8, 6, 8, 6)
            cl.setSpacing(2)
            val = _label("—", 14, True, col)
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = _label(label, 6, True, T.TEXT_DIM)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(val)
            cl.addWidget(lbl)
            stats_row.addWidget(cell, stretch=1)
            self._stat_widgets[key] = val

        lay.addLayout(stats_row)

        view_btn = QPushButton("View Memory  →")
        view_btn.setFont(F(8, True))
        view_btn.setFixedHeight(26)
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.VIOLET_D}; color: {T.VIOLET};
                border: 1px solid #3d2080; border-radius: 5px;
            }}
            QPushButton:hover {{
                background: #250a4e; border: 1px solid {T.VIOLET};
                color: {T.WHITE};
            }}
        """)
        self._view_btn = view_btn
        lay.addWidget(view_btn)

        # Timer for memory refresh
        self._mem_tmr = QTimer(self)
        self._mem_tmr.timeout.connect(self._refresh)
        self._mem_tmr.start(5000)
        self._refresh()

    def _refresh(self):
        try:
            mem   = _load_memory()
            total = 0
            cats  = 0
            recent = 0
            now_ts = time.strftime("%Y-%m-%d")
            for cat, items in mem.items():
                if isinstance(items, dict) and items:
                    cats += 1
                    for _, entry in items.items():
                        if isinstance(entry, dict) and "value" in entry:
                            total += 1
                            if entry.get("updated", "") == now_ts:
                                recent += 1
            self._stat_widgets["total"].setText(str(total))
            self._stat_widgets["recent"].setText(str(recent))
            self._stat_widgets["cats"].setText(str(cats))
        except Exception:
            pass


# ── LLM status (right panel) ──────────────────────────────────────────────────
class LLMStatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(5)

        lay.addWidget(_section_header("LLM STATUS"))

        self._rows: list[tuple[str, QLabel, QLabel]] = []
        providers = [
            ("Gemini 2.5 Flash",  "gemini_api_key"),
            ("OpenRouter",         "openrouter_api_key"),
            ("Planner / Executor", None),
            ("Voice / STT",        None),
            ("Memory Engine",      None),
        ]

        for name, key in providers:
            row   = QHBoxLayout()
            row.setSpacing(8)
            dot   = _label("●", 9, True, T.TEXT_DIM)
            dot.setFixedWidth(12)
            title = _label(name, 8, False, T.TEXT)
            stat  = _label("UNKNOWN", 7, True, T.TEXT_DIM)
            stat.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(dot)
            row.addWidget(title)
            row.addStretch()
            row.addWidget(stat)

            container = QWidget()
            container.setStyleSheet("background: transparent; border: none;")
            container.setLayout(row)
            container.setFixedHeight(22)
            lay.addWidget(container)
            self._rows.append((key, dot, stat))

        # Refresh
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._refresh)
        self._tmr.start(8000)
        self._refresh()

    def _refresh(self):
        try:
            cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

        statuses = [
            bool(cfg.get("gemini_api_key", "")),
            bool(cfg.get("openrouter_api_key", "")),
            True,   # Planner always ready if we got here
            True,   # Voice
            _HAS_MEMORY,
        ]
        labels = ["CONNECTED", "CONNECTED", "READY", "ACTIVE", "LOADED"]

        for i, ((_key, dot, stat), ok) in enumerate(zip(self._rows, statuses)):
            if ok:
                dot.setStyleSheet(
                    f"color: {T.EMERALD}; background: transparent; border: none;")
                stat.setText(labels[i])
                stat.setStyleSheet(
                    f"color: {T.EMERALD}; background: transparent; border: none;")
            else:
                dot.setStyleSheet(
                    f"color: {T.TEXT_DIM}; background: transparent; border: none;")
                stat.setText("OFFLINE")
                stat.setStyleSheet(
                    f"color: {T.TEXT_DIM}; background: transparent; border: none;")

    def set_flint_online(self):
        """Mark all core services as online once FLINT connects."""
        for _key, dot, stat in self._rows[2:]:
            dot.setStyleSheet(
                f"color: {T.EMERALD}; background: transparent; border: none;")
            stat.setText("ONLINE")
            stat.setStyleSheet(
                f"color: {T.EMERALD}; background: transparent; border: none;")


# ── Voice bar (bottom) ────────────────────────────────────────────────────────
class VoiceBar(NeonPanel):
    mute_toggled   = pyqtSignal()
    command_sent   = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(glow=T.CYAN, radius=0, sweep=True, parent=parent)
        self.setFixedHeight(72)

        self._state   = "INITIALISING"
        self._muted   = False
        self._tick    = 0
        self._wave_phase = 0.0
        self._wave_tmr   = QTimer(self)
        self._wave_tmr.timeout.connect(self._wave_step)
        self._wave_tmr.start(50)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 8, 20, 8)
        outer.setSpacing(16)

        # Mic icon
        self._mic_lbl = QLabel("🎙")
        self._mic_lbl.setFont(F(20))
        self._mic_lbl.setFixedWidth(34)
        self._mic_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mic_lbl.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(self._mic_lbl)

        # Waveform + state label
        center_lay = QVBoxLayout()
        center_lay.setSpacing(3)
        center_lay.setContentsMargins(0, 0, 0, 0)

        self._state_lbl = QLabel("◌ INITIALISING...")
        self._state_lbl.setFont(F(10, True))
        self._state_lbl.setStyleSheet(
            f"color: {T.CYAN}; background: transparent; border: none; letter-spacing: 2px;")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._wave_widget = WaveformWidget()

        center_lay.addWidget(self._state_lbl)
        center_lay.addWidget(self._wave_widget)
        outer.addLayout(center_lay, stretch=1)

        # Right controls
        right_lay = QVBoxLayout()
        right_lay.setSpacing(4)
        right_lay.setContentsMargins(0, 0, 0, 0)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(F(9))
        self._input.setFixedHeight(28)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {T.INSET}; color: {T.WHITE};
                border: 1px solid {T.BORDER_HI}; border-radius: 6px;
                padding: 3px 8px;
            }}
            QLineEdit:focus {{
                border: 1px solid {T.CYAN}; background: {T.CYAN_GHO};
            }}
        """)
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("▸")
        send_btn.setFixedSize(28, 28)
        send_btn.setFont(F(12, True))
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.CYAN_GHO}; color: {T.CYAN};
                border: 1px solid {T.CYAN_DIM}; border-radius: 6px;
            }}
            QPushButton:hover {{
                background: #0a3340; border: 1px solid {T.CYAN}; color: {T.WHITE};
            }}
        """)
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        right_lay.addLayout(input_row)

        self._mute_btn = QPushButton("◉  MICROPHONE ACTIVE")
        self._mute_btn.setFont(F(8, True))
        self._mute_btn.setFixedHeight(24)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self.mute_toggled.emit)
        self._style_mute()
        right_lay.addWidget(self._mute_btn)

        outer.addLayout(right_lay)

    def _wave_step(self):
        self._wave_phase += 0.08
        self._wave_widget.set_state(self._state, self._muted, self._wave_phase)
        self._tick += 1

    def set_state(self, state: str, muted: bool = False):
        self._state  = state
        self._muted  = muted
        col   = _STATE_COLORS.get(state, T.CYAN)
        label = _STATE_LABEL.get(state, f"● {state}")
        if muted:
            col   = T.MAGENTA
            label = "⊘ MUTED"

        self._state_lbl.setText(label)
        self._state_lbl.setStyleSheet(
            f"color: {col}; background: transparent; border: none; letter-spacing: 2px;")
        self.set_glow(col)
        self._wave_widget.set_state(state, muted, self._wave_phase)

        if state == "SPEAKING" or state == "LISTENING":
            self._mic_lbl.setStyleSheet(
                f"color: {col}; background: transparent; border: none;")
        else:
            self._mic_lbl.setStyleSheet(
                "background: transparent; border: none;")

    def set_muted(self, muted: bool):
        self._muted = muted
        self._style_mute()
        self.set_state(self._state, muted)

    def _style_mute(self):
        if self._muted:
            self._mute_btn.setText("⊘  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #260a18; color: {T.MAGENTA};
                    border: 1px solid {T.MAGENTA}; border-radius: 5px;
                }}
                QPushButton:hover {{ background: #330d20; }}
            """)
        else:
            self._mute_btn.setText("◉  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {T.EMERALD_D}; color: {T.EMERALD};
                    border: 1px solid #1a4a30; border-radius: 5px;
                }}
                QPushButton:hover {{
                    background: #0a4a30; border: 1px solid {T.EMERALD};
                }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if txt:
            self._input.clear()
            self.command_sent.emit(txt)


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._state  = "INITIALISING"
        self._muted  = False
        self._phase  = 0.0

    def set_state(self, state: str, muted: bool, phase: float):
        self._state = state
        self._muted = muted
        self._phase = phase
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        N, bw = 60, max(3, W // 64)
        total = N * (bw + 1)
        x0 = (W - total) / 2
        col = _STATE_COLORS.get(self._state, T.CYAN)

        for i in range(N):
            if self._muted:
                hgt, c = 2, qcol(T.MAGENTA, 100)
            elif self._state == "SPEAKING":
                hgt = int(2 + 14 * abs(math.sin(self._phase * 1.8 + i * 0.22)))
                c   = qcol(T.WHITE if hgt > 8 else T.AMBER, 190)
            elif self._state in ("THINKING", "PROCESSING"):
                hgt = int(3 + 8 * abs(math.sin(self._phase * 1.2 + i * 0.35)))
                c   = qcol(col, 160)
            elif self._state == "LISTENING":
                hgt = int(2 + 5 * abs(math.sin(self._phase * 0.9 + i * 0.28)))
                c   = qcol(col, 140)
            else:
                hgt = int(1 + 2 * abs(math.sin(self._phase * 0.5 + i * 0.4)))
                c   = qcol(T.BORDER_HI, 120)

            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            bar_x = x0 + i * (bw + 1)
            bar_y = (H - hgt) / 2
            p.drawRoundedRect(QRectF(bar_x, bar_y, bw, hgt), 1, 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  CENTER VIEW PANELS
# ═══════════════════════════════════════════════════════════════════════════════

class AICoreView(QWidget):
    """Default center view: orb + agents + mission timeline + quick commands + sysmon."""

    quick_command = pyqtSignal(str)

    def __init__(self, hud: HudCanvas, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # ── Orb section ─────────────────────────────────────────────────────
        orb_panel = NeonPanel(glow=T.CYAN, radius=12, sweep=True)
        orb_panel.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
        orb_lay = QVBoxLayout(orb_panel)
        orb_lay.setContentsMargins(0, 6, 0, 0)
        orb_lay.setSpacing(0)

        # Header in orb panel
        orb_hdr = QHBoxLayout()
        orb_hdr.setContentsMargins(14, 0, 14, 0)
        flint_lbl = _label("FLINT  AI CORE", 9, True, T.TEXT_DIM)
        flint_lbl.setStyleSheet(
            f"color: {T.TEXT_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        self._orb_status = _label("● INITIALISING", 9, True, T.CYAN)
        self._orb_status.setStyleSheet(
            f"color: {T.CYAN}; background: transparent; border: none; letter-spacing: 2px;")
        self._orb_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        orb_hdr.addWidget(flint_lbl)
        orb_hdr.addStretch()
        orb_hdr.addWidget(self._orb_status)

        hdr_container = QWidget()
        hdr_container.setStyleSheet("background: transparent; border: none;")
        hdr_container.setLayout(orb_hdr)
        orb_lay.addWidget(hdr_container)

        orb_lay.addWidget(hud, stretch=1)
        lay.addWidget(orb_panel, stretch=5)

        # ── Agents strip ────────────────────────────────────────────────────
        self.agents = AgentsStrip()
        lay.addWidget(self.agents, stretch=0)

        # ── Mission timeline + Quick commands ────────────────────────────────
        bot_row = QHBoxLayout()
        bot_row.setSpacing(8)

        self.timeline = MissionTimeline()
        self.quickcmds = QuickCommandsPanel()
        self.quickcmds.command_triggered.connect(self.quick_command.emit)

        bot_row.addWidget(self.timeline, stretch=5)
        bot_row.addWidget(self.quickcmds, stretch=4)
        lay.addLayout(bot_row, stretch=3)

        # ── System monitor strip ─────────────────────────────────────────────
        self.sysmon = SystemMonitorStrip()
        lay.addWidget(self.sysmon, stretch=0)

    def set_state(self, state: str):
        col   = _STATE_COLORS.get(state, T.CYAN)
        label = _STATE_LABEL.get(state, f"● {state}")
        self._orb_status.setText(label)
        self._orb_status.setStyleSheet(
            f"color: {col}; background: transparent; border: none; letter-spacing: 2px;")


class ConversationsView(QWidget):
    """Center view showing conversation log."""

    def __init__(self, log_widget: LogWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lay.addWidget(_section_header("CONVERSATIONS"))
        lay.addWidget(log_widget, stretch=1)


class TerminalView(QWidget):
    """Center view showing system terminal."""

    def __init__(self, terminal: TerminalWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lay.addWidget(_section_header("SYSTEM TERMINAL"))
        lay.addWidget(terminal, stretch=1)


class MemoryView(QWidget):
    """Center view showing memory categories."""

    _sig = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        lay.addWidget(_section_header("MEMORY MATRIX"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 5px; border: none; }
            QScrollBar::handle:vertical { background: #1a3060; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent; border: none;")
        self._ilay  = QVBoxLayout(self._inner)
        self._ilay.setContentsMargins(0, 0, 0, 0)
        self._ilay.setSpacing(6)
        self._ilay.addStretch()

        scroll.setWidget(self._inner)
        lay.addWidget(scroll, stretch=1)

        refresh_btn = QPushButton("↻  Refresh Memory")
        refresh_btn.setFont(F(8, True))
        refresh_btn.setFixedHeight(28)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {T.VIOLET_D}; color: {T.VIOLET};
                border: 1px solid #3d2080; border-radius: 5px;
            }}
            QPushButton:hover {{ background: #250a4e; border: 1px solid {T.VIOLET}; color: {T.WHITE}; }}
        """)
        refresh_btn.clicked.connect(self.refresh)
        lay.addWidget(refresh_btn)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self.refresh)
        self._tmr.start(10000)
        self.refresh()

    def refresh(self):
        while self._ilay.count() > 1:
            item = self._ilay.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        try:
            mem  = _load_memory()
            cats = [(k, v) for k, v in mem.items() if isinstance(v, dict) and v]
            if not cats:
                lbl = _label("No memories stored yet.", 9, False, T.TEXT_DIM)
                self._ilay.insertWidget(0, lbl)
                return

            for cat, items in cats:
                cat_lbl = _label(f"▸  {cat.upper()}", 9, True, T.VIOLET)
                cat_lbl.setStyleSheet(
                    f"color: {T.VIOLET}; background: transparent; border: none; padding-top: 4px;")
                self._ilay.insertWidget(self._ilay.count() - 1, cat_lbl)

                for key, entry in list(items.items())[:10]:
                    val   = entry.get("value", "") if isinstance(entry, dict) else str(entry)
                    upd   = entry.get("updated", "") if isinstance(entry, dict) else ""
                    row_w = QWidget()
                    row_w.setStyleSheet(f"""
                        QWidget {{
                            background: {T.PANEL2}; border: 1px solid {T.BORDER};
                            border-radius: 6px;
                        }}
                    """)
                    rlay  = QHBoxLayout(row_w)
                    rlay.setContentsMargins(10, 6, 10, 6)
                    rlay.setSpacing(10)
                    rlay.addWidget(_label(key, 8, True, T.CYAN))
                    rlay.addWidget(_label(str(val)[:80], 8, False, T.TEXT), stretch=1)
                    rlay.addWidget(_label(upd, 7, False, T.TEXT_DIM))
                    row_w.setFixedHeight(36)
                    self._ilay.insertWidget(self._ilay.count() - 1, row_w)
        except Exception:
            lbl = _label("Memory unavailable.", 9, False, T.TEXT_DIM)
            self._ilay.insertWidget(0, lbl)


class PlaceholderView(QWidget):
    def __init__(self, title: str = "COMING SOON", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = _label("◎", 48, False, T.BORDER_HI)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl  = _label(title, 13, True, T.TEXT_DIM)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub  = _label("This section is under development.", 9, False, T.TEXT_DIM)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(icon)
        lay.addWidget(lbl)
        lay.addWidget(sub)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _link_sig  = pyqtSignal(int)
    _jobs_sig  = pyqtSignal(int)
    _toast_sig = pyqtSignal(str, str)
    _task_sig  = pyqtSignal(str, str, bool)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("F.L.I.N.T — MISSION CONTROL")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width()  - _DEFAULT_W) // 2,
                  (screen.height() - _DEFAULT_H) // 2)

        self.on_text_command = None
        self._muted   = False
        self._compact = False
        self._state   = "INITIALISING"

        # Central widget
        central = QWidget()
        central.setStyleSheet(f"background: {T.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──────────────────────────────────────────────────────────
        self._topbar = TopBar()
        self._topbar._compact_btn.clicked.connect(self._toggle_compact_mode)
        root.addWidget(self._topbar)

        # ── Body row ─────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left sidebar
        self._sidebar = NavSidebar()
        self._sidebar.nav_changed.connect(self._switch_center)
        body.addWidget(self._sidebar)

        # Thin left border separator
        sep_l = QFrame()
        sep_l.setFixedWidth(1)
        sep_l.setStyleSheet(f"background: {T.BORDER}; border: none;")
        body.addWidget(sep_l)

        # Center area
        self._center_wrap = QWidget()
        self._center_wrap.setStyleSheet("background: transparent; border: none;")
        center_lay = QVBoxLayout(self._center_wrap)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        # Shared widgets
        self.hud      = HudCanvas(face_path)
        self._log     = LogWidget()
        self._terminal = TerminalWidget()

        # Center stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        self._ai_view    = AICoreView(self.hud)
        self._conv_view  = ConversationsView(self._log)
        self._term_view  = TerminalView(self._terminal)
        self._mem_view   = MemoryView()
        self._placeholder = PlaceholderView()

        self._stack.addWidget(self._ai_view)      # 0
        self._stack.addWidget(self._conv_view)    # 1
        self._stack.addWidget(self._term_view)    # 2
        self._stack.addWidget(self._mem_view)     # 3
        self._stack.addWidget(self._placeholder)  # 4

        # Connect quick commands
        self._ai_view.quick_command.connect(self._on_quick_cmd)

        center_lay.addWidget(self._stack)
        body.addWidget(self._center_wrap, stretch=1)

        # Thin right border separator
        sep_r = QFrame()
        sep_r.setFixedWidth(1)
        sep_r.setStyleSheet(f"background: {T.BORDER}; border: none;")
        body.addWidget(sep_r)

        # Right panel
        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel)

        root.addLayout(body, stretch=1)

        # ── Voice bar ─────────────────────────────────────────────────────────
        self._voicebar = VoiceBar()
        self._voicebar.mute_toggled.connect(self._toggle_mute)
        self._voicebar.command_sent.connect(self._on_voicebar_cmd)
        root.addWidget(self._voicebar)

        # ── Timers ────────────────────────────────────────────────────────────
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        # ── Cross-thread signals ──────────────────────────────────────────────
        self._log_sig.connect(self._on_log)
        self._state_sig.connect(self._apply_state)
        self._link_sig.connect(self._apply_link)
        self._jobs_sig.connect(self._apply_jobs)
        self._toast_sig.connect(self._on_toast_sig)
        self._task_sig.connect(self._on_task_sig)

        # ── Boot overlay ──────────────────────────────────────────────────────
        self._boot = BootOverlay(central)
        self._boot.setGeometry(0, 0, self.width(), self.height())
        self._boot.show()
        self._boot.raise_()

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        # ── Keyboard shortcuts ────────────────────────────────────────────────
        QShortcut(QKeySequence("Ctrl+Space"),       self).activated.connect(self._wake_up)
        QShortcut(QKeySequence("Ctrl+Shift+Space"), self).activated.connect(self._wake_up)
        QShortcut(QKeySequence("F10"),              self).activated.connect(self._toggle_compact_mode)
        QShortcut(QKeySequence("Ctrl+M"),           self).activated.connect(self._toggle_compact_mode)
        QShortcut(QKeySequence("F4"),               self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("F11"),              self).activated.connect(self._toggle_fullscreen)

        # ── System tray ───────────────────────────────────────────────────────
        self._setup_tray()

    # ── Right panel builder ───────────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(276)
        panel.setStyleSheet(f"background: {T.SIDEBAR}; border: none;")

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._intel_feed = IntelligenceFeed()
        lay.addWidget(self._intel_feed, stretch=3)

        self._mem_insights = MemoryInsightsWidget()
        self._mem_insights.setFixedHeight(132)
        # wire view memory button
        self._mem_insights._view_btn.clicked.connect(
            lambda: self._switch_center(3))
        lay.addWidget(self._mem_insights)

        self._llm_status = LLMStatusWidget()
        self._llm_status.setFixedHeight(136)
        lay.addWidget(self._llm_status)

        # File upload section
        file_card = QWidget()
        file_card.setStyleSheet(f"""
            QWidget {{
                background: {T.PANEL};
                border: 1px solid {T.BORDER};
                border-radius: 10px;
            }}
        """)
        fl = QVBoxLayout(file_card)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(5)
        fl.addWidget(_section_header("FILE UPLOAD"))

        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        fl.addWidget(self._drop_zone)

        self._file_hint = _label("No file loaded", 7, False, T.TEXT_DIM)
        self._file_hint.setWordWrap(True)
        fl.addWidget(self._file_hint)

        lay.addWidget(file_card)
        return panel

    # ── Resize / fullscreen ───────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._boot and self._boot.isVisible():
            self._boot.setGeometry(0, 0, cw.width(), cw.height())
        if self._overlay and self._overlay.isVisible():
            ow, oh = 490, 430
            self._overlay.setGeometry((cw.width() - ow) // 2,
                                      (cw.height() - oh) // 2, ow, oh)

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # ── Center view switching ─────────────────────────────────────────────────
    def _switch_center(self, page: int):
        self._stack.setCurrentIndex(min(page, self._stack.count() - 1))

    # ── Metric updates ────────────────────────────────────────────────────────
    def _update_metrics(self):
        snap = _metrics.snapshot()
        self._ai_view.sysmon.update_metrics(snap)

    # ── Log entry classifier → intelligence feed ──────────────────────────────
    def _on_log(self, text: str):
        # Always append to conversation log
        self._log.append_log(text)

        # Classify for intelligence feed
        tl = text.lower()
        if text.startswith("You:") or text.startswith("you:"):
            user_text = text[4:].strip()
            if user_text:
                self._intel_feed.add_event("YOU", user_text)
        elif text.lower().startswith("flint:"):
            ai_text = text[6:].strip()
            if ai_text:
                self._intel_feed.add_event("AI", ai_text)
        elif "memory" in tl and any(w in tl for w in ("stored", "loaded", "saved", "updated", "✅")):
            self._intel_feed.add_event("MEMORY", text)
        elif "whatsapp" in tl and any(w in tl for w in ("sent", "received", "message")):
            self._intel_feed.add_event("WHATSAPP", text)
        elif text.startswith("SYS:") or text.startswith("sys:"):
            self._intel_feed.add_event("SYSTEM", text[4:].strip())
        elif "err" in tl and len(text) < 200:
            self._intel_feed.add_event("ERROR", text)

    # ── File selected ─────────────────────────────────────────────────────────
    def _on_file_selected(self, path: str):
        p    = Path(path)
        icon, _ = _FILE_ICONS.get(_file_category(p), _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        self._intel_feed.add_event("FILE", f"{p.name} loaded ({size})")
        if self.on_text_command:
            msg = (f"[FILE_UPLOADED] path={path} | name={p.name} | "
                   f"type={p.suffix.lstrip('.')} | size={size} | "
                   f"Briefly tell the user you can see the file '{p.name}' "
                   f"({size}) has been uploaded and ask what they'd like to do with it.")
            threading.Thread(target=self.on_text_command, args=(msg,),
                             daemon=True).start()

    # ── Quick command ─────────────────────────────────────────────────────────
    def _on_quick_cmd(self, cmd: str):
        if not cmd:
            return
        self._on_log(f"You: {cmd}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,),
                             daemon=True).start()

    def _on_voicebar_cmd(self, txt: str):
        self._on_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,),
                             daemon=True).start()

    # ── State application ─────────────────────────────────────────────────────
    def _apply_state(self, state: str):
        self._state  = state
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        self.hud.muted    = self._muted

        self._ai_view.set_state(state if not self._muted else "MUTED")
        self._voicebar.set_state(state, self._muted)
        self._topbar.set_state_badge(state)

        col = _STATE_COLORS.get(state, T.CYAN)
        if state in ("THINKING", "PROCESSING"):
            self._topbar._spinner.set_color(col)
            self._topbar._spinner.start()
        else:
            self._topbar._spinner.stop()

        # Boot finish trigger
        if state in ("LISTENING", "SPEAKING") and self._boot.isVisible():
            self._boot.finish()
            self._llm_status.set_flint_online()
            self._sidebar.set_status("● FLINT ONLINE", T.EMERALD)
            self._intel_feed.add_event("SYSTEM", "FLINT connected and listening")

    def _apply_link(self, clients: int):
        self._topbar.set_link_clients(clients)

    def _apply_jobs(self, active: int):
        lbl = f"JOBS {active}" if active > 0 else ""
        self._topbar._jobs_lbl.setText(lbl)

    # ── Mute ─────────────────────────────────────────────────────────────────
    def _toggle_mute(self):
        self._muted   = not self._muted
        self.hud.muted = self._muted
        self._voicebar.set_muted(self._muted)
        self._apply_state("MUTED" if self._muted else "LISTENING")
        msg = "SYS: Microphone muted." if self._muted else "SYS: Microphone active."
        self._log.append_log(msg)
        self._intel_feed.add_event("SYSTEM",
            "Microphone muted" if self._muted else "Microphone activated")

    # ── Compact mode ──────────────────────────────────────────────────────────
    def _toggle_compact_mode(self):
        self._compact = not self._compact
        if self._compact:
            self._sidebar.hide()
            self._right_panel.hide()
            self._topbar.hide()
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self.resize(360, 380)
            self.show()
            self._on_toast_sig("❐ Compact Mode  (F10 to restore)", "info")
        else:
            self._sidebar.show()
            self._right_panel.show()
            self._topbar.show()
            self.setWindowFlags(
                self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            self.resize(_DEFAULT_W, _DEFAULT_H)
            self.show()
            self._on_toast_sig("⤢ Dashboard Restored", "info")

    # ── Wake up ───────────────────────────────────────────────────────────────
    def _wake_up(self):
        if self.isMinimized():
            self.showNormal()
        self.activateWindow()
        self.raise_()
        if self._muted:
            self._toggle_mute()
        else:
            self._apply_state("LISTENING")
        self._on_toast_sig("⚡ FLINT Awakened & Listening", "ok")
        self._intel_feed.add_event("SYSTEM", "FLINT awakened via Ctrl+Space")

    # ── Toast ─────────────────────────────────────────────────────────────────
    def _on_toast_sig(self, message: str, level: str):
        cw = self.centralWidget()
        if not cw:
            return
        toast = ToastWidget(message, level, cw)
        toast.adjustSize()
        tw, th = max(toast.width(), 260), toast.height()
        toast.setGeometry(cw.width() - tw - 16, 60, tw, th)
        toast.show()
        toast.raise_()
        toast.fade_in_and_out()

    # ── Task state → mission timeline ─────────────────────────────────────────
    def _on_task_sig(self, goal: str, text: str, active: bool):
        self._ai_view.timeline.add_event(goal, text, active)
        # Update agents strip with which tool is active
        if active and text:
            tool = text.replace("Executing ", "").replace("...", "").strip()
            self._ai_view.agents.set_active_tool(tool)
        elif not active:
            self._ai_view.agents.set_active_tool(None)

        if active and text:
            self._intel_feed.add_event("AGENT", text)

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self)
        px = QPixmap(32, 32)
        px.fill(QColor(T.BG))
        p = QPainter(px)
        p.setFont(F(13, True))
        p.setPen(QPen(QColor(T.CYAN)))
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignmentFlag.AlignCenter, "F")
        p.end()
        self._tray.setIcon(QIcon(px))

        menu = QMenu(self)
        menu.addAction("◉ Show Dashboard",           self._wake_up)
        menu.addAction("⚡ Wake Up (Ctrl+Space)",     self._wake_up)
        menu.addAction("🎙 Toggle Mic (F4)",          self._toggle_mute)
        menu.addAction("❐ Toggle Compact (F10)",      self._toggle_compact_mode)
        menu.addSeparator()
        menu.addAction("❌ Exit FLINT",               QApplication.quit)

        self._tray.setContextMenu(menu)
        self._tray.setToolTip("FLINT — Ctrl+Space to Wake")
        self._tray.show()

    # ── Config gate ───────────────────────────────────────────────────────────
    def _check_config(self) -> bool:
        if not API_FILE.exists():
            return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (bool(d.get("gemini_api_key"))
                    and bool(d.get("openrouter_api_key"))
                    and bool(d.get("os_system")))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 490, 430
        ov.setGeometry((cw.width() - ow) // 2,
                       (cw.height() - oh) // 2, ow, oh)
        ov.done.connect(self._on_setup_done)
        ov.show()
        ov.raise_()
        self._overlay = ov

    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        existing = {}
        try:
            existing = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        existing.update({
            "gemini_api_key":      key,
            "openrouter_api_key":  or_key,
            "os_system":           os_name,
        })
        API_FILE.write_text(json.dumps(existing, indent=4), encoding="utf-8")
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. FLINT online.")


# ── Qt mainloop shim (main.py compatibility) ──────────────────────────────────
class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


# ── Public API (stable interface for main.py and all actions/) ────────────────
class FlintUI:
    """Public API — all callers in main.py use only these methods/properties."""

    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    # ── Properties ────────────────────────────────────────────────────────────
    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    # ── Methods ───────────────────────────────────────────────────────────────
    def set_state(self, state: str):
        """Thread-safe state update."""
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        """Thread-safe log entry (conversation + intelligence feed)."""
        self._win._log_sig.emit(text)

    def set_link_clients(self, n: int):
        """Remote phone client count update."""
        self._win._link_sig.emit(n)

    def show_toast(self, message: str, level: str = "info"):
        """Show a floating toast notification."""
        self._win._toast_sig.emit(message, level)

    def update_task_state(self, goal: str, text: str = "", active: bool = True):
        """Update mission timeline with current task progress."""
        self._win._task_sig.emit(goal, text, active)

    def toggle_compact_mode(self):
        self._win._toggle_compact_mode()

    def wake_up(self):
        self._win._wake_up()

    def attach_pipeline(self, pipeline):
        """Mirror pipeline job count in the top bar (thread-safe)."""
        def _refresh(_payload):
            try:
                self._win._jobs_sig.emit(
                    len(pipeline.active_jobs()) + pipeline.queued_count())
            except Exception:
                pass
        for ev in ("job_submitted", "job_started", "job_finished", "job_failed"):
            pipeline.bus.on(ev, _refresh)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
