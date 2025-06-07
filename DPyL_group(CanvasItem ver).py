# -*- coding: utf-8 -*-
"""
DPyL_group.py ― GroupItem（Qt6 / PyQt6 専用）
--------------------------------------------------------------------
機能:
  - 複数のCanvasItemをグループ化して一括操作
  - グループ移動時に子アイテムを追従移動
  - CanvasItemの基底機能を完全継承
"""

from __future__ import annotations
from typing import Any, List
from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen

# 基底クラスと必要なモジュールをインポート
from DPyL_classes import CanvasItem
from DPyL_utils import warn

class GroupItem(CanvasItem):
    """
    複数のCanvasItemをグループ化するためのコンテナアイテム
    - CanvasItemの全機能を継承
    - 子アイテムの一括移動機能
    - グループの枠表示とキャプション表示
    """
    TYPE_NAME = "group"

    def __init__(self, d: dict[str, Any] | None = None, 
                 cb_resize=None, text_color=None):
        """
        GroupItemの初期化
        基底クラスCanvasItemの初期化を呼び出し、グループ固有の属性を追加
        """
        # 基底クラスの初期化を最初に実行
        super().__init__(d, cb_resize, text_color)
        
        # === グループ固有の属性初期化 ===
        self.child_items: List[QGraphicsItem] = []
        self.child_item_ids: List[int] = d.get("child_item_ids", []).copy()
        
        # 位置追跡用（グループ移動時の子アイテム追従に使用）
        self._last_group_pos = QPointF(d.get("x", 0), d.get("y", 0))
        
        # === グループ表示設定 ===
        # 背景の枠線設定（半透明の枠）
        pen = QPen(QColor(100, 100, 255, 150))  # 青い半透明の枠
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)  # 破線スタイル
        self._rect_item.setPen(pen)
        self._rect_item.setBrush(QBrush(QColor(100, 100, 255, 30)))  # 薄い背景
        
        # 初期サイズ設定
        w = int(d.get("width", 200))
        h = int(d.get("height", 100))
        self._rect_item.setRect(0, 0, w, h)
        
        # キャプション表示設定のデフォルト値
        if "show_caption" not in self.d:
            self.d["show_caption"] = True
            
        # グリップ位置の初期化
        self._update_grip_pos()
        
        warn(f"[GroupItem] Initialized: ID={d.get('id', 'none')}, "
             f"caption={d.get('caption', 'none')}, children={len(self.child_item_ids)}")

    def init_caption(self):
        """
        基底クラスのキャプション機能を利用してグループ名を表示
        """
        if "caption" in self.d and self.d.get("show_caption", True):
            super().init_caption()
            # グループキャプションのスタイル調整
            if hasattr(self, "cap_item"):
                font = self.cap_item.font()
                font.setPointSize(10)  # グループ用に少し大きめ
                font.setBold(True)     # 太字
                self.cap_item.setFont(font)
                self.cap_item.setDefaultTextColor(QColor("#0066cc"))  # 青色

    def boundingRect(self) -> QRectF:
        """
        グループのバウンディング矩形を返す
        キャプション分の高さも含める
        """
        w = int(self.d.get("width", 200))
        h = int(self.d.get("height", 100))
        
        caption_h = 0
        if (self.d.get("caption") and self.d.get("show_caption", True) and 
            hasattr(self, "cap_item")):
            caption_h = self.cap_item.boundingRect().height()
            
        return QRectF(0, 0, w, h + caption_h)

    def resize_content(self, w: int, h: int):
        """
        グループサイズ変更時の処理
        """
        self.d["width"], self.d["height"] = w, h
        self._rect_item.setRect(0, 0, w, h)
        
        # キャプション位置を更新
        self.init_caption()
        
        # グリップ位置を更新
        self._update_grip_pos()

    def itemChange(self, change, value):
        """
        アイテム変更時の処理
        グループ移動時に子アイテムを追従移動させる
        """
        # グループ位置変更時の子アイテム追従処理
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            current_pos = self.pos()
            
            # _last_group_posの存在確認（安全チェック）
            if hasattr(self, '_last_group_pos') and self._last_group_pos is not None:
                delta = current_pos - self._last_group_pos
                
                # 移動量が微小な場合はスキップ（無限ループ防止）
                if abs(delta.x()) < 0.1 and abs(delta.y()) < 0.1:
                    return super().itemChange(change, value)
                
                warn(f"[GroupItem] Moving group and {len(self.child_items)} children by delta: ({delta.x():.1f}, {delta.y():.1f})")
                
                # 子アイテムを同じ分だけ移動（グループ移動フラグを設定してスナップを無効化）
                for child_item in self.child_items:
                    if child_item.scene():  # シーンに存在する場合のみ
                        # グループ移動中フラグを設定（スナップを無効化）
                        setattr(child_item, '_group_moving', True)
                        try:
                            old_pos = child_item.pos()
                            new_pos = old_pos + delta
                            child_item.setPos(new_pos)
                            
                            # データも更新
                            if hasattr(child_item, 'd'):
                                child_item.d["x"], child_item.d["y"] = new_pos.x(), new_pos.y()
                        finally:
                            # フラグをクリア
                            setattr(child_item, '_group_moving', False)
            
            # 現在位置を記録
            self._last_group_pos = current_pos
        
        # 基底クラスの処理を実行（座標保存、グリップ更新など）
        return super().itemChange(change, value)

    def setPos(self, *args):
        """
        位置設定時に_last_group_posも更新
        QPointF または x, y 座標の両方に対応
        """
        super().setPos(*args)
        # setPos後の実際の位置を記録
        self._last_group_pos = self.pos()

    def add_item(self, item: QGraphicsItem):
        """
        アイテムをグループに追加
        """
        if item not in self.child_items:
            self.child_items.append(item)
            
            # アイテムのIDを記録（保存用）
            if hasattr(item, 'd') and isinstance(item.d, dict):
                item_id = item.d.get('id')
                if item_id is not None and item_id not in self.child_item_ids:
                    self.child_item_ids.append(item_id)
            
            warn(f"[GroupItem] Added item: {item.__class__.__name__} "
                 f"(ID: {getattr(item, 'd', {}).get('id', 'none')})")
            
            # バウンディングボックスを更新
            self._update_bounds()

    def remove_item(self, item: QGraphicsItem):
        """
        アイテムをグループから削除
        """
        if item in self.child_items:
            self.child_items.remove(item)
            
            # IDリストからも削除
            if hasattr(item, 'd') and isinstance(item.d, dict):
                item_id = item.d.get('id')
                if item_id is not None and item_id in self.child_item_ids:
                    self.child_item_ids.remove(item_id)
            
            warn(f"[GroupItem] Removed item: {item.__class__.__name__}")
            
            # バウンディングボックスを更新
            self._update_bounds()

    def _update_bounds(self):
        """
        子アイテムに基づいてグループのバウンディングボックスを更新
        """
        if not self.child_items:
            # 子アイテムがない場合はデフォルトサイズを維持
            return

        # 子アイテムの全体的なバウンディングボックスを計算
        all_rects = []
        for item in self.child_items:
            if item.scene():  # シーンに存在する場合のみ
                rect = item.sceneBoundingRect()
                all_rects.append(rect)
        
        if all_rects:
            union_rect = all_rects[0]
            for rect in all_rects[1:]:
                union_rect = union_rect.united(rect)
            
            # マージンを追加（子アイテムより少し大きく）
            margin = 20
            union_rect.adjust(-margin, -margin, margin, margin)
            
            # グループの位置とサイズを更新
            old_pos = self.pos()
            new_pos = union_rect.topLeft()
            
            # 位置の更新（_last_group_posも同時に更新）
            self._last_group_pos = new_pos
            self.setPos(new_pos)
            
            # サイズの更新
            new_width = max(100, union_rect.width())
            new_height = max(50, union_rect.height())
            
            self.d["x"] = new_pos.x()
            self.d["y"] = new_pos.y()
            self.d["width"] = new_width
            self.d["height"] = new_height
            
            # 矩形アイテムのサイズを更新
            self._rect_item.setRect(0, 0, new_width, new_height)
            
            # キャプションとグリップの位置を更新
            self.init_caption()
            self._update_grip_pos()
            
            warn(f"[GroupItem] Updated bounds: pos=({new_pos.x():.1f}, {new_pos.y():.1f}), "
                 f"size=({new_width:.1f}x{new_height:.1f})")

    def restore_child_items(self, scene):
        """
        ロード時に子アイテムの関係を復元
        """
        self.child_items = []
        found_items = 0
        
        for item_id in self.child_item_ids:
            # シーン内のアイテムを検索
            for scene_item in scene.items():
                if (isinstance(scene_item, (CanvasItem, VideoItem)) and 
                    hasattr(scene_item, 'd') and 
                    scene_item.d.get('id') == item_id):
                    
                    self.child_items.append(scene_item)
                    found_items += 1
                    break
        
        # 復元時も_last_group_posを初期化
        self._last_group_pos = self.pos()
        
        warn(f"[GroupItem] Restored {found_items}/{len(self.child_item_ids)} child items")

    def set_run_mode(self, run: bool):
        """
        実行(True)/編集(False)モード切替
        基底クラスの処理に加えて、グループ固有の表示制御
        """
        super().set_run_mode(run)
        
        # 実行モードでは枠線を薄く、編集モードでは濃く表示
        if run:
            # 実行モード：目立たない表示
            pen = self._rect_item.pen()
            pen.setColor(QColor(100, 100, 255, 80))
            self._rect_item.setPen(pen)
            self._rect_item.setBrush(QBrush(QColor(100, 100, 255, 15)))
        else:
            # 編集モード：はっきりとした表示
            pen = self._rect_item.pen()
            pen.setColor(QColor(100, 100, 255, 200))
            self._rect_item.setPen(pen)
            self._rect_item.setBrush(QBrush(QColor(100, 100, 255, 40)))

    def on_activate(self):
        """
        実行モード時のダブルクリック動作
        グループ内の全アイテムを選択状態にする
        """
        if self.scene():
            # 現在の選択をクリア
            for item in self.scene().selectedItems():
                item.setSelected(False)
            
            # グループ内のアイテムを選択
            for child in self.child_items:
                if child.scene():
                    child.setSelected(True)

    def on_edit(self):
        """
        編集モード時のダブルクリック動作
        グループ自体を選択状態にする
        """
        if self.scene():
            # 他のアイテムの選択をクリア
            for item in self.scene().selectedItems():
                if item is not self:
                    item.setSelected(False)
            
            # 自分を選択
            self.setSelected(True)

# VideoItemのインポート（循環インポート回避）
try:
    from DPyL_video import VideoItem
except ImportError:
    VideoItem = None

# エクスポート
__all__ = ["GroupItem"]