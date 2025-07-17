# -*- coding: utf-8 -*-
"""
DPyL_shapes.py ― カスタム描画アイテム（Qt6 / PySide6 専用）
--------------------------------------------------------------------
機能:
  - MarkerItemを継承したカスタム描画クラス
  - 矩形描画クラス（色、枠、背景、角丸設定可能）
  - 矢印描画クラス（角度、直線/ポリゴン切替、ドラッグ回転可能）
  - リンク機能はMarkerItemから継承
"""

from __future__ import annotations
import math
from typing import Any, Dict
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QMessageBox, QSpinBox,
    QColorDialog, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsPolygonItem
)
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QPainterPath, QPolygonF
from PySide6.QtCore import Qt, QPointF, QRectF

from DPyL_marker import MarkerItem
from DPyL_utils import warn


# ==============================================================
#   CustomDrawingItem（カスタム描画基底クラス）
# ==============================================================
class CustomDrawingItem(MarkerItem):
    """
    MarkerItemを継承したカスタム描画基底クラス
    - 枠の色、太さ、背景色、透明度、角丸設定可能
    - リンク機能はMarkerItemから継承
    """
    TYPE_NAME = "custom_drawing"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        # デフォルト値を設定
        d.setdefault("frame_color", "#FF0000")
        d.setdefault("frame_width", 2)
        d.setdefault("background_color", "#FFFFFF")
        d.setdefault("background_transparent", True)
        d.setdefault("corner_radius", 0)
        
        super().__init__(d, text_color=text_color)
        
        # カスタム描画用のプロパティ
        self.frame_color = d.get("frame_color", "#FF0000")
        self.frame_width = d.get("frame_width", 2)
        self.background_color = d.get("background_color", "#FFFFFF")
        self.background_transparent = d.get("background_transparent", True)
        self.corner_radius = d.get("corner_radius", 0)
        
        # 描画を更新
        self._update_drawing()

    def _update_drawing(self):
        """描画スタイルを更新（サブクラスでオーバーライド）"""
        pass

    def resize_content(self, w: int, h: int):
        """リサイズ時の処理"""
        super().resize_content(w, h)
        # リサイズ後に境界矩形と矢印を再描画
        self._update_drawing()

    def on_edit(self):
        """編集ダイアログを開く"""
        dlg = CustomDrawingEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # プロパティを更新
            self.frame_color = self.d.get("frame_color", "#FF0000")
            self.frame_width = self.d.get("frame_width", 2)
            self.background_color = self.d.get("background_color", "#FFFFFF")
            self.background_transparent = self.d.get("background_transparent", True)
            self.corner_radius = self.d.get("corner_radius", 0)
            
            # キャプションを更新
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPlainText(self.d.get("caption", ""))
            
            # 描画を更新
            self._update_drawing()
            self._update_caption_visibility()
        
        # モード切替
        if self.scene() and self.scene().views():
            mw = self.scene().views()[0].window()
            self.set_run_mode(not mw.a_edit.isChecked())


# ==============================================================
#   RectItem（矩形描画クラス）
# ==============================================================
class RectItem(CustomDrawingItem):
    """
    矩形を描画するクラス
    CustomDrawingItemのプロパティをもとに矩形を描画
    """
    TYPE_NAME = "rect"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        # キャプションのデフォルト設定
        if "caption" not in d and "id" in d:
            d["caption"] = f"RECT-{d['id']}"
        
        super().__init__(d, text_color=text_color)

    def _update_drawing(self):
        """矩形の描画スタイルを更新"""
        if not hasattr(self, '_rect_item'):
            return
            
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        
        # 矩形のサイズを設定
        self._rect_item.setRect(0, 0, w, h)
        
        # ペンの設定（枠線）
        pen = QPen()
        pen.setColor(QColor(self.frame_color))
        pen.setWidth(self.frame_width)
        self._rect_item.setPen(pen)
        
        # ブラシの設定（背景）
        if self.background_transparent:
            self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        else:
            brush = QBrush(QColor(self.background_color))
            self._rect_item.setBrush(brush)

    def _update_frame_visibility(self):
        """
        枠線表示・非表示の制御
        RectItemは実行モードでも常に表示する
        """
        if not hasattr(self, "_rect_item"):
            return

        # RectItemは常に矩形を表示（実行モード・編集モード問わず）
        self._rect_item.setVisible(True)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == self.GraphicsItemChange.ItemSelectedHasChanged:
            pen = self._rect_item.pen()
            if self.isSelected():
                pen.setColor(QColor("#ff3355"))
            else:
                pen.setColor(QColor(self.frame_color))
            pen.setWidth(self.frame_width)
            self._rect_item.setPen(pen)
        return result
        
