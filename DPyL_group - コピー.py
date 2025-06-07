# -*- coding: utf-8 -*-
"""
DPyL_group.py ― GroupItem / Group管理（Qt6 / PyQt6 専用）
--------------------------------------------------------------------
機能:
  - MarkerItemから継承したGroupItem
  - 複数のアイテムをグループ化して一括管理
  - グループの移動時に内包するアイテムも一緒に移動
  - グループのリサイズ（枠の大きさのみ、内包アイテムの倍率ではない）
  - グループ化の解除
"""

from __future__ import annotations
from typing import Any, Optional, Dict, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QTextEdit, QMessageBox, QSpinBox
)
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt, QPointF, QRectF

from DPyL_marker import MarkerItem
from DPyL_utils import warn
from PyQt6.QtWidgets import QGraphicsTextItem, QGraphicsRectItem, QGraphicsItem


# ==============================================================
#   GroupItem
# ==============================================================
class GroupItem(MarkerItem):
    TYPE_NAME = "group"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        super().__init__(d, text_color=text_color)
        
        # グループに含まれるアイテムのIDリスト（永続化用）
        self.child_item_ids: List[int] = d.get("child_item_ids", [])
        
        # 実際のアイテム参照リスト（実行時のみ）
        self.child_items: List[QGraphicsItem] = []
        
        # 前回の位置を記録（位置変更時の差分計算用）
        self._last_group_pos = QPointF(d.get("x", 0), d.get("y", 0))
        
        # グループの枠を視覚的に分かりやすくする
        self._rect_item.setBrush(QBrush(QColor(100, 150, 255, 30)))  # 薄い青
        pen = self._rect_item.pen()
        pen.setColor(QColor(100, 150, 255, 150))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)  # 破線
        self._rect_item.setPen(pen)
        
        # 初期状態では最背面に配置
        self.setZValue(-1000)
        
    def add_item(self, item: QGraphicsItem):
        """アイテムをグループに追加"""
        if item not in self.child_items:
            self.child_items.append(item)
            
            # IDを保存（永続化用）
            # 既存のアイテムにIDがない場合は、位置とタイプで識別
            item_id = None
            if hasattr(item, 'd'):
                if 'id' not in item.d:
                    # IDがない場合は、ハッシュベースのIDを生成
                    id_source = f"{item.d.get('type', 'unknown')}_{item.d.get('x', 0)}_{item.d.get('y', 0)}_{item.d.get('caption', '')}"
                    item_id = abs(hash(id_source)) % 1000000  # 100万以下の正数
                    item.d['id'] = item_id
                    warn(f"[GroupItem] Generated ID {item_id} for item {item.d.get('type', 'unknown')}")
                else:
                    item_id = item.d['id']
                    
                if item_id is not None and item_id not in self.child_item_ids:
                    self.child_item_ids.append(item_id)
                    warn(f"[GroupItem] Added item with ID {item_id} to group")
            
            self._update_bounds()
            # バウンディングボックス更新後に現在位置を記録
            self._last_group_pos = self.pos()
            
            warn(f"[GroupItem] Group now contains {len(self.child_items)} items")
            
    def remove_item(self, item: QGraphicsItem):
        """アイテムをグループから削除"""
        if item in self.child_items:
            self.child_items.remove(item)
            
            # IDからも削除
            if hasattr(item, 'd') and 'id' in item.d:
                item_id = item.d['id']
                if item_id in self.child_item_ids:
                    self.child_item_ids.remove(item_id)
            
            self._update_bounds()
            # バウンディングボックス更新後に現在位置を記録
            self._last_group_pos = self.pos()
            
    def _update_bounds(self):
        """GroupItem / 内包するアイテムに基づいてバウンディングボックスを更新"""
        if not self.child_items:
            # 子アイテムがない場合はデフォルトサイズ
            self.resize_content(100, 100)
            return
            
        # 全アイテムのバウンディングボックスを計算
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        for item in self.child_items:
            try:
                rect = item.sceneBoundingRect()
                min_x = min(min_x, rect.left())
                min_y = min(min_y, rect.top())
                max_x = max(max_x, rect.right())
                max_y = max(max_y, rect.bottom())
            except Exception:
                continue
                
        if min_x == float('inf'):
            return
            
        # マージンを追加
        margin = 50
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin
        
        # GroupItemの位置とサイズを更新
        width = max_x - min_x
        height = max_y - min_y
        
        # 位置変更時に子アイテムを動かさないよう一時的に無効化
        self._updating_bounds = True
        self.setPos(min_x, min_y)
        self._last_group_pos = QPointF(min_x, min_y)  # 現在位置を記録
        self.d["x"] = min_x
        self.d["y"] = min_y
        self.d["width"] = width
        self.d["height"] = height
        self.resize_content(width, height)
        self._updating_bounds = False
        
    def restore_child_items(self, scene):
            """
            ロード時に子アイテムの関係を復元
            """
            self.child_items = []
            
            for item_id in self.child_item_ids:
                # シーン内のアイテムを検索
                for scene_item in scene.items():
                    if (isinstance(scene_item, (CanvasItem, VideoItem)) and 
                        hasattr(scene_item, 'd') and 
                        scene_item.d.get('id') == item_id):
                        
                        self.child_items.append(scene_item)
                        break
            
            # 復元時も_last_group_posを初期化
            self._last_group_pos = self.pos()
                    
    def mousePressEvent(self, event):
        """マウス押下時の処理"""
        # 現在位置を記録
        self._last_pos = self.pos()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        """マウス移動時の処理"""
        # setPos メソッドで統一的に処理されるため、追加処理は不要
        super().mouseMoveEvent(event)
                    
    def mouseReleaseEvent(self, event):
        """マウス離放時の処理"""
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        """アイテム変更時の処理"""
        # シーンに追加された時の初期化
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if value is not None:  # シーンに追加された
                # 現在位置を記録
                self._last_group_pos = self.pos()
                warn(f"[GroupItem] Added to scene, initialized position: ({self._last_group_pos.x():.1f}, {self._last_group_pos.y():.1f})")
        
        # 位置確定時の処理
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # バウンディングボックス更新中は子アイテムを移動しない
            if not getattr(self, '_updating_bounds', False):
                current_pos = self.pos()
                delta = current_pos - self._last_group_pos
                
                # 微小な移動でも確実に同期させる（条件を削除）
                if hasattr(self, 'child_items') and self.child_items and (delta.x() != 0 or delta.y() != 0):
                    warn(f"[GroupItem] Position changed: delta=({delta.x():.3f}, {delta.y():.3f}), child_items={len(self.child_items)}")
                    
                    for i, item in enumerate(self.child_items):
                        try:
                            old_item_pos = item.pos()
                            new_item_pos = old_item_pos + delta
                            
                            # デバッグログ（より詳細な精度で表示）
                            warn(f"[GroupItem] Moving child {i}: {old_item_pos.x():.3f},{old_item_pos.y():.3f} -> {new_item_pos.x():.3f},{new_item_pos.y():.3f}")
                            
                            # 子アイテムの移動時にスナップ処理を無効化
                            if hasattr(item, '__class__') and item.__class__.__name__ == 'GroupItem':
                                # 子GroupItemの場合は、バウンディングボックス更新フラグを設定
                                item._updating_bounds = True
                                item.setPos(new_item_pos)
                                item._last_group_pos = new_item_pos
                                item._updating_bounds = False
                            else:
                                # 通常のアイテムの場合、スナップを無効化して移動
                                # 子アイテムにグループ移動中フラグを設定
                                item._group_moving = True
                                
                                # 一時的にロード中フラグを設定してスナップ処理をスキップ
                                scene = item.scene()
                                if scene and scene.views():
                                    win = scene.views()[0].window()
                                    old_loading_flag = getattr(win, '_loading_in_progress', False)
                                    win._loading_in_progress = True  # スナップ処理を無効化
                                    item.setPos(new_item_pos)
                                    win._loading_in_progress = old_loading_flag  # 元に戻す
                                else:
                                    item.setPos(new_item_pos)
                                
                                # グループ移動中フラグをクリア
                                item._group_moving = False
                            
                            # 子アイテムの座標もデータに反映
                            if hasattr(item, 'd'):
                                item.d["x"] = new_item_pos.x()
                                item.d["y"] = new_item_pos.y()
                                
                        except Exception as e:
                            warn(f"Failed to move child item {i} in itemChange: {e}")
                
                # 現在位置を記録
                self._last_group_pos = current_pos
            
            # データに座標を保存
            pos = self.pos()
            self.d["x"], self.d["y"] = pos.x(), pos.y()
            # グリップ位置を更新
            if hasattr(self, '_update_grip_pos'):
                self._update_grip_pos()
                
        return super().itemChange(change, value)
        
    def resize_content(self, w: int, h: int):
        """
        リサイズ処理：枠の大きさのみ変更
        （内包アイテムの倍率変更ではない）
        """
        self.d["width"], self.d["height"] = w, h
        self._rect_item.setRect(0, 0, w, h)
        
        # キャプション位置を更新
        if hasattr(self, "cap_item"):
            self.cap_item.setPos(0, h)
        self._update_grip_pos()
        
    def on_activate(self):
        """
        実行モード時のダブルクリック動作：
        グループ内の全アイテムを選択
        """
        if self.scene():
            # 他の選択を解除
            for item in self.scene().selectedItems():
                item.setSelected(False)
                
            # グループ内アイテムを選択
            for item in self.child_items:
                if item.scene():
                    item.setSelected(True)

    def on_edit(self):
        """
        編集モード時のダブルクリックで設定ダイアログを表示
        """
        dlg = GroupEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # ダイアログ内で self.d を直接更新しているので、キャプションのみ再描画
            self.cap_item.setPlainText(self.d.get("caption", ""))
            # キャプション表示設定を更新
            self._update_caption_visibility()
        
        # モード切替
        if self.scene() and self.scene().views():
            mw = self.scene().views()[0].window()
            self.set_run_mode(not mw.a_edit.isChecked())

    def get_save_data(self):
        """保存用データを取得"""
        data = self.d.copy()
        data["child_item_ids"] = self.child_item_ids.copy()
        return data


