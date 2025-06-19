# -*- coding: utf-8 -*-
"""
desktopPyLauncher.py ― エントリポイント
◎ Qt6 / PyQt6 専用
"""
from __future__ import annotations

# --- 標準・サードパーティライブラリ ---
import sys, json, base64, os, inspect, traceback
from datetime import datetime
from pathlib import Path
import math
import time
    
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsRectItem, QToolBar, QMessageBox,
    QFileDialog, QFileIconProvider, QStyleFactory, QDialog,
    QLabel, QLineEdit, QTextEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QToolButton, QMenu, QComboBox, QSpinBox, QCheckBox, QSizePolicy,
    QWidget, QSlider, QGraphicsProxyWidget
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem
from PyQt6.QtGui import (
    QPixmap, QPainter, QBrush, QColor, QPalette, QAction,
    QIcon, QImage, QPen, QTransform, QFont, QRadialGradient
)
from PyQt6.QtCore import (
    Qt, QRectF, QSizeF, QPointF, QFileInfo, QProcess, 
    QCoreApplication, QEvent,
    QBuffer, QIODevice, QTimer, QUrl, QObject
)
# --- プロジェクト内モジュール ---
from DPyL_utils   import (
    warn, debug_print, b64e, fetch_favicon_base64,
    compose_url_icon, b64encode_pixmap, normalize_unc_path, 
    is_network_drive, _icon_pixmap, _default_icon, _load_pix_or_icon, ICON_SIZE
)
from DPyL_classes import (
    LauncherItem, JSONItem, 
    ImageItem, GifItem, GifMixin,
    CanvasItem, CanvasResizeGrip,
    BackgroundDialog
)
from DPyL_ticker import (
    NotificationManager, show_save_notification, show_export_html_notification,
    show_export_error_notification, show_project_load_notification, 
    show_error_notification, show_warning_notification
)
from DPyL_note    import (NoteItem,NOTE_BG_COLOR,NOTE_FG_COLOR)
from DPyL_video   import VideoItem
from DPyL_marker import MarkerItem
from DPyL_group import GroupItem
from configparser import ConfigParser
from urllib.parse import urlparse

from DPyL_debug import my_has_attr,dump_missing_attrs,trace_this
from DPyL_shapes import RectItem, ArrowItem
#from DPyL_effects import EffectManager

    
EXPAND_STEP = 500  # 端に到達したときに拡張する幅・高さ（px）

SHOW_MINIMAP = True

# ==============================================================
# migration 関数
# ==============================================================
def extract_image_info_from_base64(base64_data: str, format_hint: str = None) -> dict:
    """Base64データから画像情報を抽出"""
    try:
        pix = QPixmap()
        pix.loadFromData(base64.b64decode(base64_data))
        if not pix.isNull():
            return {
                "image_width": pix.width(),
                "image_height": pix.height(),
                "image_bits": pix.depth()
            }
    except:
        pass
    
    return {}

def detect_image_format(data: bytes) -> str:
    """
    バイナリデータから画像フォーマットを検出してData URLのプレフィックスを返す
    """
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return "data:image/png;base64,"
    elif data.startswith(b'\xff\xd8\xff'):
        return "data:image/jpeg;base64,"
    elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return "data:image/gif;base64,"
    elif data.startswith(b'<svg') or b'<svg' in data[:100]:
        return "data:image/svg+xml;base64,"
    else:
        # デフォルトはPNG
        return "data:image/png;base64,"
        
def migrate_item_to_v1_1(item_data: dict) -> dict:
    """
    version 1.0 のアイテムデータを version 1.1 に移行
    """
    # コピーを作成
    data = item_data.copy()
    
    caption = data.get("caption", "<no caption>")
    item_type = data.get("type", "<no type>")
    
    # LauncherItem の icon_embed
    if "icon_embed" in data:
        warn(f"[MIGRATE] Converting icon_embed for '{caption}' (type={item_type})")
        
        # icon_embedがbool型の場合のチェック
        if isinstance(data["icon_embed"], bool):
            warn(f"[MIGRATE] WARNING: icon_embed is bool for '{caption}': {data['icon_embed']}")
            # boolの場合は埋め込みフラグとして扱い、データは削除
            data["image_embedded"] = data.pop("icon_embed")
        else:
            # 正常な文字列データの場合
            data["image_embedded"] = True
            embed_str = data.pop("icon_embed")
            data["image_embedded_data"] = embed_str
            
            # バイナリデータから実際のフォーマットを検出
            try:
                raw_data = base64.b64decode(embed_str)
                data["image_format"] = detect_image_format(raw_data)
                warn(f"[MIGRATE] Detected format: {data['image_format']}")
            except Exception as e:
                warn(f"[MIGRATE] Failed to detect format for '{caption}': {e}")
                data["image_format"] = "data:image/png;base64,"
    
    # ImageItem/GifItem の embed と store
    if "embed" in data:
        warn(f"[MIGRATE] Converting embed for '{caption}' (type={item_type})")
        
        # embedがbool型の場合のチェック
        if isinstance(data["embed"], bool):
            warn(f"[MIGRATE] WARNING: embed is bool for '{caption}': {data['embed']}")
            # boolの場合は埋め込みフラグとして扱い、データは削除
            data["image_embedded"] = data.pop("embed")
        else:
            # 正常な文字列データの場合
            data["image_embedded"] = True
            embed_str = data.pop("embed")
            data["image_embedded_data"] = embed_str
            
            # バイナリデータから実際のフォーマットを検出
            try:
                raw_data = base64.b64decode(embed_str)
                data["image_format"] = detect_image_format(raw_data)
                warn(f"[MIGRATE] Detected format: {data['image_format']}")
            except Exception as e:
                warn(f"[MIGRATE] Failed to detect format for '{caption}': {e}")
                # フォールバック：拡張子から判定
                path = data.get("path", "").lower()
                if data.get("type") == "gif" or path.endswith(".gif"):
                    data["image_format"] = "data:image/gif;base64,"
                else:
                    data["image_format"] = "data:image/png;base64,"
        
        # path_last_embedded の移行
        for old in ("path_last_embedded", "path_last_embeded"):
            if old in data:
                data["image_path_last_embedded"] = data.pop(old)
                break
            elif data.get("store") == "embed" and "path" in data:
                data["image_path_last_embedded"] = data["path"]
    
    # store フィールドの処理
    if "store" in data:
        if data["store"] in ("embed", "embeded") and "image_embedded" not in data:
            data["image_embedded"] = True
        data.pop("store")
    
    # 埋め込みでない場合のデフォルト値
    if "image_embedded" not in data:
        data["image_embedded"] = False
    
    # デバッグ：最終的なデータ状態を確認
    if data.get("image_embedded"):
        has_data = "image_embedded_data" in data
        warn(f"[MIGRATE] Result for '{caption}': embedded=True, has_data={has_data}")
    
    return data

# ==============================================================
# Water Effect Classes
# ==============================================================

class WaterRipple:
    """個々の波紋を表現するクラス"""
    def __init__(self, x, y, start_time):
        self.x = x
        self.y = y
        self.start_time = start_time
        self.max_radius = 200  # 最大半径
        self.speed = 80  # 波の伝播速度 (pixels/second)
        self.decay_time = 3.0  # 減衰時間（秒）
        
    def get_radius(self, current_time):
        """現在時刻での波紋の半径を取得"""
        elapsed = current_time - self.start_time
        if elapsed < 0:
            return 0
        return min(elapsed * self.speed, self.max_radius)
    
    def get_amplitude(self, current_time):
        """現在時刻での波の振幅を取得（減衰を考慮）"""
        elapsed = current_time - self.start_time
        if elapsed < 0 or elapsed > self.decay_time:
            return 0
        return math.exp(-elapsed / self.decay_time * 3)
    
    def is_alive(self, current_time):
        """波紋がまだ有効かどうか"""
        elapsed = current_time - self.start_time
        return elapsed < self.decay_time and self.get_radius(current_time) < self.max_radius


