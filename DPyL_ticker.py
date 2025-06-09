# -*- coding: utf-8 -*-
"""
DPyL_ticker.py ―  desktopPyLauncher通知ティッカーシステム
◎ Qt6 / PyQt6 専用
従来のOKボタン付きダイアログに代わる、ニュースティッカー風通知システム
"""

from __future__ import annotations
import sys
from enum import Enum
from typing import Optional

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, 
    QParallelAnimationGroup, QSequentialAnimationGroup,
    QRect, QSize, pyqtSignal, QObject
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QPainter, QPen, QBrush,
    QLinearGradient, QPixmap, QIcon
)
from PyQt6.QtWidgets import (
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
    scene上に表示される通知ティッカー（QGraphicsProxyWidget経由）
    """
    
    # シグナル定義
    clicked = pyqtSignal()
    
    def __init__(self, scene=None):
        super().__init__()
        self.scene = scene
        self.proxy_widget: Optional[QGraphicsProxyWidget] = None
        self.current_timer: Optional[QTimer] = None
        self.animation_group: Optional[QParallelAnimationGroup] = None
        
        # 初期設定
        self.setup_ui()
        self.setup_animations()
        
    def setup_ui(self):
        """UIの初期設定"""
        # ウィジェットの基本設定
        self.setFixedHeight(50)
        self.setFixedWidth(400)  # 固定幅に設定
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # レイアウト作成
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(15, 5, 15, 5)
        self.main_layout.setSpacing(10)
        
        # アイコンラベル
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 16px;")
        
        # メッセージラベル
        self.message_label = QLabel()
        self.message_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # プログレスバー用のウィジェット
        self.progress_widget = QWidget()
        self.progress_widget.setFixedHeight(2)
        
        # レイアウトに追加
        self.main_layout.addWidget(self.icon_label)
        self.main_layout.addWidget(self.message_label)
        
        # メインコンテナ
        self.container = QWidget()
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
        
    def add_to_scene(self, scene):
        """sceneにプロキシウィジェットとして追加"""
        if self.proxy_widget is None:
            self.proxy_widget = QGraphicsProxyWidget()
            self.proxy_widget.setWidget(self)
            self.proxy_widget.setZValue(9999)  # 最前面に表示
            
        scene.addItem(self.proxy_widget)
        self.scene = scene
        
    def remove_from_scene(self):
        """sceneから削除"""
        if self.proxy_widget and self.scene:
            self.scene.removeItem(self.proxy_widget)
            
    def position_on_scene(self, view_rect):
        """scene上での位置を設定（画面上部中央）"""
        if not self.proxy_widget:
            return
            
        # 画面上部中央に配置
        x = view_rect.center().x() - self.width() / 2
        y = view_rect.top() + 10  # 上部から10px下
        
        self.proxy_widget.setPos(x, y)
        
    def show_notification(self, 
                         message: str, 
                         notification_type: NotificationType = NotificationType.SUCCESS,
                         duration: int = 10000,
                         view_rect=None):
        """
        通知を表示する
        
        Args:
            message: 表示するメッセージ
            notification_type: 通知タイプ
            duration: 表示時間（ミリ秒）
            view_rect: ビューの表示領域（位置決め用）
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
        if view_rect:
            self.position_on_scene(view_rect)
            
        # プログレスバーの設定
        self.progress_widget.setMaximumWidth(self.width())
        self.progress_animation.setDuration(duration)
        self.progress_animation.setStartValue(self.width())
        self.progress_animation.setEndValue(0)
        
        # 表示アニメーション
        self._animate_show()
        
        # プログレスアニメーション開始
        self.progress_animation.start()
        
        # 自動非表示タイマー
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
        """通知タイプに応じてスタイルを設定"""
        type_config = {
            NotificationType.SUCCESS: {
                "icon": "✓",
                "bg_color": "rgba(76, 175, 80, 0.9)",
                "border_color": "#4CAF50",
                "text_color": "#FFFFFF"
            },
            NotificationType.INFO: {
                "icon": "ℹ️",
                "bg_color": "rgba(33, 150, 243, 0.9)",
                "border_color": "#2196F3", 
                "text_color": "#FFFFFF"
            },
            NotificationType.WARNING: {
                "icon": "⚠️",
                "bg_color": "rgba(255, 152, 0, 0.9)",
                "border_color": "#FF9800",
                "text_color": "#FFFFFF"
            },
            NotificationType.ERROR: {
                "icon": "❌",
                "bg_color": "rgba(244, 67, 54, 0.9)", 
                "border_color": "#f44336",
                "text_color": "#FFFFFF"
            }
        }
        
        config = type_config[notification_type]
        
        # アイコン設定
        self.icon_label.setText(config["icon"])
        
        # テキスト色設定
        self.message_label.setStyleSheet(f"color: {config['text_color']};")
        
        # 背景スタイル設定
        style = f"""
        QWidget {{
            background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                        stop: 0 {config["bg_color"]},
                        stop: 1 rgba(0, 0, 0, 0.1));
            border-bottom: 3px solid {config["border_color"]};
            border-radius: 8px;
        }}
        """
        self.container.setStyleSheet(style)
        
    def _animate_show(self):
        """表示アニメーション"""
        # フェードインアニメーション
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        
    def _animate_hide(self):
        """非表示アニメーション"""
        # フェードアウトアニメーション  
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        
        # アニメーション完了後にsceneから削除
        self.fade_animation.finished.connect(self.remove_from_scene)
        self.fade_animation.start()
        
    def _on_click(self, event):
        """クリック時の処理"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self.hide_notification()

class NotificationManager(QObject):
    """
    通知管理クラス
    scene上に通知ティッカーを表示・管理する
    """
    
    def __init__(self, scene=None, view=None):
        super().__init__()
        self.scene = scene
        self.view = view
        self.current_ticker: Optional[NotificationTicker] = None
        
    def show_success(self, message: str, duration: int = 10000):
        """成功通知を表示"""
        self._show_notification(message, NotificationType.SUCCESS, duration)
        
    def show_info(self, message: str, duration: int = 10000):
        """情報通知を表示"""
        self._show_notification(message, NotificationType.INFO, duration)
        
    def show_warning(self, message: str, duration: int = 10000):
        """警告通知を表示"""
        self._show_notification(message, NotificationType.WARNING, duration)
        
    def show_error(self, message: str, duration: int = 10000):
        """エラー通知を表示"""
        self._show_notification(message, NotificationType.ERROR, duration)
        
    def _show_notification(self, message: str, notification_type: NotificationType, duration: int):
        """内部: 通知表示処理"""
        if not self.scene:
            debug_print("[NotificationManager] Scene not set")
            return
            
        # 既存の通知があれば隠す
        if self.current_ticker:
            self.current_ticker.hide_notification()
            
        # 新しい通知ティッカーを作成
        self.current_ticker = NotificationTicker(self.scene)
        self.current_ticker.add_to_scene(self.scene)
        
        # ビューの表示領域を取得
        view_rect = None
        if self.view:
            view_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
            
        self.current_ticker.show_notification(message, notification_type, duration, view_rect)
        
    def hide_current(self):
        """現在の通知を非表示"""
        if self.current_ticker:
            self.current_ticker.hide_notification()
            
    def set_scene_and_view(self, scene, view):
        """scene と view を設定"""
        self.scene = scene
        self.view = view

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