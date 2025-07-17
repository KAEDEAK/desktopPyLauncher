# -*- coding: utf-8 -*-
"""
DPyL_ticker.py ―  desktopPyLauncher通知ティッカーシステム
◎ Qt6 / PySide6 専用
従来のOKボタン付きダイアログに代わる、ニュースティッカー風通知システム
"""

from __future__ import annotations
import sys
from enum import Enum
from typing import Optional

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, 
    QParallelAnimationGroup, QSequentialAnimationGroup,
    QRect, QPointF, QSize, Signal, QObject
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QPainter, QPen, QBrush,
    QLinearGradient, QPixmap, QIcon
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout,
    QGraphicsOpacityEffect, QSizePolicy, QApplication,
    QGraphicsProxyWidget, QGraphicsItem
)

from DPyL_utils import warn, debug_print

class NotificationType(Enum):
    """通知タイプの定義"""
    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NotificationTicker(QWidget):
    """
    ビュー上に直接表示される通知ティッカー（シンプルな黒い半透明）
    """
    
    # シグナル定義
    clicked = Signal()
    
    def __init__(self, parent_view=None):
        super().__init__(parent_view)
        self.parent_view = parent_view
        self.current_timer: Optional[QTimer] = None
        self.animation_group: Optional[QParallelAnimationGroup] = None
        
        # 初期設定
        self.setup_ui()
        self.setup_animations()
        
        # 親ウィジェットの上部に固定表示するための設定
        if parent_view:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            # 親ウィジェットの子として表示
        else:
            # 親がない場合のみWindowフラグを設定
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
    def setup_ui(self):
        """UIの初期設定（シンプルな黒い半透明）"""
        # ウィジェットの基本設定
        self.setFixedHeight(35)  # コンパクトに
        
        # レイアウト作成
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(15, 8, 15, 8)
        self.main_layout.setSpacing(12)
        
        # アイコンラベル
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 14px;")
        
        # メッセージラベル
        self.message_label = QLabel()
        self.message_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # 閉じるボタン
        self.close_label = QLabel("×")
        self.close_label.setFixedSize(16, 16)
        self.close_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.close_label.setStyleSheet("""
            font-size: 12px; 
            font-weight: bold; 
            color: rgba(255, 255, 255, 0.7);
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
        """)
        self.close_label.mousePressEvent = lambda e: self.hide_notification()
        
        # プログレスバー用のウィジェット
        self.progress_widget = QWidget()
        self.progress_widget.setFixedHeight(2)
        self.progress_widget.setStyleSheet("background-color: rgba(255, 255, 255, 0.6);")
        
        # レイアウトに追加
        self.main_layout.addWidget(self.icon_label)
        self.main_layout.addWidget(self.message_label)
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.close_label)
        
        # メインコンテナ（黒い半透明背景）
        self.container = QWidget()
        self.container.setStyleSheet("""
        QWidget {
            background: rgba(0, 0, 0, 0.8);
            border: none;
        }
        """)
        
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # コンテンツエリア
        content_widget = QWidget()
        content_widget.setLayout(self.main_layout)
        
        container_layout.addWidget(content_widget)
        container_layout.addWidget(self.progress_widget)
        
        self.container.setLayout(container_layout)
        
        # 全体レイアウト
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)
        self.setLayout(layout)
        
        # 不透明度エフェクト
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        
        # クリックイベント
        self.mousePressEvent = self._on_click
        
    def setup_animations(self):
        """アニメーションの設定"""
        # フェードイン/アウトアニメーション
        self.fade_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(300)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        # プログレスアニメーション
        self.progress_animation = QPropertyAnimation(self.progress_widget, b"maximumWidth")
        self.progress_animation.setEasingCurve(QEasingCurve.Type.Linear)
        
    def position_on_view(self):
        """ビューの上部に固定位置を設定"""
        if not self.parent_view:
            return
            
        # ビューの幅に合わせる
        view_width = self.parent_view.width()
        self.setFixedWidth(view_width)
        
        # ビューの上部に配置（親ウィジェットの座標系で）
        self.move(0, 0)
        
        # 最前面に表示
        self.raise_()
        
        # プログレスバーの幅も更新
        self.progress_widget.setMaximumWidth(view_width)
        
    def show_notification(self, 
                         message: str, 
                         notification_type: NotificationType = NotificationType.SUCCESS,
                         duration: int = 5000):  # 5秒に変更
        """
        通知を表示する
        
        Args:
            message: 表示するメッセージ
            notification_type: 通知タイプ
            duration: 表示時間（ミリ秒、デフォルト5秒）
        """
        debug_print(f"[NotificationTicker] Showing: {message} ({notification_type.value})")
        
        # 既存のタイマーをクリア
        if self.current_timer:
            self.current_timer.stop()
            self.current_timer = None
            
        # 既存のアニメーションを停止
        if self.animation_group:
            self.animation_group.stop()
            
        # メッセージとアイコンを設定
        self.message_label.setText(message)
        self._set_style_for_type(notification_type)
        
        # 位置設定
        self.position_on_view()
        
        # プログレスバーの設定
        self.progress_animation.setDuration(duration)
        self.progress_animation.setStartValue(self.width())
        self.progress_animation.setEndValue(0)
        
        # 表示
        self.show()
        self.raise_()  # 最前面に表示
        
        # 表示アニメーション
        self._animate_show()
        
        # プログレスアニメーション開始
        self.progress_animation.start()
        
        # 自動非表示タイマー（5秒）
        self.current_timer = QTimer()
        self.current_timer.timeout.connect(self.hide_notification)
        self.current_timer.setSingleShot(True)
        self.current_timer.start(duration)
        
    def hide_notification(self):
        """通知を非表示にする"""
        debug_print("[NotificationTicker] Hiding notification")
        
        if self.current_timer:
            self.current_timer.stop()
            self.current_timer = None
            
        self.progress_animation.stop()
        self._animate_hide()
        
    def _set_style_for_type(self, notification_type: NotificationType):
        """通知タイプに応じて文字色とアイコンを設定"""
        type_config = {
            NotificationType.SUCCESS: {
                "icon": "✓",
                "text_color": "#4CAF50"  # 緑
            },
            NotificationType.INFO: {
                "icon": "ℹ️",
                "text_color": "#2196F3"  # 青
            },
            NotificationType.WARNING: {
                "icon": "⚠️", 
                "text_color": "#FF9800"  # オレンジ
            },
            NotificationType.ERROR: {
                "icon": "❌",
                "text_color": "#f44336"  # 赤
            }
        }
        
        config = type_config[notification_type]
        
        # アイコン設定
        self.icon_label.setText(config["icon"])
        self.icon_label.setStyleSheet(f"color: {config['text_color']}; font-size: 14px;")
        
        # テキスト色設定
        self.message_label.setStyleSheet(f"color: {config['text_color']};")
        
    def _animate_show(self):
        """表示アニメーション（フェードイン）"""
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        
    def _animate_hide(self):
        """非表示アニメーション（フェードアウト）"""
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        
        # アニメーション完了後に非表示
        self.fade_animation.finished.connect(self.hide)
        self.fade_animation.start()
        
    def _on_click(self, event):
        """クリック時の処理"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self.hide_notification()


class NotificationManager(QObject):
    """
    通知管理クラス - シンプルな黒い半透明ステータスバーを管理
    """
    
    def __init__(self, scene=None, view=None):
        super().__init__()
        self.scene = scene
        self.view = view
        self.current_ticker: Optional[NotificationTicker] = None
        
    def show_success(self, message: str, duration: int = 5000):
        """成功通知を表示"""
        self._show_notification(message, NotificationType.SUCCESS, duration)
        
    def show_info(self, message: str, duration: int = 5000):
        """情報通知を表示"""
        self._show_notification(message, NotificationType.INFO, duration)
        
    def show_warning(self, message: str, duration: int = 5000):
        """警告通知を表示"""
        self._show_notification(message, NotificationType.WARNING, duration)
        
    def show_error(self, message: str, duration: int = 5000):
        """エラー通知を表示"""
        self._show_notification(message, NotificationType.ERROR, duration)
        
    def _show_notification(self, message: str, notification_type: NotificationType, duration: int):
        """内部: 通知表示処理"""
        # viewを取得（sceneからviewを探すか、直接設定されたviewを使用）
        target_view = self.view
        if not target_view and self.scene:
            # sceneからviewを取得
            for view in self.scene.views():
                if view:
                    target_view = view
                    break
        
        if not target_view:
            debug_print("[NotificationManager] View not found")
            return
            
        # 既存の通知があれば隠す
        if self.current_ticker:
            self.current_ticker.hide_notification()
            
        # 新しい通知ティッカーを作成（ビューを親にする）
        self.current_ticker = NotificationTicker(target_view)
        
        # 通知を表示
        self.current_ticker.show_notification(message, notification_type, duration)
        
        # ビューサイズ変更時の対応
        self._setup_view_resize_handler(target_view)
        
    def hide_current(self):
        """現在の通知を非表示"""
        if self.current_ticker:
            self.current_ticker.hide_notification()
            
    def set_view(self, view):
        """view を設定"""
        self.view = view
        
    def set_scene_and_view(self, scene, view):
        """scene と view を設定"""
        self.scene = scene
        self.view = view
        
    def _setup_view_resize_handler(self, target_view):
        """ビューサイズ変更時のハンドラー設定"""
        if hasattr(target_view, 'resizeEvent'):
            original_resize = getattr(target_view, '_original_resize_event', target_view.resizeEvent)
            target_view._original_resize_event = original_resize
            
            def new_resize_event(event):
                original_resize(event)
                # ステータスバーの位置とサイズを更新
                if self.current_ticker:
                    self.current_ticker.position_on_view()
                    
            target_view.resizeEvent = new_resize_event


# ======================== 既存システムとの互換性用ヘルパー ========================

def show_save_notification(parent=None):
    """保存完了通知 - 既存のQMessageBox.information()の代替"""
    # parent は DesktopPyLauncherWindow インスタンスを想定
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_success("保存しました")

def show_export_notification(parent=None):
    """エクスポート完了通知 - 既存のQMessageBox.information()の代替"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_success("エクスポート完了")