class WaterEffectItem(QGraphicsItem):
    """水面エフェクトを描画するQGraphicsItem"""
    def __init__(self, scene_rect):
        super().__init__()
        self.scene_rect = scene_rect
        self.ripples = []
        self.setZValue(10000)  # 最前面に表示
        
        # アニメーション用タイマー
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)  # 約60FPS
        
        self.enabled = False
        
    def boundingRect(self):
        return self.scene_rect
    
    def add_ripple(self, x, y):
        """指定座標に新しい波紋を追加"""
        if not self.enabled:
            return
        current_time = time.time()
        self.ripples.append(WaterRipple(x, y, current_time))
        self.update()
    
    def set_enabled(self, enabled):
        """エフェクトの有効/無効を切り替え"""
        self.enabled = enabled
        if not enabled:
            self.ripples.clear()
        self.setVisible(enabled)
        self.update()
    
    def update_animation(self):
        """アニメーションフレームの更新"""
        if not self.enabled:
            return
            
        current_time = time.time()
        self.ripples = [r for r in self.ripples if r.is_alive(current_time)]
        
        if self.ripples:
            self.update()
    
    def paint(self, painter, option, widget):
        if not self.enabled or not self.ripples:
            return
            
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current_time = time.time()
        
        for ripple in self.ripples:
            radius = ripple.get_radius(current_time)
            amplitude = ripple.get_amplitude(current_time)
            
            if radius <= 0 or amplitude <= 0:
                continue
            
            center = QPointF(ripple.x, ripple.y)
            
            # 複数の波の輪を描画
            for i in range(3):
                wave_radius = radius - i * 15
                if wave_radius <= 0:
                    continue
                    
                alpha = int(amplitude * 100 * (1 - i * 0.3))
                if alpha <= 0:
                    continue
                
                # 波の位相を考慮した色の変化
                phase = (current_time - ripple.start_time) * 8 + i * math.pi / 2
                color_intensity = int(abs(math.sin(phase)) * alpha)
                
                # 波紋の色（青っぽい水の色）
                color = QColor(100, 150, 255, color_intensity)
                pen = QPen(color, 2)
                painter.setPen(pen)
                
                # 円形の波紋を描画
                painter.drawEllipse(center, wave_radius, wave_radius)
                
                # 内側のグラデーション効果
                if i == 0:
                    gradient = QRadialGradient(center, wave_radius * 0.8)
                    gradient.setColorAt(0, QColor(150, 200, 255, alpha // 3))
                    gradient.setColorAt(1, QColor(100, 150, 255, 0))
                    brush = QBrush(gradient)
                    painter.setBrush(brush)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawEllipse(center, wave_radius * 0.8, wave_radius * 0.8)

# ==============================================================
# Spark Effect Classes
# ==============================================================

class SparkParticle:
    """個々の火花を表現するクラス"""
    def __init__(self, x, y, start_time):
        self.start_x = x
        self.start_y = y
        self.start_time = start_time
        
        # 初期速度（ランダムな方向に飛び散る）
        import random
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(80, 200)  # ピクセル/秒
        self.velocity_x = math.cos(angle) * speed
        self.velocity_y = math.sin(angle) * speed - random.uniform(50, 100)  # 上向きの初期速度
        
        # 物理パラメータ
        self.gravity = 300  # 重力加速度 (pixels/second²)
        self.life_time = random.uniform(1.5, 3.0)  # 生存時間（秒）
        
        # 視覚効果パラメータ
        self.size = random.uniform(2, 5)
        self.color_hue = random.uniform(0, 60)  # 赤〜黄色の範囲
        
    def get_position(self, current_time):
        """現在時刻での火花の位置を取得"""
        elapsed = current_time - self.start_time
        if elapsed < 0:
            return self.start_x, self.start_y
            
        # 物理計算（重力を考慮した放物運動）
        x = self.start_x + self.velocity_x * elapsed
        y = self.start_y + self.velocity_y * elapsed + 0.5 * self.gravity * elapsed * elapsed
        
        return x, y
    
    def get_alpha(self, current_time):
        """現在時刻での火花の透明度を取得（減衰を考慮）"""
        elapsed = current_time - self.start_time
        if elapsed < 0 or elapsed > self.life_time:
            return 0
        return max(0, 1 - elapsed / self.life_time)
    
    def is_alive(self, current_time):
        """火花がまだ有効かどうか"""
        elapsed = current_time - self.start_time
        return elapsed < self.life_time


class SparkEffectItem(QGraphicsItem):
    """火花エフェクトを描画するQGraphicsItem"""
    def __init__(self, scene_rect):
        super().__init__()
        self.scene_rect = scene_rect
        self.sparks = []
        self.setZValue(9999)  # 最前面に表示（Waterより少し後ろ）
        
        # アニメーション用タイマー
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(16)  # 約60FPS
        
        self.enabled = False
        
    def boundingRect(self):
        return self.scene_rect
    
    def add_spark_burst(self, x, y, count=30):
        """指定座標に火花バーストを追加"""
        if not self.enabled:
            return
        current_time = time.time()
        
        # 複数の火花を一度に生成
        for _ in range(count):
            self.sparks.append(SparkParticle(x, y, current_time))
        
        self.update()
    
    def set_enabled(self, enabled):
        """エフェクトの有効/無効を切り替え"""
        self.enabled = enabled
        if not enabled:
            self.sparks.clear()
        self.setVisible(enabled)
        self.update()
    
    def update_animation(self):
        """アニメーションフレームの更新"""
        if not self.enabled:
            return
            
        current_time = time.time()
        self.sparks = [s for s in self.sparks if s.is_alive(current_time)]
        
        if self.sparks:
            self.update()
    
    def paint(self, painter, option, widget):
        if not self.enabled or not self.sparks:
            return
            
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current_time = time.time()
        
        for spark in self.sparks:
            x, y = spark.get_position(current_time)
            alpha = spark.get_alpha(current_time)
            
            if alpha <= 0:
                continue
            
            # 火花の色（赤〜黄色〜オレンジ）
            hue = spark.color_hue
            saturation = 255
            value = int(255 * alpha)
            color = QColor()
            color.setHsv(int(hue), saturation, value, int(255 * alpha))
            
            # 火花を描画（小さな円）
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QPointF(x, y), 
                spark.size * alpha, 
                spark.size * alpha
            )
            
            # グロー効果（外側の淡い光）
            glow_color = QColor(color)
            glow_color.setAlpha(int(100 * alpha))
            painter.setBrush(QBrush(glow_color))
            painter.drawEllipse(
                QPointF(x, y), 
                spark.size * alpha * 2, 
                spark.size * alpha * 2
            )

# ==============================================================
# ミニマップ
# ==============================================================
class MiniMapWidget(QWidget):
    """
    ミニマップを表示するためのカスタムウィジェット。
    - 親として MainWindow インスタンスを受け取り、その scene や view の情報を参照して描画を行う。
    - 表示されたあと、一定時間（ここでは3秒）経過すると自動的に非表示になるタイマーを持つ。
    """
    def __init__(self, win: "MainWindow", parent=None):
        super().__init__(parent)
        self.win = win
        # ミニマップ自体の固定サイズ（お好みで変更可）
        self.setFixedSize(200, 200)
        # 背景を半透明の黒（やや暗め）、境界線を黒 1px で設定
        #self.setStyleSheet("background-color: rgba(0, 0, 0, 150); border: 1px solid black;")
        # 境界線だけはスタイルシートで指定（背景は paintEvent で自力塗りつぶす）
        self.setStyleSheet("border: 1px solid black;")

        # --- 3秒後に自動的に hide() するためのタイマーを用意 ---
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        # タイマーが期限切れになったら this.hide() を呼ぶ
        self._hide_timer.timeout.connect(self.hide)

    def updateVisibility(self):
        """
        現在のビューポートがシーン全体をほぼ覆っているかを判定し、
        『ほぼ全体（90%以上）をカバー＋位置的に10%マージン内』の場合は非表示にし、
        それ以外の場合は表示して「3秒後に自動非表示タイマー」をスタートする。
        """
        # -- scene が既に破棄されている場合に備えて例外キャッチする --
        try:
            scene = self.win.scene
            scene_rect: QRectF = scene.sceneRect()
        except Exception:
            # QGraphicsScene が削除済みなどでアクセスできない場合は何もしない
            warn("Exception at updateVisibility")
            return
        view = self.win.view
        if scene_rect.isEmpty():
            # シーンサイズが空ならミニマップ自体を非表示
            self._hide_timer.stop()
            self.hide()
            return

        # ビューポート内の矩形領域（シーン座標）を取得
        visible_scene_rect: QRectF = view.mapToScene(view.viewport().rect()).boundingRect()

        # 「表示範囲がシーン全体の90%以上をカバーしていれば非表示」とするマージン付き判定
        #   動作イメージ：幅・高さそれぞれについて 0.9（＝90%） のしきい値を設ける
        threshold = 0.5
        w_scene = scene_rect.width()
        h_scene = scene_rect.height()
        w_vis   = visible_scene_rect.width()
        h_vis   = visible_scene_rect.height()

        # ① 幅・高さとも「ビューポートのサイズがしきい値×シーンサイズ以上」であれば大きさ的にはOK
        cond_size = (w_vis >= w_scene * threshold) and (h_vis >= h_scene * threshold)
        # ② 位置的にも「ビューポートの左端／上端がシーンの左端／上端よりはみ出していない」
        #    かつ「ビューポートの右端／下端がシーンの右端／下端よりはみ出していない」かどうかをチェック
        #    ここでは、許容マージンを幅・高さ各 10% として算出する
        margin_w = w_scene * (1 - threshold)  # 例：幅の10%分
        margin_h = h_scene * (1 - threshold)  # 例：高さの10%分
        cond_pos = (
            (visible_scene_rect.left()   <= scene_rect.left() + margin_w) and
            (visible_scene_rect.top()    <= scene_rect.top()  + margin_h) and
            (visible_scene_rect.right()  >= scene_rect.right()  - margin_w) and
            (visible_scene_rect.bottom() >= scene_rect.bottom() - margin_h)
        )

        # -------------- 判定結果に応じて表示／タイマー制御 --------------
        if cond_size and cond_pos:
            # 「ほぼ全体をカバーしている」と判断 → 非表示
            self._hide_timer.stop()
            self.hide()
        else:
            # それ以外 → 表示し、3秒後に自動非表示タイマーをスタート
            # （既にタイマーが動いている場合はリスタート）
            self.show()
            self.update()
            self._hide_timer.start(3000)

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # ① 背景を自力で半透明黒に塗りつぶす
            painter.fillRect(self.rect(), QColor(0, 0, 0, 150))        

            scene = self.win.scene
            view = self.win.view

            # シーン全体の矩形を取得
            scene_rect: QRectF = scene.sceneRect()
            if scene_rect.isEmpty():
                painter.end()
                return

            # ミニマップ描画領域の大きさ
            w_map = self.width()
            h_map = self.height()

            # シーン全体を縮小してミニマップ内に収めるためのスケールを算出
            scale_x = w_map / scene_rect.width()
            scale_y = h_map / scene_rect.height()
            scale = min(scale_x, scale_y)

            # 縮小後、ミニマップ中央に余白をつくるためのオフセット
            offset_x = (w_map - scene_rect.width() * scale) / 2
            offset_y = (h_map - scene_rect.height() * scale) / 2

            # 1) シーン内のオブジェクトを青の半透過矩形で描画
            pen_item = QPen(QColor(0, 0, 255))
            brush_item = QBrush(QColor(0, 0, 255, 100))
            for item in scene.items():
                try:
                    rect: QRectF = item.sceneBoundingRect()
                except Exception:
                    warn("Exception at paintEvent")
                    continue
                x = (rect.x() - scene_rect.x()) * scale + offset_x
                y = (rect.y() - scene_rect.y()) * scale + offset_y
                w = rect.width() * scale
                h = rect.height() * scale
                painter.setPen(pen_item)
                painter.setBrush(brush_item)
                painter.drawRect(QRectF(x, y, w, h))

            # 2) 現在のビューポート範囲を赤い枠で描画
            visible_scene_rect: QRectF = view.mapToScene(view.viewport().rect()).boundingRect()
            vx = (visible_scene_rect.x() - scene_rect.x()) * scale + offset_x
            vy = (visible_scene_rect.y() - scene_rect.y()) * scale + offset_y
            vw = visible_scene_rect.width() * scale
            vh = visible_scene_rect.height() * scale
            pen_view = QPen(QColor(255, 0, 0), 2)
            painter.setPen(pen_view)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(vx, vy, vw, vh))

            painter.end()
        except Exception as e:
            warn(f"{e}")

    def mousePressEvent(self, event):
        """クリックされた位置をメインビューに表示する"""
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                scene_rect = self.win.scene.sceneRect()
                if scene_rect.isEmpty():
                    return

                w_map, h_map = self.width(), self.height()
                scale_x = w_map / scene_rect.width()
                scale_y = h_map / scene_rect.height()
                scale = min(scale_x, scale_y)
                offset_x = (w_map - scene_rect.width() * scale) / 2
                offset_y = (h_map - scene_rect.height() * scale) / 2

                pos = event.position().toPoint()
                sx = (pos.x() - offset_x) / scale + scene_rect.x()
                sy = (pos.y() - offset_y) / scale + scene_rect.y()
                self.win.view.centerOn(QPointF(sx, sy))
                self.updateVisibility()
            except Exception as e:
                warn(f"Exception at minimap click: {e}")
        else:
            super().mousePressEvent(event)
        
# ==============================================================
#  CanvasView - キャンバス表示・ドラッグ&ドロップ対応
# ==============================================================
class CanvasView(QGraphicsView):
    def __init__(self, scene, win):
        super().__init__(scene, win)
        self.win = win
        self._zoom      = 1.0   # 現在の拡大率
        self._MIN_ZOOM  = 0.2   # 最小 20 %
        self._MAX_ZOOM  = 5.0   # 最大 500 %
        
        # Water Effect の初期化
        self.water_effect = None
        self.water_enabled = False
        
        # Spark Effect の初期化
        self.spark_effect = None
        self.spark_enabled = False
        
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setRenderHint(self.renderHints() | self.renderHints().Antialiasing)

        # --- スクロールバー端到達時のシーン拡張 ---
        self.horizontalScrollBar().valueChanged.connect(self._on_hscroll)
        self.verticalScrollBar().valueChanged.connect(self._on_vscroll)
        
    def toggle_water_effect(self, enabled):
        '''Water エフェクトのオン/オフ切り替え'''
        self.water_enabled = enabled
        
        if enabled:
            if not self.water_effect:
                # エフェクトアイテムを作成してシーンに追加
                scene_rect = self.scene().sceneRect()
                self.water_effect = WaterEffectItem(scene_rect)
                self.scene().addItem(self.water_effect)
            self.water_effect.set_enabled(True)
        else:
            if self.water_effect:
                self.water_effect.set_enabled(False)
             
    def toggle_spark_effect(self, enabled):
        '''Spark エフェクトのオン/オフ切り替え'''
        self.spark_enabled = enabled
        
        if enabled:
            if not self.spark_effect:
                # エフェクトアイテムを作成してシーンに追加
                scene_rect = self.scene().sceneRect()
                self.spark_effect = SparkEffectItem(scene_rect)
                self.scene().addItem(self.spark_effect)
            self.spark_effect.set_enabled(True)
        else:
            if self.spark_effect:
                self.spark_effect.set_enabled(False)
    
    def clear_water_effect(self):
        """
        WaterEffectItem をタイマー停止＆シーンから削除して破棄する
        """
        if self.water_effect:
            # タイマーを止める
            try:
                self.water_effect.timer.stop()
            except Exception:
                warn("Exception at clear_water_effect")
                pass
            # シーンから外す
            if self.water_effect.scene():
                self.scene().removeItem(self.water_effect)
            # 参照をクリア
            self.water_effect = None
            
    def clear_spark_effect(self):
        """
        SparkEffectItem をタイマー停止＆シーンから削除して破棄する
        """
        if self.spark_effect:
            # タイマーを止める
            try:
                self.spark_effect.timer.stop()
            except Exception:
                warn("Exception at clear_spark_effect")
                pass
            # シーンから外す
            if self.spark_effect.scene():
                self.scene().removeItem(self.spark_effect)
            # 参照をクリア
            self.spark_effect = None
    def dragEnterEvent(self, e): 
        # ファイルやURLドロップの受付
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)
        
    def dragMoveEvent(self, e):  
        e.acceptProposedAction()
        
    def dropEvent(self, e):      
        self.win.handle_drop(e)
    
    def mouseMoveEvent(self, ev):
        # 親のマウスムーブイベント（＝スクロール処理など）を先に実行
        super().mouseMoveEvent(ev)

        # ビューポートに映っているシーン領域を取得
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        scene = self.scene()
        if scene:
            scene_rect = scene.sceneRect()
            # ビューに映る領域がシーン外ならシーンを拡張
            if not scene_rect.contains(rect):
                new_rect = scene_rect.united(rect)
                scene.setSceneRect(new_rect)

    def mousePressEvent(self, ev):

        if self.water_enabled and ev.button() == Qt.MouseButton.LeftButton and self.water_effect:
            scene_pos = self.mapToScene(ev.position().toPoint())
            self.water_effect.add_ripple(scene_pos.x(), scene_pos.y())
            
        if self.spark_enabled and ev.button() == Qt.MouseButton.LeftButton and self.spark_effect:
            scene_pos = self.mapToScene(ev.position().toPoint())
            self.spark_effect.add_spark_burst(scene_pos.x(), scene_pos.y())
            
        # 右クリック時、空白エリアならペーストメニュー表示
        if ev.button() == Qt.MouseButton.RightButton:
            pos = ev.position().toPoint()
            scene_pos = self.mapToScene(pos)
            items = self.items(pos)
            if not items:
                menu = QMenu(self)
                
                # === ペーストメニュー ===
                act_paste = menu.addAction("ペースト")

                # --- クリップボードの内容を判定して有効/無効を切替 ---
                cb = QApplication.clipboard()
                can_paste = False

                try:
                    js = json.loads(cb.text())
                    if isinstance(js, dict):
                        can_paste = "items" in js and isinstance(js["items"], list)
                    elif isinstance(js, list):
                        can_paste = all(isinstance(d, dict) for d in js)
                except Exception:
                    pass

                # 静止画 or GIFファイルURL を貼れるように判定
                if not can_paste:
                    mime = cb.mimeData()
                    if mime.hasImage():
                        can_paste = True
                    elif mime.hasUrls() and any(
                        u.isLocalFile() and u.toLocalFile().lower().endswith(".gif")
                        for u in mime.urls()
                    ):
                        can_paste = True                    
                act_paste.setEnabled(can_paste)

                # === プロジェクト読み込みメニューを追加 ===
                menu.addSeparator()
                act_load_project = menu.addAction("ここにプロジェクトを読み込む")
                
                # === グループ化メニューを追加 ===
                menu.addSeparator()
                
                # 現在選択されているアイテムを取得
                selected_items = [item for item in self.scene().selectedItems() 
                                 if isinstance(item, (CanvasItem, VideoItem))]
                
                # グループ化（複数選択時のみ有効、GroupItem自体は除外）
                from DPyL_group import GroupItem  # インポート
                non_group_selected = [item for item in selected_items if not isinstance(item, GroupItem)]
                act_group = menu.addAction("グループ化")
                act_group.setEnabled(len(non_group_selected) > 1)
                
                # グループ化の解除（GroupItemが選択されている時のみ有効）
                selected_groups = [item for item in selected_items if isinstance(item, GroupItem)]
                act_ungroup = menu.addAction("グループ化の解除")
                act_ungroup.setEnabled(len(selected_groups) > 0)

                # === メニュー実行 ===
                sel = menu.exec(ev.globalPosition().toPoint())
                
                if sel == act_paste:
                    pasted_items = []
                    mime = cb.mimeData()
                    # 1) クリップボードにGIFファイルURLがあれば優先貼り付け
                    if mime.hasUrls():
                        for u in mime.urls():
                            if u.isLocalFile() and u.toLocalFile().lower().endswith(".gif"):
                                path = u.toLocalFile()
                                # ファクトリ経由でGifItemを生成・追加
                                item, d = self.win._create_item_from_path(path, scene_pos)
                                if item:
                                    self.win.scene.addItem(item)
                                    self.win.data["items"].append(d)
                                    pasted_items.append(item)
                                break
                    # 2) GIFがなければ従来の画像／JSON貼り付け
                    if not pasted_items:
                        self.win._paste_image_if_available(scene_pos)
                        pasted_items = self.win._paste_items_at(scene_pos)
                    if pasted_items:
                        for item in pasted_items:
                            item.set_editable(True)
                            item.set_run_mode(False)
                            
                elif sel == act_load_project:
                    # 新機能：プロジェクト読み込み
                    self.win._load_project_at_position(scene_pos)
                    
                elif sel == act_group:
                    # グループ化処理を呼び出し
                    self.win._group_selected_items()
                    
                elif sel == act_ungroup:
                    # グループ化解除処理を呼び出し
                    self.win._ungroup_selected_items()
                            
                ev.accept()
                return
        super().mousePressEvent(ev)
        
    def _on_vscroll(self, value: int):
        vbar = self.verticalScrollBar()
        scene = self.scene()
        if not scene:
            return
        rect = scene.sceneRect()
        # 「下端」に達したら下方向に領域を広げる
        if value >= vbar.maximum():
            new_rect = QRectF(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height() + EXPAND_STEP
            )
            scene.setSceneRect(new_rect)
            # スクロールバー範囲を更新
            new_max = int(new_rect.height() - self.viewport().height())
            if new_max < 0:
                new_max = 0
            vbar.setRange(int(new_rect.y()), int(new_rect.y() + new_max))
        # 「上端」に達したら上方向に領域を広げる
        elif value <= vbar.minimum():
            new_rect = QRectF(
                rect.x(),
                rect.y() - EXPAND_STEP,
                rect.width(),
                rect.height() + EXPAND_STEP
            )
            scene.setSceneRect(new_rect)
            # 上方向に広げたぶん、スクロール位置をシフトさせる
            vbar.setRange(int(new_rect.y()), int(new_rect.y() + new_rect.height() - self.viewport().height()))
            vbar.setValue(vbar.minimum() + EXPAND_STEP)
            
    def _on_hscroll(self, value: int):
        hbar = self.horizontalScrollBar()
        scene = self.scene()
        if not scene:
            return
        rect = scene.sceneRect()
        # 「右端」に達したら右方向に領域を広げる
        if value >= hbar.maximum():
            new_rect = QRectF(
                rect.x(),
                rect.y(),
                rect.width() + EXPAND_STEP,
                rect.height()
            )
            scene.setSceneRect(new_rect)
            # スクロールバー範囲を更新
            new_max = int(new_rect.width() - self.viewport().width())
            if new_max < 0:
                new_max = 0
            hbar.setRange(int(new_rect.x()), int(new_rect.x() + new_max))
        # 「左端」に達したら左方向に領域を広げる
        elif value <= hbar.minimum():
            new_rect = QRectF(
                rect.x() - EXPAND_STEP,
                rect.y(),
                rect.width() + EXPAND_STEP,
                rect.height()
            )
            scene.setSceneRect(new_rect)
            # 左方向に広げたぶん、スクロール位置をシフトさせる
            hbar.setRange(int(new_rect.x()), int(new_rect.x() + new_rect.width() - self.viewport().width()))
            hbar.setValue(hbar.minimum() + EXPAND_STEP)
    # --------------------------------------------------------------
    #   Ctrl + ホイール でビューをズーム
    # --------------------------------------------------------------
    r"""
    # 2025-06-07 以前の挙動
    # config とか 実行時引数で選べるようにするかも
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return

            # 拡大／縮小倍率を決定
            step_factor = 1.25 if delta > 0 else 0.8
            new_zoom = self._zoom * step_factor
            if not (self._MIN_ZOOM <= new_zoom <= self._MAX_ZOOM):
                return  # 制限外は無視

            # ズーム中心をマウス位置に合わせる
            old_pos = self.mapToScene(event.position().toPoint())
            self._zoom = new_zoom
            self.scale(step_factor, step_factor)
            new_pos = self.mapToScene(event.position().toPoint())
            diff = new_pos - old_pos
            self.translate(diff.x(), diff.y())

            event.accept()
        else:
            super().wheelEvent(event)
    """
    # --------------------------------------------------------------
    #   ホイール でビューをズーム（NoteItemスクロールモード考慮）
    # --------------------------------------------------------------
    def wheelEvent(self, event):
        # NoteItemのスクロールモードチェック
        pos = event.position().toPoint()
        scene_pos = self.mapToScene(pos)
        items = self.scene().items(scene_pos)
        
        # マウス位置にあるNoteItemで_scroll_ready=Trueのものがあれば直接スクロール処理
        for item in items:
            if hasattr(item, 'TYPE_NAME') and item.TYPE_NAME == "note":
                if getattr(item, '_scroll_ready', False):
                    debug_print(f"CanvasView: Found _scroll_ready=True NoteItem, processing scroll")
                    # NoteItemのスクロール処理を直接実行
                    delta = event.angleDelta().y()
                    if delta != 0:
                        step_px = 40  # 1 ステップあたりの移動量
                        old_offset = item.scroll_offset
                        new_offset = old_offset - int(delta / 120 * step_px)
                        item.set_scroll(new_offset)
                        debug_print(f"CanvasView: Scrolled from {old_offset} to {new_offset}")
                    event.accept()
                    return
                else:
                    debug_print(f"CanvasView: Found NoteItem but _scroll_ready=False")
        
        debug_print("CanvasView: No scroll-ready NoteItem, doing zoom")
        # 通常の拡大縮小処理
        delta = event.angleDelta().y()
        if delta == 0:
            return

        # 拡大／縮小倍率を決定
        step_factor = 1.25 if delta > 0 else 0.8
        new_zoom = self._zoom * step_factor
        if not (self._MIN_ZOOM <= new_zoom <= self._MAX_ZOOM):
            return  # 制限外は無視

        # ズーム中心をマウス位置に合わせる
        old_pos = self.mapToScene(event.position().toPoint())
        self._zoom = new_zoom
        self.scale(step_factor, step_factor)
        new_pos = self.mapToScene(event.position().toPoint())
        diff = new_pos - old_pos
        self.translate(diff.x(), diff.y())

        event.accept()
    # ----------------------------------------------
    #   何もない所をダブルクリック → ズーム 100 % に戻す
    # ----------------------------------------------
    def mouseDoubleClickEvent(self, event):
        # クリック位置にアイテムが無い＝「空白」とみなす
        # 現状、直下に何か あっても通ります
       
        if not self.scene() or self.scene().sceneRect().isEmpty():
            warn("⚠️ Scene is not ready, skipping double-click handling")
            return
        
        if not self.items(event.position().toPoint()):
            # 現在ズームが 1.0 以外ならリセット
            if self._zoom != 1.0:
                factor = 1.0 / self._zoom        # 元倍率へ戻す係数
                self.scale(factor, factor)       # 行列を一気にリセット
                self._zoom = 1.0
            event.accept()
        else:
            # アイテムの上なら既存挙動（選択など）を維持
            super().mouseDoubleClickEvent(event)

