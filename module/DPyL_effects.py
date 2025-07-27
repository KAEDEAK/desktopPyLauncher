# -*- coding: utf-8 -*-
"""
DPyL_effects.py - MainWindow管理エフェクトシステム

MainWindowでエフェクトインスタンスを管理し、
アイテム間で共有する安全な設計
"""

from PySide6.QtWidgets import QGraphicsEffect
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import QTimer, QPropertyAnimation, QEasingCurve, Property, QPointF
import math

__all__ = [
    'LaserRingEffect',
    'RGBShiftVibrateEffect',
    'EffectManager'
]


class LaserRingEffect(QGraphicsEffect):
    """回転するレーザーリングエフェクト"""
    
    def __init__(self, parent=None):
        super().__init__(parent)  # 親オブジェクトを指定
        self._rotation = 0.0
        self._opacity = 0.0
        self._ring_count = 3  # リングの数
        self._is_active = False
        
        # 回転アニメーション
        self._rotation_timer = QTimer(self)  # 親を指定
        self._rotation_timer.timeout.connect(self._update_rotation)
        self._rotation_timer.setInterval(16)  # 60fps
        
        # フェードイン/アウト用アニメーション
        self._fade_animation = QPropertyAnimation(self, b"opacity", self)
        self._fade_animation.setDuration(300)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_animation.finished.connect(self._on_fade_finished)
    
    @Property(float)
    def opacity(self):
        return self._opacity
    
    @opacity.setter
    def opacity(self, value):
        self._opacity = value
        self.update()
    
    def start_effect(self):
        """エフェクト開始"""
        print("[DEBUG] レーザーエフェクト開始")
        self._is_active = True
        self._rotation_timer.start()
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(0.8)
        self._fade_animation.start()
    
    def stop_effect(self):
        """エフェクト停止"""
        print("[DEBUG] レーザーエフェクト停止")
        self._is_active = False
        self._fade_animation.setStartValue(self._opacity)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()
    
    def _on_fade_finished(self):
        """フェードアニメーション完了時"""
        if not self._is_active and self._opacity <= 0:
            self._rotation_timer.stop()
    
    def _update_rotation(self):
        """回転角度更新"""
        if self._is_active:
            self._rotation += 2.0  # 回転速度
            if self._rotation >= 360:
                self._rotation = 0
            self.update()
    
    def draw(self, painter: QPainter):
        """エフェクト描画"""
        # 元のアイテムを描画
        self.drawSource(painter)
        
        if self._opacity <= 0:
            return
        
        # エフェクト描画準備
        painter.save()
        rect = self.sourceBoundingRect()
        center = rect.center()
        
        # 複数のレーザーリングを描画
        for i in range(self._ring_count):
            ring_opacity = self._opacity * (1.0 - i * 0.2)
            if ring_opacity <= 0:
                continue
                
            # リングサイズとオフセット
            ring_scale = 1.2 + i * 0.3
            rotation_offset = i * 120  # 各リングの回転オフセット
            
            self._draw_laser_ring(
                painter, center, rect.width() * ring_scale, 
                self._rotation + rotation_offset, ring_opacity
            )
        
        painter.restore()
    
    def _draw_laser_ring(self, painter: QPainter, center, size, rotation, opacity):
        """個別のレーザーリング描画"""
        painter.save()
        painter.translate(center)
        painter.rotate(rotation)
        
        # レーザー光の色（サイバー風）
        colors = [
            QColor(0, 255, 255, int(255 * opacity)),    # シアン
            QColor(255, 0, 255, int(255 * opacity)),    # マゼンタ
            QColor(0, 255, 0, int(255 * opacity))       # グリーン
        ]
        
        # 円周上にレーザーラインを描画
        laser_count = 12
        for i in range(laser_count):
            angle = (360 / laser_count) * i
            color = colors[i % len(colors)]
            
            painter.save()
            painter.rotate(angle)
            
            # グラデーションペン
            pen = QPen(color, 2)
            painter.setPen(pen)
            
            # レーザーライン描画（QPointFを使用）
            start_radius = size * 0.4
            end_radius = size * 0.6
            start_point = QPointF(start_radius, 0)
            end_point = QPointF(end_radius, 0)
            painter.drawLine(start_point, end_point)
            
            painter.restore()
        
        painter.restore()


