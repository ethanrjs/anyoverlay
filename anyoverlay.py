import sys
import json
import os
import ctypes
from PyQt5 import QtWidgets, QtGui, QtCore

import keyboard  

if sys.platform == "win32":
    from ctypes.wintypes import HWND, LONG, DWORD, BOOL

    user32 = ctypes.WinDLL('user32', use_last_error=True)

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080

    SetWindowLong = user32.SetWindowLongW
    SetWindowLong.restype = LONG
    SetWindowLong.argtypes = [HWND, ctypes.c_int, LONG]

    GetWindowLong = user32.GetWindowLongW
    GetWindowLong.restype = LONG
    GetWindowLong.argtypes = [HWND, ctypes.c_int]

    SetLayeredWindowAttributes = user32.SetLayeredWindowAttributes
    SetLayeredWindowAttributes.restype = BOOL
    SetLayeredWindowAttributes.argtypes = [HWND, DWORD, ctypes.c_byte, DWORD]

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, image_path, screen_geometry, opacity=1.0, gif_speed=100, scaling_mode='fit'):
        super().__init__(None, QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.image_path = image_path
        self.screen_geometry = screen_geometry
        self.opacity = opacity
        self.gif_speed = gif_speed
        self.scaling_mode = scaling_mode
        self.initUI()

    def initUI(self):
        self.setGeometry(self.screen_geometry)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)

        
        if sys.platform == "win32":
            hwnd = self.winId().__int__()
            exStyle = GetWindowLong(hwnd, GWL_EXSTYLE)
            exStyle |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            SetWindowLong(hwnd, GWL_EXSTYLE, exStyle)
        else:
            self.setWindowFlag(QtCore.Qt.WindowTransparentForInput, True)

        self.setWindowOpacity(self.opacity)

        
        self.initImage()

        
        if not self.layout():
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)
        else:
            
            while self.layout().count():
                child = self.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        self.layout().addWidget(self.label)
    
    def resource_path(self, relative_path):
        try:
            
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")

        return os.path.join(base_path, relative_path)

    def initImage(self):
        if hasattr(self, 'label'):
            self.label.setParent(None)
            del self.label
        if hasattr(self, 'movie'):
            self.movie.stop()
            del self.movie

        if self.image_path.lower().endswith('.gif'):
            
            self.movie = QtGui.QMovie(self.image_path)
            self.movie.setSpeed(self.gif_speed)
            self.movie.setCacheMode(QtGui.QMovie.CacheAll)

            if self.scaling_mode in ['fit', 'stretch']:
                aspect_mode = QtCore.Qt.KeepAspectRatio if self.scaling_mode == 'fit' else QtCore.Qt.IgnoreAspectRatio
                self.movie.setScaledSize(self.size())
            elif self.scaling_mode == 'center':
                
                self.movie.setScaledSize(QtCore.QSize())
            elif self.scaling_mode == 'tile':
                
                QtWidgets.QMessageBox.warning(self, "Warning", "Tile mode is not supported for GIFs.")
                self.scaling_mode = 'fit'
                self.movie.setScaledSize(self.size())

            self.label = QtWidgets.QLabel(self)
            self.label.setAlignment(QtCore.Qt.AlignCenter)
            self.label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
            self.label.setMovie(self.movie)
            self.movie.start()
        else:
            
            pixmap = QtGui.QPixmap(self.image_path)
            if pixmap.isNull():
                QtWidgets.QMessageBox.warning(self, "Error", "Failed to load image.")
                return

            if self.scaling_mode == 'fit':
                scaled_pixmap = pixmap.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            elif self.scaling_mode == 'stretch':
                scaled_pixmap = pixmap.scaled(self.size(), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
            elif self.scaling_mode == 'center':
                scaled_pixmap = pixmap  
            elif self.scaling_mode == 'tile':
                
                tile_size = pixmap.size()
                window_size = self.size()
                tiled_pixmap = QtGui.QPixmap(window_size)
                painter = QtGui.QPainter(tiled_pixmap)
                for x in range(0, window_size.width(), tile_size.width()):
                    for y in range(0, window_size.height(), tile_size.height()):
                        painter.drawPixmap(x, y, pixmap)
                painter.end()
                scaled_pixmap = tiled_pixmap

            self.label = QtWidgets.QLabel(self)
            self.label.setPixmap(scaled_pixmap)
            self.label.setAlignment(QtCore.Qt.AlignCenter)
            self.label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")

        
        self.label.setScaledContents(False)
        self.label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def setImage(self, image_path):
        if self.image_path == image_path:
            return  
        self.image_path = image_path
        self.initImage()

    def setOpacity(self, opacity):
        self.opacity = opacity
        self.setWindowOpacity(self.opacity)

    def setGifSpeed(self, speed):
        self.gif_speed = speed
        if hasattr(self, 'movie'):
            self.movie.setSpeed(self.gif_speed)

    def setScalingMode(self, mode):
        if self.scaling_mode == mode:
            return
        self.scaling_mode = mode
        self.initImage()

class MediaGallery(QtWidgets.QDialog):
    def __init__(self, overlays_dir, parent=None):
        super().__init__(parent)
        self.overlays_dir = overlays_dir
        self.selected_image_path = None
        self.selected_button = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Choose Overlay")
        self.setMinimumSize(600, 400)
        self.resize(600, 400)
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout()

        
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)

        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout()
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)  
        self.grid_widget.setLayout(self.grid_layout)

        scroll_area.setWidget(self.grid_widget)
        layout.addWidget(scroll_area)

        
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        ok_button = QtWidgets.QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.load_images()

    def load_images(self):
        
        if not os.path.exists(self.overlays_dir):
            os.makedirs(self.overlays_dir)

        self.image_buttons = []
        row = 0
        col = 0
        max_cols = 3  

        
        image_files = [f for f in os.listdir(self.overlays_dir)
                       if os.path.isfile(os.path.join(self.overlays_dir, f)) and
                       f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'))]  

        
        add_widget = QtWidgets.QWidget()
        add_layout = QtWidgets.QVBoxLayout()
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(0)
        add_widget.setLayout(add_layout)

        add_button = QtWidgets.QPushButton()
        add_button.setFixedSize(150, 150)
        add_button.clicked.connect(self.add_new_image)
        add_button.setStyleSheet("border: 1px dashed #ffffff;")

        
        plus_icon = QtGui.QIcon.fromTheme("list-add") or QtGui.QIcon("add_icon.png")
        if plus_icon.isNull():
            
            pixmap = QtGui.QPixmap(50, 50)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setPen(QtGui.QPen(QtCore.Qt.white, 5))
            painter.drawLine(25, 5, 25, 45)
            painter.drawLine(5, 25, 45, 25)
            painter.end()
            plus_icon = QtGui.QIcon(pixmap)

        add_button.setIcon(plus_icon)
        add_button.setIconSize(QtCore.QSize(50, 50))
        add_button.setToolTip("Import Image...")
        add_layout.addWidget(add_button, alignment=QtCore.Qt.AlignCenter)

        add_label = QtWidgets.QLabel("Import Image...")
        add_label.setAlignment(QtCore.Qt.AlignCenter)
        add_layout.addWidget(add_label)

        self.grid_layout.addWidget(add_widget, row, col)
        col += 1
        if col >= max_cols:
            col = 0
            row += 1

        
        for image_file in image_files:
            image_path = os.path.join(self.overlays_dir, image_file)
            
            tile_widget = QtWidgets.QWidget()
            tile_layout = QtWidgets.QVBoxLayout()
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(0)
            tile_widget.setLayout(tile_layout)

            button = QtWidgets.QPushButton()
            button.setFixedSize(150, 150)
            
            reader = QtGui.QImageReader(image_path)
            reader.setScaledSize(QtCore.QSize(140, 140))
            image = reader.read()
            if image.isNull():
                continue  
            pixmap = QtGui.QPixmap.fromImage(image)
            icon = QtGui.QIcon(pixmap)
            button.setIcon(icon)
            button.setIconSize(QtCore.QSize(140, 140))
            button.setToolTip(image_file)
            button.clicked.connect(lambda checked, path=image_path, btn=button: self.select_image(path, btn))
            tile_layout.addWidget(button, alignment=QtCore.Qt.AlignCenter)
            self.image_buttons.append(button)

            label = QtWidgets.QLabel(image_file)
            label.setAlignment(QtCore.Qt.AlignCenter)
            tile_layout.addWidget(label)

            
            button.tile_widget = tile_widget

            self.grid_layout.addWidget(tile_widget, row, col)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def add_new_image(self):
        options = QtWidgets.QFileDialog.Options()
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Add Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)", options=options)  
        if file_name:
            
            name, ok = QtWidgets.QInputDialog.getText(self, "Image Name", "Enter a name for the overlay:")
            if not ok or not name.strip():
                QtWidgets.QMessageBox.warning(self, "Warning", "You must enter a name for the overlay.")
                return
            name = name.strip()

            
            base_name = name + os.path.splitext(file_name)[1]
            dest_path = os.path.join(self.overlays_dir, base_name)
            if not os.path.exists(dest_path):
                import shutil
                shutil.copy(file_name, dest_path)
            else:
                
                base, ext = os.path.splitext(base_name)
                i = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(self.overlays_dir, f"{base}_{i}{ext}")
                    i += 1
                shutil.copy(file_name, dest_path)
            
            for i in reversed(range(self.grid_layout.count())):
                widget_to_remove = self.grid_layout.itemAt(i).widget()
                self.grid_layout.removeWidget(widget_to_remove)
                widget_to_remove.setParent(None)
            self.load_images()

    def select_image(self, image_path, button):
        self.selected_image_path = image_path
        self.selected_button = button
        
        for btn in self.image_buttons:
            btn.setStyleSheet("")
        
        sender = self.sender()
        sender.setStyleSheet("border: 2px solid #00aaff;")

    def accept(self):
        if self.selected_image_path:
            super().accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Warning", "Please select an overlay or cancel.")

    def keyPressEvent(self, event):
        if self.selected_image_path and event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            
            reply = QtWidgets.QMessageBox.question(
                self, 'Confirm Deletion',
                'Are you sure you want to delete this image from your gallery?',
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                
                try:
                    os.remove(self.selected_image_path)
                except Exception as e:
                    QtWidgets.QMessageBox.warning(self, "Error", f"Failed to delete image: {e}")
                    return
                
                self.selected_image_path = None
                self.selected_button = None
                
                for i in reversed(range(self.grid_layout.count())):
                    widget_to_remove = self.grid_layout.itemAt(i).widget()
                    self.grid_layout.removeWidget(widget_to_remove)
                    widget_to_remove.setParent(None)
                self.load_images()
            event.accept()
        else:
            super().keyPressEvent(event)

class AnyOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.overlay_window = None
        self.is_overlay_visible = False
        self.global_hotkey = 'ctrl+alt+o'  
        self.image_path = None
        self.display_index = 0  
        self.opacity = 1.0  
        self.overlays_dir = os.path.join(os.path.expanduser("~"), ".anyoverlay_overlays")
        self.settings_file = 'anyoverlay_settings.json'
        self.gif_speed = 100  
        self.is_gif = False  
        self.scaling_mode = 'fit'  
        self.initUI()
        self.load_settings()
        self.start_hotkey_listener()

    def initUI(self):
        self.setWindowTitle('AnyOverlay')
        self.setFixedSize(400, 350)  

        
        self.apply_dark_theme()

        layout = QtWidgets.QVBoxLayout()

        
        self.choose_overlay_button = QtWidgets.QPushButton('Choose Overlay')
        self.choose_overlay_button.clicked.connect(self.open_media_gallery)
        layout.addWidget(self.choose_overlay_button)

        
        display_layout = QtWidgets.QHBoxLayout()
        display_label = QtWidgets.QLabel('Display:')
        display_layout.addWidget(display_label)
        self.display_combo = QtWidgets.QComboBox()
        screens = QtWidgets.QApplication.screens()
        for i, screen in enumerate(screens):
            self.display_combo.addItem(f'Display {i+1}')
        self.display_combo.setCurrentIndex(self.display_index)
        self.display_combo.currentIndexChanged.connect(self.on_display_changed)
        display_layout.addWidget(self.display_combo)
        layout.addLayout(display_layout)

        
        opacity_layout = QtWidgets.QHBoxLayout()
        opacity_label = QtWidgets.QLabel('Opacity:')
        opacity_layout.addWidget(opacity_label)
        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setMinimum(1)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(int(self.opacity * 100))
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        layout.addLayout(opacity_layout)

        
        self.gif_options_layout = QtWidgets.QVBoxLayout()
        self.gif_options_label = QtWidgets.QLabel('GIF Options:')
        self.gif_options_layout.addWidget(self.gif_options_label)

        
        gif_speed_layout = QtWidgets.QHBoxLayout()
        self.gif_speed_label = QtWidgets.QLabel('Playback Speed:')
        gif_speed_layout.addWidget(self.gif_speed_label)
        self.gif_speed_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gif_speed_slider.setMinimum(10)   
        self.gif_speed_slider.setMaximum(200)  
        self.gif_speed_slider.setValue(self.gif_speed)
        self.gif_speed_slider.setTickInterval(10)
        self.gif_speed_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.gif_speed_slider.valueChanged.connect(self.on_gif_speed_changed)
        gif_speed_layout.addWidget(self.gif_speed_slider)
        self.gif_options_layout.addLayout(gif_speed_layout)

        
        self.gif_options_label.hide()
        self.gif_speed_slider.hide()
        self.gif_speed_label.hide()

        layout.addLayout(self.gif_options_layout)

        
        self.rendering_options_button = QtWidgets.QPushButton('Show Rendering Options')
        self.rendering_options_button.setCheckable(True)
        self.rendering_options_button.clicked.connect(self.toggle_rendering_options)
        layout.addWidget(self.rendering_options_button)

        
        self.rendering_options_frame = QtWidgets.QFrame()
        self.rendering_options_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.rendering_options_frame.setVisible(False)  

        rendering_layout = QtWidgets.QVBoxLayout()

        
        scaling_mode_layout = QtWidgets.QHBoxLayout()
        scaling_mode_label = QtWidgets.QLabel('Scaling Mode:')
        scaling_mode_layout.addWidget(scaling_mode_label)
        self.scaling_mode_combo = QtWidgets.QComboBox()
        self.scaling_mode_combo.addItems(['Fit to Screen', 'Stretch to Fill', 'Center', 'Tile'])
        self.scaling_mode_combo.currentIndexChanged.connect(self.on_scaling_mode_changed)
        scaling_mode_layout.addWidget(self.scaling_mode_combo)
        rendering_layout.addLayout(scaling_mode_layout)

        self.rendering_options_frame.setLayout(rendering_layout)
        layout.addWidget(self.rendering_options_frame)

        
        hotkey_layout = QtWidgets.QHBoxLayout()
        hotkey_label = QtWidgets.QLabel('Global Hotkey:')
        hotkey_layout.addWidget(hotkey_label)
        self.hotkey_entry = QtWidgets.QLineEdit(self.global_hotkey)
        hotkey_layout.addWidget(self.hotkey_entry)
        self.set_hotkey_button = QtWidgets.QPushButton('Set Hotkey')
        self.set_hotkey_button.clicked.connect(self.on_set_hotkey)
        hotkey_layout.addWidget(self.set_hotkey_button)
        layout.addLayout(hotkey_layout)

        
        self.toggle_button = QtWidgets.QPushButton('Toggle Overlay')
        self.toggle_button.clicked.connect(self.toggle_overlay)
        layout.addWidget(self.toggle_button)

        self.setLayout(layout)
        self.show()

    def apply_dark_theme(self):
        dark_stylesheet = """
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            font-family: Arial;
            font-size: 10pt;
        }
        QPushButton {
            background-color: #3c3f41;
            color: #ffffff;
            border: none;
            padding: 5px;
        }
        QPushButton:hover {
            background-color: #4b4b4b;
        }
        QLineEdit, QComboBox {
            background-color: #3c3f41;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 2px;
        }
        QLabel {
            color: #ffffff;
        }
        QSlider::groove:horizontal {
            border: 1px solid #3A3939;
            height: 8px;
            background: #201F1F;
            margin: 0px;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #3c3f41;
            border: 1px solid #3A3939;
            width: 14px;
            height: 14px;
            margin: -3px 0;
            border-radius: 7px;
        }
        """
        self.setStyleSheet(dark_stylesheet)

    def open_media_gallery(self):
        gallery = MediaGallery(self.overlays_dir, self)
        if gallery.exec_() == QtWidgets.QDialog.Accepted:
            self.image_path = gallery.selected_image_path
            self.is_gif = self.image_path.lower().endswith('.gif')
            self.update_gif_options_visibility()
            self.save_settings()
            if self.is_overlay_visible:
                self.destroy_overlay()
                self.create_overlay()

    def update_gif_options_visibility(self):
        if self.is_gif:
            self.gif_options_label.show()
            self.gif_speed_slider.show()
            self.gif_speed_label.show()
        else:
            self.gif_options_label.hide()
            self.gif_speed_slider.hide()
            self.gif_speed_label.hide()

    def toggle_rendering_options(self):
        if self.rendering_options_frame.isVisible():
            self.rendering_options_frame.setVisible(False)
            self.rendering_options_button.setText('Show Rendering Options')
        else:
            self.rendering_options_frame.setVisible(True)
            self.rendering_options_button.setText('Hide Rendering Options')

    def on_scaling_mode_changed(self, index):
        scaling_modes = ['fit', 'stretch', 'center', 'tile']
        self.scaling_mode = scaling_modes[index]
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.setScalingMode(self.scaling_mode)

    def on_display_changed(self, index):
        self.display_index = index
        self.save_settings()
        if self.is_overlay_visible:
            if self.overlay_window:
                
                geometry = self.get_screen_geometry()
                self.overlay_window.setGeometry(geometry)
                self.overlay_window.update()

    def on_opacity_changed(self, value):
        self.opacity = value / 100.0
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.setOpacity(self.opacity)

    def on_gif_speed_changed(self, value):
        self.gif_speed = value
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.setGifSpeed(self.gif_speed)

    def on_set_hotkey(self):
        self.global_hotkey = self.hotkey_entry.text()
        keyboard.unhook_all_hotkeys()
        keyboard.add_hotkey(self.global_hotkey, self.toggle_overlay)
        self.save_settings()

    def toggle_overlay(self):
        if self.is_overlay_visible:
            self.destroy_overlay()
        else:
            self.create_overlay()

    def create_overlay(self):
        if not self.image_path or not os.path.exists(self.image_path):
            QtWidgets.QMessageBox.warning(self, "Warning", "No image selected.")
            return

        screens = QtWidgets.QApplication.screens()
        if self.display_index >= len(screens):
            QtWidgets.QMessageBox.warning(self, "Warning", "Invalid display selected.")
            return

        geometry = self.get_screen_geometry()

        if not self.overlay_window:
            self.overlay_window = OverlayWindow(self.image_path, geometry, self.opacity, self.gif_speed, self.scaling_mode)
        else:
            
            self.overlay_window.setGeometry(geometry)
            self.overlay_window.setOpacity(self.opacity)
            self.overlay_window.setGifSpeed(self.gif_speed)
            self.overlay_window.setScalingMode(self.scaling_mode)
            self.overlay_window.setImage(self.image_path)

        self.overlay_window.showFullScreen()
        self.is_overlay_visible = True

    def destroy_overlay(self):
        if self.overlay_window:
            self.overlay_window.hide()
            self.overlay_window.deleteLater()
            self.overlay_window = None
        self.is_overlay_visible = False

    def start_hotkey_listener(self):
        keyboard.add_hotkey(self.global_hotkey, self.toggle_overlay)

    def get_screen_geometry(self):
        screens = QtWidgets.QApplication.screens()
        if self.display_index >= len(screens):
            return QtWidgets.QApplication.primaryScreen().geometry()
        return screens[self.display_index].geometry()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.image_path = settings.get('image_path', None)
                    self.display_index = settings.get('display_index', 0)
                    self.global_hotkey = settings.get('global_hotkey', 'ctrl+alt+o')
                    self.opacity = settings.get('opacity', 1.0)
                    self.gif_speed = settings.get('gif_speed', 100)
                    self.scaling_mode = settings.get('scaling_mode', 'fit')
                    self.is_gif = self.image_path.lower().endswith('.gif') if self.image_path else False
                    self.update_gif_options_visibility()
                    
                    self.hotkey_entry.setText(self.global_hotkey)
                    self.opacity_slider.setValue(int(self.opacity * 100))
                    self.display_combo.setCurrentIndex(self.display_index)
                    scaling_modes = ['fit', 'stretch', 'center', 'tile']
                    index = scaling_modes.index(self.scaling_mode) if self.scaling_mode in scaling_modes else 0
                    self.scaling_mode_combo.setCurrentIndex(index)
            except Exception as e:
                print(f"Error loading settings: {e}")

    def save_settings(self):
        settings = {
            'image_path': self.image_path,
            'display_index': self.display_index,
            'global_hotkey': self.global_hotkey,
            'opacity': self.opacity,
            'gif_speed': self.gif_speed,
            'scaling_mode': self.scaling_mode
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def closeEvent(self, event):
        keyboard.unhook_all_hotkeys()
        self.save_settings()
        event.accept()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    ex = AnyOverlay()
    sys.exit(app.exec_())
