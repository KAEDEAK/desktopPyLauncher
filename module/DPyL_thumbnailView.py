# -*- coding: utf-8 -*-
"""
DPyL_thumbnailView.py - 正式版サムネイルビューアイテム
データ永続化問題を解決した最終版
"""

from __future__ import annotations
import os
import sys
from typing import Any, Callable

# libpng警告を抑制
os.environ['QT_IMAGEIO_MAXALLOC'] = '268435456'  # 256MB
os.environ['QT_LOGGING_RULES'] = 'qt.gui.imageio.debug=false'

# 親ディレクトリからlocalizationをインポート
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from localization import _

from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QPoint, QThread, QObject
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent
from PySide6.QtWidgets import (
    QGraphicsProxyWidget, QWidget, QVBoxLayout, QLabel, 
    QPushButton, QLineEdit, QFileDialog, QDialog, QHBoxLayout,
    QSpinBox, QComboBox, QGroupBox, QMessageBox, QMenu, QApplication
)

from .DPyL_classes import CanvasItem
from .DPyL_utils import warn, debug_print

# 確実にデバッグを表示するための関数（完全無効化）
def force_debug(msg):
    # メインスレッドブロッキング回避のため、すべてのログを無効化
    pass


class ThumbnailWorker(QObject):
    """サムネイル生成用のワーカークラス（QPixmap直接送信版）"""
    thumbnail_ready = Signal(str, object)  # image_path, QPixmap (converted in worker thread)
    finished = Signal()
    process_request = Signal(str, int)  # image_path, thumbnail_size - 単一ファイル処理用
    
    def __init__(self):
        super().__init__()
        self._should_stop = False
        self.pending_requests = []  # 処理待ちリクエスト
        self.is_processing = False  # 処理中フラグ
        
        # 内部シグナル接続
        self.process_request.connect(self.add_single_request)
        
    def generate_thumbnails(self, image_files, thumbnail_size):
        """サムネイルを順次生成（QImageを使用してスレッドセーフに）"""
        from PySide6.QtGui import QImage, QImageReader
        
        force_debug(f"ThumbnailWorker: Starting generation for {len(image_files)} images")
        
        for i, image_path in enumerate(image_files):
            if self._should_stop:
                force_debug("ThumbnailWorker: Stop requested, terminating")
                break
                
            try:
                # QImageReaderを使用してスレッドセーフに画像を読み込み
                reader = QImageReader(image_path)
                reader.setAutoTransform(True)  # EXIF回転情報を自動適用
                
                # 元画像を読み込み
                image = reader.read()
                
                if not image.isNull():
                    # QImageでリサイズ（スレッドセーフ）
                    scaled_image = image.scaled(
                        thumbnail_size - 2, 
                        thumbnail_size - 2, 
                        Qt.AspectRatioMode.KeepAspectRatio, 
                        Qt.TransformationMode.SmoothTransformation
                    )
                    
                    # ワーカースレッド内でQPixmapに変換してメインスレッドの負荷を軽減
                    from PySide6.QtGui import QPixmap
                    pixmap = QPixmap.fromImage(scaled_image)
                    
                    # メインスレッドにQPixmapを送信
                    if not self._should_stop:
                        self.thumbnail_ready.emit(image_path, pixmap)
                        
                        # 10枚ごとに進捗ログ（ログ量を削減）
                        if (i + 1) % 10 == 0:
                            force_debug(f"ThumbnailWorker: Generated {i+1}/{len(image_files)} thumbnails")
                        
                        # Windows環境での応答なし回避：大幅な待機時間で負荷軽減
                        import time
                        time.sleep(0.5)  # 500ms待機でWindows環境での応答なしを完全回避
                else:
                    # エラー画像の場合もシグナルを送信（Noneで）
                    if not self._should_stop:
                        self.thumbnail_ready.emit(image_path, None)
                        force_debug(f"ThumbnailWorker: Failed to load {os.path.basename(image_path)}")
                        
            except Exception as e:
                force_debug(f"ThumbnailWorker: Error processing {os.path.basename(image_path)}: {e}")
                if not self._should_stop:
                    self.thumbnail_ready.emit(image_path, None)
        
        force_debug("ThumbnailWorker: Generation completed")
        self.finished.emit()
    
    def stop(self):
        """ワーカーの停止要求"""
        force_debug("ThumbnailWorker: Stop requested")
        self._should_stop = True
    
    def add_single_request(self, image_path, thumbnail_size):
        """単一ファイルのサムネイル生成リクエストを追加"""
        self.pending_requests.append((image_path, thumbnail_size))
        force_debug(f"Added thumbnail request: {os.path.basename(image_path)} (queue size: {len(self.pending_requests)})")
        
        # 処理中でなければ開始
        if not self.is_processing:
            self.process_pending_requests()
    
    def process_pending_requests(self):
        """待機中のリクエストを順次処理"""
        if self.is_processing or not self.pending_requests or self._should_stop:
            return
        
        self.is_processing = True
        force_debug(f"Starting to process {len(self.pending_requests)} pending thumbnail requests")
        
        # 全ての待機中リクエストを処理
        while self.pending_requests and not self._should_stop:
            image_path, thumbnail_size = self.pending_requests.pop(0)
            self._generate_single_thumbnail(image_path, thumbnail_size)
        
        self.is_processing = False
        force_debug("Finished processing all pending thumbnail requests")
    
    def _generate_single_thumbnail(self, image_path, thumbnail_size):
        """単一ファイルのサムネイル生成"""
        from PySide6.QtGui import QImage, QImageReader, QPixmap
        
        try:
            force_debug(f"Generating thumbnail for: {os.path.basename(image_path)}")
            
            # QImageReaderを使用してスレッドセーフに画像を読み込み
            reader = QImageReader(image_path)
            reader.setAutoTransform(True)  # EXIF回転情報を自動適用
            
            # 元画像を読み込み
            image = reader.read()
            
            if not image.isNull():
                # QImageでリサイズ（スレッドセーフ）
                scaled_image = image.scaled(
                    thumbnail_size - 2, 
                    thumbnail_size - 2, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                
                # ワーカースレッド内でQPixmapに変換
                pixmap = QPixmap.fromImage(scaled_image)
                
                # メインスレッドにQPixmapを送信
                if not self._should_stop:
                    self.thumbnail_ready.emit(image_path, pixmap)
                    force_debug(f"Thumbnail generated and sent: {os.path.basename(image_path)}")
            else:
                # エラー画像の場合
                if not self._should_stop:
                    self.thumbnail_ready.emit(image_path, None)
                    force_debug(f"Failed to load image: {os.path.basename(image_path)}")
                    
        except Exception as e:
            force_debug(f"Error generating thumbnail for {os.path.basename(image_path)}: {e}")
            if not self._should_stop:
                self.thumbnail_ready.emit(image_path, None)
        
        # Windows環境での負荷軽減
        import time
        time.sleep(0.1)


class ClickableLabel(QLabel):
    """クリック・ダブルクリック・右クリック対応のQLabel"""
    clicked = Signal()
    double_clicked = Signal()
    right_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.click_timer = QTimer()
        self.click_timer.timeout.connect(self._single_click_timeout)
        self.click_timer.setSingleShot(True)
        self.pending_single_click = False
        
        # マウスイベントを確実にキャプチャするための設定
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        
        # QGraphicsProxyWidget内でのマウスイベント優先度を上げる
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        
    def mousePressEvent(self, event: QMouseEvent):
        force_debug(f"ClickableLabel mousePressEvent: button={event.button()}")
        if event.button() == Qt.MouseButton.LeftButton:
            # イベントの伝播を完全に停止
            event.accept()
            event.stopPropagation() if hasattr(event, 'stopPropagation') else None
            
            if self.click_timer.isActive():
                # ダブルクリック
                force_debug("Double click detected")
                self.click_timer.stop()
                self.pending_single_click = False
                self.double_clicked.emit()
            else:
                # シングルクリックの可能性
                force_debug("Single click detected, starting timer")
                self.pending_single_click = True
                self.click_timer.start(300)  # 300ms待機
            return  # イベント処理を完了
        elif event.button() == Qt.MouseButton.RightButton:
            # 右クリック処理
            force_debug("Right click detected")
            event.accept()
            event.stopPropagation() if hasattr(event, 'stopPropagation') else None
            self.right_clicked.emit()
            return
        else:
            super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        force_debug(f"ClickableLabel mouseReleaseEvent: button={event.button()}")
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            event.stopPropagation() if hasattr(event, 'stopPropagation') else None
            return  # イベント処理を完了
        elif event.button() == Qt.MouseButton.RightButton:
            event.accept()
            event.stopPropagation() if hasattr(event, 'stopPropagation') else None
            return
        else:
            super().mouseReleaseEvent(event)
    
    def _single_click_timeout(self):
        if self.pending_single_click:
            self.clicked.emit()
            self.pending_single_click = False


class ThumbnailDialog(QDialog):
    """サムネイル設定ダイアログ（拡張版）"""
    
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item  # ThumbnailViewItemインスタンスを保持
        self.setWindowTitle("Thumbnail Settings")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # ディレクトリパス設定グループ
        path_group = QGroupBox("Directory")
        path_layout = QVBoxLayout(path_group)
        
        self.path_edit = QLineEdit()
        self.path_edit.setText(self.item.d.get("directory_path", ""))
        path_layout.addWidget(QLabel("Directory Path:"))
        path_layout.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_directory)
        path_layout.addWidget(self.browse_btn)
        
        layout.addWidget(path_group)
        
        # 表示設定グループ
        display_group = QGroupBox("Display Settings")
        display_layout = QVBoxLayout(display_group)
        
        # サムネイルサイズ
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Thumbnail Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(64, 512)
        self.size_spin.setSingleStep(16)
        self.size_spin.setValue(self.item.d.get("thumbnail_size", 128))
        self.size_spin.setSuffix(" px")
        size_layout.addWidget(self.size_spin)
        size_layout.addStretch()
        display_layout.addLayout(size_layout)
        
        # マージン
        margin_layout = QHBoxLayout()
        margin_layout.addWidget(QLabel("Margin:"))
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 50)
        self.margin_spin.setValue(self.item.d.get("margin", 8))
        self.margin_spin.setSuffix(" px")
        margin_layout.addWidget(self.margin_spin)
        margin_layout.addStretch()
        display_layout.addLayout(margin_layout)
        
        layout.addWidget(display_group)
        
        # 連携設定グループ
        link_group = QGroupBox("Image Item Link")
        link_layout = QVBoxLayout(link_group)
        
        link_layout.addWidget(QLabel("Linked ImageItem:"))
        self.image_item_combo = QComboBox()
        self._populate_image_items()
        link_layout.addWidget(self.image_item_combo)
        
        layout.addWidget(link_group)
        
        # ボタン
        button_layout = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.save_and_accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)
    
    def browse_directory(self):
        current_path = self.path_edit.text() or os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory", current_path)
        if dir_path:
            self.path_edit.setText(dir_path)
    
    def _populate_image_items(self):
        """プロジェクト内のImageItemを検索してコンボボックスに追加"""
        self.image_item_combo.clear()
        self.image_item_combo.addItem("(None)", "")  # 空の選択肢
        
        try:
            # MainWindowのデータからImageItemを検索
            scene = self.item.scene()
            if scene and scene.views():
                main_window = scene.views()[0].window()
                if hasattr(main_window, 'data') and 'items' in main_window.data:
                    image_items = []
                    
                    for item_data in main_window.data['items']:
                        if item_data.get('type') == 'image':
                            # ImageItemのIDを取得
                            item_id = item_data.get("id", 0)
                            
                            # ImageItemのキャプションまたはパスを表示用テキストにする
                            display_text = item_data.get("caption", "")
                            if not display_text:
                                path = item_data.get("path", "")
                                if path:
                                    display_text = os.path.basename(path)
                                else:
                                    display_text = "Image Item"
                            
                            force_debug(f"Found ImageItem: ID={item_id}, text='{display_text}'")
                            image_items.append((item_id, display_text))
                    
                    # IDでソートして表示
                    image_items.sort(key=lambda x: x[0])
                    for item_id, display_text in image_items:
                        self.image_item_combo.addItem(f"{display_text} (ID: {item_id})", item_id)
            
            # 現在の選択値を設定
            current_id = self.item.d.get("linked_image_item_id", "")
            if current_id:
                # コンボボックスから該当するアイテムを探して選択
                for i in range(self.image_item_combo.count()):
                    if self.image_item_combo.itemData(i) == current_id:
                        self.image_item_combo.setCurrentIndex(i)
                        break
        except Exception as e:
            force_debug(f"Error populating image items: {e}")
    
    def save_and_accept(self):
        """設定を保存してダイアログを閉じる（拡張版）"""
        force_debug(f"=== Dialog save_and_accept ===")
        force_debug(f"BEFORE save - self.item.d: {self.item.d}")
        
        # 各設定を更新
        self.item.d["directory_path"] = self.path_edit.text()
        self.item.d["thumbnail_size"] = self.size_spin.value()
        self.item.d["margin"] = self.margin_spin.value()
        selected_id = self.image_item_combo.currentData() or ""
        self.item.d["linked_image_item_id"] = selected_id
        
        force_debug(f"Selected ImageItem ID: {selected_id}")
        force_debug(f"AFTER save - self.item.d: {self.item.d}")
        force_debug(f"=== Dialog accepting ===")
        self.accept()


