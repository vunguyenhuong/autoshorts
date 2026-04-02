"""
Custom iOS-style toggle switch widget for PyQt6
"""
from PyQt6.QtWidgets import QCheckBox
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 24)  # Smaller size
        self._circle_position = 2
        self.animation = QPropertyAnimation(self, b"circle_position", self)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.setDuration(200)
        
        self.stateChanged.connect(self.start_animation)
    
    @pyqtProperty(float)
    def circle_position(self):
        return self._circle_position
    
    @circle_position.setter
    def circle_position(self, pos):
        self._circle_position = pos
        self.update()
    
    def start_animation(self, state):
        self.animation.stop()
        if state:
            self.animation.setEndValue(self.width() - 22)  # Adjusted for smaller size
        else:
            self.animation.setEndValue(2)
        self.animation.start()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background
        if self.isChecked():
            bg_color = QColor("#4CAF50")  # Green when ON
        else:
            bg_color = QColor("#BDBDBD")  # Gray when OFF
        
        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2)
        
        # Draw circle
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(self._circle_position), 2, 20, 20)  # Smaller circle
        
        painter.end()
    
    def hitButton(self, pos):
        return self.contentsRect().contains(pos)
