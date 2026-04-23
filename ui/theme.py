"""
AutoTiktok Design System — v3 (SaaS Clean)
Style: Modern SaaS Dashboard (Linear / Vercel / Notion inspired)
- Primary: Indigo (not harsh purple)
- Neutral grayscale for surfaces & borders
- High-contrast text (WCAG AA compliant)
"""

# ── DARK palette ──────────────────────────────────────────────────────────────
DARK = {
    # Backgrounds
    "bg":             "#0F1117",   # deepest background
    "surface":        "#1C1F28",   # card / panel
    "surface2":       "#252A36",   # input / elevated element
    "surface3":       "#2E3344",   # hover state

    # Borders
    "border":         "#2D3244",   # default border (subtle)
    "border_hover":   "#4A526A",   # hover border
    "border_focus":   "#6366F1",   # focus (indigo)

    # Brand
    "primary":        "#6366F1",   # indigo-500
    "primary_hover":  "#818CF8",   # indigo-400 (lighter on hover)
    "primary_pressed":"#4F46E5",   # indigo-600

    # Text
    "text":           "#F1F5F9",   # slate-100 — high contrast
    "text_sub":       "#CBD5E1",   # slate-300 — subtext
    "text_muted":     "#64748B",   # slate-500 — placeholder
    "text_disabled":  "#334155",   # slate-700 — disabled

    # Semantic
    "success":        "#10B981",   # emerald-500
    "success_bg":     "#022C22",
    "warning":        "#F59E0B",   # amber-500
    "warning_bg":     "#1C1400",
    "danger":         "#EF4444",   # red-500
    "danger_hover":   "#F87171",
    "danger_bg":      "#2C0A0A",

    # Scrollbar
    "scroll_track":   "#1C1F28",
    "scroll_thumb":   "#2D3244",
    "scroll_hover":   "#4A526A",

    # Sidebar
    "sidebar_bg":     "#0A0C12",
    "sidebar_border": "#1E2130",
}

# ── LIGHT palette ─────────────────────────────────────────────────────────────
LIGHT = {
    "bg":             "#F8F9FB",
    "surface":        "#FFFFFF",
    "surface2":       "#F1F3F7",
    "surface3":       "#E8EBF2",

    "border":         "#E2E8F0",
    "border_hover":   "#CBD5E1",
    "border_focus":   "#6366F1",

    "primary":        "#4F46E5",   # indigo-600
    "primary_hover":  "#6366F1",   # indigo-500
    "primary_pressed":"#4338CA",   # indigo-700

    "text":           "#0F172A",   # slate-900
    "text_sub":       "#334155",   # slate-700
    "text_muted":     "#64748B",   # slate-500
    "text_disabled":  "#94A3B8",   # slate-400

    "success":        "#059669",
    "success_bg":     "#ECFDF5",
    "warning":        "#D97706",
    "warning_bg":     "#FFFBEB",
    "danger":         "#DC2626",
    "danger_hover":   "#EF4444",
    "danger_bg":      "#FEF2F2",

    "scroll_track":   "#F1F3F7",
    "scroll_thumb":   "#CBD5E1",
    "scroll_hover":   "#94A3B8",

    "sidebar_bg":     "#0A0C12",
    "sidebar_border": "#1E2130",
}