class ThumbnailWidget(QWidget):
    """サムネイル表示ウィジェット"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        
        # マウスイベントを子ウィジェットで確実に処理するため
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, False)
        
        self.directory_path = ""
        self.thumbnail_size = 128
        self.margin = 8
        
        # リサイズ遅延用のタイマー
        self.resize_timer = QTimer()
        self.resize_timer.timeout.connect(self._on_resize_timeout)
        self.resize_timer.setSingleShot(True)
        
        # ドラッグスクロール用の変数
        self.drag_scrolling = False
        self.drag_start_pos = None
        self.drag_start_scroll_x = 0
        self.drag_start_scroll_y = 0
        
        # マルチスレッドサムネイル生成用の変数
        self.worker = None
        self.worker_thread = None
        self.thumbnail_labels = {}  # image_path -> ClickableLabel のマッピング
        
        # 1件ずつ処理では更新制御は不要（即座表示）
        
        # 1件ずつ処理用のタイマー（Windows環境対応）
        self.file_scan_timer = QTimer()
        self.file_scan_timer.timeout.connect(self._process_next_file)
        self.file_scan_timer.setSingleShot(True)
        
        # ディレクトリスキャン関連
        self.current_directory = ""
        self.file_iterator = None
        self.processed_files = []
        self.grid_position = 0  # 現在のグリッド位置
        self.grid_cols = 1     # グリッドの列数
        self.is_processing_files = False  # ファイル処理中フラグ
        
        # スクロールエリアを作成
        from PySide6.QtWidgets import QScrollArea, QGridLayout
        
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # サムネイル表示用のウィジェット
        self.thumbnail_container = QWidget()
        self.grid_layout = QGridLayout(self.thumbnail_container)
        self.grid_layout.setSpacing(self.margin)
        
        self.scroll_area.setWidget(self.thumbnail_container)
        
        # スクロールエリアにもドラッグスクロール機能を追加
        self.scroll_area.mousePressEvent = self._scroll_area_mouse_press
        self.scroll_area.mouseMoveEvent = self._scroll_area_mouse_move
        self.scroll_area.mouseReleaseEvent = self._scroll_area_mouse_release
        
        # メインレイアウト
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll_area)
        
        # ステータスラベル
        self.status_label = QLabel("ThumbnailView ∶∶ ドラッグ移動可能エリア")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("""
            color: white; 
            background-color: #404040; 
            font-size: 10px; 
            border: 1px solid #666; 
            padding: 2px;
            border-radius: 3px;
        """)
        self.status_label.setMaximumHeight(30)
        self.status_label.setToolTip("この帯部分をドラッグしてアイテムを移動できます")
        main_layout.addWidget(self.status_label)
    
    def __del__(self):
        """デストラクタ - ワーカースレッドの安全な終了"""
        self._stop_worker_thread()
    
    def _stop_worker_thread(self):
        """ワーカースレッドとタイマーを安全に停止"""
        # UIタイマーを停止
        if hasattr(self, 'ui_update_timer'):
            self.ui_update_timer.stop()
        
        if self.worker and self.worker_thread:
            force_debug("ThumbnailWidget: Stopping worker thread")
            self.worker.stop()
            
            # スレッドの終了を待つ（最大3秒）
            if self.worker_thread.isRunning():
                if not self.worker_thread.wait(3000):
                    force_debug("ThumbnailWidget: Force terminating worker thread")
                    self.worker_thread.terminate()
                    self.worker_thread.wait(1000)
            
            self.worker = None
            self.worker_thread = None
            force_debug("ThumbnailWidget: Worker thread stopped")
    
    
    
    def resizeEvent(self, event):
        """リサイズイベントを検出してタイマーで遅延実行"""
        super().resizeEvent(event)
        
        # 既存のタイマーをリセット
        self.resize_timer.stop()
        
        # リサイズが完了してから300ms後に再計算を実行
        self.resize_timer.start(300)
        
        force_debug(f"ThumbnailWidget resize detected: {event.size()}")
    
    def _on_resize_timeout(self):
        """リサイズ完了後のサムネイル再計算"""
        # ファイル処理中はリサイズによる再生成を無効化
        if self.is_processing_files:
            force_debug("Resize timeout - skipping recalculation during file processing")
            return
            
        force_debug("Resize timeout - recalculating thumbnails")
        self._update_thumbnails()
    
    def wheelEvent(self, event: QWheelEvent):
        """ホイールイベントをスクロールエリアに転送"""
        force_debug(f"ThumbnailWidget wheelEvent: delta={event.angleDelta()}")
        
        # イベントを受け入れてスクロールエリアに処理させる
        if hasattr(self, 'scroll_area') and self.scroll_area:
            # スクロールエリアのビューポートにイベントを転送
            self.scroll_area.wheelEvent(event)
            event.accept()
            force_debug("Wheel event forwarded to scroll area")
        else:
            super().wheelEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        """ドラッグスクロール開始の検出"""
        if event.button() == Qt.MouseButton.MiddleButton:
            # 中ボタンでドラッグスクロール開始
            self._start_drag_scroll(event)
        elif event.button() == Qt.MouseButton.LeftButton:
            # 左ボタン + Ctrlキーでもドラッグスクロール
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._start_drag_scroll(event)
            else:
                # 通常の左クリックの場合、クリック位置をチェック
                click_pos = event.pos()
                clicked_thumbnail = None
                
                # グリッドレイアウト内のサムネイルをチェック
                for i in range(self.grid_layout.count()):
                    item = self.grid_layout.itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        if hasattr(widget, 'image_path'):
                            widget_rect = widget.geometry()
                            if widget_rect.contains(click_pos):
                                clicked_thumbnail = widget
                                break
                
                if not clicked_thumbnail:
                    # サムネイルが見つからない場合（隙間部分）はドラッグスクロール開始
                    force_debug("Left click in empty space - starting drag scroll")
                    self._start_drag_scroll(event)
                else:
                    # サムネイル上の場合は通常処理
                    super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """ドラッグスクロール中の処理"""
        if self.drag_scrolling:
            self._update_drag_scroll(event)
        else:
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """ドラッグスクロール終了"""
        if self.drag_scrolling:
            self._end_drag_scroll()
        else:    
            super().mouseReleaseEvent(event)
    
    def _start_drag_scroll(self, event: QMouseEvent):
        """ドラッグスクロール開始"""
        force_debug("Starting drag scroll")
        self.drag_scrolling = True
        self.drag_start_pos = event.pos()
        
        # 現在のスクロール位置を記録
        if hasattr(self, 'scroll_area') and self.scroll_area:
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            self.drag_start_scroll_x = h_bar.value() if h_bar else 0
            self.drag_start_scroll_y = v_bar.value() if v_bar else 0
        
        # カーソルを変更
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.grabMouse()
    
    def _update_drag_scroll(self, event: QMouseEvent):
        """ドラッグスクロール更新"""
        if not self.drag_start_pos or not hasattr(self, 'scroll_area') or not self.scroll_area:
            return
        
        # マウスの移動量を計算
        delta = event.pos() - self.drag_start_pos
        
        # スクロールバーを移動（マウス移動と逆方向）
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        
        if h_bar:
            new_x = self.drag_start_scroll_x - delta.x()
            h_bar.setValue(int(new_x))
        
        if v_bar:
            new_y = self.drag_start_scroll_y - delta.y()
            v_bar.setValue(int(new_y))
    
    def _end_drag_scroll(self):
        """ドラッグスクロール終了"""
        force_debug("Ending drag scroll")
        self.drag_scrolling = False
        self.drag_start_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.releaseMouse()
    
    def _scroll_area_mouse_press(self, event: QMouseEvent):
        """スクロールエリアのマウスプレスイベント"""
        force_debug(f"Scroll area mouse press: {event.button()}")
        if event.button() == Qt.MouseButton.MiddleButton:
            # 中ボタンでドラッグスクロール開始
            self._start_drag_scroll(event)
        elif event.button() == Qt.MouseButton.LeftButton:
            # 左ボタン + Ctrlキーでもドラッグスクロール
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._start_drag_scroll(event)
            else:
                # 通常のクリック処理は元のハンドラに委譲
                QScrollArea.mousePressEvent(self.scroll_area, event)
        else:
            QScrollArea.mousePressEvent(self.scroll_area, event)
    
    def _scroll_area_mouse_move(self, event: QMouseEvent):
        """スクロールエリアのマウス移動イベント"""
        if self.drag_scrolling:
            self._update_drag_scroll(event)
        else:
            QScrollArea.mouseMoveEvent(self.scroll_area, event)
    
    def _scroll_area_mouse_release(self, event: QMouseEvent):
        """スクロールエリアのマウスリリースイベント"""
        if self.drag_scrolling:
            self._end_drag_scroll()
        else:
            QScrollArea.mouseReleaseEvent(self.scroll_area, event)
    
    def set_directory(self, path: str):
        self.directory_path = path or ""
        self._update_thumbnails()
    
    def _update_thumbnails(self):
        # 既存のワーカースレッドを停止
        self._stop_worker_thread()
        
        # 既存のサムネイルをクリア
        self._clear_thumbnails()
        
        if not self.directory_path or not os.path.isdir(self.directory_path):
            self.status_label.setText("ThumbnailView")
            self.status_label.setStyleSheet("color: white; background-color: gray; font-size: 12px; border: 1px solid gray; padding: 2px;")
            return
        
        # 1件ずつ処理を開始（UX改善）
        self._start_progressive_scan(self.directory_path)
    
    def _clear_thumbnails(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.thumbnail_labels.clear()
        
        # 1件ずつ処理用の変数をリセット
        self.processed_files = []
        self.grid_position = 0
        self.is_processing_files = False
    
    def _start_progressive_scan(self, directory_path):
        """1件ずつファイルを処理する段階的スキャンを開始"""
        self.current_directory = directory_path
        self.processed_files = []
        self.grid_position = 0
        self.is_processing_files = True  # ファイル処理開始
        
        # グリッドレイアウトの列数を計算（処理開始時に固定）
        available_width = self.width()
        if hasattr(self, 'scroll_area') and self.scroll_area.viewport():
            viewport_width = self.scroll_area.viewport().width()
            if viewport_width > 50:
                available_width = viewport_width
        
        available_width = max(100, available_width - 20)
        self.grid_cols = max(1, available_width // (self.thumbnail_size + self.margin))
        
        if self.grid_cols == 1 and available_width > (self.thumbnail_size + self.margin) * 2:
            self.grid_cols = 2
        
        force_debug(f"Fixed grid columns for processing: {self.grid_cols} (available_width: {available_width})")
        
        # ディレクトリスキャンを開始
        try:
            self.file_iterator = self._create_file_iterator(directory_path)
            self.status_label.setText(f"Scanning directory:\n{os.path.basename(directory_path)}")
            self.status_label.setStyleSheet("color: white; background-color: blue; font-size: 10px; border: 1px solid blue; padding: 2px;")
            
            force_debug(f"Starting progressive scan of directory: {directory_path}")
            
            # 最初のファイル処理を開始
            self._process_next_file()
            
        except Exception as e:
            force_debug(f"Error starting progressive scan: {e}")
            self.status_label.setText(f"Error scanning:\n{os.path.basename(directory_path)}")
            self.status_label.setStyleSheet("color: white; background-color: red; font-size: 10px; border: 1px solid red; padding: 2px;")
    
    def _create_file_iterator(self, directory_path):
        """ディレクトリから画像ファイルを1件ずつ返すイテレータを作成"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.ico'}
        
        try:
            files = os.listdir(directory_path)
            for file in files:
                if os.path.splitext(file)[1].lower() in image_extensions:
                    full_path = os.path.join(directory_path, file)
                    yield full_path
        except (OSError, PermissionError):
            pass
    
    def _process_next_file(self):
        """次のファイルを1件処理（プレースホルダー作成 + サムネイル生成）"""
        try:
            if self.file_iterator is None:
                return
            
            # 次のファイルを取得
            try:
                image_path = next(self.file_iterator)
            except StopIteration:
                # 全ファイル処理完了
                self._on_scan_completed()
                return
            
            # 処理数制限（Windows環境対応）
            if len(self.processed_files) >= 50:
                force_debug("Reached file limit (50) for Windows environment")
                self._on_scan_completed()
                return
            
            # プレースホルダーを即座に作成
            self._create_single_placeholder(image_path)
            
            # サムネイル生成を即座に開始
            self._start_single_thumbnail_generation(image_path)
            
            # 処理済みファイルに追加
            self.processed_files.append(image_path)
            self.grid_position += 1
            
            # 次のファイル処理をスケジュール（50ms間隔でスムーズに）
            self.file_scan_timer.start(50)
            
            force_debug(f"Processed file {len(self.processed_files)}: {os.path.basename(image_path)}")
            
        except Exception as e:
            force_debug(f"Error processing next file: {e}")
            # エラーが発生しても次のファイル処理は継続
            self.file_scan_timer.start(100)
    
    def _create_single_placeholder(self, image_path):
        """単一ファイル用のプレースホルダーを作成"""
        row = self.grid_position // self.grid_cols
        col = self.grid_position % self.grid_cols
        
        force_debug(f"Creating placeholder for {os.path.basename(image_path)} at position ({row}, {col}) - grid_position: {self.grid_position}, grid_cols: {self.grid_cols}")
        
        # プレースホルダーラベルを作成
        thumb_label = ClickableLabel()
        thumb_label.setFixedSize(self.thumbnail_size, self.thumbnail_size)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setStyleSheet("border: 2px dashed #ccc; background-color: #f8f8f8; color: #666;")
        thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # ファイル名を表示
        filename = os.path.basename(image_path)
        if len(filename) > 15:
            filename = filename[:12] + "..."
        thumb_label.setText(f"Loading...\n{filename}")
        
        # 画像パスを保存
        thumb_label.image_path = image_path
        
        # ツールチップでフルパスを表示
        thumb_label.setToolTip(image_path)
        
        # グリッドに配置
        self.grid_layout.addWidget(thumb_label, row, col)
        
        # マッピングに追加
        self.thumbnail_labels[image_path] = thumb_label
        
        # Windows環境での固まり回避
        QApplication.processEvents()
    
    def _start_single_thumbnail_generation(self, image_path):
        """単一ファイル用のサムネイル生成を開始"""
        # 既存のワーカーがない場合は作成
        if not hasattr(self, 'worker') or not self.worker or not hasattr(self, 'worker_thread') or not self.worker_thread or not self.worker_thread.isRunning():
            self._create_thumbnail_worker()
        
        # 単一ファイルの生成をワーカーに依頼
        force_debug(f"Requesting thumbnail generation for: {os.path.basename(image_path)}")
        
        # ワーカーに単一ファイルの処理を依頼
        QTimer.singleShot(10, lambda: self._request_single_thumbnail(image_path))
    
    def _request_single_thumbnail(self, image_path):
        """ワーカーに単一サムネイル生成を依頼"""
        if self.worker and self.worker_thread and self.worker_thread.isRunning():
            try:
                # シグナルを使用してワーカースレッド内で処理
                self.worker.process_request.emit(image_path, self.thumbnail_size)
                force_debug(f"Sent single thumbnail request to worker: {os.path.basename(image_path)}")
            except Exception as e:
                force_debug(f"Error sending single thumbnail request: {e}")
        else:
            force_debug("Worker not available for thumbnail generation")
    
    def _create_thumbnail_worker(self):
        """サムネイル生成ワーカーを作成（1件ずつ処理用）"""
        # 既存のワーカーがあれば停止
        self._stop_worker_thread()
        
        self.worker = ThumbnailWorker()
        self.worker_thread = QThread()
        
        # Windows対応：スレッド優先度をLowに設定
        self.worker_thread.setPriority(QThread.Priority.LowPriority)
        
        # ワーカーをスレッドに移動
        self.worker.moveToThread(self.worker_thread)
        
        # シグナル接続（1件ずつ処理用に統一）
        self.worker.thumbnail_ready.connect(self._on_thumbnail_ready, Qt.ConnectionType.QueuedConnection)
        
        # スレッド開始
        self.worker_thread.start()
        force_debug("Created thumbnail worker for single-file progressive processing")
    
    def _on_scan_completed(self):
        """ディレクトリスキャン完了時の処理"""
        total_files = len(self.processed_files)
        self.status_label.setText(f"Found {total_files} images in:\n{os.path.basename(self.current_directory)}")
        self.status_label.setStyleSheet("color: white; background-color: green; font-size: 10px; border: 1px solid green; padding: 2px;")
        
        force_debug(f"Progressive scan completed: {total_files} files processed")
        
        # ファイルイテレータをクリア
        self.file_iterator = None
        self.is_processing_files = False  # ファイル処理完了
    
    
    
    
    
    def _on_thumbnail_ready(self, image_path, pixmap):
        """ワーカーからサムネイルが完成した時の処理（1件ずつ即座表示版）"""
        force_debug(f"Received thumbnail for: {os.path.basename(image_path)}")
        
        # 1件ずつ処理システムでは即座にUIに反映
        self._apply_thumbnail_to_ui_immediate(image_path, pixmap)
    
    def _apply_thumbnail_to_ui_immediate(self, image_path, pixmap):
        """サムネイルをUIに即座に適用（1件ずつ処理用）"""
        if image_path not in self.thumbnail_labels:
            force_debug(f"Warning: Label not found for {os.path.basename(image_path)}")
            return
            
        thumb_label = self.thumbnail_labels[image_path]
        
        if pixmap is not None and not pixmap.isNull():
            # 正常に生成されたサムネイルを設定
            thumb_label.setPixmap(pixmap)
            thumb_label.setText("")  # テキストをクリア
            thumb_label.setStyleSheet("border: 1px solid #ccc; background-color: #f0f0f0;")
            
            force_debug(f"Successfully applied thumbnail: {os.path.basename(image_path)}")
        else:
            # エラーの場合
            thumb_label.setText("Error")
            thumb_label.setStyleSheet("border: 1px solid #f00; background-color: #ffe0e0; color: red;")
            force_debug(f"Error applying thumbnail: {os.path.basename(image_path)}")
        
        # 即座にUIを更新
        thumb_label.update()
        QApplication.processEvents()
    
    
    
    def _find_image_files(self, directory: str):
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.ico'}
        image_files = []
        
        try:
            for file in os.listdir(directory):
                if os.path.splitext(file)[1].lower() in image_extensions:
                    image_files.append(os.path.join(directory, file))
        except (OSError, PermissionError):
            pass
        
        # Windows環境での固まり回避のため、初回読み込み時は50枚に制限
        sorted_files = sorted(image_files)
        if len(sorted_files) > 50:
            force_debug(f"Windows environment: Limiting thumbnails to 50 out of {len(sorted_files)} images")
            return sorted_files[:50]
        
        return sorted_files
    
    def _on_thumbnail_clicked(self, image_path: str):
        """サムネイルクリック時の処理"""
        force_debug(f"Thumbnail clicked: {image_path}")
        
        # 連携設定されたImageItemに画像を読み込み
        if hasattr(self, 'thumbnail_view_item'):
            thumbnail_item = self.thumbnail_view_item
            if hasattr(thumbnail_item, 'get_linked_image_item'):
                linked_item = thumbnail_item.get_linked_image_item()
                if linked_item:
                    # ImageItemに画像パスを設定
                    linked_item.d["path"] = image_path
                    linked_item.path = image_path
                    linked_item._apply_pixmap()
                    force_debug(f"Loaded image to linked ImageItem: {os.path.basename(image_path)}")
                else:
                    force_debug("No linked ImageItem found")
            else:
                force_debug("ThumbnailViewItem doesn't have get_linked_image_item method")
        else:
            force_debug("No thumbnail_view_item reference found")
    
    def _on_thumbnail_double_clicked(self, image_path: str):
        """サムネイルダブルクリック時の処理"""
        force_debug(f"Thumbnail double-clicked: {image_path}")
        
        # システムの既定アプリケーションで画像を開く
        try:
            import subprocess
            import platform
            
            if platform.system() == "Windows":
                subprocess.run(["start", image_path], shell=True, check=True)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", image_path], check=True)
            else:  # Linux
                subprocess.run(["xdg-open", image_path], check=True)
                
            force_debug(f"Opened image with system default app: {os.path.basename(image_path)}")
        except Exception as e:
            force_debug(f"Failed to open image: {e}")
            QMessageBox.warning(
                self, 
                "Error", 
                f"Failed to open image:\n{os.path.basename(image_path)}\n\nError: {str(e)}"
            )
    
    def _on_thumbnail_right_clicked(self, image_path: str, label_widget):
        """サムネイル右クリック時のコンテキストメニュー表示"""
        force_debug(f"Thumbnail right-clicked: {image_path}")
        
        # 親ウィジェットを正しく設定（メインウィンドウから取得）
        try:
            scene = self.scene()
            parent_widget = None
            if scene and scene.views():
                parent_widget = scene.views()[0]
        except:
            parent_widget = None
        
        # コンテキストメニューを作成
        menu = QMenu(parent_widget)
        
        # 各アクションで明示的にクロージャを作成
        def copy_full_path():
            force_debug(f"Action: Copy full path - {image_path}")
            self._copy_to_clipboard(image_path)
        
        def copy_filename():
            filename = os.path.basename(image_path)
            force_debug(f"Action: Copy filename - {filename}")
            self._copy_to_clipboard(filename)
        
        def copy_dirname():
            dirname = os.path.dirname(image_path)
            force_debug(f"Action: Copy dirname - {dirname}")
            self._copy_to_clipboard(dirname)
        
        def open_parent():
            force_debug(f"Action: Open parent directory - {image_path}")
            self._open_parent_directory(image_path)
        
        def copy_image():
            force_debug(f"Action: Copy image - {image_path}")
            self._copy_image_to_clipboard(image_path)
        
        def reload_thumbnails():
            force_debug("Action: Reload thumbnails")
            self._reload_thumbnails()
        
        # メニューアイテムを追加
        copy_full_path_action = menu.addAction("フルパスをコピー")
        copy_full_path_action.triggered.connect(copy_full_path)
        
        copy_filename_action = menu.addAction("ファイル名をコピー")
        copy_filename_action.triggered.connect(copy_filename)
        
        copy_dirname_action = menu.addAction("ディレクトリ名をコピー")
        copy_dirname_action.triggered.connect(copy_dirname)
        
        menu.addSeparator()
        
        open_parent_action = menu.addAction("親ディレクトリを開く")
        open_parent_action.triggered.connect(open_parent)
        
        menu.addSeparator()
        
        copy_image_action = menu.addAction("画像をコピー")
        copy_image_action.triggered.connect(copy_image)
        
        menu.addSeparator()
        
        reload_action = menu.addAction("リロード")
        reload_action.triggered.connect(reload_thumbnails)
        
        # メニューを表示（マウス位置で）
        try:
            # グローバル位置を正確に計算
            from PySide6.QtGui import QCursor
            global_pos = QCursor.pos()
            force_debug(f"Showing menu at position: {global_pos}")
            
            # メニューを表示
            selected_action = menu.exec(global_pos)
            if selected_action:
                force_debug(f"Menu action selected: {selected_action.text()}")
            else:
                force_debug("Menu closed without selection")
                
        except Exception as e:
            force_debug(f"Error showing context menu: {e}")
            # フォールバック: 簡単な位置でメニュー表示
            menu.exec()
    
    def _copy_to_clipboard(self, text: str):
        """テキストをクリップボードにコピー"""
        force_debug(f"_copy_to_clipboard called with: {text}")
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            force_debug(f"Successfully copied to clipboard: {text}")
            
            # 成功メッセージを表示
            QMessageBox.information(
                None, 
                "情報", 
                f"クリップボードにコピーしました:\n{text}"
            )
        except Exception as e:
            force_debug(f"Failed to copy to clipboard: {e}")
            QMessageBox.warning(
                None, 
                "Error", 
                f"Failed to copy to clipboard:\n{str(e)}"
            )
    
    def _open_parent_directory(self, image_path: str):
        """親ディレクトリを開く"""
        force_debug(f"_open_parent_directory called with: {image_path}")
        try:
            import subprocess
            import platform
            
            parent_dir = os.path.dirname(image_path)
            force_debug(f"Parent directory: {parent_dir}")
            
            if platform.system() == "Windows":
                # Windowsの場合、ファイルを選択した状態でエクスプローラーを開く
                force_debug("Opening with Windows Explorer")
                subprocess.run(["explorer", "/select,", image_path], check=True)
            elif platform.system() == "Darwin":  # macOS
                force_debug("Opening with macOS Finder")
                subprocess.run(["open", "-R", image_path], check=True)
            else:  # Linux
                force_debug("Opening with Linux file manager")
                subprocess.run(["xdg-open", parent_dir], check=True)
                
            force_debug(f"Successfully opened parent directory: {parent_dir}")
        except Exception as e:
            force_debug(f"Failed to open parent directory: {e}")
            QMessageBox.warning(
                None, 
                "Error", 
                f"Failed to open parent directory:\n{str(e)}"
            )
    
    def _copy_image_to_clipboard(self, image_path: str):
        """画像をクリップボードにコピー"""
        force_debug(f"_copy_image_to_clipboard called with: {image_path}")
        try:
            from PySide6.QtGui import QPixmap
            
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                clipboard = QApplication.clipboard()
                clipboard.setPixmap(pixmap)
                force_debug(f"Successfully copied image to clipboard: {os.path.basename(image_path)}")
                
                # 成功メッセージを表示
                QMessageBox.information(
                    None, 
                    "情報", 
                    f"画像をクリップボードにコピーしました:\n{os.path.basename(image_path)}"
                )
            else:
                raise Exception("Failed to load image")
        except Exception as e:
            force_debug(f"Failed to copy image to clipboard: {e}")
            QMessageBox.warning(
                None, 
                "Error", 
                f"Failed to copy image to clipboard:\n{str(e)}"
            )
    
    def _reload_thumbnails(self):
        """サムネイルをリロード"""
        force_debug("_reload_thumbnails called")
        self._update_thumbnails()
        force_debug("Thumbnails reloaded")