# ==============================================================
#  MainWindow - メインウィンドウ
# ==============================================================
class MainWindow(QMainWindow):
    def __init__(self, json_path: Path):
        super().__init__()
        self.loading_label = QLabel("LOADING...", self)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet(
            "font-size: 32px; color: white; background-color: rgba(0, 0, 0, 160);"
        )
        self.loading_label.setGeometry(self.rect())
        self.loading_label.setVisible(False)

        self.json_path = json_path.expanduser().resolve()
        os.chdir(self.json_path.parent)
        self.data: dict = {"items": []}
        self.text_color = self.palette().color(QPalette.ColorRole.Text)
        self._ignore_window_geom = False
        self.bg_pixmap = None

        # --- 履歴（ツールバーより先に初期化） ---
        self.history: list[Path] = []
        self.hidx: int = -1

        # --- シーンとビューのセットアップ ---
        self.scene = QGraphicsScene(self)
        self.view  = CanvasView(self.scene, self)
        self.setCentralWidget(self.view)
        self.scene.sceneRectChanged.connect(lambda _: self._apply_background())

        # --- 背景リサイズ用タイマー ---
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_background)

        # --- UI初期化 ---
        self._toolbar()
        self.setWindowTitle(f"desktopPyLauncher - {self.json_path.name}")
        self.resize(900, 650)
        
        # --- ミニマップを生成して右上に配置 ---
        if not SHOW_MINIMAP:
            self.minimap=None
        else:
            self.minimap = MiniMapWidget(self)
            self.minimap.setParent(self)          # MainWindow 上に重ねる
            self.minimap.show()
            
        # 初回配置：ウィンドウ幅・高さが確定してから move したいので、
        # 少し遅延させるか、resizeEvent 内で配置し直すのが確実
        self._position_minimap()        

        # --- 履歴エントリ追加 ---
        self._push_history(self.json_path)

        # --- データ読み込み＆編集モード初期化 ---
        self._load()
        self._set_mode(edit=False)
        
        #self.view.installEventFilter(self)
        
        self.notification_manager = NotificationManager(self.scene, self.view)
        
        # --- スクロールやシーン変更時にミニマップを再描画 / スクロールやシーン変更時に「表示／非表示判定」を行う ---
        if SHOW_MINIMAP:
            self.view.horizontalScrollBar().valueChanged.connect(self.minimap.updateVisibility)
            self.view.verticalScrollBar().valueChanged.connect(self.minimap.updateVisibility)
            self.scene.sceneRectChanged.connect(self.minimap.updateVisibility)

            # ウィンドウサイズ変更時にも「表示／非表示判定」を行う
            self.resizeEvent  # ← resizeEvent の中で _position_minimap() と一緒に判定されるので不要な場合もある

            # --- アプリ起動直後に一度、ミニマップの表示判定を実行 ---
            QTimer.singleShot(0, self.minimap.updateVisibility)
        
        # エフェクトマネージャーを作成
        #self.effect_manager = EffectManager(parent=self)
        
    def _position_minimap(self):
        """
        ミニマップを常にウィンドウの右上に配置する。
        余白（マージン）を 10px 程度にして配置。
        """
        if not SHOW_MINIMAP:
           return
        margin = 10
        # フレーム幅などを考慮して、QMainWindow のクライアント領域の右上に合わせる
        # self.width(), self.height() はウィンドウ全体サイズなので、
        # 必要に応じてフレーム幅を差し引くか、中央ウィジェットの座標系で計算してもよい。
        x = self.width() - self.minimap.width() - margin
        y = margin
        self.minimap.move(x, y)

    def resizeEvent(self, event):
        """
        ウィンドウやビューのリサイズ時に背景を再適用
        """
        super().resizeEvent(event)
        self._position_minimap()
        self._resize_timer.start(100)
        
        # 変更: 通知マネージャーのシーンとビューを更新
        if hasattr(self, 'notification_manager'):
            self.notification_manager.set_scene_and_view(self.scene, self.view) 
                
        
    def mouseReleaseEvent(self, ev):
        """
        5ボタンマウス（XButton1/XButton2）対応( 戻る／進む )
        PyQt6 は mousePressEvent より、こっちのほうが安定するらしい。
        """
        # XButton1 → 戻る（_go_prev）、XButton2 → 進む（_go_next）
        if ev.button() == Qt.MouseButton.XButton1:
            # 戻るボタンが押されたら _go_prev を呼ぶっす
            self._go_prev()
            return
        elif ev.button() == Qt.MouseButton.XButton2:
            # 進むボタンが押されたら _go_next を呼ぶっす
            self._go_next()
            return
        elif ev.button() == Qt.MouseButton.MiddleButton:
            # 中央のボタンで編集/実行切り替え
            # これが、mousePressEventではなく releaseEventでやらないと、偶数回目のトグルでダブルクリックが必要になる
            self.a_run.trigger()
            return
        
        super().mouseReleaseEvent(ev)
        
    # --- CanvasItem レジストリ経由でアイテム生成 ----------
    def _create_item_from_path(self, path, sp):
        """
        ドロップされたファイルから対応するアイテムを生成する。
        VideoItem は CanvasItem から派生していないので、特化した処理を行います。
        """
        ext = Path(path).suffix.lower()

        # --- VideoItem 特別対応 ---
        if VideoItem.supports_path(path):
            try:
                return VideoItem.create_from_path(path, sp, self)
            except Exception as e:
                warn(f"[drop] VideoItem creation failed: {e}")

        # --- 通常の CanvasItem 方式 ---
        for cls in CanvasItem.ITEM_CLASSES:
            try:
                if cls.supports_path(path):
                    return cls.create_from_path(path, sp, self)
            except Exception as e:
                warn(f"[factory] {cls.__name__}: {e}")
        return None, None


    def _get_item_class_by_type(self, t: str):
        for i in range(len(CanvasItem.ITEM_CLASSES)):
            c = CanvasItem.ITEM_CLASSES[i]
            if getattr(c, "TYPE_NAME", None) == t:
                return c

        # --- 特例: CanvasItem を継承していない VideoItem を手動で対応 ---
        if t == "video":
            from DPyL_video import VideoItem
            return VideoItem

    
        # === DPyL_shapes のクラス対応 ===
        if t == "rect":
            from DPyL_shapes import RectItem
            return RectItem
        elif t == "arrow":
            from DPyL_shapes import ArrowItem
            return ArrowItem
        # ==========================================

        return None

    def _new_project(self):
        # 新規プロジェクト作成
        path, _ = QFileDialog.getSaveFileName(
            self, "新規Jsonプロジェクト作成", "", "JSONファイル (*.json)"
        )
        if not path:
            return
        new_data = {
            "fileinfo": {
                "name": "desktopPyLauncher.py",
                "info": "project data file",
                "version": "1.0"
            },
            "items": []
        }
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        d = {
            "type": "json",
            "caption": Path(path).stem,
            "path": str(path),
            "x": 100,
            "y": 100
        }
        item = JSONItem(d, self.text_color)
        self.scene.addItem(item)
        self.data["items"].append(d)
        item.set_run_mode(False)

    # --- ツールバー構築 ---
    def _toolbar(self):
        tb = QToolBar("Main", self); self.addToolBar(tb)
        def act(text, slot, *, chk=False):
            a = QAction(text, self, checkable=chk); a.triggered.connect(slot)
            tb.addAction(a); return a
        
        act("🌱NEW", self._new_project)
        
        act("💾SAVE", self._save)
        act("🔁LOAD", lambda: (self._load(), self._set_mode(edit=False)))        
        act("📤EXPORT", self._export_html)
        tb.addSeparator()
        
        spacer1 = QWidget()
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer1.setFixedWidth(24)
        tb.addWidget(spacer1)
        
        self.a_home = act("🏠HOME",    self._go_home)
        self.a_prev = act("⏪️PREV",    self._go_prev)
        self.a_next = act("⏩NEXT",    self._go_next)
        
        # 5 button mouse --
        self.prev_action = QAction("PREV", self)
        self.next_action = QAction("NEXT", self)
        self.prev_action.triggered.connect(self._go_prev)
        self.next_action.triggered.connect(self._go_next)
        # ---
        
        self.add_toolbar_spacer(tb, width=24)

        self.a_edit = act("編集モード", lambda c: self._set_mode(edit=c), chk=True)
        self.a_run  = act("実行モード", lambda c: self._set_mode(edit=not c), chk=True)
        #self.a_edit = act("編集モード", self._on_edit_mode_toggled, chk=True)
        #self.a_run  = act("実行モード", self._on_run_mode_toggled, chk=True)
        
        self.add_toolbar_spacer(tb, width=24)

        # 「オブジェクト追加」ボタン
        menu_obj = QMenu(self)
        act_marker = menu_obj.addAction("マーカー追加")
        act_note   = menu_obj.addAction("ノート追加")
        menu_obj.addSeparator()  # セパレータで分ける
        act_rect   = menu_obj.addAction("矩形追加")
        act_arrow  = menu_obj.addAction("矢印追加")
    
        act_marker.triggered.connect(self._add_marker)
        act_note.triggered.connect(self._add_note)
        act_rect.triggered.connect(self._add_rect)
        act_arrow.triggered.connect(self._add_arrow)

        btn_obj  = QToolButton(self)
        btn_obj.setText("オブジェクト追加")
        btn_obj.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn_obj.setMenu(menu_obj)
        tb.addWidget(btn_obj)

        act("背景", self._background_dialog)
        
        # === Effects メニューを追加 ===
        menu_effects = QMenu(self)
        self.a_water = menu_effects.addAction("🌊Water")
        self.a_water.setCheckable(True)
        self.a_water.triggered.connect(self._toggle_water_effect)
        
        self.a_spark = menu_effects.addAction("✨Spark")
        self.a_spark.setCheckable(True)
        self.a_spark.triggered.connect(self._toggle_spark_effect)
        
        btn_effects = QToolButton(self)
        btn_effects.setText("Effects")
        btn_effects.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn_effects.setMenu(menu_effects)
        tb.addWidget(btn_effects)
        
        self.add_toolbar_spacer(tb, width=24)

        act("▶一括再生",   self._play_all_videos)
        act("⏸一括停止",   self._pause_all_videos)
        act("🔇一括ミュート", self._mute_all_videos)
        
        self.add_toolbar_spacer(tb, width=24)
         
        act("[-1-]", lambda: self._jump_all_videos(0))
        act("[-2-]", lambda: self._jump_all_videos(1))
        act("[-3-]", lambda: self._jump_all_videos(2))
        
        self.add_toolbar_spacer(tb, width=24)

        act("Exit", self.close)
        
        self._update_nav()
        
    def _toggle_water_effect(self, checked):
        '''Water エフェクトのオン/オフ切り替え'''
        self.view.toggle_water_effect(checked)
        
    def _toggle_spark_effect(self, checked):
        '''Spark エフェクトのオン/オフ切り替え'''
        self.view.toggle_spark_effect(checked)
        
    r"""
    def _on_edit_mode_toggled(self, checked: bool):
        print(f"[DEBUG] 編集モード toggled: {checked}")
        self._set_mode(edit=checked)

    def _on_run_mode_toggled(self, checked: bool):
        print(f"[DEBUG] 実行モード toggled: {checked}")
        self._set_mode(edit=not checked)
    """
    def add_toolbar_spacer(self, tb: QToolBar, width: int = 24):
        """
        ツールバーに区切り線と幅固定スペーサーを挿入
        """
        tb.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer.setFixedWidth(width)
        tb.addWidget(spacer)
        tb.addSeparator()
    # --- 3. 新規追加メソッド ---
    def _add_rect(self):
        """
        シーンの中央付近に新規 RectItem を追加する。
        """
        # 画面中心位置を取得
        sp = self.view.mapToScene(self.view.viewport().rect().center())

        # 既存の図形IDを調べ、最大ID + 10 を新規IDとする
        existing_ids = []
        for it in self.scene.items():
            if hasattr(it, 'd') and it.d.get("type") in ("rect", "arrow", "marker"):
                try:
                    existing_ids.append(int(it.d.get("id", 0)))
                except (TypeError, ValueError):
                    continue
        
        if existing_ids:
            new_id = max(existing_ids) + 10
        else:
            new_id = 1000

        # デフォルトの辞書を構築
        d = {
            "type": "rect",
            "id": new_id,
            "caption": f"RECT-{new_id}",
            "x": sp.x(),
            "y": sp.y(),
            "width": 100,
            "height": 60,
            "frame_color": "#FF0000",
            "frame_width": 2,
            "background_color": "#FFFFFF",
            "background_transparent": True,
            "corner_radius": 0,
            "jump_id": None,
            "show_caption": True,
            "z": 0,
        }

        # RectItem インスタンスを生成してシーンに追加
        item = RectItem(d, text_color=self.text_color)
        self.scene.addItem(item)
        item.setZValue(d["z"])
        self.data.setdefault("items", []).append(d)

        # 追加直後は編集モードにする
        item.set_run_mode(False)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)

    def _add_arrow(self):
        """
        シーンの中央付近に新規 ArrowItem を追加する。
        """
        # 画面中心位置を取得
        sp = self.view.mapToScene(self.view.viewport().rect().center())

        # 既存の図形IDを調べ、最大ID + 10 を新規IDとする
        existing_ids = []
        for it in self.scene.items():
            if hasattr(it, 'd') and it.d.get("type") in ("rect", "arrow", "marker"):
                try:
                    existing_ids.append(int(it.d.get("id", 0)))
                except (TypeError, ValueError):
                    continue
        
        if existing_ids:
            new_id = max(existing_ids) + 10
        else:
            new_id = 1000

        # デフォルトの辞書を構築
        d = {
            "type": "arrow",
            "id": new_id,
            "caption": f"ARROW-{new_id}",
            "x": sp.x(),
            "y": sp.y(),
            "width": 80,
            "height": 40,
            "frame_color": "#FF0000",
            "frame_width": 2,
            "background_color": "#FFFFFF",
            "background_transparent": True,
            "corner_radius": 0,
            "angle": 0,  # 右向き
            "is_line": False,  # ポリゴンスタイル
            "jump_id": None,
            "show_caption": True,
            "z": 0,
        }

        # ArrowItem インスタンスを生成してシーンに追加
        item = ArrowItem(d, text_color=self.text_color)
        self.scene.addItem(item)
        item.setZValue(d["z"])
        self.data.setdefault("items", []).append(d)

        # 追加直後は編集モードにする
        item.set_run_mode(False)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)

    # --- 編集モード限定の共通コンテキストメニュー ---
    def show_context_menu(self, item: QGraphicsItem, ev):
        if not self.a_edit.isChecked():
            return
            
        is_vid = isinstance(item, VideoItem)
        is_pix = isinstance(item, (ImageItem, GifItem, JSONItem, LauncherItem))
        is_shape = isinstance(item, (RectItem, ArrowItem))
        is_group = isinstance(item, GroupItem)
        
        menu = QMenu(self)
        
        act_copy = menu.addAction("コピー")
        act_cut  = menu.addAction("カット")
        
        menu.addSeparator()
        
        act_front = menu.addAction("最前面へ")
        act_back  = menu.addAction("最背面へ")
        menu.addSeparator()

        # === グループ化メニューを追加 ===
        selected_items = [item for item in self.scene.selectedItems() 
                         if isinstance(item, (CanvasItem, VideoItem))]
        
        # グループ化（複数選択時のみ有効、GroupItem自体は除外）
        non_group_selected = [item for item in selected_items if not isinstance(item, GroupItem)]
        act_group = menu.addAction("グループ化")
        act_group.setEnabled(len(non_group_selected) > 1)
        
        # グループ化の解除（GroupItemが選択されている時のみ有効）
        selected_groups = [item for item in selected_items if isinstance(item, GroupItem)]
        act_ungroup = menu.addAction("グループ化の解除")
        act_ungroup.setEnabled(len(selected_groups) > 0)
        
        menu.addSeparator()
        # ==========================================

        act_fit_orig = act_fit_inside_v = act_fit_inside_h = act_reset_size = None
        
        if is_pix or is_vid or is_shape:
            if is_pix or is_vid:
                act_fit_orig   = menu.addAction("元のサイズに合わせる")
                act_fit_inside_v = menu.addAction("内側（上下）にフィット")
                act_fit_inside_h = menu.addAction("内側（左右）にフィット")
            elif is_shape:  # 図形用のメニュー項目
                act_reset_size = menu.addAction("標準サイズにリセット")
            menu.addSeparator()

        act_del = menu.addAction("Delete")
        sel = menu.exec(ev.screenPos())

        # === グループ化メニューの処理 ===
        if sel == act_group:
            self._group_selected_items()
            ev.accept()
            return
        elif sel == act_ungroup:
            self._ungroup_selected_items()
            ev.accept()
            return
        # =====================================

        # --- コピー（複数選択対応） ---
        if sel == act_copy:
            self.copy_or_cut_selected_items(cut=False)
            ev.accept()
            return

        # --- カット（複数選択対応） ---
        if sel == act_cut:
            # 定義済みメソッドを呼び出し（cut=True で切り取り）
            self.copy_or_cut_selected_items(cut=True)
            ev.accept()
            return
        
        # --- Zオーダー変更 ---
        if sel == act_front:
            item.setZValue(max((i.zValue() for i in self.scene.items()), default=0) + 1)
        elif sel == act_back:
            item.setZValue(min((i.zValue() for i in self.scene.items()), default=0) - 1)
            
        # --- 図形用の標準サイズリセット ---
        elif sel == act_reset_size and is_shape:
            if isinstance(item, RectItem):
                # 矩形の標準サイズ：100x60
                standard_w, standard_h = 100, 60
            elif isinstance(item, ArrowItem):
                # 矢印の標準サイズ：80x40
                standard_w, standard_h = 80, 40
            else:
                standard_w, standard_h = 64, 64
                
            item.prepareGeometryChange()
            item.d["width"], item.d["height"] = standard_w, standard_h
            item.resize_content(standard_w, standard_h)
            item._update_grip_pos()
            item.init_caption()
        # --- 元のサイズに合わせる 
        elif sel == act_fit_orig and not is_shape:
        #elif sel == act_fit_orig:
            if is_pix:
                if isinstance(item, GifItem):
                    # GifItemの場合：現在のフレームから取得
                    pix = item._movie.currentPixmap() if item._movie else None
                    if not pix or pix.isNull():
                        warn("GIFフレーム取得失敗")
                        return
                    w = pix.width()
                    h = pix.height()
                    item._pix_item.setPixmap(pix)
                else:
                    # ImageItem, LauncherItem, JSONItem の場合
                    pix = None
                    src_pix = None

                    # === 新フィールド構造に対応した取得処理 ===
                    if isinstance(item, ImageItem):
                        # ImageItem用のフォールバック順序
                        # 1) image_embedded_data (埋め込みデータ)
                        # 2) image_path_last_embedded (最後に埋め込んだファイルのパス)
                        # 3) path (現在のパス)
                        
                        if item.d.get("image_embedded") and item.d.get("image_embedded_data"):
                            # 埋め込みデータから取得
                            pix = QPixmap()
                            try:
                                pix.loadFromData(base64.b64decode(item.d["image_embedded_data"]))
                                warn(f"[FIT_ORIG] ImageItem: 埋め込みデータから取得 ({pix.width()}x{pix.height()})")
                            except Exception as e:
                                warn(f"[FIT_ORIG] 埋め込みデータデコード失敗: {e}")
                                pix = None
                        
                        if (not pix or pix.isNull()) and item.d.get("image_path_last_embedded"):
                            # 最後に埋め込んだファイルのパスから取得
                            try:
                                pix = QPixmap(item.d["image_path_last_embedded"])
                                if not pix.isNull():
                                    warn(f"[FIT_ORIG] ImageItem: image_path_last_embeddedから取得 ({pix.width()}x{pix.height()})")
                            except Exception as e:
                                warn(f"[FIT_ORIG] image_path_last_embedded読み込み失敗: {e}")
                                pix = None
                        
                        if (not pix or pix.isNull()) and item.d.get("path"):
                            # 通常のパスから取得
                            try:
                                pix = QPixmap(item.d["path"])
                                if not pix.isNull():
                                    warn(f"[FIT_ORIG] ImageItem: pathから取得 ({pix.width()}x{pix.height()})")
                            except Exception as e:
                                warn(f"[FIT_ORIG] path読み込み失敗: {e}")
                                pix = None
                                
                    else:
                        # LauncherItem, JSONItem用のフォールバック順序
                        if item.d.get("image_embedded"):
                            # 埋め込みモード
                            # 1) image_embedded_data (新フィールド)
                            # 2) image_path_last_embedded (最後に埋め込んだファイルのパス)
                            # 3) path (現在のパス)
                            
                            if item.d.get("image_embedded_data"):
                                pix = QPixmap()
                                try:
                                    pix.loadFromData(base64.b64decode(item.d["image_embedded_data"]))
                                    warn(f"[FIT_ORIG] LauncherItem: 新埋め込みデータから取得 ({pix.width()}x{pix.height()})")
                                except Exception as e:
                                    warn(f"[FIT_ORIG] 新埋め込みデータデコード失敗: {e}")
                                    pix = None
                            
                            if (not pix or pix.isNull()) and item.d.get("image_path_last_embedded"):
                                try:
                                    pix = QPixmap(item.d["image_path_last_embedded"])
                                    if not pix.isNull():
                                        warn(f"[FIT_ORIG] LauncherItem: image_path_last_embeddedから取得 ({pix.width()}x{pix.height()})")
                                except Exception as e:
                                    warn(f"[FIT_ORIG] image_path_last_embedded読み込み失敗: {e}")
                                    pix = None
                            
                            if (not pix or pix.isNull()) and item.d.get("path"):
                                try:
                                    pix = QPixmap(item.d["path"])
                                    if not pix.isNull():
                                        warn(f"[FIT_ORIG] LauncherItem: pathから取得 ({pix.width()}x{pix.height()})")
                                except Exception as e:
                                    warn(f"[FIT_ORIG] path読み込み失敗: {e}")
                                    pix = None
                        else:
                            # 非埋め込みモード：icon/icon_index使用
                            src = item.d.get("icon") or item.d.get("path") or ""
                            idx = item.d.get("icon_index", 0)
                            if src:
                                pix = _load_pix_or_icon(src, idx, ICON_SIZE)
                                if not pix.isNull():
                                    warn(f"[FIT_ORIG] LauncherItem: icon/pathから取得 ({pix.width()}x{pix.height()})")

                    # === 旧フィールドサポート（後方互換性） ===
                    # 新フィールドで取得できなかった場合のフォールバック
                    if not pix or pix.isNull():
                        # 旧フィールド: icon_embed or embed
                        embed_data = item.d.get("icon_embed") or item.d.get("embed")
                        if embed_data:
                            pix = QPixmap()
                            try:
                                pix.loadFromData(base64.b64decode(embed_data))
                                warn(f"[FIT_ORIG] 旧埋め込みデータから取得 ({pix.width()}x{pix.height()})")
                            except Exception as e:
                                warn(f"[FIT_ORIG] 旧埋め込みデータデコード失敗: {e}")
                                pix = None

                    # === 最終フォールバック ===
                    if not pix or pix.isNull():
                        # icon/path から取得を再試行
                        src = item.d.get("icon") or item.d.get("path") or ""
                        idx = item.d.get("icon_index", 0)
                        if src:
                            pix = _load_pix_or_icon(src, idx, ICON_SIZE)

                    # 最終手段: デフォルトアイコン
                    if not pix or pix.isNull():
                        warn("[FIT_ORIG] 全ての画像ソース取得に失敗、デフォルトアイコンを使用")
                        pix = _default_icon(ICON_SIZE)

                    # --- サイズ判定 ---
                    w = max(pix.width(), ICON_SIZE)
                    h = max(pix.height(), ICON_SIZE)

                    item._src_pixmap = pix.copy()
                    item._pix_item.setPixmap(pix)

                # --- 共通処理（画像・GIF） ---
                item.prepareGeometryChange()
                item._rect_item.setRect(0, 0, w, h)
                item.d["width"], item.d["height"] = w, h
                item.resize_content(w, h)
                item._update_grip_pos()
                item.init_caption()

            elif is_vid:
                ns = item.nativeSize()
                if not ns.isValid():
                    warn("動画サイズ取得失敗: nativeSize が無効")
                    return
                w, h = int(ns.width()), int(ns.height())
                item.prepareGeometryChange()
                item.setSize(QSizeF(w, h))
                item.d["width"], item.d["height"] = w, h
                item.resize_content(w, h)
                item._update_grip_pos()
                item.init_caption()



        # --- 内側フィット（上下／左右） --------------------------
        elif sel in (act_fit_inside_v, act_fit_inside_h):
            fit_axis = "v" if sel == act_fit_inside_v else "h"
            # 1) 現在の表示領域サイズを取得
            cur_w = int(item.boundingRect().width())
            cur_h = int(item.boundingRect().height())

            # 2) ソース元サイズの取得（全タイプ網羅）
            if isinstance(item, GifItem):
                frame_rect = item.movie.frameRect()
                if not frame_rect.isValid():
                    warn("GIFフレームサイズ取得失敗")
                    return
                orig_w, orig_h = frame_rect.width(), frame_rect.height()
                src_pix = item.movie.currentPixmap()
                if src_pix.isNull():
                    warn("GIFフレーム取得失敗")
                    return

            elif is_vid:
                ns = item.nativeSize()
                if not ns.isValid():
                    warn("動画サイズ取得失敗: nativeSizeが無効")
                    return
                orig_w, orig_h = ns.width(), ns.height()
                src_pix = None  # 動画はpixmap不要

            elif is_pix:
                # ✅ embed/icon/path の順に取得を試みる
                pix = None
                embed_data = item.d.get("icon_embed") or item.d.get("embed")
                if embed_data:
                    pix = QPixmap()
                    try:
                        pix.loadFromData(base64.b64decode(embed_data))
                    except Exception as e:
                        warn(f"Base64デコード失敗: {e}")
                        pix = None

                if not pix or pix.isNull():
                    src = item.d.get("icon") or item.d.get("path") or ""
                    idx = item.d.get("icon_index", 0)
                    if src:
                        pix = _load_pix_or_icon(src, idx, ICON_SIZE)

                if not pix or pix.isNull():
                    warn("画像取得失敗: embed/icon/path 無効")
                    pix = _default_icon(ICON_SIZE)

                orig_w, orig_h = pix.width(), pix.height()
                src_pix = pix

            else:
                warn("未対応のアイテムタイプ")
                return

            # 3) アスペクト比を保って縮小（軸別フィット）
            if orig_w <= 0 or orig_h <= 0:
                warn("元サイズが無効")
                return

            if fit_axis == "v":            # 高さ基準
                scale = cur_h / orig_h
                w, h = int(orig_w * scale), int(cur_h)
            else:                          # 幅基準
                scale = cur_w / orig_w
                w, h = int(cur_w), int(orig_h * scale)

            # 4) 描画とリサイズ（静止画と動画で処理分岐）
            item.prepareGeometryChange()

            if is_pix:
                pm = src_pix.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                item._rect_item.setRect(0, 0, w, h)
                item._pix_item.setPixmap(pm)
            else:
                item.setSize(QSizeF(w, h))

            # 5) 共通後処理
            item.d["width"], item.d["height"] = w, h
            item.resize_content(w, h)
            item._update_grip_pos()
            item.init_caption()
             
            #return
        # --- 削除 ---
        elif sel == act_del:
            # 複数選択対応：選択されているすべてのアイテムを削除
            selected_items = [it for it in self.scene.selectedItems() 
                             if isinstance(it, (CanvasItem, VideoItem))]
            
            if len(selected_items) > 1:
                # 複数選択の場合は確認ダイアログを表示
                reply = QMessageBox.question(
                    self, 
                    "複数削除の確認", 
                    f"{len(selected_items)}個のアイテムを削除しますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    ev.accept()
                    return
            
            # 選択されているアイテムをすべて削除
            for selected_item in selected_items:
                self._remove_item(selected_item)

        ev.accept()

    # --- 選択アイテムのコピー／カット ---
    def copy_or_cut_selected_items(self, cut=False):
        """
        選択されたアイテムをコピーまたはカットする
        RectItem と ArrowItem にも対応
        """
        items = self.scene.selectedItems()
        
        # === 修正：図形アイテムも含める ===
        from DPyL_shapes import RectItem, ArrowItem
        ds = [it.d for it in items if isinstance(it, (CanvasItem, VideoItem, RectItem, ArrowItem))]
        # ===============================
        
        if not ds:
            return
            
        min_x = min(d.get("x", 0) for d in ds)
        min_y = min(d.get("y", 0) for d in ds)
        clipboard_data = {
            "base": [min_x, min_y],
            "items": ds
        }
        QApplication.clipboard().setText(json.dumps(clipboard_data, ensure_ascii=False, indent=2))
        
        if cut:
            for it in items:
                # === 修正：図形アイテムも削除対象に含める ===
                if isinstance(it, (CanvasItem, VideoItem, RectItem, ArrowItem)):
                    self._remove_item(it)
                # =======================================

    # --- 指定座標へペースト ---
    def _paste_items_at(self, scene_pos):
        """
        クリップボードデータを現在座標へ貼り付け  
        * 新形式 (base/items) → 相対配置  
        * 旧形式 (単一/複数)  → そのまま配置  
        戻り値: List[QGraphicsItem]
        """
        txt = QApplication.clipboard().text()
        pasted_items = []
        try:
            js = json.loads(txt)
            items = []
            # --- 新形式 ---
            if isinstance(js, dict) and "items" in js and "base" in js:
                base_x, base_y = js["base"]
                for d in js["items"]:
                    items.append((d, d.get("x", 0) - base_x, d.get("y", 0) - base_y))
            else:  # --- 旧形式 ---
                js_list = js if isinstance(js, list) else [js]
                items = [(d, 0, 0) for d in js_list]

            for d, dx, dy in items:
                cls = self._get_item_class_by_type(d.get("type"))
                if cls is None:
                    warn(f"[paste] unknown type: {d.get('type')}")
                    continue
                    
                d_new = d.copy()
                d_new["x"] = int(scene_pos.x()) + dx
                d_new["y"] = int(scene_pos.y()) + dy

                # === 修正：図形アイテムのコンストラクタ対応 ===
                if d.get("type") in ("rect", "arrow"):
                    # RectItem と ArrowItem は text_color のみを受け取る
                    item = cls(d_new, text_color=self.text_color)
                elif cls.TYPE_NAME != "video":
                    item = cls(d_new, self.text_color)
                else:
                    item = cls(d_new, win=self)
                # ================================================
                
                self.scene.addItem(item)
                self.data["items"].append(d_new)
                pasted_items.append(item)

        except Exception as e:
            warn(f"ペースト失敗: {e}")

        return pasted_items


    # --- 画像ペースト処理 ---
    def _paste_image_if_available(self, scene_pos):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        if mime.hasImage():
            img = clipboard.image()
            if img.isNull():
                warn("クリップボード画像が null です")
                return

            pixmap = QPixmap.fromImage(img)
            # base64エンコードして保存用に変換
            embed_data = b64encode_pixmap(pixmap)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            d = {
                "type": "image",
                "caption": now_str,
                # --- 新フォーマット: 埋め込み情報 ---
                "image_embedded": True,
                "image_embedded_data": embed_data,
                "image_format": "data:image/png;base64",
                # --- 座標・サイズ情報 ---
                "x": int(scene_pos.x()),
                "y": int(scene_pos.y()),
                "width": pixmap.width(),
                "height": pixmap.height()
            }

            item = ImageItem(d, text_color=self.text_color)
            self.scene.addItem(item)
            self.data["items"].append(d)
           
            # ドロップした直後は編集モードON
            item.set_run_mode(False)
            item.grip.setVisible(True)
            item._grip.setVisible(True)     
            
        else:
            warn("画像データがクリップボードにありません")
 
    # TODO: 様子見
    def REPLACED_remove_item(self, item: QGraphicsItem):
        """
        アイテムを安全に削除
        ① VideoItem は専用後始末
        ② CanvasItem 派生は delete_self() 呼び出し
        ③ その他はシーン除去＋ data["items"] から辞書削除
        """
        # ① VideoItem はこれまでどおり deleteLater() も呼ぶ
        r"""
        if isinstance(item, VideoItem):
            item.delete_self()
            if item.video_resize_dots and item.video_resize_dots.scene():
                item.video_resize_dots.scene().removeItem(item.video_resize_dots)
            item.video_resize_dots = None
            return
        """
        if isinstance(item, VideoItem):
            item.delete_self()
            if item.video_resize_dots and item.video_resize_dots.scene():
                item.video_resize_dots.scene().removeItem(item.video_resize_dots)
            item.video_resize_dots = None
            # JSONから辞書を削除
            if hasattr(item, "d") and item.d in self.data.get("items", []):
                self.data["items"].remove(item.d)
            return            

        # ② CanvasItem 派生は自身の delete_self() に委譲
        r"""
        if isinstance(item, CanvasItem):
            item.delete_self()
            return
        """
            
        if isinstance(item, CanvasItem):
            # シーンからの各種後始末
            item.delete_self()
            # JSONから辞書も削除
            if hasattr(item, "d") and item.d in self.data.get("items", []):
                self.data["items"].remove(item.d)
            return            

        # ③ それ以外
        if item.scene():
            item.scene().removeItem(item)
            
        if hasattr(item, "d") and item.d in self.data.get("items", []):
            self.data["items"].remove(item.d)

    def _remove_item(self, item: QGraphicsItem):
        """
        アイテムを安全に削除
        ① VideoItem は専用後始末
        ② CanvasItem 派生は delete_self() 呼び出し
        ③ RectItem/ArrowItem は専用処理（CanvasItemを継承していないため）
        ④ その他はシーン除去＋ data["items"] から辞書削除
        """
        # ① VideoItem はこれまでどおり deleteLater() も呼ぶ
        if isinstance(item, VideoItem):
            item.delete_self()
            if item.video_resize_dots and item.video_resize_dots.scene():
                item.video_resize_dots.scene().removeItem(item.video_resize_dots)
            item.video_resize_dots = None
            # JSONから辞書を削除
            if hasattr(item, "d") and item.d in self.data.get("items", []):
                self.data["items"].remove(item.d)
            return
            
        # ② CanvasItem 派生は自身の delete_self() に委譲
        if isinstance(item, CanvasItem):
            # シーンからの各種後始末
            item.delete_self()
            # JSONから辞書も削除
            if hasattr(item, "d") and item.d in self.data.get("items", []):
                self.data["items"].remove(item.d)
            return
            
        # === ③ 新規追加：RectItem/ArrowItem の専用処理 ===
        from DPyL_shapes import RectItem, ArrowItem
        if isinstance(item, (RectItem, ArrowItem)):
            # ArrowItemの場合はドラッグポイントも削除
            if isinstance(item, ArrowItem):
                if hasattr(item, '_arrow_tip') and item._arrow_tip and item._arrow_tip.scene():
                    item._arrow_tip.scene().removeItem(item._arrow_tip)
                    item._arrow_tip = None
            
            # グリップがある場合は削除
            if hasattr(item, 'grip') and item.grip and item.grip.scene():
                item.grip.scene().removeItem(item.grip)
                item.grip = None
                
            # シーンから削除
            if item.scene():
                item.scene().removeItem(item)
                
            # JSONから辞書を削除
            if hasattr(item, "d") and item.d in self.data.get("items", []):
                self.data["items"].remove(item.d)
            return
    # --- 動画一括操作 ---
    r"""
    # old version
    def _play_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                it.player.play(); it.btn_play.setChecked(True); it.btn_play.setText("⏸")
            elif isinstance(it, GifItem):
                it.play() 

    def _pause_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                # 再生中のときだけ Pause（Stopped への余計な遷移を防止）
                if it.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    it.player.pause()
                # ▶/⏸ ボタンと内部フラグを同期
                it.btn_play.setChecked(False)
                it.btn_play.setText("▶")
                it.active_point_index = None
            elif isinstance(it, GifItem):
                it.pause()     
    """
    def _play_all_videos(self):
        """すべての動画とGIFアニメーションを一括再生"""
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                # VideoItem の再生制御
                it.player.play()
                it.btn_play.setChecked(True)
                it.btn_play.setText("⏸")
            elif isinstance(it, GifMixin):
                # GifMixin を継承している全てのアイテム（GifItem, LauncherItem など）
                # _movie.start() でGIF再生開始（一時停止状態からでも再開可能）
                if hasattr(it, '_movie') and it._movie:
                    it._movie.start()

    def _pause_all_videos(self):
        """すべての動画とGIFアニメーションを一括停止"""
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                # VideoItem の停止制御
                # 再生中のときだけ Pause（Stopped への余計な遷移を防止）
                if it.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    it.player.pause()
                # ▶/⏸ ボタンと内部フラグを同期
                it.btn_play.setChecked(False)
                it.btn_play.setText("▶")
                it.active_point_index = None
            elif isinstance(it, GifMixin):
                # GifMixin を継承している全てのアイテム（GifItem, LauncherItem など）
                # setPaused(True) を使用して一時停止（完全停止ではない）
                if hasattr(it, '_movie') and it._movie:
                    it._movie.setPaused(True)
                
    def _mute_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                new_mute = not it.audio.isMuted()
                it.audio.setMuted(new_mute)
                it.btn_mute.setChecked(new_mute)
                it.d["muted"] = new_mute

    def _jump_all_videos(self, idx: int):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                it._jump(idx)

    # --- 背景設定ダイアログ ---
    def _background_dialog(self):
        # 現在の背景設定取得
        cur = self.data.get("background", {})
        if cur.get("path"):                    # 画像
            def_mode, def_val = "image", cur["path"]
        elif cur.get("mode") == "color":       # 単色
            def_mode, def_val = "color", cur.get("color", "")
        else:                                  # クリア
            def_mode, def_val = "clear", ""

        def_bri = cur.get("brightness", 50)  # 既存の明るさ or デフォルト50

        # 明るさ付きで取得
        ok, mode, value, bri = BackgroundDialog.get(def_mode, def_val, def_bri)
        if not ok:
            return

        if mode == "image":
            self.data["background"] = {"path": value, "brightness": bri}
        elif mode == "color":
            self.data["background"] = {"mode": "color", "color": value}
        else:
            self.data.pop("background", None)

        self._apply_background()

    def _apply_background(self):
        """
        背景画像・単色・クリアを描画
        """
        bg = self.data.get("background")

        # --- 単色背景モード ---
        if bg and bg.get("mode") == "color":
            self.bg_pixmap = None
            self.scene.setBackgroundBrush(QBrush(QColor(bg.get("color", "#000000"))))
            self.view.viewport().update()
            return

        # --- 背景設定なしまたは画像パス未指定 ---
        if not bg or not bg.get("path"):
            self.bg_pixmap = None
            self.scene.setBackgroundBrush(QBrush())
            self.view.viewport().update()
            return

        # --- 画像背景モード ---
        src = QPixmap(bg["path"])
        if not src.isNull():
            vw = self.view.viewport().width()
            vh = self.view.viewport().height()
            scaled = src.scaled(vw, vh,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x_off = (scaled.width()  - vw)//2
            y_off = (scaled.height() - vh)//2
            pm = scaled.copy(x_off, y_off, vw, vh)

            # 明暗補正（50=標準, <50暗く, >50明るく）
            b = bg.get("brightness", 50)
            if b != 50:
                painter = QPainter(pm)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                alpha = int(abs(b - 50) / 50.0 * 255)
                col = QColor(0,0,0,alpha) if b < 50 else QColor(255,255,255,alpha)
                painter.fillRect(pm.rect(), col)
                painter.end()

            self.bg_pixmap = pm
        else:
            self.bg_pixmap = None

        if self.bg_pixmap is None:
            self.scene.setBackgroundBrush(QBrush())
            self.view.viewport().update()
            return

        # タイル背景の設定
        brush = QBrush(self.bg_pixmap)
        tl = self.view.mapToScene(self.view.viewport().rect().topLeft())
        dx = int(tl.x()) % self.bg_pixmap.width()
        dy = int(tl.y()) % self.bg_pixmap.height()
        brush.setTransform(QTransform().translate(dx, dy))
        self.scene.setBackgroundBrush(brush)

    # --- Web URLからLauncherItem生成 ---
    def _make_web_launcher(self, weburl: str, sp: QPointF, icon_path: str = "", is_url_file: bool = False):
        if not isinstance(weburl, str) or not weburl.strip():
            warn(f"[drop] 無効なURL: {weburl!r}")
            return None, None

        domain = urlparse(weburl).netloc or weburl
        d = {
            "type": "launcher",
            "caption": domain,
            "path": weburl,
            "icon": icon_path if is_url_file else "",
            "icon_index": 0,
            "x": sp.x(), "y": sp.y()
        }

        if is_url_file:
            d["icon"] = icon_path
        else:
            icon_b64 = fetch_favicon_base64(domain)
            if icon_b64:
                d["icon_embed"] = icon_b64

        it = LauncherItem(d, self.text_color)
        return it, d

    # --- MainWindowドラッグ＆ドロップ対応 ---
    def handle_drop(self, e):
        """
        URL / ファイルドロップ共通ハンドラ
        * http(s) URL           → favicon 付き LauncherItem   ←最優先
        * ネットワークドライブ   → 専用 LauncherItem
        * CanvasItem レジストリ → 自動判定で生成
        ドロップ後は全体を編集モードへ強制切替！
        """
        added_any = False
        added_items = []
        sp = self.view.mapToScene(e.position().toPoint())
        for url in e.mimeData().urls():

            # ① まずは “http/https” を最優先で処理  -----------------
            weburl = url.toString().strip()
            if weburl.startswith(("http://", "https://")):
                it, d = self._make_web_launcher(weburl, sp)
                if it:
                    self.scene.addItem(it); self.data["items"].append(d)
                    added_any = True
                    added_items.append(it)
                continue          # GenericFileItem へフォールバックさせない

            # ② ローカルパス判定 ------------------------------------
            raw_path = url.toLocalFile().strip()
            if not raw_path:
                warn(f"[drop] パスも URL も解釈できない: {url}")
                continue
            path = normalize_unc_path(raw_path)

            # ④ レジストリ経由 (CanvasItem.ITEM_CLASSES) ------------
            it, d = self._create_item_from_path(path, sp)
            if it:
                self.scene.addItem(it); self.data["items"].append(d)
                added_any = True
                added_items.append(it)
                continue
                
            # ③ ネットワークドライブ -------------------------------
            if is_network_drive(path):
                dll = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                   "System32", "imageres.dll")
                d = {
                    "type": "launcher",
                    "caption": os.path.basename(path.rstrip('\\/')),
                    "path": path,
                    "workdir": path,
                    "icon": dll,
                    "icon_index": 28,
                    "x": sp.x(), "y": sp.y()
                }
                it = LauncherItem(d, self.text_color)
                self.scene.addItem(it); self.data["items"].append(d)
                added_any = True
                added_items.append(it)
                continue



            # ⑤ ここまで来ても未判定なら警告 -----------------------
            warn(f"[drop] unsupported: {url}")

        
        # 追加アイテムだけ run_mode=False にして編集モードにする
        # 別の仕組みにより、編集ウィンドウで編集後 OK または CANCEL後、全体の実行/編集モードに同期します
        for item in added_items:
            item.set_run_mode(False)



        self._arrange_new_items(added_items, sp)

    def _arrange_new_items(self, items: list[QGraphicsItem], base_pos: QPointF):
        """新規追加されたアイテムをグリッド状に並べる"""
        if not items:
            return

        # 最大アイテムサイズを取得しスペーシングを計算
        max_w = max(it.boundingRect().width() for it in items)
        max_h = max(it.boundingRect().height() for it in items)
        step_x = max_w + ICON_SIZE
        step_y = max_h + ICON_SIZE

        # ビューの可視領域サイズをシーン座標で求める
        view_rect = self.view.viewport().rect()
        tl = self.view.mapToScene(view_rect.topLeft())
        br = self.view.mapToScene(view_rect.bottomRight())
        view_w = br.x() - tl.x()
        view_h = br.y() - tl.y()

        max_cols = max(1, int(view_w // step_x))
        max_rows = max(1, int(view_h // step_y))

        n = len(items)
        cols = max(1, min(max_cols, round(math.sqrt(n))))
        rows = math.ceil(n / cols)
        if rows > max_rows:
            rows = max_rows
            cols = max(1, math.ceil(n / rows))

        while cols * rows < n:
            if cols < max_cols:
                cols += 1
            else:
                rows += 1

        for idx, it in enumerate(items):
            r = idx // cols
            c = idx % cols
            x = base_pos.x() + c * step_x
            y = base_pos.y() + r * step_y
            it.setPos(x, y)
            if hasattr(it, "d"):
                it.d["x"] = int(x)
                it.d["y"] = int(y)


    # --- スナップ ---
    def snap_position(self, item, new_pos: QPointF) -> QPointF:
        # === グループ移動中の子アイテムはスナップしない ===
        if getattr(item, '_group_moving', False):
            return new_pos
        # ====================================================
        
        # 他アイテムに吸着する座標補正
        SNAP_THRESHOLD = 10
        best_dx = None
        best_dy = None
        best_x = new_pos.x()
        best_y = new_pos.y()
        r1 = item.boundingRect().translated(new_pos)

        #for other in self.scene.items():
        all_items = list(self.scene.items())
        for other in all_items:            
            if other is item or not my_has_attr(other, "boundingRect"):
            #if isinstance(other, QGraphicsItem) and other is not item:
                continue

            r2 = other.boundingRect().translated(other.pos())

            # X方向スナップ
            for ox, tx in [(r2.left(), r1.left()), (r2.right(), r1.right())]:
                dx = abs(tx - ox)
                if dx < SNAP_THRESHOLD and (best_dx is None or dx < best_dx):
                    best_dx = dx
                    best_x = new_pos.x() + (ox - tx)

            # Y方向スナップ
            for oy, ty in [(r2.top(), r1.top()), (r2.bottom(), r1.bottom())]:
                dy = abs(ty - oy)
                if dy < SNAP_THRESHOLD and (best_dy is None or dy < best_dy):
                    best_dy = dy
                    best_y = new_pos.y() + (oy - ty)

        return QPointF(best_x, best_y)
        
    def snap_size(self, target_item, new_w, new_h):
        # === グループ移動中の子アイテムはスナップしない ===
        if getattr(target_item, '_group_moving', False):
            return new_w, new_h
        # ====================================================
        
        SNAP_THRESHOLD = 10
        best_dw, best_dh = None, None
        best_w, best_h = new_w, new_h
        # 現在の位置
        r1 = target_item.mapToScene(target_item.boundingRect()).boundingRect()
        x0, y0 = r1.left(), r1.top()

        for other in self.scene.items():
            if other is target_item or not my_has_attr(other, "boundingRect"):
                continue
            r2 = other.mapToScene(other.boundingRect()).boundingRect()
            # 横（幅）端スナップ
            for ox in [r2.left(), r2.right()]:
                dw = abs(x0 + new_w - ox)
                if dw < SNAP_THRESHOLD and (best_dw is None or dw < best_dw):
                    best_dw = dw
                    best_w = ox - x0
            # 縦（高さ）端スナップ
            for oy in [r2.top(), r2.bottom()]:
                dh = abs(y0 + new_h - oy)
                if dh < SNAP_THRESHOLD and (best_dh is None or dh < best_dh):
                    best_dh = dh
                    best_h = oy - y0

        return best_w, best_h

    # --- ノート追加 ---
    def _add_note(self):
        sp = self.view.mapToScene(self.view.viewport().rect().center())
        d = {
            "type": "note",
            "x": sp.x(),
            "y": sp.y(),
            "width": 200,
            "height": 120,
            "note": b64e("New note"),
            "isLabel": False,
            "color": NOTE_FG_COLOR,
            "fontsize": 14,
            "noteType": "text",
            "path": "",
        }
        it = NoteItem(d, self.text_color)
        self.scene.addItem(it)
        self.data.setdefault("items", []).append(d)
        #self._set_mode(edit=True)
        it.set_run_mode(False)

    # --- マーカー追加 ---
    def _add_marker(self):
        """
        シーンの中央付近に、新規 MarkerItem を追加する。
        - 既存のマーカーIDを調べ、最大ID + 100 を新規IDとする
        - デフォルトで幅・高さ 32×32、キャプション「MARKER-<ID>」、ジャンプ先なし、開始地点 False、align="左上"
        """
        # 画面中心位置を取得
        sp = self.view.mapToScene(self.view.viewport().rect().center())

        # 既存マーカーの ID をすべて収集
        existing_ids = []
        for it in self.scene.items():
            if isinstance(it, MarkerItem):
                try:
                    existing_ids.append(int(it.d.get("id", 0)))
                except (TypeError, ValueError):
                    continue
        if existing_ids:
            new_id = max(existing_ids) + 100
        else:
            new_id = 10000

        # デフォルトの辞書を構築
        d = {
            "type": "marker",
            "id": new_id,
            "caption": f"MARKER-{new_id}",
            "jump_id": None,
            "is_start": False,
            "align": "左上",
            "x": sp.x(),
            "y": sp.y(),
            "width": 32,
            "height": 32,
            # z は後で必要なら指定。ここでは 0 にしておく
            "z": 0,
        }

        # MarkerItem インスタンスを生成してシーンに追加
        item = MarkerItem(d, text_color=self.text_color)
        self.scene.addItem(item)
        item.setZValue(d["z"])
        self.data.setdefault("items", []).append(d)

        # 追加直後は編集モードでプロパティを設定できるようにする
        item.set_run_mode(False)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)

    # --- 履歴管理 ---
    def _push_history(self, p: Path):
        # 履歴を現在位置で切り詰めて追加
        if self.hidx < len(self.history) - 1:
            self.history = self.history[:self.hidx+1]
        self.history.append(p)
        self.hidx = len(self.history)-1
        self._update_nav()

    def _update_nav(self):
        # ナビゲーションボタンの有効・無効切替
        self.a_prev.setEnabled(self.hidx > 0)
        self.a_next.setEnabled(self.hidx < len(self.history)-1)

    def _go_home(self):
        # 履歴の先頭へ移動
        if self.history:
            self._load_path(self.history[0], ignore_geom=True)

    def _go_prev(self):
        """
        履歴を1つ戻る
        """
        if self.hidx > 0:
            self._load_path(
                self.history[self.hidx - 1],
                ignore_geom=True,
                from_history=True
            )
    def _go_next(self):
        """
        履歴を1つ進める
        """
        if self.hidx < len(self.history) - 1:
            self._load_path(
                self.history[self.hidx + 1],
                ignore_geom=True,
                from_history=True
            )


    def _load_path(self, p: Path, *, ignore_geom=False, from_history=False):
        """
        ファイルを読み込む。
        - from_history=False の場合 → 新規読み込みなので履歴に追加し、hidx を末尾にセット
        - from_history=True の場合 → 履歴移動なので履歴には追加せず、hidx を history.index(p) にセット
        """
        # ウィンドウジオメトリを保持するかどうか
        self._ignore_window_geom = ignore_geom
        # 読み込む JSON ファイルのパスをセット
        self.json_path = p

        if from_history:
            # 履歴移動：渡されたパスの index を hidx にセット（履歴は変更しない）
            self.hidx = self.history.index(p)
        else:
            # 新規読み込み：履歴に追加し、hidx を履歴末尾に設定
            self._push_history(p)

        # 実際の JSON 読み込み処理を実行
        self._load()
        # ジオメトリ保持フラグをリセット
        self._ignore_window_geom = ignore_geom
        # 読み込み後は必ず編集モードを解除
        self._set_mode(edit=False)
        # PREV/NEXT ボタンの有効・無効状態を更新
        self._update_nav()


    # --- モード切替（編集⇔実行） ---
    def _set_mode(self, *, edit: bool):
        """
        全CanvasItemの編集可否切替。
        edit=True: 移動・リサイズ可、False: 固定
        """

        #-----------------------
        # 呼び出し元のスタックトレースを取得
        #trace_this("edit")

        #-----------------------
        
        self.a_edit.blockSignals(True)
        self.a_run.blockSignals(True)
        self.a_edit.setChecked(edit)
        self.a_run.setChecked(not edit)
        self.a_edit.blockSignals(False)
        self.a_run.blockSignals(False)

        movable_flag    = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        selectable_flag = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        focusable_flag  = QGraphicsItem.GraphicsItemFlag.ItemIsFocusable

        for it in self.scene.items():
            # 保存対象（.d, set_run_mode を持つ）以外はスキップ
            if not isinstance(it, (CanvasItem, VideoItem)):
                continue

            # 実行モード切替
            it.set_run_mode(not edit)

            it.setFlag(movable_flag, edit)
            it.setFlag(selectable_flag, edit)
            it.setFlag(focusable_flag, edit)

            # リサイズグリップ表示切替
            if isinstance(it, CanvasItem):
                it.grip.setVisible(edit)
            elif isinstance(it, VideoItem):
                it.video_resize_dots.setVisible(edit)

        self.view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag if not edit
            else QGraphicsView.DragMode.RubberBandDrag
        )

    # --- データ読み込み ---
    
    def _load(self, on_finished=None):
        self._show_loading(True)
        self._on_load_finished = on_finished  # ← 後で呼ぶ
        QTimer.singleShot(50, self._do_load_actual)

    def _show_loading(self, show: bool):
        self.loading_label.setGeometry(self.rect())
        self.loading_label.setVisible(show)
        self.loading_label.raise_()


    def _do_load_actual(self):
        """実際のロード処理（マイグレーション付き）"""
        # ロード中フラグを設定してスナップを無効化
        self._loading_in_progress = True
        
        # ウォーターモードのcleanupと維持
        was_water_enabled = False
        try:
            was_water_enabled = self.a_water.isChecked()
        except Exception:
            was_water_enabled = False

        try:
            self.view.clear_water_effect()
        except Exception as e:
            warn(f"[WATER] clear_water_effect failed: {e}")
        
        # 既存アイテムを全削除
        for it in list(self.scene.items()):
            self._remove_item(it)

        # 背景画像付きの空のプロジェクトを読み込むとクラッシュする件の仮の対策
        self.scene.setSceneRect(QRectF(0, 0, 1, 1)) 
        
        # 背景削除
        self.data.pop("background", None)
        self.bg_pixmap = None
        self.scene.setBackgroundBrush(QBrush())
        
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.scene.clear()
        
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
                
            # ===== マイグレーション処理を追加 =====
            fileinfo = self.data.get("fileinfo", {})
            version = fileinfo.get("version", "1.0")
            
            if version == "1.0":
                warn(f"[LOAD] Migrating project from version {version} to 1.1")
                items = self.data.get("items", [])
                migrated_items = []
                
                for item in items:
                    migrated_item = migrate_item_to_v1_1(item)
                    
                    # 画像情報を補完
                    if migrated_item.get("image_embedded") and migrated_item.get("image_embedded_data"):
                        info = extract_image_info_from_base64(
                            migrated_item["image_embedded_data"],
                            migrated_item.get("image_format")
                        )
                        migrated_item.update(info)
                    
                    migrated_items.append(migrated_item)
                
                self.data["items"] = migrated_items
                # バージョンは保存時に1.1に更新される
                warn(f"[LOAD] Migration completed for {len(migrated_items)} items")
            # =====================================
                
        except Exception as e:
            warn(f"LOAD failed: {e}")
            QMessageBox.critical(self, "Error", str(e))
            self._loading_in_progress = False
            return
            
        items = self.data.get("items", [])
        if not isinstance(items, list):
            warn(f"[LOAD] 'items' が配列ではありません: {type(items).__name__}")
            self._loading_in_progress = False
            return
            
        # --- 相対パス補完用ベースディレクトリを決定 ---
        base_dir = Path(
            self.data.get("fileinfo", {}).get("path", self.json_path.parent)
        )
        base_dir = base_dir.expanduser().resolve()

        if len(items) == 0:
            self._show_loading(False)
            # 仮のシーン矩形（Qtの描画クラッシュ回避）
            if self.scene.sceneRect().isEmpty():
                warn("_do_load_actual reset setSceneRect")
                self.scene.setSceneRect(QRectF(0, 0, 1, 1))
            self._loading_in_progress = False
            if callable(getattr(self, "_on_load_finished", None)):
                self._on_load_finished()
                self._on_load_finished = None
            return
           
        # アイテム復元
        for d in self.data.get("items", []):
            
            # 相対パス補完
            for k in ("path", "workdir"):
                v = d.get(k)
                if isinstance(v, str) and v:
                    if v.startswith("http://") or v.startswith("https://"):
                        continue
                    if not os.path.isabs(v):
                        d[k] = str((base_dir / v).resolve())
            
            cls = self._get_item_class_by_type(d.get("type", ""))
            if not cls:
                warn(f"[LOAD] Unknown item type: {d.get('type')}")
                continue

            # ---- コンストラクタの引数を動的に組み立てる ----
            kwargs = {}
            sig = inspect.signature(cls.__init__).parameters
            if "win" in sig:
                kwargs["win"] = self
            if "text_color" in sig:
                kwargs["text_color"] = self.text_color

            try:
                # MarkerItem と GroupItem は win を受け取らないため、text_color のみ指定する
                if cls is MarkerItem:
                    it = cls(d, text_color=self.text_color)
                elif cls.__name__ == 'GroupItem':  # GroupItem対応
                    from DPyL_group import GroupItem
                    it = GroupItem(d, text_color=self.text_color)
                else:
                    it = cls(d, **kwargs)                
            except Exception as e:
                warn(f"[LOAD] {cls.__name__} create failed: {e}")
                continue

            it.setZValue(d.get("z", 0))
            self.scene.addItem(it)
            
            # JSONの座標をそのまま使用（シフト処理なし）
            x, y = d.get("x", 0), d.get("y", 0)
            it.setPos(x, y)
            warn(f"[LOAD] Restored {it.__class__.__name__} at ({x}, {y})")
            
            # MarkerItem は初期配置時にグリップをシーンに追加する必要があるため
            if isinstance(it, MarkerItem) and it.grip.scene() is None:
                self.scene.addItem(it.grip)
                
            # GroupItem も同様にグリップをシーンに追加
            if hasattr(it, '__class__') and it.__class__.__name__ == 'GroupItem' and it.grip.scene() is None:
                self.scene.addItem(it.grip)

            # VideoItem はリサイズグリップをシーンに載せる
            from DPyL_video import VideoItem
            if isinstance(it, VideoItem) and it.video_resize_dots.scene() is None:
                self.scene.addItem(it.video_resize_dots)

        # ロードフラグをクリア
        self._loading_in_progress = False

        # ウィンドウジオメトリ復元
        if not self._ignore_window_geom and (geo := self.data.get("window_geom")):
            try:
                self.restoreGeometry(base64.b64decode(geo))
            except Exception as e:
                warn(f"Geometry restore failed: {e}")

        self._apply_scene_padding()
        
        # GroupItem の子アイテム関係を復元（少し遅延させて確実に）
        QTimer.singleShot(100, self._restore_group_relationships)
        
        self._scroll_to_start_marker()
        self._apply_background()

        self._show_loading(False)

        if callable(getattr(self, "_on_load_finished", None)):
            self._on_load_finished()
            self._on_load_finished = None
            
        # ウォーターモード復元    
        try:
            if was_water_enabled:
                self.a_water.setChecked(True)
                self.view.toggle_water_effect(True)
        except Exception as e:
            warn(f"[WATER] reload toggle failed: {e}")

    def _restore_group_relationships(self):
        """
        ロード完了後にGroupItemの子アイテム関係を復元
        """
        try:
            from DPyL_group import GroupItem
            
            for it in self.scene.items():
                if hasattr(it, '__class__') and it.__class__.__name__ == 'GroupItem':
                    it.restore_child_items(self.scene)
                    warn(f"[LOAD] Restored group relationships for {it.d.get('caption', 'unnamed group')}")
                    # バウンディングボックスは通常更新不要（ロード時は既存の位置・サイズを保持）
                    # 必要に応じて有効化: it._update_bounds()
        except Exception as e:
            warn(f"[LOAD] Group relationship restoration failed: {e}")
       
    def _apply_scene_padding(self, margin: int = 64):
        """シーン全体のバウンディングボックスを計算し中央寄せ"""
        #items = [i for i in self.scene.items() if my_has_attr(i, "d")]
        items = [i for i in self.scene.items() if isinstance(i, (CanvasItem, VideoItem))]
        if not items:
            return

        bounds = items[0].sceneBoundingRect()
        for it in items[1:]:
            bounds = bounds.united(it.sceneBoundingRect())

        bounds.adjust(-margin, -margin, margin, margin)
        self.scene.setSceneRect(bounds)


    # --- JSONプロジェクト切替用 ---
    def _load_json(self, path: Path):
        self._ignore_window_geom = True
        self.json_path = Path(path).expanduser().resolve()
        self.setWindowTitle(f"desktopPyLauncher - {self.json_path.name}")
        self._push_history(self.json_path)

        # 明示的にモードを一時保存し、ロード後に復元
        def after_load():
            self._ignore_window_geom = False
        self._load(on_finished=after_load)


    def _save(self, *, auto=False):
        """プロジェクトファイルの保存（version 1.1）"""
        # 保存時に座標系を正規化
        items_list = [it for it in self.scene.items() if isinstance(it, (CanvasItem, VideoItem))]
        
        if items_list:
            # 1. 現在の座標を記録
            current_positions = [(it, it.pos().x(), it.pos().y()) for it in items_list]
            
            # 2. 最小x, yを見つける
            min_x = min(x for _, x, _ in current_positions)
            min_y = min(y for _, _, y in current_positions)
            
            # 3. 正規化が必要な場合（負の座標がある場合）のみ処理
            if min_x < 0 or min_y < 0:
                warn(f"[SAVE] Normalizing coordinates (min_x={min_x}, min_y={min_y})")
                
                # オフセットを計算（最小座標を0にする）
                dx = -min_x if min_x < 0 else 0
                dy = -min_y if min_y < 0 else 0
                
                # 4. 全アイテムを一律にシフト
                for it, old_x, old_y in current_positions:
                    new_x = old_x + dx
                    new_y = old_y + dy
                    it.setPos(new_x, new_y)
            else:
                warn(f"[SAVE] No coordinate normalization needed (min_x={min_x}, min_y={min_y})")
        
        # ===== バージョンを1.1に更新 =====
        if "fileinfo" not in self.data:
            self.data["fileinfo"] = {}
        
        self.data["fileinfo"]["version"] = "1.1"
        self.data["fileinfo"]["name"] = "desktopPyLauncher.py"
        self.data["fileinfo"]["info"] = "project data file"
        # ================================
        
        # 5. シフト後の座標をJSONに保存
        for it in self.scene.items():
            if not isinstance(it, (CanvasItem, VideoItem)):
                continue
            
            pos = it.pos()
            it.d["x"], it.d["y"] = pos.x(), pos.y()
            it.d["z"] = it.zValue()

            # === GroupItem の特別処理を追加 ===
            if isinstance(it, GroupItem):
                # 子アイテムIDリストを保存データに反映
                it.d["child_item_ids"] = it.child_item_ids.copy()
            # =====================================

            if isinstance(it, VideoItem):
                try:
                    if hasattr(it, "audio"):
                        it.d["muted"] = it.audio.isMuted()
                except Exception as e:
                    warn(f"[WARN] muted状態の取得に失敗: {e}")

        # ウィンドウ位置を保存
        self.data["window_geom"] = base64.b64encode(self.saveGeometry()).decode("ascii")
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            if not auto:
                show_save_notification(self)
        except Exception as e:
            show_error_notification(f"保存エラー: {str(e)}", self)
            
    # ==============================================================
    #  export
    # ==============================================================
    def _export_html(self):
        """
        現在のプロジェクトをHTMLファイルとしてエクスポート
        """
        try:
            # テンプレートファイルを読み込み
            template_path = Path(__file__).parent / "template" / "template.html"
            if not template_path.exists():
                show_error_notification(f"テンプレートファイルが見つかりません: {template_path}", self)

                return
                
            with open(template_path, "r", encoding="utf-8") as f:
                template_html = f.read()
            
            # データをコピーしてローカルパスを削除
            export_data = json.loads(json.dumps(self.data))  # ディープコピー
            
            def escape_windows_path(path_str):
                """Windowsパスのバックスラッシュをエスケープ"""
                if path_str and isinstance(path_str, str):
                    return path_str.replace('\\', '\\\\')
                return path_str
            
            for item in export_data.get("items", []):
                # embedデータがあるかチェック
                has_embed = item.get("icon_embed") or item.get("embed")
                
                # pathの処理
                path = item.get("path", "")
                if path:
                    if path.startswith(("http://", "https://")):
                        # URLは保持（エスケープして）
                        item["path"] = escape_windows_path(path)
                    elif has_embed:
                        # embedがある場合はパスをマスクして保持
                        item["path"] = "--truncated_by_security_reason--"
                    else:
                        # ローカルパスでembedがない場合は削除
                        item.pop("path", None)
                
                # workdirを削除
                item.pop("workdir", None)
                
                # iconパスの処理
                icon = item.get("icon", "")
                if icon:
                    if icon.startswith(("http://", "https://")) or icon.endswith((".dll", ".exe")):
                        # URL、システムファイルは保持
                        item["icon"] = escape_windows_path(icon)
                    elif has_embed:
                        # embedがある場合はアイコンパスをマスク
                        item["icon"] = "--truncated_by_security_reason--"
                    else:
                        # ローカルファイルでembedがない場合は削除
                        item.pop("icon", None)
            
            # 背景パスの処理（embedはないのでローカルパスは削除）
            if "background" in export_data and "path" in export_data["background"]:
                bg_path = export_data["background"]["path"]
                if bg_path and not bg_path.startswith(("http://", "https://")):
                    export_data["background"].pop("path", None)
                else:
                    export_data["background"]["path"] = escape_windows_path(bg_path)
            
            # JSONに変換
            json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
            
            # テンプレートの置換マーカーを実際のJSONデータに置き換え
            html_content = template_html.replace('<!-- title -->', self.json_path.stem)
            html_content = html_content.replace('<!-- embedded_json_data//-->', json_str)
            
            # 保存先ファイルダイアログ
            default_name = self.json_path.stem + ".html"
            save_path, _ = QFileDialog.getSaveFileName(
                self, 
                "HTMLファイルとして保存", 
                str(self.json_path.parent / default_name),
                "HTML files (*.html);;All files (*)"
            )
            
            if save_path:
                # HTMLファイルとして保存
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                
                show_export_html_notification(Path(save_path).name, self)
                
        except Exception as e:
            show_export_error_notification(str(e), self)
    #  private helpers
    # ==============================================================
    def _scroll_to_start_marker(self):
        """
        is_start==True の Marker があれば align に従ってビューをジャンプ
        """
        try:
            start_markers = sorted(
                (it for it in self.scene.items()
                 if isinstance(it, MarkerItem) and it.d.get("is_start")),
                key=lambda m: int(m.d.get("id", 0))
            )
            if not start_markers:
                warn("[SCROLL] 開始地点のマーカーが見つかりません")
                return

            m   = start_markers[0]
            sp  = m.scenePos()
            
            # 画面上での実際の描画領域を取得（キャプション分も含む）
            bounding_rect = m.boundingRect()
            w = bounding_rect.width()
            h = bounding_rect.height()
            aln = m.d.get("align", "左上")
            
            warn(f"[SCROLL] マーカーID {m.d.get('id')}: 位置({sp.x()}, {sp.y()}), 実際のサイズ{w}x{h}, 配置: {aln}")

            if aln == "中央":
                # -- ビューポート中央寄せ -----------------
                # マーカーの中心座標を計算（実際の描画領域の中心）
                marker_center_x = sp.x() + w/2
                marker_center_y = sp.y() + h/2
                warn(f"[SCROLL] 中央配置: マーカー中心座標 ({marker_center_x}, {marker_center_y})")
                
                # centerOnを実行
                self.view.centerOn(marker_center_x, marker_center_y)
                
                # 少し遅延させてもう一度確実に実行 (今は必要ない)
                #QTimer.singleShot(50, lambda: self.view.centerOn(marker_center_x, marker_center_y))
                
            else:
                # -- 左上寄せ ---------------------------
                # ビューポート寸法をシーン座標へ変換（ズーム倍率対応）
                transform = self.view.transform()
                vp_w = self.view.viewport().width()  / transform.m11()
                vp_h = self.view.viewport().height() / transform.m22()
                
                # マーカーの左上をビューポートの左上に配置するため、
                # ビューポートの中央座標をマーカーの左上からオフセット
                target_x = sp.x() + vp_w/2
                target_y = sp.y() + vp_h/2
                
                warn(f"[SCROLL] 左上配置: 目標座標 ({target_x}, {target_y}), ビューポート {vp_w}x{vp_h}")
                self.view.centerOn(target_x, target_y)
                
        except Exception as e:
            warn(f"[SCROLL] 開始地点へのスクロールに失敗: {e}")
            import traceback
            traceback.print_exc()
    def _get_next_group_id(self):
        """新しいグループIDを取得"""
        existing_ids = []
        for item in self.scene.items():
            if isinstance(item, GroupItem):
                try:
                    existing_ids.append(int(item.d.get("id", 0)))
                except (TypeError, ValueError):
                    continue
        
        if existing_ids:
            return max(existing_ids) + 100
        else:
            return 20000  # グループIDは20000から開始

    def _group_selected_items(self):
        """選択されたアイテムをグループ化"""
        selected_items = [item for item in self.scene.selectedItems() 
                         if isinstance(item, (CanvasItem, VideoItem)) and 
                         not isinstance(item, GroupItem)]
        
        if len(selected_items) < 2:
            QMessageBox.information(self, "グループ化", "グループ化するには2つ以上のアイテムを選択してください。")
            return
            
        # GroupItem作成
        group_id = self._get_next_group_id()
        d = {
            "type": "group",
            "id": group_id,
            "caption": f"GROUP-{group_id}",
            "show_caption": True,
            "x": 0, "y": 0, "width": 100, "height": 100,
            "z": -1000,  # 最背面
            "child_item_ids": []
        }
        
        group_item = GroupItem(d, text_color=self.text_color)
        
        # 選択されたアイテムをグループに追加
        for item in selected_items:
            group_item.add_item(item)
            item.setSelected(False)  # 選択解除
            
        # シーンに追加
        self.scene.addItem(group_item)
        self.data["items"].append(d)
        
        # 最背面に設定
        group_item.setZValue(-1000)
        
        # 新しいグループを選択
        group_item.setSelected(True)
        
        print(f"グループ化完了: {len(selected_items)}個のアイテムを含むグループを作成しました")

    def _ungroup_selected_items(self):
        """選択されたGroupItemを解除（削除）"""
        selected_groups = [item for item in self.scene.selectedItems() 
                          if isinstance(item, GroupItem)]
        
        if not selected_groups:
            QMessageBox.information(self, "グループ化の解除", "解除するグループが選択されていません。")
            return
            
        ungroup_count = 0
        for group_item in selected_groups:
            # グループ内のアイテムを選択状態にする
            for child_item in group_item.child_items:
                if child_item.scene():
                    child_item.setSelected(True)
                    
            # グループアイテムを削除
            self._remove_item(group_item)
            ungroup_count += 1
            
        print(f"グループ化解除完了: {ungroup_count}個のグループを解除しました")

    def _load_project_at_position(self, scene_pos):
        """
        指定した位置にプロジェクトを読み込む
        - 現在のビューポートの左上を基準として相対配置
        - 読み込んだアイテムをグループ化
        - グループのキャプションをファイル名にする
        """
        # ファイル選択ダイアログ
        path, _ = QFileDialog.getOpenFileName(
            self, "読み込むプロジェクトを選択", "", "JSONファイル (*.json)"
        )
        if not path:
            return
        
        try:
            # JSONファイルを読み込み
            with open(path, "r", encoding="utf-8") as f:
                project_data = json.load(f)
            
            items_data = project_data.get("items", [])
            if not items_data:
                QMessageBox.information(self, "読み込み", "プロジェクトにアイテムがありません。")
                return
            
            # 読み込んだアイテムの最小座標を計算
            min_x = min((item.get("x", 0) for item in items_data), default=0)
            min_y = min((item.get("y", 0) for item in items_data), default=0)
            
            # 現在のビューポートの左上座標を取得
            viewport_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
            target_x = viewport_rect.left()
            target_y = viewport_rect.top()
            
            # オフセットを計算（ビューポートの左上を基準とする）
            offset_x = target_x - min_x
            offset_y = target_y - min_y
            
            warn(f"[LOAD_AT_POS] 基準座標: ({target_x}, {target_y}), オフセット: ({offset_x}, {offset_y})")
            
            # アイテムを作成し、相対配置
            loaded_items = []
            for item_data in items_data:
                # データをコピーして座標を調整
                d = item_data.copy()
                d["x"] = item_data.get("x", 0) + offset_x
                d["y"] = item_data.get("y", 0) + offset_y
                
                # アイテムクラスを取得
                cls = self._get_item_class_by_type(d.get("type", ""))
                if not cls:
                    warn(f"[LOAD_AT_POS] Unknown item type: {d.get('type')}")
                    continue
                
                # アイテムを作成
                kwargs = {}
                sig = inspect.signature(cls.__init__).parameters
                if "win" in sig:
                    kwargs["win"] = self
                if "text_color" in sig:
                    kwargs["text_color"] = self.text_color
                
                try:
                    if cls is MarkerItem:
                        item = cls(d, text_color=self.text_color)
                    elif cls.__name__ == 'GroupItem':
                        from DPyL_group import GroupItem
                        item = GroupItem(d, text_color=self.text_color)
                    else:
                        item = cls(d, **kwargs)
                    
                    # シーンに追加
                    item.setZValue(d.get("z", 0))
                    self.scene.addItem(item)
                    self.data["items"].append(d)
                    loaded_items.append(item)
                    
                    # グリップの追加処理（必要に応じて）
                    if isinstance(item, MarkerItem) and item.grip.scene() is None:
                        self.scene.addItem(item.grip)
                    elif hasattr(item, '__class__') and item.__class__.__name__ == 'GroupItem' and item.grip.scene() is None:
                        self.scene.addItem(item.grip)
                    elif isinstance(item, VideoItem) and item.video_resize_dots.scene() is None:
                        self.scene.addItem(item.video_resize_dots)
                        
                except Exception as e:
                    warn(f"[LOAD_AT_POS] {cls.__name__} create failed: {e}")
                    continue
            
            # 読み込んだアイテムをグループ化（複数の場合）
            if len(loaded_items) > 1:
                # グループ作成
                group_id = self._get_next_group_id()
                project_name = Path(path).stem  # ファイル名（拡張子なし）
                
                # グループの初期位置・サイズを計算
                if loaded_items:
                    # 読み込んだアイテムのバウンディングボックスを計算
                    all_rects = [item.sceneBoundingRect() for item in loaded_items]
                    union_rect = all_rects[0]
                    for rect in all_rects[1:]:
                        union_rect = union_rect.united(rect)
                    
                    group_x = union_rect.left()
                    group_y = union_rect.top()
                    group_w = max(200, union_rect.width())
                    group_h = max(100, union_rect.height())
                else:
                    group_x = target_x
                    group_y = target_y
                    group_w = 200
                    group_h = 100
                
                group_data = {
                    "type": "group",
                    "id": group_id,
                    "caption": project_name,  # ファイル名をキャプションに設定
                    "show_caption": True,
                    "x": group_x, "y": group_y, 
                    "width": group_w, "height": group_h,
                    "z": -1000,  # 最背面
                    "child_item_ids": []
                }
                
                from DPyL_group import GroupItem
                group_item = GroupItem(group_data, text_color=self.text_color)
                
                # 読み込んだアイテムをグループに追加
                for item in loaded_items:
                    group_item.add_item(item)
                
                # シーンに追加
                self.scene.addItem(group_item)
                self.data["items"].append(group_data)
                group_item.setZValue(-1000)
                
                # グループを選択状態にする
                for item in self.scene.selectedItems():
                    item.setSelected(False)
                group_item.setSelected(True)
                
                # 編集モードに切り替え
                self._set_mode(edit=True)
                
                show_project_load_notification(project_name, len(loaded_items), self)

            elif len(loaded_items) == 1:
                # 単一アイテムの場合はそのまま選択
                for item in self.scene.selectedItems():
                    item.setSelected(False)
                loaded_items[0].setSelected(True)
                self._set_mode(edit=True)
                
                show_project_load_notification("", 1, self)
            else:
                show_project_load_notification("", 0, self)
            
        except Exception as e:
            show_error_notification(f"プロジェクトの読み込みに失敗しました: {str(e)}", self)
            import traceback
            traceback.print_exc()
# ==============================================================
#  App helper - 補助関数
# ==============================================================
def apply_theme(app: QApplication):
    # ダークテーマ自動設定
    if app.palette().color(QPalette.ColorRole.WindowText).lightness() <= 128:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        txt = QColor(255, 255, 255)
        for r in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                  QPalette.ColorRole.ButtonText):
            pal.setColor(r, txt)
        pal.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        pal.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        app.setPalette(pal)

# ==============================================================
#  main - アプリ起動エントリポイント
# ==============================================================
class SafeApp(QApplication):
    """
    例外をログに残してイベントを 1 回だけ処理する
    """

    DEBUG_NOTIFY = False

    def notify(self, obj, ev):
        if self.DEBUG_NOTIFY:
            cls_name = "<none>"
            try:
                if obj is None:
                    cls_name = "<None>"
                elif isinstance(obj, QObject):
                    cls_name = obj.metaObject().className()
                else:
                    cls_name = obj.__class__.__name__
            except Exception as e:
                cls_name = f"<unresolved:{e.__class__.__name__}>"

            print(f"[notify] obj={cls_name:<28} ev={ev.__class__.__name__}")

        try:
            return super().notify(obj, ev)
        except Exception as e:
            warn(f"[SafeApp] {type(e).__name__}: {e}")
            return True   # 再ディスパッチは禁止

def _global_excepthook(exc_type, exc, tb):
    warn(f"[Uncaught] {exc_type.__name__}: {exc}")
    traceback.print_exception(exc_type, exc, tb)

sys.excepthook = _global_excepthook    # 最後の盾

# エラーがあっても続行します
def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "-create":
        tmpl = {"fileinfo": {"name": __file__, "info": "project data file", "version": "1.0"},
                "items": []}
        tgt = Path(sys.argv[2]).expanduser().resolve()
        if tgt.exists():
            print("Already exists!"); sys.exit(1)
        tgt.write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Created {tgt}"); sys.exit(0)

    # ② 通常起動
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("default.json")

    app = SafeApp(sys.argv)
    apply_theme(app)
    MainWindow(json_path).show()
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    finally:
        dump_missing_attrs()
r"""
# ==============================================================
#  main - アプリ起動エントリポイント
# ==============================================================
# 通常

# エラーで落としたいときはこっち使います
def main():
    # コマンドライン引数 -create で空jsonテンプレ生成
    if len(sys.argv) >= 3 and sys.argv[1] == "-create":
        tmpl = {"fileinfo": {"name": Path(__file__).name,
                             "info": "project data file", "version": "1.0"},
                "items": []}
        tgt = Path(sys.argv[2]).expanduser().resolve()
        if tgt.exists():
            print("Already exists!"); sys.exit(1)
        with open(tgt, "w", encoding="utf-8") as f:
            json.dump(tmpl, f, ensure_ascii=False, indent=2)
        print(f"Created {tgt}"); sys.exit(0)

    # デフォルトjson or 引数受け取り
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("default.json")
    app = QApplication(sys.argv)
    apply_theme(app)
    MainWindow(json_path).show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
"""