def get_stylesheet(dark: bool = True) -> str:
    c = DARK if dark else LIGHT

    return f"""
/* ═══════════════════════════════════════════
   BASE RESET
═══════════════════════════════════════════ */
* {{
    outline: none;
}}
QWidget {{
    color: {c['text']};
    font-family: "Inter", "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog, QStackedWidget {{
    background-color: {c['bg']};
}}
QFrame {{
    border: none;
}}

/* ═══════════════════════════════════════════
   SCROLLBARS — thin & clean
═══════════════════════════════════════════ */
QScrollBar:vertical {{
    background: {c['scroll_track']};
    width: 7px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c['scroll_thumb']};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    border: none;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QScrollBar:horizontal {{
    background: {c['scroll_track']};
    height: 7px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {c['scroll_thumb']};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    border: none;
    background: none;
}}

/* ═══════════════════════════════════════════
   LINE EDIT — clean, focused
═══════════════════════════════════════════ */
QLineEdit {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 6px 10px;
    color: {c['text']};
    font-size: 13px;
    selection-background-color: {c['primary']};
    selection-color: white;
    min-height: 28px;
}}
QLineEdit:focus {{
    border-color: {c['border_focus']};
    background-color: {c['surface']};
}}
QLineEdit:disabled {{
    background-color: {c['surface']};
    color: {c['text_disabled']};
    border-color: {c['border']};
}}
QLineEdit:read-only {{
    background-color: {c['surface']};
    color: {c['text_sub']};
}}

/* ═══════════════════════════════════════════
   TEXT EDIT
═══════════════════════════════════════════ */
QTextEdit {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 8px 10px;
    color: {c['text']};
    font-size: 13px;
    selection-background-color: {c['primary']};
}}
QTextEdit:focus {{
    border-color: {c['border_focus']};
    background-color: {c['surface']};
}}

/* ═══════════════════════════════════════════
   COMBO BOX
═══════════════════════════════════════════ */
QComboBox {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 6px 28px 6px 10px;
    color: {c['text']};
    font-size: 13px;
    min-height: 28px;
}}
QComboBox:hover {{ border-color: {c['border_hover']}; }}
QComboBox:focus, QComboBox:on {{ border-color: {c['border_focus']}; }}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    subcontrol-position: right center;
}}
QComboBox::down-arrow {{ width: 0; }}
QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    border: 1px solid {c['border_hover']};
    border-radius: 7px;
    padding: 4px;
    selection-background-color: {c['primary']};
    selection-color: white;
    color: {c['text']};
    outline: none;
}}

/* ═══════════════════════════════════════════
   SPIN BOX — no colored arrows
═══════════════════════════════════════════ */
QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit {{
    background-color: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 6px 24px 6px 10px;
    color: {c['text']};
    font-size: 13px;
    min-height: 28px;
}}
QSpinBox:focus, QDoubleSpinBox:focus,
QTimeEdit:focus, QDateEdit:focus {{
    border-color: {c['border_focus']};
    background-color: {c['surface']};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {c['text_disabled']};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button,
QDateEdit::up-button, QDateEdit::down-button {{
    background: transparent;
    border: none;
    width: 14px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QTimeEdit::up-button, QDateEdit::up-button {{
    subcontrol-position: top right;
    margin: 2px 2px 0 0;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button,
QTimeEdit::down-button, QDateEdit::down-button {{
    subcontrol-position: bottom right;
    margin: 0 2px 2px 0;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 0; height: 0; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 0; height: 0; }}

/* ═══════════════════════════════════════════
   CHECKBOX
═══════════════════════════════════════════ */
QCheckBox {{
    color: {c['text_sub']};
    spacing: 8px;
    background: transparent;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {c['border_hover']};
    border-radius: 4px;
    background-color: {c['surface2']};
}}
QCheckBox::indicator:hover {{ border-color: {c['primary']}; }}
QCheckBox::indicator:checked {{
    background-color: {c['primary']};
    border-color: {c['primary']};
    image: none;
}}
QCheckBox:disabled {{ color: {c['text_disabled']}; }}

/* ═══════════════════════════════════════════
   RADIO BUTTON
═══════════════════════════════════════════ */
QRadioButton {{
    color: {c['text_sub']};
    spacing: 8px;
    background: transparent;
    font-size: 13px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {c['border_hover']};
    border-radius: 8px;
    background-color: {c['surface2']};
}}
QRadioButton::indicator:hover {{ border-color: {c['primary']}; }}
QRadioButton::indicator:checked {{
    background-color: {c['primary']};
    border-color: {c['primary']};
}}

/* ═══════════════════════════════════════════
   GROUP BOX — card style
═══════════════════════════════════════════ */
QGroupBox {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    margin-top: 20px;
    padding: 16px 14px 12px 14px;
    font-weight: 600;
    font-size: 13px;
    color: {c['text']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -1px;
    padding: 1px 8px;
    color: {c['text_sub']};
    background-color: {c['bg']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border-radius: 4px;
    text-transform: uppercase;
}}

/* ═══════════════════════════════════════════
   PUSH BUTTON — base / secondary
═══════════════════════════════════════════ */
QPushButton {{
    background-color: {c['surface2']};
    color: {c['text_sub']};
    border: 1px solid {c['border']};
    border-radius: 7px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 13px;
    min-height: 30px;
}}
QPushButton:hover {{
    background-color: {c['surface3']};
    border-color: {c['border_hover']};
    color: {c['text']};
}}
QPushButton:pressed {{
    background-color: {c['surface']};
}}
QPushButton:disabled {{
    color: {c['text_disabled']};
    border-color: {c['border']};
    background-color: {c['surface']};
}}
QPushButton:checked {{
    background-color: {c['surface3']};
    border-color: {c['primary']};
    color: {c['text']};
}}

/* ═══════════════════════════════════════════
   PROGRESS BAR
═══════════════════════════════════════════ */
QProgressBar {{
    background-color: {c['surface2']};
    border: none;
    border-radius: 6px;
    min-height: 8px;
    max-height: 8px;
    color: transparent;
    text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {c['primary']}, stop:1 {c['primary_hover']});
    border-radius: 6px;
}}

/* ═══════════════════════════════════════════
   SLIDER
═══════════════════════════════════════════ */
QSlider::groove:horizontal {{
    background: {c['surface2']};
    height: 5px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {c['primary']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {c['surface']};
}}
QSlider::sub-page:horizontal {{
    background: {c['primary']};
    border-radius: 3px;
}}

/* ═══════════════════════════════════════════
   LABEL
═══════════════════════════════════════════ */
QLabel {{
    color: {c['text_sub']};
    background: transparent;
    border: none;
    font-size: 13px;
}}

/* ═══════════════════════════════════════════
   SCROLL AREA
═══════════════════════════════════════════ */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ═══════════════════════════════════════════
   TAB WIDGET (fallback)
═══════════════════════════════════════════ */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    background: {c['surface']};
}}
QTabBar::tab {{
    background: transparent;
    color: {c['text_muted']};
    border: none;
    padding: 8px 16px;
    font-weight: 600;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {c['text']};
    border-bottom: 2px solid {c['primary']};
}}
QTabBar::tab:hover {{ color: {c['text_sub']}; }}

/* ═══════════════════════════════════════════
   MESSAGE BOX
═══════════════════════════════════════════ */
QMessageBox {{
    background-color: {c['surface']};
    color: {c['text']};
}}
QMessageBox QLabel {{ color: {c['text']}; background: transparent; }}
QMessageBox QPushButton {{ min-width: 80px; padding: 6px 18px; }}

/* ═══════════════════════════════════════════
   TOOLTIP
═══════════════════════════════════════════ */
QToolTip {{
    background-color: {c['surface3']};
    color: {c['text']};
    border: 1px solid {c['border_hover']};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
}}

/* ═══════════════════════════════════════════
   CALENDAR
═══════════════════════════════════════════ */
QCalendarWidget {{ background-color: {c['surface']}; color: {c['text']}; }}
QCalendarWidget QAbstractItemView {{
    background: {c['surface']};
    color: {c['text']};
    selection-background-color: {c['primary']};
    selection-color: white;
}}
QCalendarWidget QToolButton {{
    background: transparent;
    color: {c['text']};
    border: none;
    border-radius: 4px;
    padding: 3px 6px;
}}
QCalendarWidget QToolButton:hover {{ background: {c['surface2']}; }}

/* ═══════════════════════════════════════════
   SIDEBAR (always dark)
═══════════════════════════════════════════ */
#Sidebar {{
    background-color: #0A0C12;
    border-right: 1px solid #1E2130;
}}
#Sidebar QLabel {{
    background: transparent;
    border: none;
}}

/* ═══════════════════════════════════════════
   LOG CONTAINER (always dark terminal)
═══════════════════════════════════════════ */
#LogContainer {{
    background-color: #0A0C12;
    border-top: 1px solid #1E2130;
}}
TerminalLog {{
    background-color: #0D1117;
    color: #8B949E;
    border: 1px solid #21262D;
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "JetBrains Mono", "Cascadia Code", "Courier New", monospace;
    font-size: 11px;
    line-height: 1.6;
}}

/* ═══════════════════════════════════════════
   VIDEO ITEM WIDGET (autocut)
═══════════════════════════════════════════ */
VideoItemWidget {{
    background-color: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 8px;
}}
"""


def apply_theme(app, dark: bool = True):
    app.setStyleSheet(get_stylesheet(dark))


_current_dark = False


def is_dark() -> bool:
    return _current_dark


def toggle_theme(app) -> bool:
    global _current_dark
    _current_dark = not _current_dark
    apply_theme(app, _current_dark)
    return _current_dark