class ThumbnailViewItem(CanvasItem):
    """サムネイルビューアイテム（データ永続化対応版）"""
    
    TYPE_NAME = "thumbnail_view"
    
    @classmethod
    def supports_path(cls, path: str) -> bool:
        return False
    
    def __init__(
        self,
        d: dict[str, Any] | None = None,
        cb_resize: Callable[[int, int], None] | None = None,
        text_color: QColor | None = None
    ):
        try:
            force_debug("ThumbnailViewItem.__init__ starting")
            force_debug(f"Input d parameter: {d}")
            
            super().__init__(d, cb_resize, text_color)
            
            # ドラッグ状態管理
            self.mouse_press_pos = None
            self.is_dragging = False
            
            # ホバーイベントを有効化
            self.setAcceptHoverEvents(True)
            
            # デフォルト値を設定（既存の値がない場合のみ）
            if "directory_path" not in self.d:
                self.d["directory_path"] = ""
            if "thumbnail_size" not in self.d:
                self.d["thumbnail_size"] = 128
            if "margin" not in self.d:
                self.d["margin"] = 8
            if "linked_image_item_id" not in self.d:
                self.d["linked_image_item_id"] = ""
            
            force_debug(f"super().__init__ completed, self.d = {self.d}")
            force_debug(f"self.d id: {id(self.d)}")
            
            force_debug("Creating ThumbnailWidget")
            self.thumbnail_widget = ThumbnailWidget()
            self.thumbnail_widget.thumbnail_view_item = self  # 親への参照を設定
            force_debug("ThumbnailWidget created successfully")
            
            force_debug("Creating QGraphicsProxyWidget")
            self.proxy = QGraphicsProxyWidget(parent=self)
            force_debug("QGraphicsProxyWidget created")
            
            # プロキシウィジェットでマウスイベントを子ウィジェットに適切に伝達
            self.proxy.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsSelectable, False)
            self.proxy.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsMovable, False)
            
            force_debug("Setting widget to proxy")
            self.proxy.setWidget(self.thumbnail_widget)
            force_debug("Widget set to proxy successfully")
            
            force_debug("Setting initial directory")
            initial_path = self.d.get("directory_path", "")
            force_debug(f"Initial directory path: '{initial_path}'")
            
            # サムネイルサイズとマージンを設定
            self.thumbnail_widget.thumbnail_size = self.d.get("thumbnail_size", 128)
            self.thumbnail_widget.margin = self.d.get("margin", 8)
            self.thumbnail_widget.grid_layout.setSpacing(self.thumbnail_widget.margin)
            
            # 初期ディレクトリは遅延設定（レイアウトが安定してから）
            if initial_path:
                # 少し遅らせてからディレクトリを設定
                QTimer.singleShot(100, lambda: self._delayed_directory_setup(initial_path))
            else:
                self.thumbnail_widget.set_directory("")
            force_debug("Initial directory setup scheduled")
            
            force_debug("Updating size")
            self.update_size()
            force_debug("Size updated")
            
            force_debug("ThumbnailViewItem.__init__ completed successfully")
            
        except Exception as e:
            warn(f"ThumbnailViewItem.__init__ error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def __del__(self):
        """デストラクタ - ThumbnailWidgetのワーカースレッドを安全に終了"""
        try:
            if hasattr(self, 'thumbnail_widget') and self.thumbnail_widget:
                self.thumbnail_widget._stop_worker_thread()
                force_debug("ThumbnailViewItem: Worker thread stopped on deletion")
        except Exception as e:
            force_debug(f"ThumbnailViewItem: Error stopping worker thread: {e}")
    
    def _delayed_directory_setup(self, path: str):
        """遅延ディレクトリ設定（レイアウト安定後）"""
        force_debug(f"Delayed directory setup: {path}")
        self.thumbnail_widget.set_directory(path)
    
    def update_size(self):
        """サイズを更新"""
        w = self.d.get("width", 300)
        h = self.d.get("height", 200)
        
        # 矩形アイテムのサイズ更新
        self._rect_item.setRect(0, 0, w, h)
        
        # プロキシウィジェットのサイズ更新  
        self.proxy.resize(w, h)
        self.thumbnail_widget.resize(w, h)
        
        # グリップ位置更新
        self._update_grip_pos()
    
    def resize_content(self, w: int, h: int):
        """CanvasResizeGripからのリサイズ処理"""
        self.proxy.resize(w, h)
        self.thumbnail_widget.resize(w, h)
        # リサイズ中はサムネイル再計算を行わない（負荷軽減）
        # resizeEvent()のタイマーで遅延実行される
    
    def on_resized(self, w: int, h: int):
        """リサイズ時のコールバック"""
        super().on_resized(w, h)  # 基底クラスの処理（グリップ位置更新）
        self.resize_content(w, h)
    
    def on_edit(self):
        """編集ダイアログを開く（ImageItem方式）"""
        force_debug("=== ThumbnailViewItem on_edit called ===")
        force_debug(f"BEFORE dialog - self.d: {self.d}")
        force_debug(f"BEFORE dialog - self.d id: {id(self.d)}")
        
        # ImageItemと同じパターン：selfを渡す
        dialog = ThumbnailDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # ダイアログ内で既にself.d["directory_path"]が更新済み
            force_debug(f"AFTER dialog - self.d: {self.d}")
            force_debug(f"AFTER dialog - self.d id: {id(self.d)}")
            
            # 更新された設定をUIに反映
            new_path = self.d.get("directory_path", "")
            new_size = self.d.get("thumbnail_size", 128)
            new_margin = self.d.get("margin", 8)
            
            force_debug(f"Setting UI with path: '{new_path}', size: {new_size}, margin: {new_margin}")
            
            # サムネイルウィジェットの設定を更新
            self.thumbnail_widget.thumbnail_size = new_size
            self.thumbnail_widget.margin = new_margin
            self.thumbnail_widget.grid_layout.setSpacing(new_margin)
            
            # ディレクトリを設定（サムネイルを再生成）
            self.thumbnail_widget.set_directory(new_path)
            force_debug(f"=== on_edit completed ===")
        else:
            force_debug("Dialog was cancelled")
    
    def get_linked_image_item(self):
        """連携設定されたImageItemを取得する"""
        linked_id = self.d.get("linked_image_item_id", "")
        if not linked_id:
            return None
        
        try:
            # シーン内のImageItemから実際のアイテムを探す
            scene = self.scene()
            if scene:
                for item in scene.items():
                    if hasattr(item, 'TYPE_NAME') and item.TYPE_NAME == 'image':
                        # ImageItemのIDで比較
                        item_id = item.d.get("id", 0)
                        if item_id == linked_id:
                            return item
        except Exception as e:
            force_debug(f"Error finding linked image item: {e}")
        
        return None
    
    def _is_status_label_area(self, pos):
        """ステータスラベル領域かどうかを判定（ドラッグ移動可能領域）"""
        try:
            # ThumbnailViewItemの高さを取得
            item_height = self.d.get("height", 200)
            
            # ステータスラベルは下端の30pxの高さ
            status_label_top = item_height - 30
            
            if pos.y() >= status_label_top:
                force_debug(f"Status label area detected: pos.y()={pos.y()}, threshold={status_label_top}")
                return True
            
            return False
        except Exception as e:
            force_debug(f"Error checking status label area: {e}")
            return False
    
    def _is_proxy_margin_area(self, local_pos):
        """プロキシウィジェット内の外枠部分かどうかを判定（ドラッグ移動可能領域）"""
        try:
            # スクロールエリアの位置とサイズを取得
            scroll_area = self.thumbnail_widget.scroll_area
            if not scroll_area:
                return False
            
            scroll_rect = scroll_area.geometry()
            margin = 5  # 外枠として判定するマージン幅
            
            # スクロールエリアの外側（プロキシウィジェット内のマージン部分）
            if (local_pos.x() < scroll_rect.x() + margin or 
                local_pos.x() > scroll_rect.right() - margin or
                local_pos.y() < scroll_rect.y() + margin or
                local_pos.y() > scroll_rect.bottom() - margin):
                
                force_debug(f"Proxy margin area detected: pos=({local_pos.x()}, {local_pos.y()}), scroll_rect={scroll_rect}")
                return True
            
            return False
        except Exception as e:
            force_debug(f"Error checking proxy margin area: {e}")
            return False
    
    def hoverMoveEvent(self, event):
        """マウスホバー時のカーソル変更とビジュアルフィードバック"""
        try:
            # ドラッグ可能エリアの判定
            is_status_area = self._is_status_label_area(event.pos())
            is_margin_area = False
            
            if not is_status_area:
                local_pos = self.proxy.mapFromScene(event.scenePos())
                is_margin_area = self._is_proxy_margin_area(local_pos)
            
            # ドラッグ可能エリアではカーソルを変更
            if is_status_area or is_margin_area:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                if is_status_area:
                    # ステータスラベルのスタイルを強調
                    self.thumbnail_widget.status_label.setStyleSheet("""
                        color: white; 
                        background-color: #555555; 
                        font-size: 10px; 
                        border: 1px solid #888; 
                        padding: 2px;
                        border-radius: 3px;
                    """)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                # ステータスラベルのスタイルを通常に戻す
                self.thumbnail_widget.status_label.setStyleSheet("""
                    color: white; 
                    background-color: #404040; 
                    font-size: 10px; 
                    border: 1px solid #666; 
                    padding: 2px;
                    border-radius: 3px;
                """)
            
            super().hoverMoveEvent(event)
            
        except Exception as e:
            force_debug(f"Error in hoverMoveEvent: {e}")
    
    def hoverLeaveEvent(self, event):
        """ホバー終了時の処理"""
        try:
            # カーソルとスタイルを通常に戻す
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.thumbnail_widget.status_label.setStyleSheet("""
                color: white; 
                background-color: #404040; 
                font-size: 10px; 
                border: 1px solid #666; 
                padding: 2px;
                border-radius: 3px;
            """)
            super().hoverLeaveEvent(event)
        except Exception as e:
            force_debug(f"Error in hoverLeaveEvent: {e}")
    
    def mousePressEvent(self, ev):
        """
        ThumbnailViewItem内でのマウスクリック処理
        スクロール機能とドラッグ移動の両立
        """
        force_debug(f"ThumbnailViewItem mousePressEvent: button={ev.button()}, pos={ev.pos()}")
        force_debug(f"Current run_mode: {getattr(self, 'run_mode', 'undefined')}")
        
        # ドラッグ状態をリセット
        self.mouse_press_pos = ev.pos()
        self.is_dragging = False
        
        # ステータスラベル領域でのクリックをチェック（下端の帯部分）
        if self._is_status_label_area(ev.pos()):
            force_debug("Click in status label area - allowing item drag")
            super().mousePressEvent(ev)
            return
        
        # プロキシウィジェット内の位置を計算
        local_pos = self.proxy.mapFromScene(ev.scenePos())
        
        # プロキシウィジェット領域内かチェック
        if self.proxy.contains(local_pos):
            # スクロールエリア外枠部分でのクリックをチェック
            if self._is_proxy_margin_area(local_pos):
                force_debug("Click in proxy margin area - allowing item drag")
                super().mousePressEvent(ev)
                return
            
            # サムネイルコンテンツ領域内での処理
            # ドラッグスクロール用のイベントをチェック
            if ev.button() == Qt.MouseButton.MiddleButton or \
               (ev.button() == Qt.MouseButton.LeftButton and ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
                # ドラッグスクロールイベントはThumbnailWidgetに転送
                force_debug("Forwarding drag scroll event to ThumbnailWidget")
                widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
                
                # QMouseEventを作成してThumbnailWidgetに送信
                from PySide6.QtCore import QPointF
                mouse_event = QMouseEvent(
                    QMouseEvent.Type.MouseButtonPress,
                    QPointF(widget_pos),
                    QPointF(widget_pos),
                    ev.button(),
                    ev.buttons(),
                    ev.modifiers()
                )
                self.thumbnail_widget.mousePressEvent(mouse_event)
                ev.accept()
                return
            
            # 通常のサムネイル操作はThumbnailWidgetに転送
            widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
            from PySide6.QtCore import QPointF
            mouse_event = QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                QPointF(widget_pos),
                QPointF(widget_pos),
                ev.button(),
                ev.buttons(),
                ev.modifiers()
            )
            self.thumbnail_widget.mousePressEvent(mouse_event)
            ev.accept()
            return
        
        # プロキシウィジェット外の場合は通常のCanvasItemドラッグ移動
        super().mousePressEvent(ev)
    
    def mouseMoveEvent(self, ev):
        """ドラッグスクロール中のマウス移動処理"""
        # ドラッグ判定
        if self.mouse_press_pos and not self.is_dragging:
            drag_distance = (ev.pos() - self.mouse_press_pos).manhattanLength()
            if drag_distance > 3:  # 3ピクセル以上移動したらドラッグとみなす
                self.is_dragging = True
                force_debug("Drag detected - setting is_dragging=True")
                
                # ステータスラベル領域またはプロキシマージン領域でのドラッグの場合
                if (self._is_status_label_area(self.mouse_press_pos) or 
                    self._is_proxy_margin_area(self.proxy.mapFromScene(ev.scenePos()))):
                    force_debug("Item drag detected in allowed area")
                    super().mouseMoveEvent(ev)
                    return
        
        if hasattr(self, 'thumbnail_widget') and self.thumbnail_widget.drag_scrolling:
            # ドラッグスクロール中の場合はThumbnailWidgetに転送
            local_pos = self.proxy.mapFromScene(ev.scenePos())
            if self.proxy.contains(local_pos):
                widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
                
                from PySide6.QtCore import QPointF
                mouse_event = QMouseEvent(
                    QMouseEvent.Type.MouseMove,
                    QPointF(widget_pos),
                    QPointF(widget_pos),
                    ev.button(),
                    ev.buttons(),
                    ev.modifiers()
                )
                self.thumbnail_widget.mouseMoveEvent(mouse_event)
                ev.accept()
                return
        
        super().mouseMoveEvent(ev)
    
    def mouseReleaseEvent(self, ev):
        """ドラッグスクロール終了処理とクリック判定"""
        force_debug(f"ThumbnailViewItem mouseReleaseEvent: pos={ev.pos()}, is_dragging={self.is_dragging}")
        
        # ドラッグ中の場合の処理
        if self.is_dragging:
            force_debug("Mouse release after drag")
            
            # ステータスラベル領域またはプロキシマージン領域でのドラッグ終了の場合
            if (self._is_status_label_area(ev.pos()) or 
                self._is_proxy_margin_area(self.proxy.mapFromScene(ev.scenePos()))):
                force_debug("Item drag release in allowed area")
                super().mouseReleaseEvent(ev)
                self.mouse_press_pos = None
                self.is_dragging = False
                return
            
            # その他のエリアでのドラッグ終了はクリック処理をスキップ
            self.mouse_press_pos = None
            self.is_dragging = False
            return
            
        if hasattr(self, 'thumbnail_widget') and self.thumbnail_widget.drag_scrolling:
            # ドラッグスクロール中の場合はThumbnailWidgetに転送
            local_pos = self.proxy.mapFromScene(ev.scenePos())
            widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
            
            from PySide6.QtCore import QPointF
            mouse_event = QMouseEvent(
                QMouseEvent.Type.MouseButtonRelease,
                QPointF(widget_pos),
                QPointF(widget_pos),
                ev.button(),
                ev.buttons(),
                ev.modifiers()
            )
            self.thumbnail_widget.mouseReleaseEvent(mouse_event)
            ev.accept()
            return
        
        # ドラッグでない場合のクリック処理
        if not self.is_dragging and self.mouse_press_pos:
            self._handle_click(ev)
        
        # ドラッグ状態をリセット
        self.mouse_press_pos = None
        self.is_dragging = False
        
        super().mouseReleaseEvent(ev)
    
    def _handle_click(self, ev):
        """ドラッグでない場合のクリック処理"""
        force_debug(f"_handle_click: button={ev.button()}")
        
        # プロキシウィジェット内の位置を計算
        local_pos = self.proxy.mapFromScene(ev.scenePos())
        
        # サムネイル領域内かチェック
        if self.proxy.contains(local_pos):
            # ThumbnailWidget座標系に変換
            widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
            
            # スクロールエリアの座標を考慮してサムネイルコンテナ座標系に変換
            if hasattr(self.thumbnail_widget, 'scroll_area') and self.thumbnail_widget.scroll_area:
                # スクロールオフセットを取得
                h_offset = self.thumbnail_widget.scroll_area.horizontalScrollBar().value()
                v_offset = self.thumbnail_widget.scroll_area.verticalScrollBar().value()
                
                # スクロールオフセットを加味した座標に変換
                container_pos = widget_pos + QPoint(h_offset, v_offset)
                force_debug(f"Click position: widget_pos={widget_pos}, scroll_offset=({h_offset},{v_offset}), container_pos={container_pos}")
            else:
                container_pos = widget_pos
                
            clicked_thumbnail = self._find_thumbnail_at_position(container_pos)
            
            if clicked_thumbnail and hasattr(clicked_thumbnail, 'image_path'):
                if ev.button() == Qt.MouseButton.LeftButton and getattr(self, "run_mode", False):
                    # 実行モードでのサムネイルクリック処理
                    force_debug("Run mode: Click is within thumbnail proxy widget")
                    force_debug(f"Clicked thumbnail: {clicked_thumbnail.image_path}")
                    self.thumbnail_widget._on_thumbnail_clicked(clicked_thumbnail.image_path)
                elif ev.button() == Qt.MouseButton.RightButton:
                    # 右クリックコンテキストメニュー（実行・編集モード共通）
                    force_debug("Right-click detected on thumbnail")
                    force_debug(f"Right-clicked thumbnail: {clicked_thumbnail.image_path}")
                    self.thumbnail_widget._on_thumbnail_right_clicked(clicked_thumbnail.image_path, clicked_thumbnail)
    
    def _find_thumbnail_at_position(self, pos):
        """指定された位置にあるサムネイルを検索"""
        force_debug(f"_find_thumbnail_at_position called with pos: {pos}")
        
        # QGridLayout内のすべてのアイテムをチェック
        for i in range(self.thumbnail_widget.grid_layout.count()):
            layout_item = self.thumbnail_widget.grid_layout.itemAt(i)
            if layout_item and layout_item.widget():
                widget = layout_item.widget()
                if hasattr(widget, 'image_path'):
                    # ウィジェットのジオメトリを取得
                    widget_geometry = widget.geometry()
                    force_debug(f"  Item {i}: rect={widget_geometry}, path={os.path.basename(widget.image_path)}")
                    
                    # 位置がウィジェット内にあるかチェック
                    if widget_geometry.contains(pos):
                        force_debug(f"  Found thumbnail at position: {os.path.basename(widget.image_path)}")
                        return widget
        
        force_debug(f"No thumbnail found at position {pos}")
        return None
    
    def wheelEvent(self, ev):
        """
        ホイールイベントをThumbnailWidgetに転送
        スクロール機能を有効にする
        """
        force_debug(f"ThumbnailViewItem wheelEvent: delta={ev.delta()}, pos={ev.pos()}")
        
        # プロキシウィジェット内の位置を計算
        local_pos = self.proxy.mapFromScene(ev.scenePos())
        
        # プロキシウィジェット内の場合はThumbnailWidgetに転送
        if self.proxy.contains(local_pos):
            widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
            
            # QWheelEventを作成してThumbnailWidgetに送信
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QWheelEvent
            wheel_event = QWheelEvent(
                QPointF(widget_pos),
                QPointF(widget_pos),
                ev.pixelDelta(),
                ev.angleDelta(),
                ev.buttons(),
                ev.modifiers(),
                ev.phase(),
                ev.inverted()
            )
            
            # ThumbnailWidgetのwheelEventを直接呼び出す
            self.thumbnail_widget.wheelEvent(wheel_event)
            ev.accept()
            force_debug("Wheel event forwarded to ThumbnailWidget")
            return
        
        # プロキシウィジェット外の場合は親に処理を委譲
        super().wheelEvent(ev)
    
    def mouseDoubleClickEvent(self, ev):
        """
        ThumbnailViewItem内でのダブルクリック処理
        編集モード・実行モードに応じて処理を分ける
        """
        force_debug(f"ThumbnailViewItem mouseDoubleClickEvent: button={ev.button()}, pos={ev.pos()}")
        force_debug(f"Current run_mode: {getattr(self, 'run_mode', 'undefined')}")
        
        if ev.button() == Qt.MouseButton.LeftButton:
            # 編集モードの場合は設定ダイアログを開く
            if not getattr(self, "run_mode", False):
                force_debug("Edit mode: opening settings dialog")
                self.on_edit()
                ev.accept()
                return
            
            # 実行モードの場合はサムネイル個別処理
            # プロキシウィジェット内の位置を計算
            local_pos = self.proxy.mapFromScene(ev.scenePos())
            
            # サムネイル領域内かチェック
            if self.proxy.contains(local_pos):
                force_debug("Run mode: Double-click is within thumbnail proxy widget")
                # プロキシウィジェット内のダブルクリックを処理
                widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
                
                # どのサムネイルがダブルクリックされたかを判定
                clicked_thumbnail = self._find_thumbnail_at_position(widget_pos)
                if clicked_thumbnail:
                    force_debug(f"Double-clicked thumbnail: {getattr(clicked_thumbnail, 'image_path', 'unknown')}")
                    # サムネイルのダブルクリック処理を直接呼び出し
                    if hasattr(clicked_thumbnail, 'image_path'):
                        self.thumbnail_widget._on_thumbnail_double_clicked(clicked_thumbnail.image_path)
                
                ev.accept()
                return
        
        # フォールバック: 通常のCanvasItemのダブルクリック処理
        super().mouseDoubleClickEvent(ev)
    
    def _find_thumbnail_at_position(self, pos):
        """指定された位置にあるサムネイルラベルを探す"""
        try:
            force_debug(f"Searching for thumbnail at position: {pos}")
            force_debug(f"Grid layout has {self.thumbnail_widget.grid_layout.count()} items")
            
            # QGridLayoutから子ウィジェットを検索
            for i in range(self.thumbnail_widget.grid_layout.count()):
                item = self.thumbnail_widget.grid_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    widget_rect = widget.geometry()
                    force_debug(f"  Item {i}: rect={widget_rect}, path={getattr(widget, 'image_path', 'unknown')}")
                    
                    if widget_rect.contains(pos):
                        force_debug(f"Found thumbnail at position {pos}: {getattr(widget, 'image_path', 'unknown')}")
                        return widget
            
            force_debug(f"No thumbnail found at position {pos}")
        except Exception as e:
            force_debug(f"Error finding thumbnail at position: {e}")
        
        return None
    
    def wheelEvent(self, event):
        """
        ホイールイベントをサムネイルエリア内で処理
        QGraphicsSceneWheelEventとして処理される
        """
        force_debug(f"ThumbnailViewItem wheelEvent: delta={event.delta()}")
        
        # プロキシウィジェット内の位置を確認
        if hasattr(self, 'proxy') and self.proxy:
            scene_pos = event.scenePos() if hasattr(event, 'scenePos') else event.pos()
            local_pos = self.proxy.mapFromScene(scene_pos)
            
            if self.proxy.contains(local_pos):
                force_debug("Wheel event is within thumbnail proxy widget")
                
                # ホイールイベントをThumbnailWidgetに転送
                if hasattr(self, 'thumbnail_widget') and self.thumbnail_widget:
                    # QWheelEventを作成してThumbnailWidgetに送信
                    widget_pos = self.thumbnail_widget.mapFromParent(local_pos.toPoint())
                    
                    try:
                        from PySide6.QtGui import QWheelEvent
                        from PySide6.QtCore import QPointF
                        
                        # 新しいQWheelEventを作成
                        wheel_event = QWheelEvent(
                            QPointF(widget_pos),  # position
                            QPointF(widget_pos),  # globalPosition  
                            event.pixelDelta() if hasattr(event, 'pixelDelta') else QPointF(),
                            event.angleDelta() if hasattr(event, 'angleDelta') else QPointF(0, event.delta()),
                            event.buttons() if hasattr(event, 'buttons') else Qt.MouseButton.NoButton,
                            event.modifiers() if hasattr(event, 'modifiers') else Qt.KeyboardModifier.NoModifier,
                            event.phase() if hasattr(event, 'phase') else Qt.ScrollPhase.NoScrollPhase,
                            event.inverted() if hasattr(event, 'inverted') else False
                        )
                        
                        # ThumbnailWidgetにイベントを送信
                        self.thumbnail_widget.wheelEvent(wheel_event)
                        event.accept()
                        force_debug("Wheel event forwarded to ThumbnailWidget")
                        return
                        
                    except Exception as e:
                        force_debug(f"Error creating wheel event: {e}")
        
        # フォールバック: 通常のイベント処理
        super().wheelEvent(event)
    