# ==============================================================
#   ArrowItem（矢印描画クラス）
# ==============================================================
class ArrowItem(CustomDrawingItem):
    """
    矢印を描画するクラス
    - 角度設定可能（右向きが0度）
    - 直線/ポリゴン切替可能
    - 矢印先端部のドラッグで回転可能
    """
    TYPE_NAME = "arrow"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        # 矢印固有のデフォルト値を設定
        d.setdefault("angle", 0)  # 右向きが0度
        d.setdefault("is_line", False)  # False=ポリゴン, True=直線
        
        # キャプションのデフォルト設定
        if "caption" not in d and "id" in d:
            d["caption"] = f"ARROW-{d['id']}"
        
        # 矢印固有のプロパティを先に初期化
        self.angle = d.get("angle", 0)
        self.is_line = d.get("is_line", False)
        
        # 回転用のドラッグポイントを初期化
        self._arrow_tip = None
        
        # 親クラスの初期化（この時点で_update_drawing()が呼ばれる）
        super().__init__(d, text_color=text_color)
        
        # ドラッグポイントを作成
        self._create_arrow_tip()

        # 初期状態では実行モードなのでドラッグポイントを非表示
        if self._arrow_tip:
            self._arrow_tip.setVisible(False)

        # 描画を再更新（ドラッグポイント位置含む）
        self._update_drawing()

    def _create_arrow_tip(self):
        """矢印先端のドラッグポイントを作成"""
        if not hasattr(self, '_arrow_tip') or self._arrow_tip is None:
            self._arrow_tip = ArrowTipGrip(self)
            if self.scene():
                self.scene().addItem(self._arrow_tip)
        self._update_arrow_tip_position()

    def _update_arrow_tip_position(self):
        """矢印先端のドラッグポイント位置を更新（楕円上に配置）"""
        if not hasattr(self, '_arrow_tip') or not self._arrow_tip:
            return
            
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        
        # 矢印の先端位置を計算（楕円との交点）
        center_x = w / 2
        center_y = h / 2
        
        # 楕円との交点までの距離を計算（半径）
        radius = self._calculate_arrow_length(w, h, self.angle) / 2
        
        angle_rad = math.radians(self.angle)
        tip_x = center_x + radius * math.cos(angle_rad)
        tip_y = center_y + radius * math.sin(angle_rad)
        
        # シーン座標に変換
        scene_pos = self.mapToScene(QPointF(tip_x, tip_y))
        self._arrow_tip.setPos(scene_pos)

    def _update_drawing(self):
        """矢印の描画を更新"""
        if not hasattr(self, '_rect_item'):
            return
            
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        
        # 背景矩形の設定（編集モードでは境界を表示）
        self._rect_item.setRect(0, 0, w, h)
        if hasattr(self, 'run_mode') and not self.run_mode:
            # 編集モード：点線で境界矩形を表示
            pen = QPen()
            pen.setColor(QColor("#888888"))  # グレー
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)  # 点線
            self._rect_item.setPen(pen)
            self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))  # 透明
        else:
            # 実行モード：境界矩形を非表示
            self._rect_item.setPen(QPen(Qt.PenStyle.NoPen))
            self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        
        # 既存の矢印アイテムを削除
        for child in self.childItems():
            if hasattr(child, '_is_arrow_path'):
                child.setParentItem(None)
                if child.scene():
                    child.scene().removeItem(child)
        
        # 新しい矢印を描画
        if self.is_line:
            self._draw_line_arrow()
        else:
            self._draw_polygon_arrow()
        
        # ドラッグポイント位置を更新
        self._update_arrow_tip_position()

    def _draw_line_arrow(self):
        """直線矢印を描画（→）"""
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        
        path = QPainterPath()
        
        # 矢印の基本形状（横向き）
        center_x = w / 2
        center_y = h / 2
        
        # 矢印の長さを楕円との交点で計算
        arrow_length = self._calculate_arrow_length(w, h, self.angle) * 0.9  # 90%に制限してマージンを確保
        arrow_head_size = arrow_length * 0.3
        
        # 矢印の線
        start_x = center_x - arrow_length / 2
        end_x = center_x + arrow_length / 2
        path.moveTo(start_x, center_y)
        path.lineTo(end_x, center_y)
        
        # 矢印の頭部
        path.lineTo(end_x - arrow_head_size * 0.3, center_y - arrow_head_size * 0.2)
        path.moveTo(end_x, center_y)
        path.lineTo(end_x - arrow_head_size * 0.3, center_y + arrow_head_size * 0.2)
        
        # 回転変換を適用
        angle_rad = math.radians(self.angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        # 新しいパスを作成して回転
        rotated_path = QPainterPath()
        
        # パスを構成する線分を個別に回転
        lines = [
            (start_x, center_y, end_x, center_y),
            (end_x, center_y, end_x - arrow_head_size * 0.3, center_y - arrow_head_size * 0.2),
            (end_x, center_y, end_x - arrow_head_size * 0.3, center_y + arrow_head_size * 0.2)
        ]
        
        for x1, y1, x2, y2 in lines:
            # 回転変換
            x1_rot = (x1 - center_x) * cos_a - (y1 - center_y) * sin_a + center_x
            y1_rot = (x1 - center_x) * sin_a + (y1 - center_y) * cos_a + center_y
            x2_rot = (x2 - center_x) * cos_a - (y2 - center_y) * sin_a + center_x
            y2_rot = (x2 - center_x) * sin_a + (y2 - center_y) * cos_a + center_y
            
            rotated_path.moveTo(x1_rot, y1_rot)
            rotated_path.lineTo(x2_rot, y2_rot)
        
        # パスアイテムを作成
        path_item = QGraphicsPathItem(rotated_path, self)
        path_item._is_arrow_path = True
        pen = QPen()
        pen.setColor(QColor(self.frame_color))
        pen.setWidth(self.frame_width)
        path_item.setPen(pen)

    def _calculate_arrow_length(self, w: int, h: int, angle: float) -> float:
        """
        矢印の進行方向と四角形に内接する楕円との交点を求めて矢印の長さを計算
        
        Args:
            w: 四角形の幅
            h: 四角形の高さ  
            angle: 矢印の角度（度数法）
            
        Returns:
            楕円との交点までの距離（中心からの半径）
        """
        if w <= 0 or h <= 0:
            return min(w, h) * 0.8  # フォールバック
            
        # 楕円の半軸（四角形に内接する楕円）
        a = w / 2  # 横軸の半径
        b = h / 2  # 縦軸の半径
        
        # 角度をラジアンに変換
        angle_rad = math.radians(angle)
        cos_theta = math.cos(angle_rad)
        sin_theta = math.sin(angle_rad)
        
        # 楕円の方程式: (x/a)² + (y/b)² = 1
        # 角度θの直線上の点(r*cos(θ), r*sin(θ))が楕円上にある時のr:
        # r = 1 / sqrt((cos(θ)/a)² + (sin(θ)/b)²)
        try:
            denominator = (cos_theta / a) ** 2 + (sin_theta / b) ** 2
            if denominator > 0:
                r = 1.0 / math.sqrt(denominator)
                # 直径にして返す（中心から両端まで）
                return r * 2
            else:
                return min(w, h) * 0.8  # フォールバック
        except (ZeroDivisionError, ValueError):
            return min(w, h) * 0.8  # フォールバック

    def _draw_polygon_arrow(self):
        """ポリゴン矢印を描画（⇒）"""
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        
        center_x = w / 2
        center_y = h / 2
        
        # 矢印の長さを楕円との交点で計算
        arrow_length = self._calculate_arrow_length(w, h, self.angle) * 0.85  # 85%に制限してマージンを確保
        arrow_width = arrow_length * 0.4
        arrow_head_length = arrow_length * 0.3
        
        # 矢印の形状を定義（横向き）
        points = [
            QPointF(center_x - arrow_length/2, center_y - arrow_width/4),
            QPointF(center_x + arrow_length/2 - arrow_head_length, center_y - arrow_width/4),
            QPointF(center_x + arrow_length/2 - arrow_head_length, center_y - arrow_width/2),
            QPointF(center_x + arrow_length/2, center_y),
            QPointF(center_x + arrow_length/2 - arrow_head_length, center_y + arrow_width/2),
            QPointF(center_x + arrow_length/2 - arrow_head_length, center_y + arrow_width/4),
            QPointF(center_x - arrow_length/2, center_y + arrow_width/4),
        ]
        
        # 回転変換を適用
        angle_rad = math.radians(self.angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        rotated_points = []
        for point in points:
            x = point.x() - center_x
            y = point.y() - center_y
            new_x = x * cos_a - y * sin_a + center_x
            new_y = x * sin_a + y * cos_a + center_y
            rotated_points.append(QPointF(new_x, new_y))
        
        # ポリゴンアイテムを作成
        polygon = QPolygonF(rotated_points)
        polygon_item = QGraphicsPolygonItem(polygon, self)
        polygon_item._is_arrow_path = True
        
        # ペンとブラシの設定
        pen = QPen()
        pen.setColor(QColor(self.frame_color))
        pen.setWidth(self.frame_width)
        polygon_item.setPen(pen)
        
        if not self.background_transparent:
            brush = QBrush(QColor(self.background_color))
            polygon_item.setBrush(brush)
        else:
            polygon_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_angle(self, angle: float):
        """角度を設定して再描画"""
        self.angle = angle
        self.d["angle"] = angle
        self._update_drawing()

    def itemChange(self, change, value):
        """アイテム変更時の処理"""
        result = super().itemChange(change, value)
        
        # 位置変更時にドラッグポイントも移動
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            if hasattr(self, '_arrow_tip') and self._arrow_tip:
                self._update_arrow_tip_position()
        
        # シーン変更時にドラッグポイントも追加/削除
        elif change == self.GraphicsItemChange.ItemSceneChange:
            if value is not None:  # シーンに追加
                if hasattr(self, '_arrow_tip') and self._arrow_tip and self._arrow_tip.scene() is None:
                    value.addItem(self._arrow_tip)
            else:  # シーンから削除
                if hasattr(self, '_arrow_tip') and self._arrow_tip and self._arrow_tip.scene():
                    self._arrow_tip.scene().removeItem(self._arrow_tip)
        
        return result

    def on_edit(self):
        """編集ダイアログを開く"""
        dlg = ArrowEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # プロパティを更新
            self.frame_color = self.d.get("frame_color", "#FF0000")
            self.frame_width = self.d.get("frame_width", 2)
            self.background_color = self.d.get("background_color", "#FFFFFF")
            self.background_transparent = self.d.get("background_transparent", True)
            self.corner_radius = self.d.get("corner_radius", 0)
            self.angle = self.d.get("angle", 0)
            self.is_line = self.d.get("is_line", False)
            
            # キャプションを更新
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPlainText(self.d.get("caption", ""))
            
            # 描画を更新
            self._update_drawing()
            self._update_caption_visibility()
        
        # モード切替
        if self.scene() and self.scene().views():
            mw = self.scene().views()[0].window()
            self.set_run_mode(not mw.a_edit.isChecked())

    def _update_frame_visibility(self):
        """
        枠線表示・非表示の制御
        ArrowItemは実行モードでも常に表示する
        （矢印パスアイテムは_update_drawing()で管理されるため、ここでは何もしない）
        """
        # ArrowItemでは矢印自体が_rect_itemではなく、
        # _draw_line_arrow()や_draw_polygon_arrow()で作成されるパスアイテムなので、
        # 特別な処理は不要（常に表示される）
        pass

    def set_run_mode(self, run: bool):
        """
        実行(True)/編集(False)モード切替
        ArrowTipGripの表示制御と境界矩形の表示制御を含む
        """
        super().set_run_mode(run)
        
        # ドラッグポイントは編集モードでのみ表示
        if hasattr(self, '_arrow_tip') and self._arrow_tip:
            self._arrow_tip.setVisible(not run)
        
        # 境界矩形の表示を更新（編集モードでは点線表示、実行モードでは非表示）
        self._update_drawing()


# ==============================================================
#   ArrowTipGrip（矢印先端のドラッグポイント）
# ==============================================================
class ArrowTipGrip(QGraphicsEllipseItem):
    """矢印先端のドラッグポイント"""
    
    def __init__(self, arrow_item: ArrowItem):
        super().__init__()
        self.arrow_item = arrow_item
        self.setRect(-4, -4, 8, 8)
        self.setBrush(QBrush(QColor("#FF6600")))
        self.setPen(QPen(QColor("#CC4400")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(10000)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        
        self._dragging = False
        self._start_pos = QPointF()

    def mousePressEvent(self, event):
        """マウス押下時の処理"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_pos = event.scenePos()
            event.accept()

    def mouseMoveEvent(self, event):
        """マウス移動時の処理（角度計算と更新）"""
        if not self._dragging:
            return
            
        # 矢印アイテムの中心座標を取得
        arrow_rect = self.arrow_item.boundingRect()
        arrow_center = self.arrow_item.mapToScene(arrow_rect.center())
        
        # マウス位置から角度を計算
        mouse_pos = event.scenePos()
        dx = mouse_pos.x() - arrow_center.x()
        dy = mouse_pos.y() - arrow_center.y()
        
        # 角度を計算（度数法）
        angle = math.degrees(math.atan2(dy, dx))
        
        # 矢印の角度を更新
        self.arrow_item.set_angle(angle)
        
        event.accept()

    def mouseReleaseEvent(self, event):
        """マウス離放時の処理"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()

    def setVisible(self, visible: bool):
        """表示/非表示の設定"""
        # 編集モードでのみ表示
        if hasattr(self.arrow_item, 'run_mode'):
            super().setVisible(visible and not self.arrow_item.run_mode)
        else:
            super().setVisible(visible)


# ==============================================================
#   編集ダイアログ
# ==============================================================
class CustomDrawingEditDialog(QDialog):
    """カスタム描画アイテムの編集ダイアログ"""
    
    def __init__(self, item: CustomDrawingItem):
        super().__init__()
        self.setWindowTitle("カスタム描画設定")
        self.item = item
        self.d = item.d
        self._build_ui()

    def _build_ui(self):
        vbox = QVBoxLayout(self)

        # ID
        h_id = QHBoxLayout()
        h_id.addWidget(QLabel("ID"))
        self.ed_id = QLineEdit(str(self.d.get("id", "")))
        h_id.addWidget(self.ed_id, 1)
        vbox.addLayout(h_id)

        # キャプション
        h_cap = QHBoxLayout()
        h_cap.addWidget(QLabel("キャプション"))
        self.ed_cap = QLineEdit(self.d.get("caption", ""))
        h_cap.addWidget(self.ed_cap, 1)
        vbox.addLayout(h_cap)

        # キャプション表示設定
        self.chk_show_caption = QCheckBox("キャプションを表示")
        self.chk_show_caption.setChecked(bool(self.d.get("show_caption", True)))
        vbox.addWidget(self.chk_show_caption)

        # 枠線色
        h_frame_color = QHBoxLayout()
        h_frame_color.addWidget(QLabel("枠線色"))
        self.btn_frame_color = QPushButton()
        self.btn_frame_color.setStyleSheet(f"background-color: {self.d.get('frame_color', '#FF0000')}")
        self.btn_frame_color.clicked.connect(self._choose_frame_color)
        h_frame_color.addWidget(self.btn_frame_color)
        vbox.addLayout(h_frame_color)

        # 枠線の太さ
        h_frame_width = QHBoxLayout()
        h_frame_width.addWidget(QLabel("枠線の太さ"))
        self.spin_frame_width = QSpinBox()
        self.spin_frame_width.setRange(1, 20)
        self.spin_frame_width.setValue(self.d.get("frame_width", 2))
        h_frame_width.addWidget(self.spin_frame_width)
        vbox.addLayout(h_frame_width)

        # 背景透明
        self.chk_bg_transparent = QCheckBox("背景を透明にする")
        self.chk_bg_transparent.setChecked(bool(self.d.get("background_transparent", True)))
        self.chk_bg_transparent.toggled.connect(self._on_bg_transparent_changed)
        vbox.addWidget(self.chk_bg_transparent)

        # 背景色
        h_bg_color = QHBoxLayout()
        h_bg_color.addWidget(QLabel("背景色"))
        self.btn_bg_color = QPushButton()
        self.btn_bg_color.setStyleSheet(f"background-color: {self.d.get('background_color', '#FFFFFF')}")
        self.btn_bg_color.clicked.connect(self._choose_bg_color)
        h_bg_color.addWidget(self.btn_bg_color)
        vbox.addLayout(h_bg_color)

        # 角丸
        h_corner = QHBoxLayout()
        h_corner.addWidget(QLabel("角丸半径"))
        self.spin_corner = QSpinBox()
        self.spin_corner.setRange(0, 50)
        self.spin_corner.setValue(self.d.get("corner_radius", 0))
        h_corner.addWidget(self.spin_corner)
        vbox.addLayout(h_corner)

        # ジャンプ先ID（MarkerItemから継承）
        h_jump = QHBoxLayout()
        h_jump.addWidget(QLabel("ジャンプ先ID"))
        self.combo_jump = QComboBox()
        self.combo_jump.addItem("（なし）", None)
        
        # シーン内のマーカーを検索
        scene = self.item.scene()
        if scene:
            markers = []
            for it in scene.items():
                if isinstance(it, MarkerItem):
                    try:
                        mid = int(it.d.get("id", 0))
                        caption = it.d.get("caption", f"MARKER-{mid}")
                        markers.append((mid, caption))
                    except (TypeError, ValueError):
                        continue
            markers.sort(key=lambda x: x[0])
            for mid, caption in markers:
                display_text = f"{caption} (ID {mid})"
                self.combo_jump.addItem(display_text, mid)

        # 現在のジャンプ先を選択
        current_jump = self.d.get("jump_id")
        if current_jump is None:
            self.combo_jump.setCurrentIndex(0)
        else:
            idx = self.combo_jump.findData(current_jump)
            if idx >= 0:
                self.combo_jump.setCurrentIndex(idx)
            else:
                self.combo_jump.setCurrentIndex(0)

        h_jump.addWidget(self.combo_jump, 1)
        vbox.addLayout(h_jump)

        # 背景透明状態を反映
        self._on_bg_transparent_changed()

        # OK / Cancel ボタン
        h_btn = QHBoxLayout()
        h_btn.addStretch(1)
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        ng = QPushButton("Cancel")
        ng.clicked.connect(self.reject)
        h_btn.addWidget(ok)
        h_btn.addWidget(ng)
        vbox.addLayout(h_btn)

        self.resize(380, 400)

    def _choose_frame_color(self):
        """枠線色を選択"""
        color = QColorDialog.getColor(QColor(self.d.get("frame_color", "#FF0000")), self)
        if color.isValid():
            self.d["frame_color"] = color.name()
            self.btn_frame_color.setStyleSheet(f"background-color: {color.name()}")

    def _choose_bg_color(self):
        """背景色を選択"""
        color = QColorDialog.getColor(QColor(self.d.get("background_color", "#FFFFFF")), self)
        if color.isValid():
            self.d["background_color"] = color.name()
            self.btn_bg_color.setStyleSheet(f"background-color: {color.name()}")

    def _on_bg_transparent_changed(self):
        """背景透明チェックボックスの変更時処理"""
        transparent = self.chk_bg_transparent.isChecked()
        self.btn_bg_color.setEnabled(not transparent)

    def accept(self):
        """OK ボタン押下時の処理"""
        # ID
        try:
            new_id = int(self.ed_id.text().strip())
        except ValueError:
            QMessageBox.warning(self, "入力エラー", "ID は整数で入力してください。")
            return
        self.d["id"] = new_id

        # キャプション
        self.d["caption"] = self.ed_cap.text().strip() or f"SHAPE-{new_id}"

        # その他のプロパティ
        self.d["show_caption"] = self.chk_show_caption.isChecked()
        self.d["frame_width"] = self.spin_frame_width.value()
        self.d["background_transparent"] = self.chk_bg_transparent.isChecked()
        self.d["corner_radius"] = self.spin_corner.value()

        # ジャンプ先ID
        selected_jump = self.combo_jump.currentData()
        if selected_jump is None:
            self.d["jump_id"] = None
        else:
            self.d["jump_id"] = int(selected_jump)

        super().accept()


class ArrowEditDialog(CustomDrawingEditDialog):
    """矢印描画アイテムの編集ダイアログ"""
    
    def __init__(self, item: ArrowItem):
        super().__init__(item)
        self.setWindowTitle("矢印設定")
        self._add_arrow_specific_ui()

    def _add_arrow_specific_ui(self):
        """矢印固有のUI要素を追加"""
        layout = self.layout()
        
        # OK/Cancelボタンの前に挿入するため、最後の要素を取得
        last_item = layout.takeAt(layout.count() - 1)
        
        # 角度設定
        h_angle = QHBoxLayout()
        h_angle.addWidget(QLabel("角度 (度)"))
        self.spin_angle = QSpinBox()
        self.spin_angle.setRange(-360, 360)
        self.spin_angle.setValue(int(self.d.get("angle", 0)))
        h_angle.addWidget(self.spin_angle)
        layout.addLayout(h_angle)

        # 直線モード
        self.chk_is_line = QCheckBox("直線モード（→ スタイル）")
        self.chk_is_line.setChecked(bool(self.d.get("is_line", False)))
        layout.addWidget(self.chk_is_line)

        # OK/Cancelボタンを再追加
        layout.addItem(last_item)

    def accept(self):
        """OK ボタン押下時の処理"""
        # 親クラスの処理を実行
        super().accept()
        
        # 矢印固有のプロパティを追加で保存
        self.d["angle"] = self.spin_angle.value()
        self.d["is_line"] = self.chk_is_line.isChecked()


# ==============================================================
#   __all__ エクスポート
# ==============================================================
__all__ = [
    "RectItem", 
    "ArrowItem"
]
