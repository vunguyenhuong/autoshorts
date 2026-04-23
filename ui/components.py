"""
AutoTiktok — Reusable UI Components v3
Clean SaaS design — Indigo primary, neutral grays
"""

from PyQt6.QtWidgets import (
    QPushButton, QProgressBar, QTextEdit, QFrame, QLabel,
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor


# ─────────────────────────────────────────────────────────────────────────────
#  PRIMARY BUTTON — indigo fill, main CTA
# ─────────────────────────────────────────────────────────────────────────────
class PrimaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            PrimaryButton {
                background-color: #6366F1;
                color: #FFFFFF;
                border: none;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: 700;
                font-size: 13px;
                min-height: 34px;
            }
            PrimaryButton:hover {
                background-color: #818CF8;
            }
            PrimaryButton:pressed {
                background-color: #4F46E5;
            }
            PrimaryButton:disabled {
                background-color: #1E2130;
                color: #3D4663;
            }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  SUCCESS BUTTON — green, for add/confirm
# ─────────────────────────────────────────────────────────────────────────────
class SuccessButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            SuccessButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: 700;
                font-size: 13px;
                min-height: 34px;
            }
            SuccessButton:hover { background-color: #34D399; }
            SuccessButton:pressed { background-color: #059669; }
            SuccessButton:disabled { background-color: #1E2130; color: #3D4663; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  DANGER BUTTON — red, for stop/delete
# ─────────────────────────────────────────────────────────────────────────────
class DangerButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            DangerButton {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: 700;
                font-size: 13px;
                min-height: 34px;
            }
            DangerButton:hover { background-color: #F87171; }
            DangerButton:pressed { background-color: #DC2626; }
            DangerButton:disabled { background-color: #1E2130; color: #3D4663; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  SECONDARY BUTTON — outlined indigo
# ─────────────────────────────────────────────────────────────────────────────
class SecondaryButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            SecondaryButton {
                background: transparent;
                color: #818CF8;
                border: 1px solid #4A526A;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 13px;
                min-height: 34px;
            }
            SecondaryButton:hover {
                background: rgba(99,102,241,0.1);
                border-color: #6366F1;
                color: #A5B4FC;
            }
            SecondaryButton:pressed { background: rgba(99,102,241,0.2); }
            SecondaryButton:disabled { color: #3D4663; border-color: #2D3244; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  GHOST BUTTON — minimal, for save/load/utilities
# ─────────────────────────────────────────────────────────────────────────────
class GhostButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            GhostButton {
                background: transparent;
                color: #64748B;
                border: 1px solid #2D3244;
                border-radius: 7px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 13px;
                min-height: 34px;
            }
            GhostButton:hover {
                background: #252A36;
                border-color: #4A526A;
                color: #CBD5E1;
            }
            GhostButton:pressed { background: #1C1F28; }
            GhostButton:disabled { color: #3D4663; border-color: #1E2130; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  SMALL DANGER BUTTON — compact remove/delete
# ─────────────────────────────────────────────────────────────────────────────
class SmallDangerButton(QPushButton):
    def __init__(self, text="✕", parent=None):
        super().__init__(text, parent)
        self.setFixedSize(QSize(64, 30))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            SmallDangerButton {
                background: rgba(239,68,68,0.1);
                color: #F87171;
                border: 1px solid rgba(239,68,68,0.25);
                border-radius: 6px;
                font-weight: 700;
                font-size: 12px;
                padding: 4px 8px;
            }
            SmallDangerButton:hover {
                background: rgba(239,68,68,0.2);
                border-color: #EF4444;
            }
            SmallDangerButton:pressed { background: #EF4444; color: white; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  SIDEBAR NAV BUTTON
# ─────────────────────────────────────────────────────────────────────────────
class SidebarNavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._label = label
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self._build()
        self._refresh_style()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        self._icon_lbl = QLabel(self._icon)
        self._icon_lbl.setFixedWidth(20)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        self._icon_lbl.setFont(font)
        layout.addWidget(self._icon_lbl)

        self._text_lbl = QLabel(self._label)
        f = QFont("Inter", 13)
        f.setWeight(QFont.Weight.Medium)
        self._text_lbl.setFont(f)
        layout.addWidget(self._text_lbl)
        layout.addStretch()

    def _refresh_style(self):
        dark = getattr(self, '_dark', True)
        if self.isChecked():
            if dark:
                bg, border, color = "rgba(99,102,241,0.15)", "2px solid #6366F1", "#A5B4FC"
            else:
                bg, border, color = "rgba(79,70,229,0.1)", "2px solid #4F46E5", "#4F46E5"
            weight = "700"
        else:
            bg, border = "transparent", "2px solid transparent"
            color = "#475569" if dark else "#64748B"
            weight = "500"

        hover_bg = "rgba(99,102,241,0.08)" if dark else "rgba(79,70,229,0.06)"

        self.setStyleSheet(f"""
            SidebarNavButton {{
                background: {bg};
                border: none;
                border-left: {border};
                border-radius: 0;
                text-align: left;
                padding: 0;
                min-height: 44px;
            }}
            SidebarNavButton:hover {{
                background: {hover_bg};
            }}
        """)
        for lbl in (self._icon_lbl, self._text_lbl):
            lbl.setStyleSheet(
                f"color:{color}; background:transparent; border:none; font-weight:{weight};"
            )

    def apply_theme(self, dark: bool):
        self._dark = dark
        self._refresh_style()

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._refresh_style()



# ─────────────────────────────────────────────────────────────────────────────
#  TERMINAL LOG
# ─────────────────────────────────────────────────────────────────────────────
class TerminalLog(QTextEdit):
    """GitHub-dark / clean-light terminal style log area."""

    _DARK_QSS = """
        TerminalLog {
            background-color: #0D1117;
            color: #8B949E;
            border: 1px solid #21262D;
            border-radius: 8px;
            padding: 8px;
            font-family: "Consolas","JetBrains Mono","Cascadia Code","Courier New",monospace;
            font-size: 11px;
            line-height: 1.6;
        }
    """
    _LIGHT_QSS = """
        TerminalLog {
            background-color: #F8F9FB;
            color: #334155;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 8px;
            font-family: "Consolas","JetBrains Mono","Cascadia Code","Courier New",monospace;
            font-size: 11px;
            line-height: 1.6;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 11))
        self._dark = True
        self.setStyleSheet(self._DARK_QSS)

    def apply_theme(self, dark: bool):
        self._dark = dark
        self.setStyleSheet(self._DARK_QSS if dark else self._LIGHT_QSS)

    def append_log(self, msg: str):
        dark = self._dark
        ml = msg.lower()
        if any(k in ml for k in ("✅", "success", "xong", "hoàn tất", "finished", "ok", "done")):
            color = "#3FB950" if dark else "#16A34A"
        elif any(k in ml for k in ("❌", "error", "lỗi", "fail", "critical")):
            color = "#F85149" if dark else "#DC2626"
        elif any(k in ml for k in ("⚠", "warning", "cảnh báo", "thiếu")):
            color = "#D29922" if dark else "#D97706"
        elif any(k in ml for k in ("⬇", "tải", "download", "push", "adb")):
            color = "#58A6FF" if dark else "#2563EB"
        elif any(k in ml for k in ("⏳", "đang", "processing", "running", "quét", "scan")):
            color = "#A5B4FC" if dark else "#4F46E5"
        else:
            color = "#8B949E" if dark else "#475569"
        self.append(f'<span style="color:{color};font-family:Consolas,monospace">{msg}</span>')
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())



# ─────────────────────────────────────────────────────────────────────────────
#  STYLED PROGRESS BAR (uses global QSS)
# ─────────────────────────────────────────────────────────────────────────────
class StyledProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setTextVisible(False)


# ─────────────────────────────────────────────────────────────────────────────
#  INFO BADGE
# ─────────────────────────────────────────────────────────────────────────────
class InfoBadge(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet("""
            InfoBadge {
                background: rgba(99,102,241,0.1);
                color: #818CF8;
                border: 1px solid rgba(99,102,241,0.25);
                border-radius: 6px;
                padding: 5px 9px;
                font-size: 12px;
            }
        """)
