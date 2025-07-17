# -*- coding: utf-8 -*-
"""
DPyL_group.py ― GroupItem / Group管理（Qt6 / PySide6 専用）
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
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QMessageBox
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Qt, QPointF, QRectF

from DPyL_marker import MarkerItem
from DPyL_utils import warn
from PySide6.QtWidgets import QGraphicsTextItem, QGraphicsRectItem, QGraphicsItem


# ==============================================================
#   GroupItem
# ==============================================================
class GroupItem(MarkerItem):
    TYPE_NAME = "group"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        # _last_group_pos を最初に初期化
        self._last_group_pos = QPointF(d.get("x", 0), d.get("y", 0))
        
        # グループに含まれるアイテムのIDリスト（永続化用）
        self.child_item_ids: List[int] = d.get("child_item_ids", [])
        
        # 実際のアイテム参照リスト（実行時のみ）
        self.child_items: List[QGraphicsItem] = []
        
        # _updating_bounds フラグも初期化
        self._updating_bounds = False
        
        # 親クラスの初期化を呼ぶ
        super().__init__(d, text_color=text_color)
        
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
        """内包するアイテムに基づいてバウンディングボックスを更新"""
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
        """シーンからIDに基づいて子アイテムを復元"""
        self.child_items.clear()
        
        for item_id in self.child_item_ids:
            for scene_item in scene.items():
                if (hasattr(scene_item, 'd') and 
                    scene_item.d.get('id') == item_id and
                    scene_item != self):
                    self.child_items.append(scene_item)
                    break
                    
        # 現在位置を記録（ロード時の初期化）
        self._last_group_pos = self.pos()
                    
    def mousePressEvent(self, event):
        """マウス押下時の処理"""
        # _last_group_pos の安全な初期化
        if not hasattr(self, '_last_group_pos'):
            self._last_group_pos = self.pos()
        
        # 現在位置を記録
        self._last_group_pos = self.pos()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event):
        """マウス移動時の処理"""
        super().mouseMoveEvent(event)
                    
    def mouseReleaseEvent(self, event):
        """マウス離放時の処理"""
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        """アイテム変更時の処理"""
        # _last_group_pos の存在確認を追加
        if not hasattr(self, '_last_group_pos'):
            self._last_group_pos = QPointF(self.d.get("x", 0), self.d.get("y", 0))
        
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
                
                # 微小な移動でも確実に同期させる
                if hasattr(self, 'child_items') and self.child_items and (delta.x() != 0 or delta.y() != 0):
                    warn(f"[GroupItem] Position changed: delta=({delta.x():.3f}, {delta.y():.3f}), child_items={len(self.child_items)}")
                    
                    for i, item in enumerate(self.child_items):
                        try:
                            old_item_pos = item.pos()
                            new_item_pos = old_item_pos + delta
                            
                            warn(f"[GroupItem] Moving child {i}: {old_item_pos.x():.3f},{old_item_pos.y():.3f} -> {new_item_pos.x():.3f},{new_item_pos.y():.3f}")
                            
                            # 子アイテムの移動時にスナップ処理を無効化
                            if hasattr(item, '__class__') and item.__class__.__name__ == 'GroupItem':
                                # 子GroupItemの場合
                                item._updating_bounds = True
                                item.setPos(new_item_pos)
                                if hasattr(item, '_last_group_pos'):
                                    item._last_group_pos = new_item_pos
                                item._updating_bounds = False
                            else:
                                # 通常のアイテムの場合、スナップを無効化して移動
                                item._group_moving = True
                                
                                # 一時的にロード中フラグを設定してスナップ処理をスキップ
                                scene = item.scene()
                                if scene and scene.views():
                                    win = scene.views()[0].window()
                                    old_loading_flag = getattr(win, '_loading_in_progress', False)
                                    win._loading_in_progress = True
                                    item.setPos(new_item_pos)
                                    win._loading_in_progress = old_loading_flag
                                else:
                                    item.setPos(new_item_pos)
                                
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
    """
    グループの各プロパティを編集するダイアログ
    """
    def __init__(self, item):  # GroupItem型注釈を削除（循環インポート回避）
        super().__init__(item.scene().views()[0])
        self.setWindowTitle("グループ設定")
        self.item = item
        self.d = item.d
        self._build_ui()

    def _build_ui(self):
        vbox = QVBoxLayout(self)

        # グループID
        h_id = QHBoxLayout()
        h_id.addWidget(QLabel("グループID"))
        self.ed_id = QLineEdit(str(self.d.get("id", "")))
        h_id.addWidget(self.ed_id, 1)
        vbox.addLayout(h_id)

        # キャプション
        h_cap = QHBoxLayout()
        h_cap.addWidget(QLabel("キャプション"))
        self.ed_cap = QLineEdit(self.d.get("caption", ""))
        h_cap.addWidget(self.ed_cap, 1)
        vbox.addLayout(h_cap)

        # キャプション表示・非表示設定
        self.chk_show_caption = QCheckBox("キャプションを表示")
        self.chk_show_caption.setChecked(bool(self.d.get("show_caption", True)))
        vbox.addWidget(self.chk_show_caption)

        # 含まれるアイテム数の表示
        item_count = len(self.item.child_items)
        info_label = QLabel(f"含まれるアイテム数: {item_count}")
        vbox.addWidget(info_label)

        # バウンディングボックス更新ボタン
        btn_update = QPushButton("バウンディングボックスを更新")
        btn_update.clicked.connect(self._update_bounds)
        vbox.addWidget(btn_update)

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

        self.resize(380, 250)

    def _update_bounds(self):
        """バウンディングボックス更新ボタンの処理"""
        self.item._update_bounds()
        QMessageBox.information(self, "更新完了", "バウンディングボックスを更新しました。")

    def accept(self):
        """
        OK ボタン押下で入力値をセルフ更新
        """
        # ID
        try:
            new_id = int(self.ed_id.text().strip())
        except ValueError:
            QMessageBox.warning(self, "入力エラー", "ID は整数で入力してください。")
            return
        self.d["id"] = new_id

        # キャプション
        self.d["caption"] = self.ed_cap.text().strip() or f"GROUP-{new_id}"

        # キャプション表示・非表示設定
        self.d["show_caption"] = self.chk_show_caption.isChecked()

        super().accept()