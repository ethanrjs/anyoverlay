import sys
import json
import os
import ctypes
import random
import copy
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import QUrl
try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
except Exception:
    QMediaPlayer = None  # type: ignore
    QMediaContent = None  # type: ignore
    QVideoWidget = None  # type: ignore

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

class CachedImageRenderer:
    """Handles efficient image loading, caching and scaling"""
    def __init__(self, advanced_settings=None):
        self.advanced_settings = advanced_settings or {}
        self.cache = {}
        self.cache_order = []
        self.max_cache_entries = self.advanced_settings.get('renderer_cache_entries', 48)
        
    def clear_cache(self):
        """Clear the image cache"""
        self.cache.clear()
        self.cache_order.clear()

    def load_image(self, image_path, target_size=None, scaling_mode='fit', scale_factor=1.0):
        """Load and scale image efficiently"""
        cache_key = (image_path, target_size, scaling_mode, scale_factor)
        
        
        if cache_key in self.cache:
            self.cache_order.remove(cache_key)
            self.cache_order.append(cache_key)
            return self.cache[cache_key]
            
        
        image_reader = QtGui.QImageReader(image_path)
        
        
        if self.advanced_settings.get('enable_hardware_acceleration', True):
            image_reader.setAutoTransform(True)
            
        image = image_reader.read()
        if image.isNull():
            return None
            
        
        if target_size:
            scaled_width = max(1, int(target_size.width() * scale_factor))
            scaled_height = max(1, int(target_size.height() * scale_factor))
            if scaling_mode == 'fit':
                image = image.scaled(
                    scaled_width,
                    scaled_height,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation if self.advanced_settings.get('enable_antialiasing', True)
                    else QtCore.Qt.FastTransformation
                )
            elif scaling_mode == 'stretch':
                image = image.scaled(
                    scaled_width,
                    scaled_height,
                    QtCore.Qt.IgnoreAspectRatio,
                    QtCore.Qt.SmoothTransformation if self.advanced_settings.get('enable_antialiasing', True)
                    else QtCore.Qt.FastTransformation
                )
            # 'center' mode keeps original size
            
        pixmap = QtGui.QPixmap.fromImage(image)
        
        
        if len(self.cache) >= self.max_cache_entries:
            oldest_key = self.cache_order.pop(0)
            del self.cache[oldest_key]
            
        
        self.cache[cache_key] = pixmap
        self.cache_order.append(cache_key)
        
        return pixmap
    