class RGBShiftVibrateEffect(QGraphicsEffect):
    """RGBずらし + 振動エフェクト"""
    
    def __init__(self, parent=None):
        super().__init__(parent)  # 親オブジェクトを指定
        self._shift_amount = 0.0
        self._vibration_x = 0.0
        self._vibration_y = 0.0
        self._effect_timer = QTimer(self)  # 親を指定
        self._effect_timer.timeout.connect(self._update_effect)
        self._effect_timer.setInterval(16)
        self._effect_time = 0
        self._is_active = False
    
    def trigger_effect(self):
        """エフェクトをトリガー"""
        print("[DEBUG] RGBエフェクト開始")
        self._is_active = True
        self._effect_time = 0
        self._effect_timer.start()
        # 500ms後に自動停止
        QTimer.singleShot(500, self._stop_effect)
    
    def _stop_effect(self):
        """エフェクト停止"""
        print("[DEBUG] RGBエフェクト停止")
        self._is_active = False
        self._effect_timer.stop()
        self._shift_amount = 0
        self._vibration_x = 0
        self._vibration_y = 0
        self.update()
    
    def _update_effect(self):
        """エフェクト更新"""
        if not self._is_active:
            return
            
        self._effect_time += 16
        
        # RGBずらし量（減衰）
        decay = max(0, 1.0 - self._effect_time / 500.0)
        self._shift_amount = 5.0 * decay
        
        # 振動（高周波）
        vibration_intensity = 3.0 * decay
        freq = 0.5  # 振動周波数
        self._vibration_x = vibration_intensity * math.sin(self._effect_time * freq)
        self._vibration_y = vibration_intensity * math.cos(self._effect_time * freq * 1.3)
        
        self.update()
    
    def draw(self, painter: QPainter):
        """エフェクト描画"""
        if self._shift_amount <= 0:
            # エフェクトなしの場合は通常描画
            painter.save()
            painter.translate(self._vibration_x, self._vibration_y)
            self.drawSource(painter)
            painter.restore()
            return
        
        painter.save()
        
        # 振動オフセット適用
        painter.translate(self._vibration_x, self._vibration_y)
        
        # RGBずらしエフェクト
        # 赤チャンネル
        painter.save()
        painter.translate(-self._shift_amount, 0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        self.drawSource(painter)
        painter.restore()
        
        # 緑チャンネル（通常位置）
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        self.drawSource(painter)
        painter.restore()
        
        # 青チャンネル
        painter.save()
        painter.translate(self._shift_amount, 0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        self.drawSource(painter)
        painter.restore()
        
        painter.restore()


class EffectManager:
    """
    エフェクト管理クラス
    MainWindowで作成・管理する
    """
    
    def __init__(self, parent=None):
        self.parent = parent
        self._active_hover_items = set()
        self._active_click_items = set()
        
        print(f"[DEBUG] EffectManager created with parent: {parent}")
    
    def _create_laser_effect(self):
        """新しいレーザーエフェクトを作成"""
        print("[DEBUG] 新しいレーザーエフェクトを作成")
        return LaserRingEffect(parent=self.parent)
    
    def _create_rgb_effect(self):
        """新しいRGBエフェクトを作成"""
        print("[DEBUG] 新しいRGBエフェクトを作成")
        return RGBShiftVibrateEffect(parent=self.parent)
    
    def enable_hover_effects(self, item):
        """アイテムにホバーエフェクトを有効化"""
        try:
            print(f"[DEBUG] ホバーエフェクト有効化: {item.__class__.__name__}")
            
            # ホバーイベントを有効化
            item.setAcceptHoverEvents(True)
            
            # 現在のエフェクトをクリア
            current_effect = item.graphicsEffect()
            if current_effect:
                item.setGraphicsEffect(None)
            
            # 新しいレーザーエフェクトを作成・適用
            laser_effect = self._create_laser_effect()
            item.setGraphicsEffect(laser_effect)
            laser_effect.start_effect()
            
            # アクティブアイテムとして追跡
            self._active_hover_items.add(item)
            
            print(f"[DEBUG] ホバーエフェクト適用成功")
            return True
            
        except Exception as e:
            print(f"[ERROR] ホバーエフェクト適用エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def disable_hover_effects(self, item):
        """アイテムからホバーエフェクトを無効化"""
        try:
            print(f"[DEBUG] ホバーエフェクト無効化: {item.__class__.__name__}")
            
            # 現在のエフェクトを取得して停止
            current_effect = item.graphicsEffect()
            if current_effect and isinstance(current_effect, LaserRingEffect):
                print("[DEBUG] レーザーエフェクト停止")
                current_effect.stop_effect()
            
            # エフェクトをクリア（遅延実行）
            def clear_effect():
                try:
                    if item in self._active_hover_items:
                        item.setGraphicsEffect(None)
                        self._active_hover_items.discard(item)
                        print(f"[DEBUG] ホバーエフェクトクリア完了")
                except Exception as e:
                    print(f"[ERROR] ホバーエフェクトクリアエラー: {e}")
            
            QTimer.singleShot(350, clear_effect)
            return True
            
        except Exception as e:
            print(f"[ERROR] ホバーエフェクト無効化エラー: {e}")
            return False
    
    def trigger_click_effect(self, item):
        """アイテムでクリックエフェクトをトリガー"""
        try:
            print(f"[DEBUG] クリックエフェクト開始: {item.__class__.__name__}")
            
            # 現在のエフェクトをクリア
            current_effect = item.graphicsEffect()
            if current_effect:
                item.setGraphicsEffect(None)
            
            # 新しいRGBエフェクトを作成・適用
            rgb_effect = self._create_rgb_effect()
            item.setGraphicsEffect(rgb_effect)
            rgb_effect.trigger_effect()
            
            # アクティブアイテムとして追跡
            self._active_click_items.add(item)
            
            # エフェクト終了後の処理
            def restore_effect():
                try:
                    if item in self._active_click_items:
                        self._active_click_items.discard(item)
                        
                        # エフェクトをクリア
                        item.setGraphicsEffect(None)
                        
                        # マウスがまだ上にある場合はホバーエフェクトに復帰
                        if hasattr(item, 'isUnderMouse') and item.isUnderMouse():
                            print(f"[DEBUG] ホバーエフェクトに復帰")
                            self.enable_hover_effects(item)
                        else:
                            print(f"[DEBUG] エフェクトクリア完了")
                except Exception as e:
                    print(f"[ERROR] エフェクト復帰エラー: {e}")
            
            QTimer.singleShot(550, restore_effect)
            
            print(f"[DEBUG] クリックエフェクト適用成功")
            return True
            
        except Exception as e:
            print(f"[ERROR] クリックエフェクト適用エラー: {e}")
            import traceback
            traceback.print_exc()
            return False


# ========================================
# MainWindowでの使用例
# ========================================
"""
# desktopPyLauncher.py の MainWindow クラスに追加

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... 既存の初期化 ...
        
        # エフェクトマネージャーを作成
        self.effect_manager = EffectManager(parent=self)
        
    # ... 既存のメソッド ...

# DPyL_classes.py の CanvasItem (基底)とか LauncherItem(一部)に追加
# ただし上書きに注意

def hoverEnterEvent(self, event):
    super().hoverEnterEvent(event)
    # MainWindow の effect_manager を取得
    main_window = self.scene().views()[0].window()
    if hasattr(main_window, 'effect_manager'):
        main_window.effect_manager.enable_hover_effects(self)

def hoverLeaveEvent(self, event):
    super().hoverLeaveEvent(event)
    main_window = self.scene().views()[0].window()
    if hasattr(main_window, 'effect_manager'):
        main_window.effect_manager.disable_hover_effects(self)

def mousePressEvent(self, event):
    super().mousePressEvent(event)
    main_window = self.scene().views()[0].window()
    if hasattr(main_window, 'effect_manager'):
        main_window.effect_manager.trigger_click_effect(self)
"""