def show_export_html_notification(filename: str, parent=None):
    """HTMLエクスポート完了通知"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_success(f"HTMLファイルとしてエクスポートしました: {filename}")

def show_export_error_notification(error_msg: str, parent=None):
    """エクスポートエラー通知"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_error(f"エクスポートエラー: {error_msg}")

def show_project_load_notification(project_name: str, item_count: int, parent=None):
    """プロジェクト読み込み完了通知"""
    if hasattr(parent, 'notification_manager'):
        if item_count > 1:
            parent.notification_manager.show_success(f"プロジェクト '{project_name}' を読み込み、{item_count}個のアイテムをグループ化しました")
        elif item_count == 1:
            parent.notification_manager.show_success("プロジェクトからアイテムを1個読み込みました")
        else:
            parent.notification_manager.show_warning("アイテムが読み込まれませんでした")

def show_error_notification(message: str, parent=None):
    """エラー通知 - 既存のQMessageBox.critical()の代替"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_error(message)

def show_warning_notification(message: str, parent=None):
    """警告通知 - 既存のQMessageBox.warning()の代替"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_warning(message)

def show_info_notification(message: str, parent=None):
    """情報通知 - 既存のQMessageBox.information()の代替"""
    if hasattr(parent, 'notification_manager'):
        parent.notification_manager.show_info(message)

# ------------------------------ __all__ ------------------------------
__all__ = [
    # 基本クラス・型
    "NotificationType", "NotificationTicker", "NotificationManager",
    # 便利なヘルパー関数
    "show_save_notification", "show_export_notification", 
    "show_export_html_notification", "show_export_error_notification",
    "show_project_load_notification", "show_error_notification", 
    "show_warning_notification", "show_info_notification"
]