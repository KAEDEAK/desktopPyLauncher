# -*- coding: utf-8 -*-
"""
DPyL_marker.py ― MarkerItem / MarkerEditDialog（Qt6 / PyQt6 専用）
--------------------------------------------------------------------
機能:
  - Warp Point（マーカー）をキャンバス上に配置
  - マーカー固有のプロパティを管理（ID, ジャンプ先ID, キャプション, 開始地点フラグ, 表示位置, キャプション表示・非表示）
  - ダブルクリック（実行モード時）で、ジャンプ先ID に対応するマーカーを表示領域の中央 or 左上に移動
  - 編集モード時にダイアログで各プロパティを編集可能
  - キャプション表示・非表示の設定に対応
"""

from __future__ import annotations
from typing import Any, Optional, Dict
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QMessageBox
)
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt, QPointF, QRectF

from DPyL_classes import CanvasItem
from DPyL_utils import warn
from PyQt6.QtWidgets import QGraphicsTextItem, QGraphicsRectItem, QGraphicsItem


# ==============================================================
#   MarkerItem
# ==============================================================
class MarkerItem(CanvasItem):
    TYPE_NAME = "marker"

    def __init__(self, d: Dict[str, Any], *, text_color=None):
        super().__init__(d, cb_resize=None, text_color=text_color)

        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))

        # 背景矩形（透過した赤い枠）
        self._rect_item = QGraphicsRectItem(0, 0, w, h, parent=self)
        pen = self._rect_item.pen()
        pen.setColor(QColor(200, 50, 50, 200))
        pen.setWidth(2)
        self._rect_item.setPen(pen)
        self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))

        # キャプション表示用 TextItem
        self.cap_item = QGraphicsTextItem(self.d.get("caption", ""), parent=self)
        self.cap_item.setDefaultTextColor(QColor("#ffffff"))
        font = self.cap_item.font()
        font.setPointSize(8)
        self.cap_item.setFont(font)
        self.cap_item.setPos(0, h)

        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setZValue(d.get("z", 0))

        # キャプション表示設定のデフォルト値を設定
        if "show_caption" not in self.d:
            self.d["show_caption"] = True

        self._update_grip_pos()
        self._update_caption_visibility()
        self._update_frame_visibility()

    # -------------------- キャプション処理を抑制 --------------------
    def init_caption(self):
        """
        基底クラスのキャプション生成を無効化するために、何もしない。
        MarkerItem では独自に cap_item（下端表示）を使うので、基底のものは不要。
        """
        return

    def boundingRect(self) -> QRectF:
        w = int(self.d.get("width", 32))
        h = int(self.d.get("height", 32))
        cap_item = getattr(self, "cap_item", None)
        if isinstance(cap_item, QGraphicsItem):
            cap_h = cap_item.boundingRect().height()
        else:
            cap_h = 0

        return QRectF(0, 0, w, h + cap_h)

    def resize_content(self, w: int, h: int):
        """
        リサイズ時の処理：枠線サイズとキャプション位置を更新
        """
        self.d["width"], self.d["height"] = w, h
        self._rect_item.setRect(0, 0, w, h)
        # キャプション位置を更新（マーカーの下端に配置）
        if hasattr(self, "cap_item"):
            self.cap_item.setPos(0, h)
        self._update_grip_pos()

    def set_run_mode(self, run: bool):
        """
        実行(True)/編集(False)モード切替
        キャプションと枠線の表示を制御
        """
        self.run_mode = run
        self.set_editable(not run)
        self._update_caption_visibility()
        self._update_frame_visibility()

    def set_editable(self, editable: bool):
        """
        編集可能状態の設定
        """
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, editable)
        
        # グリップ表示制御
        if hasattr(self, "grip"):
            self.grip.setVisible(editable)
        if hasattr(self, "_update_grip_pos"):
            self._update_grip_pos()

    def _update_caption_visibility(self):
        """
        キャプション表示・非表示の制御
        """
        if not hasattr(self, "cap_item"):
            return

        show_caption = self.d.get("show_caption", True)
        
        if self.run_mode:
            # 実行モード
            if show_caption:
                self.cap_item.setVisible(True)
                self.cap_item.setOpacity(1.0)  # 通常表示
            else:
                self.cap_item.setVisible(False)  # 非表示
        else:
            # 編集モード
            self.cap_item.setVisible(True)  # 常に表示
            if show_caption:
                self.cap_item.setOpacity(1.0)  # 通常表示
            else:
                self.cap_item.setOpacity(0.5)  # 半透明表示

    def _update_frame_visibility(self):
        """
        枠線表示・非表示の制御
        """
        if not hasattr(self, "_rect_item"):
            return

        if self.run_mode:
            # 実行モードでは枠線を非表示
            self._rect_item.setVisible(False)
        else:
            # 編集モードでは枠線を表示
            self._rect_item.setVisible(True)

    def on_activate(self):
        """
        実行モード時のダブルクリック動作：
        d["jump_id"] に設定されたマーカーID を探し、見つかればそのマーカーの位置へビューを移動する。
        align に応じて、「左上に合わせる」「中央に合わせる」を実装。
        """
        jump_id = self.d.get("jump_id")
        if jump_id is None:
            QMessageBox.information(None, "Jump", "ジャンプ先IDが設定されていません。")
            return
        scene = self.scene()
        if not scene:
            return
        target_item: Optional[MarkerItem] = None
        for it in scene.items():
            if isinstance(it, MarkerItem) and it.d.get("id") == jump_id:
                target_item = it
                break
        if target_item is None:
            QMessageBox.warning(None, "Jump", f"ID={jump_id} のマーカーが見つかりません。")
            return

        view = scene.views()[0]
        mw = view.window()
        scene_pos = target_item.scenePos()
        w = int(target_item.d.get("width", 32))
        h = int(target_item.d.get("height", 32))

        align = self.d.get("align", "左上")
        # 左上／中央の実装は centerOn で同じ扱いにしている
        view.centerOn(scene_pos.x() + w/2, scene_pos.y() + h/2)

    def on_edit(self):
        """
        編集モード時のダブルクリックで設定ダイアログを表示
        """
        dlg = MarkerEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # ダイアログ内で self.d を直接更新しているので、キャプションのみ再描画
            self.cap_item.setPlainText(self.d.get("caption", ""))
            # キャプション表示設定を更新
            self._update_caption_visibility()
        mw = self.scene().views()[0].window()
        self.set_run_mode(not mw.a_edit.isChecked())

    def itemChange(self, change, value):
        """
        位置変更時に self.d["x"], self.d["y"] を更新し、グリップ位置を更新
        """
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.d["x"], self.d["y"] = self.pos().x(), self.pos().y()
            self._update_grip_pos()
        return super().itemChange(change, value)