class GPUImageWidget(QtWidgets.QOpenGLWidget):
    def __init__(self, image_path=None, movie=None, scaling_mode='fit', scale_factor=1.0, advanced_settings=None, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.movie = movie
        self.scaling_mode = scaling_mode
        self.scale_factor = scale_factor
        self.advanced_settings = advanced_settings or {}
        self._pixmap = None
        if self.image_path and not self.movie:
            pm = QtGui.QPixmap(self.image_path)
            if not pm.isNull():
                self._pixmap = pm
        if self.movie:
            try:
                self.movie.frameChanged.connect(self.update)
            except Exception:
                pass

    def initializeGL(self):
        pass

    def paintGL(self):
        painter = QtGui.QPainter(self)
        if self.advanced_settings.get('enable_antialiasing', True):
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        pixmap = self._current_pixmap()
        if pixmap is None or pixmap.isNull():
            painter.end()
            return

        target_rect = self._compute_target_rect(pixmap.size(), self.size())
        painter.drawPixmap(target_rect, pixmap)
        painter.end()

    def _current_pixmap(self):
        if self.movie:
            pm = self.movie.currentPixmap()
            return pm if not pm.isNull() else None
        return self._pixmap

    def _compute_target_rect(self, content_size, widget_size):
        if self.scaling_mode == 'stretch':
            return QtCore.QRect(0, 0, widget_size.width(), widget_size.height())
        elif self.scaling_mode == 'center':
            w, h = content_size.width(), content_size.height()
            x = (widget_size.width() - w) // 2
            y = (widget_size.height() - h) // 2
            return QtCore.QRect(x, y, w, h)
        # fit (keep aspect)
        cw, ch = content_size.width(), content_size.height()
        ww, wh = widget_size.width(), widget_size.height()
        if cw == 0 or ch == 0 or ww == 0 or wh == 0:
            return QtCore.QRect(0, 0, ww, wh)
        scale = min(ww / cw, wh / ch)
        tw, th = int(cw * scale), int(ch * scale)
        x = (ww - tw) // 2
        y = (wh - th) // 2
        return QtCore.QRect(x, y, tw, th)

class TiledImageWidget(QtWidgets.QWidget):
    """Efficient widget for displaying tiled images"""
    def __init__(self, image_path, parent=None, advanced_settings=None):
        super().__init__(parent)
        self.image_path = image_path
        self.advanced_settings = advanced_settings or {}
        self.renderer = CachedImageRenderer(advanced_settings)
        
        
        self.tile_cache = {}
        self.tile_positions = []
        self.last_size = None
        self.last_tile_size = None
        
        
        self.setAttribute(QtCore.Qt.WA_PaintOnScreen, False)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
        
        
        self.background_buffer = None
        self.buffer_size = None
        
    def calculate_tile_positions(self, tile_size):
        """Pre-calculate tile positions"""
        if (self.size() == self.last_size and 
            tile_size == self.last_tile_size):
            return
            
        self.tile_positions.clear()
        for x in range(0, self.width(), tile_size.width()):
            for y in range(0, self.height(), tile_size.height()):
                self.tile_positions.append(QtCore.QPoint(x, y))
                
        self.last_size = self.size()
        self.last_tile_size = tile_size
        
    def update_background_buffer(self, base_pixmap):
        """Update the background buffer for faster rendering"""
        current_size = self.size()
        if (self.background_buffer is None or 
            self.buffer_size != current_size):
            self.background_buffer = QtGui.QPixmap(current_size)
            self.buffer_size = current_size
            
        self.background_buffer.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(self.background_buffer)
        
        if self.advanced_settings.get('enable_hardware_acceleration', True):
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            
        for pos in self.tile_positions:
            painter.drawPixmap(pos, base_pixmap)
            
        painter.end()
        
    def paintEvent(self, event):
        tile_scale = max(0.01, self.advanced_settings.get('tile_scale', 1.0))
        base_size = QtCore.QSize(
            int(self.width() * tile_scale),
            int(self.height() * tile_scale)
        )

        base_pixmap = self.renderer.load_image(
            self.image_path,
            base_size,
            'fit',
            tile_scale
        )

        if base_pixmap is None:
            return

        # Only recalc and rebuild buffer when size or tile changes
        recalc_needed = (
            self.background_buffer is None or
            self.buffer_size != self.size() or
            self.last_tile_size != base_pixmap.size()
        )

        if recalc_needed:
            self.calculate_tile_positions(base_pixmap.size())
            self.update_background_buffer(base_pixmap)

        painter = QtGui.QPainter(self)
        painter.drawPixmap(0, 0, self.background_buffer)
        painter.end()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        self.background_buffer = None
        self.buffer_size = None
        # Ensure GIF/movie resizes reflect current mode
        try:
            if hasattr(self, 'movie') and self.movie is not None:
                if self.scaling_mode in ['fit', 'stretch']:
                    if self.scaling_mode == 'fit':
                        frame_size = self.movie.frameRect().size()
                        target = self._compute_fit_size(frame_size, self.size(), self.scale_factor)
                    else:
                        target = self.size()
                    self.movie.setScaledSize(target)
        except Exception:
            pass


class TiledGIFWidget(QtWidgets.QWidget):
    def __init__(self, movie, parent=None, advanced_settings=None):
        super().__init__(parent)
        self.movie = movie
        self.advanced_settings = advanced_settings or {}
        
        
        self.max_cache_entries = self.advanced_settings.get('renderer_cache_entries', 48)
        self.scaled_frame_cache = {}
        self.frame_cache_order = []
        
        
        self.tile_positions = []
        self.last_size = None
        self.last_frame_size = None
        
        
        self.setAttribute(QtCore.Qt.WA_PaintOnScreen, False)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
        
        # FPS limiting state must be defined before connecting to avoid race
        self._last_frame_ms = 0
        # Prefer movie-driven updates; throttle via on_frame_changed
        self.movie.frameChanged.connect(self.on_frame_changed)
        
        
        self.background_buffer = None
        
        
        self.movie.setCacheMode(QtGui.QMovie.CacheAll)
        self.movie.start()

        # Start with counter initialized
    def on_frame_changed(self, _frame_index):
        # Throttle updates to animation_fps
        fps = max(1, int(self.advanced_settings.get('animation_fps', 30)))
        interval_ms = int(1000 / fps)
        now = QtCore.QDateTime.currentMSecsSinceEpoch()
        if now - self._last_frame_ms >= interval_ms:
            self._last_frame_ms = now
            self.update()

    def update_frame(self):
        # Fallback not used with frameChanged connection
        self.update()

    def calculate_tile_positions(self, frame_size):
        """Pre-calculate tile positions for current widget size"""
        if (self.size() == self.last_size and 
            frame_size == self.last_frame_size):
            return
            
        self.tile_positions.clear()
        for x in range(0, self.width(), frame_size.width()):
            for y in range(0, self.height(), frame_size.height()):
                self.tile_positions.append(QtCore.QPoint(x, y))
                
        self.last_size = self.size()
        self.last_frame_size = frame_size

    def get_scaled_frame(self, frame, frame_number, tile_scale):
        """Get scaled frame from cache or create new one"""
        cache_key = (frame_number, tile_scale)
        
        
        if cache_key in self.scaled_frame_cache:
            
            self.frame_cache_order.remove(cache_key)
            self.frame_cache_order.append(cache_key)
            return self.scaled_frame_cache[cache_key]
            
        
        scaled_frame = frame.scaled(
            max(1, int(frame.width() * tile_scale)),
            max(1, int(frame.height() * tile_scale)),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation if self.advanced_settings.get('enable_antialiasing', True)
            else QtCore.Qt.FastTransformation
        )
        
        
        if len(self.scaled_frame_cache) >= self.max_cache_entries:
            oldest_key = self.frame_cache_order.pop(0)
            del self.scaled_frame_cache[oldest_key]
            
        
        self.scaled_frame_cache[cache_key] = scaled_frame
        self.frame_cache_order.append(cache_key)
        
        return scaled_frame

    def paintEvent(self, event):
        current_frame = self.movie.currentPixmap()
        if current_frame.isNull():
            return
            
        painter = QtGui.QPainter(self)
        
        
        if self.advanced_settings.get('enable_hardware_acceleration', True):
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            
        
        tile_scale = max(0.01, self.advanced_settings.get('tile_scale', 1.0))
        scaled_frame = self.get_scaled_frame(
            current_frame,
            self.movie.currentFrameNumber(),
            tile_scale
        )
        
        
        self.calculate_tile_positions(scaled_frame.size())
        
        
        for pos in self.tile_positions:
            painter.drawPixmap(pos, scaled_frame)
            
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)

    def __del__(self):
        if hasattr(self, 'movie'):
            self.movie.stop()
            del self.movie
        self.scaled_frame_cache.clear()
        self.frame_cache_order.clear()

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, image_path, screen_geometry, opacity=1.0, gif_speed=100, scaling_mode='fit', advanced_settings=None):
        super().__init__(None, QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.image_path = image_path
        self.screen_geometry = screen_geometry
        self.opacity = opacity
        self.gif_speed = gif_speed
        self.scaling_mode = scaling_mode
        self.advanced_settings = advanced_settings or {}
        self.edit_mode = False
        self.dragging = False
        self.resizing = False
        self.last_mouse_pos = None
        self.scale_factor = self.advanced_settings.get('scale_factor', 1.0)  
        # Coalesce expensive image rebuilds during resize
        self.resize_coalesce_timer = QtCore.QTimer(self)
        self.resize_coalesce_timer.setSingleShot(True)
        self.resize_coalesce_timer.setInterval(75)
        self.resize_coalesce_timer.timeout.connect(self.initImage)

        # DVD bounce state
        self.movement_mode = self.advanced_settings.get('movement_mode', 'static')  # static|dvd
        self.dvd_speed = float(self.advanced_settings.get('dvd_speed', 200.0))  # pixels/sec
        self._dvd_timer = QtCore.QTimer(self)
        self._dvd_timer.timeout.connect(self._advance_dvd)
        self._dvd_velocity = QtCore.QPointF(0.0, 0.0)
        self._dvd_pos = None
        self.initUI()

    def initUI(self):
        self.setGeometry(self.screen_geometry)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setMouseTracking(True)

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
        if self.movement_mode == 'dvd':
            self._detach_from_layout()
            self._position_content_initial()
        else:
            self.layout().addWidget(self.label)

        bg_color = self.advanced_settings.get('background_color', '#000000')
        transparency = int(self.advanced_settings.get('transparency', 0))
        if transparency > 0:
            color = QtGui.QColor(bg_color)
            color.setAlpha(transparency)
            palette = self.palette()
            palette.setColor(QtGui.QPalette.Window, color)
            self.setPalette(palette)
            self.setAutoFillBackground(True)
        else:
            self.setAutoFillBackground(False)

        update_interval = self.advanced_settings.get('update_interval', 0)
        if update_interval > 0:
            self.update_timer = QtCore.QTimer(self)
            self.update_timer.timeout.connect(self.update)
            self.update_timer.start(update_interval)

        self._setup_movement()

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
        if hasattr(self, 'video_player'):
            try:
                self.video_player.stop()
            except Exception:
                pass
            del self.video_player
        if hasattr(self, 'video_widget'):
            self.video_widget.setParent(None)
            del self.video_widget

        pixmap_cache_mb = self.advanced_settings.get('pixmap_cache_mb', self.advanced_settings.get('cache_size', 64))
        try:
            QtGui.QPixmapCache.setCacheLimit(int(pixmap_cache_mb) * 1024)
        except Exception:
            QtGui.QPixmapCache.setCacheLimit(64 * 1024)

        lower = self.image_path.lower()
        if lower.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')) and QMediaPlayer is not None:
            # Video path
            self.video_player = QMediaPlayer(None)
            # Use QVideoWidget (leverages system pipeline); GPU toggle not used here due to layered window constraints
            self.video_widget = QVideoWidget(self)
            self.video_player.setVideoOutput(self.video_widget)
            self.video_player.setMedia(QMediaContent(QUrl.fromLocalFile(self.image_path)))
            self.video_player.setMuted(True)
            self.video_player.setLoops(-1) if hasattr(self.video_player, 'setLoops') else None
            self.label = self.video_widget
            self.video_player.play()
        elif lower.endswith('.gif'):
            self.movie = QtGui.QMovie(self.image_path)
            self.movie.setSpeed(self.gif_speed)
            # Cache mode: configurable for memory vs CPU trade-off
            if self.advanced_settings.get('gif_cache_all', False):
                self.movie.setCacheMode(QtGui.QMovie.CacheAll)
            else:
                self.movie.setCacheMode(QtGui.QMovie.CacheNone)

            # GPU path for GIFs is disabled on translucent layered windows; use QLabel/Tiled widget
            if self.scaling_mode in ['fit', 'stretch']:
                    frame_size = self.movie.frameRect().size()
                    win_size = self.size()
                    if self.scaling_mode == 'fit':
                        target = self._compute_fit_size(frame_size, win_size, self.scale_factor)
                    else:
                        target = win_size  # stretch fills entire window
                    self.movie.setScaledSize(target)
                    self.label = QtWidgets.QLabel(self)
                    self.label.setAlignment(QtCore.Qt.AlignCenter)
                    self.label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
                    self.label.setMovie(self.movie)
                    self.movie.start()
                    try:
                        self.movie.frameChanged.connect(self._update_gif_layout)
                    except Exception:
                        pass
            elif self.scaling_mode == 'center':
                    # center uses original size scaled by scale_factor
                    frame_size = self.movie.frameRect().size()
                    safe_factor = max(0.01, float(self.scale_factor))
                    scaled_w = max(1, int(max(1, frame_size.width()) * safe_factor))
                    scaled_h = max(1, int(max(1, frame_size.height()) * safe_factor))
                    self.movie.setScaledSize(QtCore.QSize(scaled_w, scaled_h))
                    self.label = QtWidgets.QLabel(self)
                    self.label.setAlignment(QtCore.Qt.AlignCenter)
                    self.label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
                    self.label.setMovie(self.movie)
                    self.movie.start()
                    try:
                        self.movie.frameChanged.connect(self._update_gif_layout)
                    except Exception:
                        pass
            elif self.scaling_mode == 'tile':
                self.label = TiledGIFWidget(self.movie, self, self.advanced_settings)
        else:
            pixmap = QtGui.QPixmap(self.image_path)
            if pixmap.isNull():
                QtWidgets.QMessageBox.warning(self, "Error", "Failed to load image.")
                return

            # clamp max render dimension
            max_dim = int(self.advanced_settings.get('max_render_dimension', 4096))
            if pixmap.width() > max_dim or pixmap.height() > max_dim:
                pixmap = pixmap.scaled(max_dim, max_dim, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

            # GPU path for images disabled on layered window; use QLabel path
            if self.scaling_mode == 'fit':
                    target = self._compute_fit_size(pixmap.size(), self.size(), self.scale_factor)
                    scaled_pixmap = pixmap.scaled(
                        target,
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation
                    )
            elif self.scaling_mode == 'stretch':
                    # Stretch fills entire window; ignore scale_factor to match semantics
                    scaled_pixmap = pixmap.scaled(
                        self.size(),
                        QtCore.Qt.IgnoreAspectRatio,
                        QtCore.Qt.SmoothTransformation
                    )
            elif self.scaling_mode == 'center':
                    # Center at original size scaled by scale_factor
                    safe_factor = max(0.01, float(self.scale_factor))
                    scaled_width = max(1, int(pixmap.width() * safe_factor))
                    scaled_height = max(1, int(pixmap.height() * safe_factor))
                    scaled_pixmap = pixmap.scaled(
                        QtCore.QSize(scaled_width, scaled_height),
                        QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.SmoothTransformation
                    )
            elif self.scaling_mode == 'tile':
                    tile_size = pixmap.size()
                    tile_scale = self.advanced_settings.get('tile_scale', 1.0)
                    if tile_scale != 1.0:
                        tile_width = max(1, int(tile_size.width() * tile_scale))
                        tile_height = max(1, int(tile_size.height() * tile_scale))
                        tile_size = QtCore.QSize(tile_width, tile_height)
                        pixmap = pixmap.scaled(tile_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    window_size = self.size()
                    tiled_pixmap = QtGui.QPixmap(window_size)
                    tiled_pixmap.fill(QtCore.Qt.transparent)  

                    painter = QtGui.QPainter(tiled_pixmap)
                    painter.setRenderHint(QtGui.QPainter.Antialiasing, self.advanced_settings.get('enable_antialiasing', True))
                    for x in range(0, window_size.width(), pixmap.width()):
                        for y in range(0, window_size.height(), pixmap.height()):
                            painter.drawPixmap(x, y, pixmap)
                    painter.end()
                    scaled_pixmap = tiled_pixmap

            self.label = QtWidgets.QLabel(self)
            # For stretch, set pixmap without preserving aspect; use label scaledContents to fill
            if self.scaling_mode == 'stretch':
                self.label.setPixmap(pixmap)
            else:
                self.label.setPixmap(scaled_pixmap)
            self.label.setAlignment(QtCore.Qt.AlignCenter)
            self.label.setStyleSheet("background-color: rgba(0, 0, 0, 0);")

        if isinstance(self.label, QtWidgets.QLabel):
            # For stretch mode, allow QLabel to scale contents to fully fill
            self.label.setScaledContents(self.scaling_mode == 'stretch')
            self.label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # Attach/detach according to movement mode to ensure live updates
        if self.movement_mode == 'dvd':
            self._detach_from_layout()
            self._position_content_initial()
            self._setup_dvd_initial_state()
        else:
            if self.layout():
                self.layout().addWidget(self.label)

    def _update_gif_layout(self, _frame_index):
        try:
            if not hasattr(self, 'movie') or self.movie is None or not hasattr(self, 'label'):
                return
            pm = self.movie.currentPixmap()
            if pm.isNull():
                return
            frame_size = pm.size()
            if self.scaling_mode == 'fit':
                target = self._compute_fit_size(frame_size, self.size(), self.scale_factor)
                if self.movie.scaledSize() != target:
                    self.movie.setScaledSize(target)
            elif self.scaling_mode == 'stretch':
                if self.movie.scaledSize() != self.size():
                    self.movie.setScaledSize(self.size())
            elif self.scaling_mode == 'center':
                safe_factor = max(0.01, float(self.scale_factor))
                scaled_w = max(1, int(frame_size.width() * safe_factor))
                scaled_h = max(1, int(frame_size.height() * safe_factor))
                size = QtCore.QSize(scaled_w, scaled_h)
                if self.movie.scaledSize() != size:
                    self.movie.setScaledSize(size)
                if self.movement_mode == 'dvd' and self.label is not None:
                    self.label.resize(scaled_w, scaled_h)
                    self.label.raise_()
        except Exception:
            pass

    def _compute_fit_size(self, content_size: QtCore.QSize, window_size: QtCore.QSize, scale_factor: float) -> QtCore.QSize:
        cw = max(1, content_size.width())
        ch = max(1, content_size.height())
        ww = max(1, window_size.width())
        wh = max(1, window_size.height())
        # desired scaled content size
        try:
            safe_factor = max(0.01, float(scale_factor))
        except Exception:
            safe_factor = 1.0
        desired_w = max(1, int(cw * safe_factor))
        desired_h = max(1, int(ch * safe_factor))
        # scale to fit within window while keeping aspect
        scale = min(ww / desired_w, wh / desired_h)
        # final size
        final_w = max(1, int(desired_w * scale))
        final_h = max(1, int(desired_h * scale))
        return QtCore.QSize(final_w, final_h)

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

    def set_edit_mode(self, edit_mode):
        self.edit_mode = edit_mode
        if self.edit_mode:
            self.setCursor(QtCore.Qt.SizeAllCursor)
            if sys.platform == "win32":
                hwnd = self.winId().__int__()
                exStyle = GetWindowLong(hwnd, GWL_EXSTYLE)
                exStyle &= ~WS_EX_TRANSPARENT
                SetWindowLong(hwnd, GWL_EXSTYLE, exStyle)
            else:
                self.setWindowFlag(QtCore.Qt.WindowTransparentForInput, False)
            self.activateWindow()
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
            if sys.platform == "win32":
                hwnd = self.winId().__int__()
                exStyle = GetWindowLong(hwnd, GWL_EXSTYLE)
                exStyle |= WS_EX_TRANSPARENT
                SetWindowLong(hwnd, GWL_EXSTYLE, exStyle)
            else:
                self.setWindowFlag(QtCore.Qt.WindowTransparentForInput, True)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            if hasattr(self, 'set_edit_mode'):
                self.set_edit_mode(False)
        elif event.key() == QtCore.Qt.Key_Delete:
            self.deleteLater()

    def mousePressEvent(self, event):
        if self.edit_mode:
            if event.button() == QtCore.Qt.LeftButton:
                self.dragging = True
                self.last_mouse_pos = event.globalPos()
            elif event.button() == QtCore.Qt.RightButton:
                self.resizing = True
                self.last_mouse_pos = event.globalPos()
        self.shift_down = event.modifiers() & QtCore.Qt.ShiftModifier

    def mouseMoveEvent(self, event):
        if self.edit_mode:
            if self.dragging:
                delta = event.globalPos() - self.last_mouse_pos
                self.move(self.pos() + delta)
                self.last_mouse_pos = event.globalPos()
            elif self.resizing:
                delta = event.globalPos() - self.last_mouse_pos
                new_width = max(self.width() + delta.x(), 50)
                new_height = max(self.height() + delta.y(), 50)
                if getattr(self, 'shift_down', False):
                    # preserve aspect ratio using current widget ratio
                    ratio = max(0.01, self.height() / max(1, self.width()))
                    new_height = int(new_width * ratio)
                self.resize(new_width, new_height)
                self.last_mouse_pos = event.globalPos()
                # avoid re-render storms; let resizeEvent clear buffers and coalesce
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.edit_mode:
            self.dragging = False
            self.resizing = False
        self.shift_down = False

    def increase_scale(self):
        """
        Increases the scale factor of the overlay image.
        """
        if self.scaling_mode == 'tile':
            current_scale = self.advanced_settings.get('tile_scale', 1.0)
            new_scale = current_scale + 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = min(new_scale, 10.0)  
            self.advanced_settings['tile_scale'] = new_scale
        else:
            new_scale = self.advanced_settings.get('scale_factor', 1.0) + 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = min(new_scale, 10.0)  
            self.advanced_settings['scale_factor'] = new_scale

        self.save_settings()
        if self.scaling_mode == 'tile':
            self.advanced_settings['tile_scale'] = self.advanced_settings['tile_scale']
        self.initImage()

    def decrease_scale(self):
        """
        Decreases the scale factor of the overlay image.
        """
        if self.scaling_mode == 'tile':
            current_scale = self.advanced_settings.get('tile_scale', 1.0)
            new_scale = current_scale - 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = max(new_scale, 0.1)  
            self.advanced_settings['tile_scale'] = new_scale
        else:
            new_scale = self.advanced_settings.get('scale_factor', 1.0) - 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = max(new_scale, 0.1)  
            self.advanced_settings['scale_factor'] = new_scale

        self.save_settings()
        if self.scaling_mode == 'tile':
            self.advanced_settings['tile_scale'] = self.advanced_settings['tile_scale']
        self.initImage()

    def save_settings(self):
        
        pass

    def _setup_movement(self):
        if self.movement_mode == 'dvd':
            self._start_dvd()
        else:
            self._stop_dvd()

    def _setup_dvd_initial_state(self):
        if self._dvd_pos is None:
            g = self.geometry()
            # random initial direction
            angle = random.uniform(0, 360)
            import math
            self._dvd_velocity = QtCore.QPointF(
                math.cos(math.radians(angle)),
                math.sin(math.radians(angle))
            )
            # normalize and scale by speed (per tick)
            self._normalize_dvd_velocity()
            self._dvd_pos = QtCore.QPointF(g.x() + g.width()/2, g.y() + g.height()/2)

    def _normalize_dvd_velocity(self):
        # per-tick displacement computed from pixels/sec and timer interval
        interval_ms = 16  # approx 60hz
        dist = self.dvd_speed * (interval_ms / 1000.0)
        v = self._dvd_velocity
        mag = max(1e-6, (v.x()**2 + v.y()**2) ** 0.5)
        self._dvd_velocity = QtCore.QPointF(v.x() / mag * dist, v.y() / mag * dist)
        self._dvd_timer.setInterval(interval_ms)

    def _start_dvd(self):
        self._detach_from_layout()
        self._position_content_initial()
        self._setup_dvd_initial_state()
        if not self._dvd_timer.isActive():
            self._dvd_timer.start()

    def _stop_dvd(self):
        if self._dvd_timer.isActive():
            self._dvd_timer.stop()
        # Reattach content to layout if exists
        try:
            if self.label and self.layout():
                self.layout().addWidget(self.label)
        except Exception:
            pass

    def _advance_dvd(self):
        if self._dvd_pos is None or not hasattr(self, 'label'):
            self._setup_dvd_initial_state()
            return
        # Move the content widget inside fullscreen window
        content = self.label
        if content is None:
            return
        g = self.geometry()
        max_w = g.width()
        max_h = g.height()
        cw = content.width() if content.width() > 0 else min(400, max_w // 3)
        ch = content.height() if content.height() > 0 else min(300, max_h // 3)

        new_x = content.x() + int(self._dvd_velocity.x())
        new_y = content.y() + int(self._dvd_velocity.y())

        # bounce horizontally against window bounds
        if new_x <= 0 or new_x + cw >= max_w:
            # reflect with slight jitter to avoid identical paths
            import random as _r
            jitter = (_r.random() - 0.5) * 0.2  # +/-10%
            self._dvd_velocity.setX(-self._dvd_velocity.x() * (1.0 + jitter))
            new_x = max(0, min(new_x, max_w - cw))
        # bounce vertically against window bounds
        if new_y <= 0 or new_y + ch >= max_h:
            import random as _r
            jitter = (_r.random() - 0.5) * 0.2  # +/-10%
            self._dvd_velocity.setY(-self._dvd_velocity.y() * (1.0 + jitter))
            new_y = max(0, min(new_y, max_h - ch))
        content.move(new_x, new_y)

    def _detach_from_layout(self):
        try:
            lay = self.layout()
            if lay and self.label:
                lay.removeWidget(self.label)
            self.label.setParent(self)
            self.label.show()
        except Exception:
            pass

    def _position_content_initial(self):
        try:
            if not self.label:
                return
            g = self.geometry()
            max_w = g.width()
            max_h = g.height()
            cw, ch = 300, 200
            if isinstance(self.label, QtWidgets.QLabel) and self.label.pixmap():
                pm = self.label.pixmap()
                cw, ch = pm.width(), pm.height()
            else:
                sz = self.label.sizeHint()
                if sz.isValid():
                    cw, ch = sz.width(), sz.height()
            cw = min(cw, max_w // 2)
            ch = min(ch, max_h // 2)
            self.label.resize(cw, ch)
            rx = random.randint(0, max(0, max_w - cw))
            ry = random.randint(0, max(0, max_h - ch))
            self.label.move(rx, ry)
        except Exception:
            pass


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
        add_button.setMinimumSize(160, 90)
        add_button.setMaximumSize(160, 90)
        add_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
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
            button.setMinimumSize(160, 90)
            button.setMaximumSize(160, 90)
            button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

            reader = QtGui.QImageReader(image_path)
            reader.setScaledSize(QtCore.QSize(160, 90))
            image = reader.read()
            if image.isNull():
                continue
            pixmap = QtGui.QPixmap.fromImage(image)
            pixmap = pixmap.scaled(160, 90, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            icon = QtGui.QIcon(pixmap)
            button.setIcon(icon)
            button.setIconSize(QtCore.QSize(160, 90))
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
            original_file_name = os.path.basename(file_name)
            name, ok = QtWidgets.QInputDialog.getText(self, "Image Name", "Enter a name for the overlay:",
                                                      text=original_file_name)
            if not ok or not name.strip():
                QtWidgets.QMessageBox.warning(self, "Warning", "You must enter a name for the overlay.")
                return
            name = name.strip()

            import re
            name = re.sub(r'[<>:"/\\|?*]', '_', name)

            ext = os.path.splitext(original_file_name)[1]
            base_name = name + ext
            dest_path = os.path.join(self.overlays_dir, base_name)

            i = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.overlays_dir, f"{name}_{i}{ext}")
                i += 1

            try:
                import shutil
                shutil.copy(file_name, dest_path)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to add image: {e}")
                return

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
            try:
                if hasattr(btn, 'tile_widget') and btn.tile_widget:
                    btn.tile_widget.setStyleSheet("")
            except Exception:
                pass

        sender = self.sender()
        sender.setStyleSheet("border: 2px solid #00aaff;")
        try:
            if hasattr(sender, 'tile_widget') and sender.tile_widget:
                sender.tile_widget.setStyleSheet("border: 2px solid #00aaff; border-radius: 4px;")
        except Exception:
            pass

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
    overlay_toggle_signal = QtCore.pyqtSignal()

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
        self.toggle_timer = QtCore.QTimer()
        self.toggle_timer.setSingleShot(True)
        self.toggle_timer.timeout.connect(self.perform_toggle)
        self.toggle_delay = 200
        self.edit_mode = False
        self.advanced_settings = {
            'enable_hardware_acceleration': True,
            'update_interval': 0,
            'tile_scale': 1.0,
            'pixmap_cache_mb': 64,
            'renderer_cache_entries': 48,
            'max_memory_usage': 512,
            'enable_antialiasing': True,
            'transparency': 0,
            'background_color': '#000000',
            'enable_scale_limits': True,
            'scale_factor': 1.0,
            'animation_fps': 30,
            'max_render_dimension': 4096,
            'gpu_rendering': False,
            'movement_mode': 'static',
            'dvd_speed': 200.0
        }
        self.advanced_settings.setdefault('close_to_tray', True)
        self.tray = None
        self.profiles = {}
        self.next_overlay_hotkey = 'ctrl+alt+right'
        self.toggle_dvd_hotkey = 'ctrl+alt+d'
        self.initUI()
        self.load_settings()
        self.start_hotkey_listener()

    def initUI(self):
        self.setWindowTitle('AnyOverlay')
        self.resize(500, 500)

        self.apply_dark_theme()

        # Landscape layout: left controls, right preview/status
        root_layout = QtWidgets.QHBoxLayout()
        left_col = QtWidgets.QVBoxLayout()
        right_col = QtWidgets.QVBoxLayout()

        self.choose_overlay_button = QtWidgets.QPushButton('Choose Overlay')
        self.choose_overlay_button.setToolTip('Open the overlay gallery and select an image/GIF/video')
        self.choose_overlay_button.clicked.connect(self.open_media_gallery)
        left_col.addWidget(self.choose_overlay_button)

        open_folder_layout = QtWidgets.QHBoxLayout()
        self.open_folder_button = QtWidgets.QPushButton('Open Overlays Folder')
        self.open_folder_button.clicked.connect(self.open_overlays_folder)
        open_folder_layout.addWidget(self.open_folder_button)
        self.reset_scale_button = QtWidgets.QPushButton('Reset Scale')
        self.reset_scale_button.clicked.connect(self.on_reset_scale)
        open_folder_layout.addWidget(self.reset_scale_button)
        open_folder_layout.addStretch(1)
        left_col.addLayout(open_folder_layout)

        # Selected overlay feedback
        selected_layout = QtWidgets.QHBoxLayout()
        selected_label_title = QtWidgets.QLabel('Selected:')
        selected_layout.addWidget(selected_label_title)
        self.selected_overlay_label = QtWidgets.QLabel(self.image_path or '(none)')
        self.selected_overlay_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        selected_layout.addWidget(self.selected_overlay_label)
        left_col.addLayout(selected_layout)

        # Preview thumbnail
        preview_layout = QtWidgets.QHBoxLayout()
        self.preview_label = QtWidgets.QLabel('(no preview)')
        self.preview_label.setFixedSize(240, 135)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #555; background-color: #1e1e1e;")
        preview_layout.addWidget(self.preview_label)
        preview_layout.addStretch(1)
        right_col.addLayout(preview_layout)

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
        left_col.addLayout(display_layout)

        opacity_layout = QtWidgets.QHBoxLayout()
        opacity_label = QtWidgets.QLabel('Opacity:')
        opacity_layout.addWidget(opacity_label)
        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setMinimum(1)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(int(self.opacity * 100))
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        left_col.addLayout(opacity_layout)

        self.edit_mode_label = QtWidgets.QLabel('')
        left_col.addWidget(self.edit_mode_label)

        self.edit_mode_button = QtWidgets.QPushButton('Toggle Edit Mode')
        self.edit_mode_button.setCheckable(True)
        self.edit_mode_button.clicked.connect(self.toggle_edit_mode)
        left_col.addWidget(self.edit_mode_button)

        self.toggle_button = QtWidgets.QPushButton('Toggle Overlay')
        self.toggle_button.clicked.connect(self.toggle_overlay)
        left_col.addWidget(self.toggle_button)

        self.overlay_status_label = QtWidgets.QLabel('Overlay: OFF')
        self.overlay_status_label.setStyleSheet('color: #ff6666;')
        right_col.addWidget(self.overlay_status_label)

        hotkey_layout = QtWidgets.QHBoxLayout()
        hotkey_label = QtWidgets.QLabel('Global Hotkey:')
        hotkey_layout.addWidget(hotkey_label)
        self.hotkey_entry = QtWidgets.QLineEdit(self.global_hotkey)
        hotkey_layout.addWidget(self.hotkey_entry)
        self.set_hotkey_button = QtWidgets.QPushButton('Set Hotkey')
        self.set_hotkey_button.clicked.connect(self.on_set_hotkey)
        hotkey_layout.addWidget(self.set_hotkey_button)
        left_col.addLayout(hotkey_layout)

        # Extra hotkeys
        extra_hotkeys_layout = QtWidgets.QHBoxLayout()
        extra_hotkeys_layout.addWidget(QtWidgets.QLabel('Next Overlay Hotkey:'))
        self.next_overlay_entry = QtWidgets.QLineEdit(self.next_overlay_hotkey)
        extra_hotkeys_layout.addWidget(self.next_overlay_entry)
        extra_hotkeys_layout.addWidget(QtWidgets.QLabel('Toggle DVD Hotkey:'))
        self.toggle_dvd_entry = QtWidgets.QLineEdit(self.toggle_dvd_hotkey)
        extra_hotkeys_layout.addWidget(self.toggle_dvd_entry)
        self.apply_extra_hotkeys_btn = QtWidgets.QPushButton('Apply')
        self.apply_extra_hotkeys_btn.clicked.connect(self.on_apply_extra_hotkeys)
        extra_hotkeys_layout.addWidget(self.apply_extra_hotkeys_btn)
        left_col.addLayout(extra_hotkeys_layout)

        self.tabs = QtWidgets.QTabWidget()
        left_col.addWidget(self.tabs)

        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #555555;
                border-radius: 4px;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3c3f41;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #3c3f41;
                border-bottom-color: #2b2b2b;
                min-width: 100px;
            }
            QTabBar::tab:selected {
                background-color: #4b4b4b;
                border-bottom-color: #4b4b4b;
            }
            QTabBar::tab:hover {
                background-color: #4b4b4b;
            }
        """)

        self.rendering_tab = QtWidgets.QWidget()
        self.rendering_layout = QtWidgets.QVBoxLayout()
        self.rendering_layout.setAlignment(QtCore.Qt.AlignTop)
        self.rendering_tab.setLayout(self.rendering_layout)
        
        self.add_rendering_options()
        
        self.tabs.addTab(self.rendering_tab, "Rendering Options")


        self.gif_tab = QtWidgets.QWidget()
        self.gif_layout = QtWidgets.QVBoxLayout()
        self.gif_layout.setAlignment(QtCore.Qt.AlignTop)
        self.gif_tab.setLayout(self.gif_layout)

        gif_speed_layout = QtWidgets.QHBoxLayout()
        self.gif_speed_label = QtWidgets.QLabel('Playback Speed (%):')
        gif_speed_layout.addWidget(self.gif_speed_label)
        self.gif_speed_input = QtWidgets.QLineEdit(str(self.gif_speed))
        self.gif_speed_input.editingFinished.connect(self.on_gif_speed_changed)
        gif_speed_layout.addWidget(self.gif_speed_input)
        self.gif_layout.addLayout(gif_speed_layout)

        self.gif_cache_checkbox = QtWidgets.QCheckBox('Cache all GIF frames (higher memory)')
        self.gif_cache_checkbox.setChecked(self.advanced_settings.get('gif_cache_all', False))
        self.gif_cache_checkbox.stateChanged.connect(self.on_gif_cache_mode_changed)
        self.gif_layout.addWidget(self.gif_cache_checkbox)

        self.tabs.addTab(self.gif_tab, "GIF Options")

        self.advanced_tab = QtWidgets.QWidget()
        self.advanced_layout = QtWidgets.QVBoxLayout()
        self.advanced_layout.setAlignment(QtCore.Qt.AlignTop)
        self.advanced_tab.setLayout(self.advanced_layout)

        self.add_advanced_options()

        self.tabs.addTab(self.advanced_tab, "Advanced Options")

        root_layout.addLayout(left_col, 2)
        root_layout.addLayout(right_col, 1)
        self.setLayout(root_layout)

        self.overlay_toggle_signal.connect(self.toggle_overlay)

        self.show()
        self._setup_tray()

    def _setup_tray(self):
        try:
            if self.tray is None:
                self.tray = QtWidgets.QSystemTrayIcon(self)
                icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
                self.tray.setIcon(icon)
                menu = QtWidgets.QMenu()
                show_action = menu.addAction('Show')
                quit_action = menu.addAction('Quit')
                show_action.triggered.connect(self._tray_show)
                quit_action.triggered.connect(QtWidgets.qApp.quit)
                self.tray.setContextMenu(menu)
                self.tray.activated.connect(self._tray_activated)
                self.tray.show()
        except Exception:
            pass

    def _tray_show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._tray_show()

    def open_overlays_folder(self):
        try:
            if not os.path.exists(self.overlays_dir):
                os.makedirs(self.overlays_dir)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.overlays_dir))
        except Exception:
            pass

    def on_reset_scale(self):
        # Reset scale factors to defaults
        self.advanced_settings['scale_factor'] = 1.0
        self.advanced_settings['tile_scale'] = 1.0
        if hasattr(self, 'scale_factor_input'):
            self.scale_factor_input.setValue(1.0)
        if hasattr(self, 'tile_scale_input'):
            self.tile_scale_input.setText('1.0')
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.scale_factor = 1.0
            self.overlay_window.advanced_settings['tile_scale'] = 1.0
            self.overlay_window.initImage()

    def add_advanced_options(self):
        hw_accel_layout = QtWidgets.QHBoxLayout()
        hw_accel_layout.setAlignment(QtCore.Qt.AlignRight)
        hw_accel_label = QtWidgets.QLabel('Enable Hardware Acceleration:')
        hw_accel_layout.addWidget(hw_accel_label)
        self.hw_accel_checkbox = QtWidgets.QCheckBox()
        self.hw_accel_checkbox.setChecked(self.advanced_settings['enable_hardware_acceleration'])
        self.hw_accel_checkbox.stateChanged.connect(self.on_hw_accel_changed)
        hw_accel_layout.addWidget(self.hw_accel_checkbox)
        self.advanced_layout.addLayout(hw_accel_layout)

        update_interval_layout = QtWidgets.QHBoxLayout()
        update_interval_layout.setAlignment(QtCore.Qt.AlignRight)
        update_interval_label = QtWidgets.QLabel('Update Interval (ms):')
        update_interval_layout.addWidget(update_interval_label)
        self.update_interval_input = QtWidgets.QLineEdit(str(self.advanced_settings['update_interval']))
        self.update_interval_input.editingFinished.connect(self.on_update_interval_changed)
        update_interval_layout.addWidget(self.update_interval_input)
        self.advanced_layout.addLayout(update_interval_layout)

        tile_scale_layout = QtWidgets.QHBoxLayout()
        tile_scale_layout.setAlignment(QtCore.Qt.AlignRight)
        tile_scale_label = QtWidgets.QLabel('Tile Scale Factor:')
        tile_scale_layout.addWidget(tile_scale_label)
        self.tile_scale_input = QtWidgets.QLineEdit(str(self.advanced_settings['tile_scale']))
        self.tile_scale_input.editingFinished.connect(self.on_tile_scale_changed)
        tile_scale_layout.addWidget(self.tile_scale_input)
        self.advanced_layout.addLayout(tile_scale_layout)

        pixmap_cache_layout = QtWidgets.QHBoxLayout()
        pixmap_cache_layout.setAlignment(QtCore.Qt.AlignRight)
        pixmap_cache_label = QtWidgets.QLabel('Pixmap Cache (MB):')
        pixmap_cache_layout.addWidget(pixmap_cache_label)
        self.pixmap_cache_input = QtWidgets.QLineEdit(str(self.advanced_settings['pixmap_cache_mb']))
        self.pixmap_cache_input.editingFinished.connect(self.on_pixmap_cache_changed)
        pixmap_cache_layout.addWidget(self.pixmap_cache_input)
        self.advanced_layout.addLayout(pixmap_cache_layout)

        renderer_cache_layout = QtWidgets.QHBoxLayout()
        renderer_cache_layout.setAlignment(QtCore.Qt.AlignRight)
        renderer_cache_label = QtWidgets.QLabel('Renderer Cache Entries:')
        renderer_cache_layout.addWidget(renderer_cache_label)
        self.renderer_cache_input = QtWidgets.QLineEdit(str(self.advanced_settings['renderer_cache_entries']))
        self.renderer_cache_input.editingFinished.connect(self.on_renderer_cache_changed)
        renderer_cache_layout.addWidget(self.renderer_cache_input)
        self.advanced_layout.addLayout(renderer_cache_layout)

        max_memory_layout = QtWidgets.QHBoxLayout()
        max_memory_layout.setAlignment(QtCore.Qt.AlignRight)
        max_memory_label = QtWidgets.QLabel('Max Memory Usage (MB):')
        max_memory_layout.addWidget(max_memory_label)
        self.max_memory_input = QtWidgets.QLineEdit(str(self.advanced_settings['max_memory_usage']))
        self.max_memory_input.editingFinished.connect(self.on_max_memory_changed)
        max_memory_layout.addWidget(self.max_memory_input)
        self.advanced_layout.addLayout(max_memory_layout)

        antialias_layout = QtWidgets.QHBoxLayout()
        antialias_layout.setAlignment(QtCore.Qt.AlignRight)
        antialias_label = QtWidgets.QLabel('Enable Antialiasing:')
        antialias_layout.addWidget(antialias_label)
        self.antialias_checkbox = QtWidgets.QCheckBox()
        self.antialias_checkbox.setChecked(self.advanced_settings['enable_antialiasing'])
        self.antialias_checkbox.stateChanged.connect(self.on_antialias_changed)
        antialias_layout.addWidget(self.antialias_checkbox)
        self.advanced_layout.addLayout(antialias_layout)

        transparency_layout = QtWidgets.QHBoxLayout()
        transparency_layout.setAlignment(QtCore.Qt.AlignRight)
        transparency_label = QtWidgets.QLabel('Transparency Level (0-255):')
        transparency_layout.addWidget(transparency_label)
        self.transparency_input = QtWidgets.QLineEdit(str(self.advanced_settings['transparency']))
        self.transparency_input.editingFinished.connect(self.on_transparency_changed)
        transparency_layout.addWidget(self.transparency_input)
        self.advanced_layout.addLayout(transparency_layout)

        bg_color_layout = QtWidgets.QHBoxLayout()
        bg_color_layout.setAlignment(QtCore.Qt.AlignRight)
        bg_color_label = QtWidgets.QLabel('Background Color (#RRGGBB):')
        bg_color_layout.addWidget(bg_color_label)
        self.bg_color_input = QtWidgets.QLineEdit(self.advanced_settings['background_color'])
        self.bg_color_input.editingFinished.connect(self.on_bg_color_changed)
        bg_color_layout.addWidget(self.bg_color_input)
        self.advanced_layout.addLayout(bg_color_layout)

        scale_limits_layout = QtWidgets.QHBoxLayout()
        scale_limits_layout.setAlignment(QtCore.Qt.AlignRight)
        scale_limits_label = QtWidgets.QLabel('Enable Scale Limits:')
        scale_limits_layout.addWidget(scale_limits_label)
        self.scale_limits_checkbox = QtWidgets.QCheckBox()
        self.scale_limits_checkbox.setChecked(self.advanced_settings.get('enable_scale_limits', True))
        self.scale_limits_checkbox.stateChanged.connect(self.on_scale_limits_changed)
        scale_limits_layout.addWidget(self.scale_limits_checkbox)
        self.advanced_layout.addLayout(scale_limits_layout)

        close_tray_layout = QtWidgets.QHBoxLayout()
        close_tray_layout.setAlignment(QtCore.Qt.AlignRight)
        close_tray_label = QtWidgets.QLabel('Close to Tray:')
        close_tray_layout.addWidget(close_tray_label)
        self.close_tray_checkbox = QtWidgets.QCheckBox()
        self.close_tray_checkbox.setChecked(self.advanced_settings.get('close_to_tray', True))
        self.close_tray_checkbox.stateChanged.connect(self.on_close_to_tray_changed)
        close_tray_layout.addWidget(self.close_tray_checkbox)
        self.advanced_layout.addLayout(close_tray_layout)

    def add_rendering_options(self):
        scaling_mode_layout = QtWidgets.QHBoxLayout()
        scaling_mode_label = QtWidgets.QLabel('Scaling Mode:')
        scaling_mode_layout.addWidget(scaling_mode_label)
        self.scaling_mode_combo = QtWidgets.QComboBox()
        self.scaling_mode_combo.addItems(['Fit to Screen', 'Stretch to Fill', 'Center', 'Tile'])
        self.scaling_mode_combo.currentIndexChanged.connect(self.on_scaling_mode_changed)
        scaling_mode_layout.addWidget(self.scaling_mode_combo)
        self.rendering_layout.addLayout(scaling_mode_layout)

        # Add new scale factor control
        scale_factor_layout = QtWidgets.QHBoxLayout()
        scale_factor_label = QtWidgets.QLabel('Scale Factor:')
        scale_factor_layout.addWidget(scale_factor_label)
        
        self.scale_factor_input = QtWidgets.QDoubleSpinBox()
        self.scale_factor_input.setRange(0.01, 500.0)
        self.scale_factor_input.setSingleStep(0.1)
        self.scale_factor_input.setValue(self.advanced_settings.get('scale_factor', 1.0))
        self.scale_factor_input.setDecimals(2)
        self.scale_factor_input.valueChanged.connect(self.on_scale_factor_changed)
        scale_factor_layout.addWidget(self.scale_factor_input)
        
        self.rendering_layout.addLayout(scale_factor_layout)

        # Movement mode
        movement_layout = QtWidgets.QHBoxLayout()
        movement_label = QtWidgets.QLabel('Movement:')
        movement_layout.addWidget(movement_label)
        self.movement_combo = QtWidgets.QComboBox()
        self.movement_combo.addItems(['Static', 'DVD Bounce'])
        current_movement = self.advanced_settings.get('movement_mode', 'static')
        self.movement_combo.setCurrentIndex(1 if current_movement == 'dvd' else 0)
        self.movement_combo.currentIndexChanged.connect(self.on_movement_changed)
        movement_layout.addWidget(self.movement_combo)
        self.rendering_layout.addLayout(movement_layout)

        # DVD speed
        dvd_speed_layout = QtWidgets.QHBoxLayout()
        dvd_speed_label = QtWidgets.QLabel('DVD Speed (px/sec):')
        dvd_speed_layout.addWidget(dvd_speed_label)
        self.dvd_speed_input = QtWidgets.QDoubleSpinBox()
        self.dvd_speed_input.setRange(1.0, 5000.0)
        self.dvd_speed_input.setSingleStep(10.0)
        self.dvd_speed_input.setValue(float(self.advanced_settings.get('dvd_speed', 200.0)))
        self.dvd_speed_input.valueChanged.connect(self.on_dvd_speed_changed)
        dvd_speed_layout.addWidget(self.dvd_speed_input)
        self.rendering_layout.addLayout(dvd_speed_layout)

        # GPU toggle
        gpu_layout = QtWidgets.QHBoxLayout()
        gpu_label = QtWidgets.QLabel('Enable GPU Rendering:')
        gpu_layout.addWidget(gpu_label)
        self.gpu_checkbox = QtWidgets.QCheckBox()
        self.gpu_checkbox.setChecked(bool(self.advanced_settings.get('gpu_rendering', False)))
        self.gpu_checkbox.stateChanged.connect(self.on_gpu_toggle)
        gpu_layout.addWidget(self.gpu_checkbox)
        self.rendering_layout.addLayout(gpu_layout)

        # Animation FPS limiter
        fps_layout = QtWidgets.QHBoxLayout()
        fps_layout.addWidget(QtWidgets.QLabel('Animation FPS (GIF/Video UI):'))
        self.anim_fps_input = QtWidgets.QSpinBox()
        self.anim_fps_input.setRange(1, 120)
        self.anim_fps_input.setValue(int(self.advanced_settings.get('animation_fps', 30)))
        self.anim_fps_input.valueChanged.connect(self.on_anim_fps_changed)
        fps_layout.addWidget(self.anim_fps_input)
        self.rendering_layout.addLayout(fps_layout)

        # Max render dimension
        max_dim_layout = QtWidgets.QHBoxLayout()
        max_dim_layout.addWidget(QtWidgets.QLabel('Max Render Dimension (px):'))
        self.max_dim_input = QtWidgets.QSpinBox()
        self.max_dim_input.setRange(256, 16384)
        self.max_dim_input.setValue(int(self.advanced_settings.get('max_render_dimension', 4096)))
        self.max_dim_input.valueChanged.connect(self.on_max_dim_changed)
        max_dim_layout.addWidget(self.max_dim_input)
        self.rendering_layout.addLayout(max_dim_layout)

    def on_scale_factor_changed(self, value):
        self.advanced_settings['scale_factor'] = value
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.scale_factor = value
            # live update without hiding the overlay
            self.overlay_window.initImage()
            self.overlay_window.update()

    def on_movement_changed(self, index):
        mode = 'dvd' if index == 1 else 'static'
        self.advanced_settings['movement_mode'] = mode
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.movement_mode = mode
            self.overlay_window._setup_movement()
        elif self.overlay_window:
            self.overlay_window.movement_mode = mode

    def on_dvd_speed_changed(self, value):
        self.advanced_settings['dvd_speed'] = float(value)
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.dvd_speed = float(value)
            self.overlay_window._normalize_dvd_velocity()

    def on_gpu_toggle(self, state):
        self.advanced_settings['gpu_rendering'] = bool(state)
        self.save_settings()
        # Restart overlay to apply change without manual toggle
        if self.overlay_window:
            was_visible = self.is_overlay_visible
            if was_visible:
                self.destroy_overlay()
            self.create_overlay()

    def on_anim_fps_changed(self, value):
        self.advanced_settings['animation_fps'] = int(value)
        self.save_settings()
        # No direct hook; used to throttle updates in widgets

    def on_max_dim_changed(self, value):
        self.advanced_settings['max_render_dimension'] = int(value)
        self.save_settings()

    def on_close_to_tray_changed(self, state):
        self.advanced_settings['close_to_tray'] = bool(state)
        self.save_settings()

    def on_scale_limits_changed(self, state):
        self.advanced_settings['enable_scale_limits'] = bool(state)
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.advanced_settings['enable_scale_limits'] = bool(state)

    def apply_dark_theme(self):
        dark_stylesheet = """
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            font-family: Arial;
            font-size: 10pt;
        }
        QTabWidget::pane {
            border: 1px solid #555555;
            border-radius: 4px;
            background-color: #2b2b2b;
        }
        QTabBar::tab {
            background-color: #3c3f41;
            color: #ffffff;
            padding: 5px;
            border: 1px solid #3c3f41;
            border-bottom-color: #2b2b2b;
            min-width: 100px;
        }
        QTabBar::tab:selected {
            background-color: #4b4b4b;
            border-bottom-color: #4b4b4b;
        }
        QTabBar::tab:hover {
            background-color: #4b4b4b;
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
            self.is_gif = self.image_path.lower().endswith('.gif') if self.image_path else False
            # apply per-overlay profile if exists
            prof = self.profiles.get(self.image_path)
            if prof:
                self.advanced_settings.update(prof.get('advanced_settings', {}))
                self.opacity = prof.get('opacity', self.opacity)
                self.scaling_mode = prof.get('scaling_mode', self.scaling_mode)
                self.display_index = prof.get('display_index', self.display_index)
            self.update_gif_options_visibility()
            self.save_settings()
            if self.is_overlay_visible:
                self.destroy_overlay()
                self.create_overlay()
            if hasattr(self, 'selected_overlay_label'):
                from os.path import basename
                self.selected_overlay_label.setText(basename(self.image_path))
            self.update_preview()

    def update_gif_options_visibility(self):
        if self.is_gif:
            self.tabs.setTabEnabled(1, True)
        else:
            self.tabs.setTabEnabled(1, False)

    def update_preview(self):
        try:
            if not hasattr(self, 'preview_label') or not self.image_path:
                return
            lower = self.image_path.lower()
            if lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                pm = QtGui.QPixmap(self.image_path)
                if not pm.isNull():
                    pm = pm.scaled(self.preview_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    self.preview_label.setPixmap(pm)
            elif lower.endswith('.gif'):
                self.preview_label.setText('(animated GIF)')
            else:
                self.preview_label.setText('(video)')
        except Exception:
            pass

    def toggle_edit_mode(self, checked):
        self.edit_mode = checked
        if self.edit_mode:
            self.edit_mode_label.setText('Edit Mode Active: Use mouse to move/resize. Scroll to scale. Press Esc to exit.')
            self.edit_mode_button.setChecked(True)
        else:
            self.edit_mode_label.setText('')
            self.edit_mode_button.setChecked(False)
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.set_edit_mode(self.edit_mode)

    def exit_edit_mode(self):
        self.edit_mode_button.setChecked(False)
        self.toggle_edit_mode(False)

    def toggle_overlay(self):
        if not self.toggle_timer.isActive():
            self.toggle_timer.start(self.toggle_delay)

    def perform_toggle(self):
        if self.is_overlay_visible:
            self.destroy_overlay()
        else:
            self.create_overlay()
        if hasattr(self, 'overlay_status_label'):
            if self.is_overlay_visible:
                self.overlay_status_label.setText('Overlay: ON')
                self.overlay_status_label.setStyleSheet('color: #66ff66;')
            else:
                self.overlay_status_label.setText('Overlay: OFF')
                self.overlay_status_label.setStyleSheet('color: #ff6666;')

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
            self.overlay_window = OverlayWindow(
                self.image_path,
                geometry,
                self.opacity,
                self.gif_speed,
                self.scaling_mode,
                self.advanced_settings
            )
        else:
            self.overlay_window.setGeometry(geometry)
            self.overlay_window.setOpacity(self.opacity)
            self.overlay_window.setGifSpeed(self.gif_speed)
            self.overlay_window.setScalingMode(self.scaling_mode)
            self.overlay_window.advanced_settings = self.advanced_settings
            self.overlay_window.scale_factor = self.advanced_settings.get('scale_factor', 1.0)
            self.overlay_window.initImage()
            self.overlay_window.setImage(self.image_path)

        self.overlay_window.showFullScreen()
        self.overlay_window.set_edit_mode(self.edit_mode)
        self.is_overlay_visible = True

    def destroy_overlay(self):
        if self.overlay_window:
            # save per-overlay profile before closing
            try:
                self.profiles[self.image_path] = {
                    'advanced_settings': copy.deepcopy(self.advanced_settings),
                    'opacity': self.opacity,
                    'scaling_mode': self.scaling_mode,
                    'display_index': self.display_index
                }
                self.save_settings()
            except Exception:
                pass
            self.overlay_window.hide()
            self.overlay_window.deleteLater()
            self.overlay_window = None
        self.is_overlay_visible = False

    def start_hotkey_listener(self):
        try:
            import importlib, typing as _typing
            keyboard = importlib.import_module('keyboard')  # type: ignore
            keyboard.add_hotkey(self.global_hotkey, lambda: self.overlay_toggle_signal.emit())
            keyboard.add_hotkey(self.next_overlay_hotkey, self.cycle_overlay)
            keyboard.add_hotkey(self.toggle_dvd_hotkey, self.toggle_dvd_mode)
        except ImportError:
            QtWidgets.QMessageBox.warning(self, "Error", "The 'keyboard' module is required for hotkey functionality.")
            self.global_hotkey = None

    def cycle_overlay(self):
        try:
            files = [f for f in os.listdir(self.overlays_dir)
                     if os.path.isfile(os.path.join(self.overlays_dir, f)) and
                     f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.mp4', '.mkv', '.avi', '.mov', '.webm'))]
            if not files:
                return
            files.sort(key=lambda x: x.lower())
            if not self.image_path:
                next_file = os.path.join(self.overlays_dir, files[0])
            else:
                base = os.path.basename(self.image_path)
                try:
                    idx = files.index(base)
                    next_file = os.path.join(self.overlays_dir, files[(idx + 1) % len(files)])
                except ValueError:
                    next_file = os.path.join(self.overlays_dir, files[0])
            self.image_path = next_file
            self.is_gif = self.image_path.lower().endswith('.gif') if self.image_path else False
            prof = self.profiles.get(self.image_path)
            if prof:
                self.advanced_settings.update(prof.get('advanced_settings', {}))
                self.opacity = prof.get('opacity', self.opacity)
                self.scaling_mode = prof.get('scaling_mode', self.scaling_mode)
                self.display_index = prof.get('display_index', self.display_index)
            self.update_gif_options_visibility()
            if self.is_overlay_visible:
                self.destroy_overlay()
                self.create_overlay()
            if hasattr(self, 'selected_overlay_label'):
                from os.path import basename
                self.selected_overlay_label.setText(basename(self.image_path))
            self.update_preview()
            self.save_settings()
        except Exception:
            pass

    def toggle_dvd_mode(self):
        new_mode = 'static' if self.advanced_settings.get('movement_mode', 'static') == 'dvd' else 'dvd'
        self.advanced_settings['movement_mode'] = new_mode
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.movement_mode = new_mode
            self.overlay_window._setup_movement()
        self.save_settings()

    def get_screen_geometry(self):
        screens = QtWidgets.QApplication.screens()
        if self.display_index >= len(screens):
            return QtWidgets.QApplication.primaryScreen().geometry()
        return screens[self.display_index].geometry()

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

    def on_gif_speed_changed(self):
        try:
            value = int(self.gif_speed_input.text())
            self.gif_speed = value
            self.save_settings()
            if self.is_overlay_visible and self.overlay_window:
                self.overlay_window.setGifSpeed(self.gif_speed)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer.")
            self.gif_speed_input.setText(str(self.gif_speed))

    def on_gif_cache_mode_changed(self, state):
        self.advanced_settings['gif_cache_all'] = bool(state)
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            # Re-apply cache mode to current movie if GIF
            if hasattr(self.overlay_window, 'movie'):
                mode = QtGui.QMovie.CacheAll if self.advanced_settings.get('gif_cache_all') else QtGui.QMovie.CacheNone
                try:
                    self.overlay_window.movie.setCacheMode(mode)
                except Exception:
                    pass
            else:
                self.overlay_window.initImage()

    def on_apply_extra_hotkeys(self):
        self.next_overlay_hotkey = self.next_overlay_entry.text()
        self.toggle_dvd_hotkey = self.toggle_dvd_entry.text()
        self.save_settings()
        try:
            import importlib
            keyboard = importlib.import_module('keyboard')  # type: ignore
            keyboard.add_hotkey(self.next_overlay_hotkey, self.cycle_overlay)
            keyboard.add_hotkey(self.toggle_dvd_hotkey, self.toggle_dvd_mode)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to set extra hotkeys: {e}")

    def on_set_hotkey(self):
        self.global_hotkey = self.hotkey_entry.text()
        if self.global_hotkey:
            try:
                import importlib
                keyboard = importlib.import_module('keyboard')  # type: ignore
                keyboard.unhook_all_hotkeys()
                keyboard.add_hotkey(self.global_hotkey, lambda: self.overlay_toggle_signal.emit())
                keyboard.add_hotkey(self.next_overlay_hotkey, self.cycle_overlay)
                keyboard.add_hotkey(self.toggle_dvd_hotkey, self.toggle_dvd_mode)
                self.save_settings()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to set hotkey: {e}")
        else:
            QtWidgets.QMessageBox.warning(self, "Invalid Hotkey", "Hotkey cannot be empty.")

    def on_hw_accel_changed(self, state):
        self.advanced_settings['enable_hardware_acceleration'] = bool(state)
        self.save_settings()

    def on_update_interval_changed(self):
        try:
            value = int(self.update_interval_input.text())
            self.advanced_settings['update_interval'] = value
            self.save_settings()
            if self.is_overlay_visible and self.overlay_window:
                if value > 0:
                    if hasattr(self.overlay_window, 'update_timer'):
                        self.overlay_window.update_timer.setInterval(value)
                    else:
                        self.overlay_window.update_timer = QtCore.QTimer(self.overlay_window)
                        self.overlay_window.update_timer.timeout.connect(self.overlay_window.update)
                        self.overlay_window.update_timer.start(value)
                else:
                    if hasattr(self.overlay_window, 'update_timer'):
                        self.overlay_window.update_timer.stop()
                        del self.overlay_window.update_timer
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer.")
            self.update_interval_input.setText(str(self.advanced_settings['update_interval']))

    def on_tile_scale_changed(self):
        try:
            value = float(self.tile_scale_input.text())
            self.advanced_settings['tile_scale'] = value
            self.save_settings()
            if self.is_overlay_visible and self.overlay_window:
                self.overlay_window.initImage()
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid number.")
            self.tile_scale_input.setText(str(self.advanced_settings['tile_scale']))

    def on_pixmap_cache_changed(self):
        try:
            value = int(self.pixmap_cache_input.text())
            self.advanced_settings['pixmap_cache_mb'] = value
            self.save_settings()
            QtGui.QPixmapCache.setCacheLimit(value * 1024)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer.")
            self.pixmap_cache_input.setText(str(self.advanced_settings['pixmap_cache_mb']))

    def on_renderer_cache_changed(self):
        try:
            value = int(self.renderer_cache_input.text())
            self.advanced_settings['renderer_cache_entries'] = value
            self.save_settings()
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer.")
            self.renderer_cache_input.setText(str(self.advanced_settings['renderer_cache_entries']))

    def on_max_memory_changed(self):
        try:
            value = int(self.max_memory_input.text())
            self.advanced_settings['max_memory_usage'] = value
            self.save_settings()

        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer.")
            self.max_memory_input.setText(str(self.advanced_settings['max_memory_usage']))

    def on_antialias_changed(self, state):
        self.advanced_settings['enable_antialiasing'] = bool(state)
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.advanced_settings['enable_antialiasing'] = bool(state)
            self.overlay_window.initImage()

    def on_transparency_changed(self):
        try:
            value = int(self.transparency_input.text())
            if 0 <= value <= 255:
                self.advanced_settings['transparency'] = value
                self.save_settings()
                if self.is_overlay_visible and self.overlay_window:
                    self.overlay_window.initUI()
            else:
                raise ValueError
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid integer between 0 and 255.")
            self.transparency_input.setText(str(self.advanced_settings['transparency']))

    def on_bg_color_changed(self):
        color = self.bg_color_input.text()
        if not color.startswith('#') or len(color) != 7:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", "Please enter a valid color in #RRGGBB format.")
            self.bg_color_input.setText(self.advanced_settings['background_color'])
            return
        self.advanced_settings['background_color'] = color
        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            self.overlay_window.initUI()

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
                    self.advanced_settings = settings.get('advanced_settings', self.advanced_settings)
                    self.scale_factor = self.advanced_settings.get('scale_factor', 1.0)
                    self.is_gif = self.image_path.lower().endswith('.gif') if self.image_path else False
                    self.profiles = settings.get('profiles', {})
                    self.next_overlay_hotkey = settings.get('next_overlay_hotkey', self.next_overlay_hotkey)
                    self.toggle_dvd_hotkey = settings.get('toggle_dvd_hotkey', self.toggle_dvd_hotkey)
                    self.update_gif_options_visibility()

                    self.hotkey_entry.setText(self.global_hotkey)
                    self.opacity_slider.setValue(int(self.opacity * 100))
                    self.display_combo.setCurrentIndex(self.display_index)
                    scaling_modes = ['fit', 'stretch', 'center', 'tile']
                    index = scaling_modes.index(self.scaling_mode) if self.scaling_mode in scaling_modes else 0
                    self.scaling_mode_combo.setCurrentIndex(index)
                    self.gif_speed_input.setText(str(self.gif_speed))
                    if hasattr(self, 'selected_overlay_label'):
                        from os.path import basename
                        self.selected_overlay_label.setText(basename(self.image_path) if self.image_path else '(none)')
                    if hasattr(self, 'next_overlay_entry'):
                        self.next_overlay_entry.setText(self.next_overlay_hotkey)
                    if hasattr(self, 'toggle_dvd_entry'):
                        self.toggle_dvd_entry.setText(self.toggle_dvd_hotkey)

                    # migrate legacy cache_size -> pixmap_cache_mb if present
                    if 'cache_size' in self.advanced_settings and 'pixmap_cache_mb' not in self.advanced_settings:
                        self.advanced_settings['pixmap_cache_mb'] = self.advanced_settings.get('cache_size', 64)
                        self.advanced_settings.pop('cache_size', None)

                    # ensure defaults for new keys
                    self.advanced_settings.setdefault('pixmap_cache_mb', 64)
                    self.advanced_settings.setdefault('renderer_cache_entries', 48)

                    self.hw_accel_checkbox.setChecked(self.advanced_settings['enable_hardware_acceleration'])
                    self.update_interval_input.setText(str(self.advanced_settings['update_interval']))
                    self.tile_scale_input.setText(str(self.advanced_settings['tile_scale']))
                    self.pixmap_cache_input.setText(str(self.advanced_settings['pixmap_cache_mb']))
                    self.renderer_cache_input.setText(str(self.advanced_settings['renderer_cache_entries']))
                    self.max_memory_input.setText(str(self.advanced_settings['max_memory_usage']))
                    self.antialias_checkbox.setChecked(self.advanced_settings['enable_antialiasing'])
                    self.transparency_input.setText(str(self.advanced_settings['transparency']))
                    self.bg_color_input.setText(self.advanced_settings['background_color'])
                    self.scale_limits_checkbox.setChecked(self.advanced_settings.get('enable_scale_limits', True))
                    if hasattr(self, 'gif_cache_checkbox'):
                        self.gif_cache_checkbox.setChecked(self.advanced_settings.get('gif_cache_all', False))
                    scale_factor = self.advanced_settings.get('scale_factor', 1.0)
                    if hasattr(self, 'scale_factor_input'):
                        self.scale_factor_input.setValue(scale_factor)
                    # Sync movement UI
                    if hasattr(self, 'movement_combo'):
                        self.movement_combo.setCurrentIndex(1 if self.advanced_settings.get('movement_mode','static')=='dvd' else 0)

            except Exception as e:
                print(f"Error loading settings: {e}")

    def save_settings(self):
        settings = {
            'image_path': self.image_path,
            'display_index': self.display_index,
            'global_hotkey': self.global_hotkey,
            'opacity': self.opacity,
            'gif_speed': self.gif_speed,
            'scaling_mode': self.scaling_mode,
            'advanced_settings': self.advanced_settings,
            'profiles': self.profiles,
            'next_overlay_hotkey': self.next_overlay_hotkey,
            'toggle_dvd_hotkey': self.toggle_dvd_hotkey
        }
        
        if self.overlay_window:
            settings['advanced_settings']['scale_factor'] = self.overlay_window.scale_factor
        # ensure legacy key is removed
        if 'cache_size' in settings['advanced_settings']:
            settings['advanced_settings'].pop('cache_size', None)
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def closeEvent(self, event):
        # Close to tray if enabled
        if self.advanced_settings.get('close_to_tray', True):
            event.ignore()
            self.hide()
            if self.tray:
                try:
                    self.tray.showMessage('AnyOverlay', 'Still running in tray. Right-click to Quit.', QtWidgets.QSystemTrayIcon.Information, 2000)
                except Exception:
                    pass
            return
        try:
            import importlib
            keyboard = importlib.import_module('keyboard')  # type: ignore
            keyboard.unhook_all_hotkeys()
        except ImportError:
            pass
        self.save_settings()
        event.accept()

    def increase_scale(self):
        """
        Increases the scale factor of the overlay image.
        """
        if self.scaling_mode == 'tile':
            current_scale = self.advanced_settings.get('tile_scale', 1.0)
            new_scale = current_scale + 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = min(new_scale, 10.0)  
            self.advanced_settings['tile_scale'] = new_scale
        else:
            new_scale = self.advanced_settings.get('scale_factor', 1.0) + 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = min(new_scale, 10.0)  
            self.advanced_settings['scale_factor'] = new_scale

        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            if self.scaling_mode == 'tile':
                self.overlay_window.advanced_settings['tile_scale'] = self.advanced_settings['tile_scale']
            else:
                self.overlay_window.scale_factor = self.advanced_settings['scale_factor']
            self.overlay_window.initImage()

    def decrease_scale(self):
        """
        Decreases the scale factor of the overlay image.
        """
        if self.scaling_mode == 'tile':
            current_scale = self.advanced_settings.get('tile_scale', 1.0)
            new_scale = current_scale - 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = max(new_scale, 0.1)  
            self.advanced_settings['tile_scale'] = new_scale
        else:
            new_scale = self.advanced_settings.get('scale_factor', 1.0) - 0.1
            if self.advanced_settings.get('enable_scale_limits', True):
                new_scale = max(new_scale, 0.1)  
            self.advanced_settings['scale_factor'] = new_scale

        self.save_settings()
        if self.is_overlay_visible and self.overlay_window:
            if self.scaling_mode == 'tile':
                self.overlay_window.advanced_settings['tile_scale'] = self.advanced_settings['tile_scale']
            else:
                self.overlay_window.scale_factor = self.advanced_settings['scale_factor']
            self.overlay_window.initImage()


    def wheelEvent(self, event):
        # Scale when in edit mode; positive delta -> increase
        if self.edit_mode:
            delta = event.angleDelta().y()
            if delta > 0:
                self.increase_scale()
            elif delta < 0:
                self.decrease_scale()
        super().wheelEvent(event)


if __name__ == '__main__':
    # Guard AA_EnableHighDpiScaling attribute for environments lacking it
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        try:
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
        except Exception:
            pass
    app = QtWidgets.QApplication(sys.argv)
    ex = AnyOverlay()
    sys.exit(app.exec_())


