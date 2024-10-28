import sys
import threading
from PyQt5 import QtWidgets, QtGui, QtCore
import keyboard  # For global hotkeys

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, image_path, screen_geometry):
        super().__init__(None, QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.image_path = image_path
        self.screen_geometry = screen_geometry
        self.initUI()

    def initUI(self):
        self.setGeometry(self.screen_geometry)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)

        self.label = QtWidgets.QLabel(self)
        pixmap = QtGui.QPixmap(self.image_path)
        scaled_pixmap = pixmap.scaled(self.screen_geometry.width(), self.screen_geometry.height(), QtCore.Qt.KeepAspectRatio)
        self.label.setPixmap(scaled_pixmap)
        self.label.setAlignment(QtCore.Qt.AlignCenter)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

class AnyOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.overlay_window = None
        self.is_overlay_visible = False
        self.global_hotkey = 'ctrl+alt+o'  # Default hotkey
        self.image_path = None
        self.display_index = 0  # Default display index
        self.initUI()
        self.start_hotkey_listener()

    def initUI(self):
        self.setWindowTitle('AnyOverlay')
        self.setFixedSize(300, 200)

        layout = QtWidgets.QVBoxLayout()

        # Import Image Button
        self.image_button = QtWidgets.QPushButton('Import Image')
        self.image_button.clicked.connect(self.on_image_import)
        layout.addWidget(self.image_button)

        # Display Selection ComboBox
        self.display_combo = QtWidgets.QComboBox()
        screens = QtWidgets.QApplication.screens()
        for i, screen in enumerate(screens):
            self.display_combo.addItem(f'Display {i+1}')
        self.display_combo.currentIndexChanged.connect(self.on_display_changed)
        layout.addWidget(self.display_combo)

        # Hotkey Entry
        hotkey_layout = QtWidgets.QHBoxLayout()
        hotkey_label = QtWidgets.QLabel('Global Hotkey:')
        hotkey_layout.addWidget(hotkey_label)
        self.hotkey_entry = QtWidgets.QLineEdit(self.global_hotkey)
        hotkey_layout.addWidget(self.hotkey_entry)
        self.set_hotkey_button = QtWidgets.QPushButton('Set Hotkey')
        self.set_hotkey_button.clicked.connect(self.on_set_hotkey)
        hotkey_layout.addWidget(self.set_hotkey_button)
        layout.addLayout(hotkey_layout)

        # Toggle Overlay Button
        self.toggle_button = QtWidgets.QPushButton('Toggle Overlay')
        self.toggle_button.clicked.connect(self.toggle_overlay)
        layout.addWidget(self.toggle_button)

        self.setLayout(layout)
        self.show()

    def on_image_import(self):
        options = QtWidgets.QFileDialog.Options()
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)", options=options)
        if file_name:
            self.image_path = file_name

    def on_display_changed(self, index):
        self.display_index = index

    def on_set_hotkey(self):
        self.global_hotkey = self.hotkey_entry.text()
        keyboard.unhook_all_hotkeys()
        keyboard.add_hotkey(self.global_hotkey, self.toggle_overlay)

    def toggle_overlay(self):
        if self.is_overlay_visible:
            self.destroy_overlay()
        else:
            self.create_overlay()

    def create_overlay(self):
        if not self.image_path:
            QtWidgets.QMessageBox.warning(self, "Warning", "No image selected.")
            return

        screens = QtWidgets.QApplication.screens()
        if self.display_index >= len(screens):
            QtWidgets.QMessageBox.warning(self, "Warning", "Invalid display selected.")
            return

        screen = screens[self.display_index]
        geometry = screen.geometry()

        self.overlay_window = OverlayWindow(self.image_path, geometry)
        self.overlay_window.showFullScreen()
        self.is_overlay_visible = True

    def destroy_overlay(self):
        if self.overlay_window:
            self.overlay_window.close()
            self.overlay_window = None
            self.is_overlay_visible = False

    def start_hotkey_listener(self):
        keyboard.add_hotkey(self.global_hotkey, self.toggle_overlay)

    def closeEvent(self, event):
        keyboard.unhook_all_hotkeys()
        event.accept()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ex = AnyOverlay()
    sys.exit(app.exec_())