# ==============================================================
#   GroupEditDialog
# ==============================================================

class GroupEditDialog(QDialog):
    def __init__(self, group_item, parent=None):
        super().__init__(parent)
        # ★重要：self.item を設定★
        self.item = group_item
        self.d = group_item.d
        
        self.setWindowTitle("グループ設定")
        self.setModal(True)
        self.resize(400, 500)
        self._build_ui()

    def _build_ui(self):
        """GroupEditDialogのUI構築"""
        vbox = QVBoxLayout(self)
        
        # キャプション設定
        h_caption = QHBoxLayout()
        h_caption.addWidget(QLabel("キャプション:"))
        self.edit_caption = QLineEdit(self.d.get("caption", ""))
        h_caption.addWidget(self.edit_caption, 1)
        vbox.addLayout(h_caption)
        
        # キャプション表示設定
        self.chk_show_caption = QCheckBox("キャプションを表示")
        self.chk_show_caption.setChecked(self.d.get("show_caption", True))
        vbox.addWidget(self.chk_show_caption)  # addWidget を使用
        
        # Z値（レイヤー順序）設定
        h_z_value = QHBoxLayout()
        h_z_value.addWidget(QLabel("レイヤー順序:"))
        self.spin_z_value = QSpinBox()
        self.spin_z_value.setRange(-10000, 10000)
        self.spin_z_value.setValue(int(self.d.get("z", -1000)))
        h_z_value.addWidget(self.spin_z_value)
        h_z_value.addStretch(1)
        vbox.addLayout(h_z_value)
        
        # グループの説明
        vbox.addWidget(QLabel("説明:"))
        self.edit_description = QTextEdit()
        self.edit_description.setMaximumHeight(80)
        self.edit_description.setPlaceholderText("グループの説明...")
        self.edit_description.setPlainText(self.d.get("description", ""))
        vbox.addWidget(self.edit_description)
        
        # 子アイテム一覧
        vbox.addWidget(QLabel("含まれるアイテム:"))
        self.list_children = QListWidget()
        self.list_children.setMaximumHeight(120)
        vbox.addWidget(self.list_children)
        
        # 子アイテム管理ボタン
        h_children = QHBoxLayout()
        self.btn_remove_child = QPushButton("選択アイテムを除外")
        self.btn_remove_child.clicked.connect(self._remove_selected_child)
        self.btn_refresh = QPushButton("リスト更新")
        self.btn_refresh.clicked.connect(self._refresh_child_list)
        h_children.addWidget(self.btn_remove_child)
        h_children.addWidget(self.btn_refresh)
        vbox.addLayout(h_children)
        
        # 統計情報
        self.lbl_stats = QLabel()
        vbox.addWidget(self.lbl_stats)
        
        vbox.addStretch(1)
        
        # OK/Cancelボタン
        h_buttons = QHBoxLayout()
        h_buttons.addStretch(1)
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        h_buttons.addWidget(ok_btn)
        h_buttons.addWidget(cancel_btn)
        vbox.addLayout(h_buttons)
        
        # 初期データロード
        self._refresh_child_list()

    def _refresh_child_list(self):
        """子アイテムリストを更新"""
        self.list_children.clear()
        
        if not hasattr(self.item, 'child_items'):
            self.lbl_stats.setText("子アイテム: 0個")
            self.btn_remove_child.setEnabled(False)
            return
        
        child_count = len(self.item.child_items)
        
        for i, child_item in enumerate(self.item.child_items):
            try:
                # アイテムの基本情報を取得
                item_type = getattr(child_item, 'TYPE_NAME', 'unknown')
                item_caption = child_item.d.get("caption", "")
                item_path = child_item.d.get("path", "")
                
                # 表示名を構築
                if item_caption:
                    display_name = f"{item_caption} ({item_type})"
                elif item_path:
                    filename = Path(item_path).name
                    display_name = f"{filename} ({item_type})"
                else:
                    display_name = f"アイテム{i+1} ({item_type})"
                
                # リストアイテムを作成
                list_item = QListWidgetItem(display_name)
                list_item.setData(Qt.ItemDataRole.UserRole, child_item)
                self.list_children.addItem(list_item)
                
            except Exception as e:
                # エラーがあっても続行
                error_item = QListWidgetItem(f"エラー: {str(e)[:30]}...")
                self.list_children.addItem(error_item)
        
        # 統計情報を更新
        self.lbl_stats.setText(f"子アイテム: {child_count}個")
        self.btn_remove_child.setEnabled(child_count > 0)

    def _remove_selected_child(self):
        """選択されたアイテムをグループから除外"""
        current_item = self.list_children.currentItem()
        if not current_item:
            QMessageBox.information(self, "選択エラー", "除外するアイテムを選択してください。")
            return
        
        child_item = current_item.data(Qt.ItemDataRole.UserRole)
        if not child_item:
            return
        
        # 確認ダイアログ
        reply = QMessageBox.question(
            self, "確認",
            "選択されたアイテムをグループから除外しますか？\n"
            "（アイテム自体は削除されません）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # グループから除外
                if hasattr(self.item, 'remove_item'):
                    self.item.remove_item(child_item)
                
                # リストを更新
                self._refresh_child_list()
                
                QMessageBox.information(self, "完了", "アイテムをグループから除外しました。")
                
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"除外に失敗しました: {str(e)}")

    def accept(self):
        """OKボタンが押されたときの処理"""
        try:
            # 基本設定を保存
            self.d["caption"] = self.edit_caption.text().strip()
            self.d["show_caption"] = self.chk_show_caption.isChecked()
            self.d["description"] = self.edit_description.toPlainText().strip()
            
            # Z値を保存して実際に適用
            z_value = self.spin_z_value.value()
            self.d["z"] = z_value
            self.item.setZValue(z_value)
            
            # グリップのZ値も更新（グリップは常に親より前面）
            if hasattr(self.item, 'grip') and self.item.grip:
                self.item.grip.update_zvalue()
            
            # GroupItemに変更を反映
            if hasattr(self.item, '_update_caption_visibility'):
                self.item._update_caption_visibility()
            
            # キャプション更新
            if hasattr(self.item, 'cap_item') and self.item.cap_item:
                self.item.cap_item.setPlainText(self.d.get("caption", ""))
            
            super().accept()
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"設定の保存に失敗しました: {str(e)}")

# ========================================
# 3. GroupItem.restore_child_items メソッドの修正
# ========================================

def restore_child_items(self, scene):
    """
    ロード時に子アイテムの関係を復元
    """
    child_ids = self.d.get("child_item_ids", [])
    if not child_ids:
        return
    
    self.child_items = []
    self.child_item_ids = []
    
    for item in scene.items():
        # CanvasItem、VideoItem、または TYPE_NAME を持つアイテムをチェック
        if not hasattr(item, 'd') or not hasattr(item, 'TYPE_NAME'):
            continue
            
        # CanvasItemまたはVideoItemかどうかをチェック
        is_canvas_item = isinstance(item, CanvasItem)
        is_video_item = hasattr(item, 'TYPE_NAME') and item.TYPE_NAME == "video"
        
        if not (is_canvas_item or is_video_item):
            continue
            
        item_id = item.d.get("id")
        if item_id in child_ids:
            self.child_items.append(item)
            self.child_item_ids.append(item_id)
            # グループフラグを設定
            setattr(item, '_in_group', True)
    
    warn(f"[GROUP] Restored {len(self.child_items)} child items")

# ==============================================================
#   exports
# ==============================================================
__all__ = [
    "GroupItem",
    "GroupEditDialog",
]