import sys
import os
import qdarktheme
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow

def main():
    # enable high dpi scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    
    # Set App User Model ID for Windows taskbar icon
    try:
        from ctypes import windll
        myappid = 'huongvn.shortsmashpro.autoshorts.1.0'
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except:
        pass
    
    # Set application icon (for taskbar)
    icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Apply Light Theme as default
    qdarktheme.setup_theme("light")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    from PyQt6.QtCore import Qt # Import here to avoid ModuleNotFoundError if imported at top level before main logic
    main()