# ==============================================================
#   MarkerEditDialog
# ==============================================================
class MarkerEditDialog(QDialog):
    """
    マーカーの各プロパティを編集するダイアログ
      - ID（編集可能。ただし重複チェックは行わない）
      - キャプション
      - キャプション表示・非表示設定
      - ジャンプ先ID（プルダウンで既存マーカーを選択）
      - 開始地点にする（チェックボックス）
      - 表示位置（左上／中央 プルダウン）
    """
    def __init__(self, item: MarkerItem):
        super().__init__(item.scene().views()[0])
        self.setWindowTitle("マーカー設定")
        self.item = item
        self.d = item.d
        self._build_ui()

    def _build_ui(self):
        vbox = QVBoxLayout(self)

        # ID
        h_id = QHBoxLayout()
        h_id.addWidget(QLabel("マーカーID"))
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

        # ジャンプ先ID（ここを QLineEdit → QComboBox に変更）
        h_jump = QHBoxLayout()
        h_jump.addWidget(QLabel("ジャンプ先ID"))
        # --- 変更: QComboBox を使う ---
        self.combo_jump = QComboBox()
        # 「なし」を先頭に登録。データとして None を保持
        self.combo_jump.addItem("（なし）", None)

        # シーン内のすべての MarkerItem を検索し、ID:キャプション の形式で追加
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
            # ID の順でソートして表示
            markers.sort(key=lambda x: x[0])
            for mid, caption in markers:
                display_text = f"{caption} (ID {mid})"
                self.combo_jump.addItem(display_text, mid)

        # 初期選択: d["jump_id"] に該当する index を探して設定
        current_jump = self.d.get("jump_id")
        if current_jump is None:
            self.combo_jump.setCurrentIndex(0)
        else:
            # data が mid と一致するアイテムを探す
            idx = self.combo_jump.findData(current_jump)
            if idx >= 0:
                self.combo_jump.setCurrentIndex(idx)
            else:
                # 仮に既存リストにない ID の場合は一番上を選択
                self.combo_jump.setCurrentIndex(0)

        h_jump.addWidget(self.combo_jump, 1)
        vbox.addLayout(h_jump)

        # 開始地点にする（チェックボックス）
        self.chk_start = QCheckBox("開始地点にする")
        self.chk_start.setChecked(bool(self.d.get("is_start", False)))
        vbox.addWidget(self.chk_start)

        # 表示位置（左上／中央）
        h_align = QHBoxLayout()
        h_align.addWidget(QLabel("表示位置"))
        self.combo_align = QComboBox()
        self.combo_align.addItems(["左上", "中央"])
        current_align = self.d.get("align", "左上")
        self.combo_align.setCurrentText(current_align)
        h_align.addWidget(self.combo_align, 1)
        vbox.addLayout(h_align)

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

        self.resize(380, 280)

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
        self.d["caption"] = self.ed_cap.text().strip() or f"MARKER-{new_id}"

        # キャプション表示・非表示設定
        self.d["show_caption"] = self.chk_show_caption.isChecked()

        # ジャンプ先ID：コンボの data() を取得
        selected_jump = self.combo_jump.currentData()
        if selected_jump is None:
            self.d["jump_id"] = None
        else:
            # comboData は int として登録しているはずなので、そのままセット
            self.d["jump_id"] = int(selected_jump)

        # 開始地点フラグ
        self.d["is_start"] = self.chk_start.isChecked()

        # 表示位置
        self.d["align"] = self.combo_align.currentText()

        super().accept()