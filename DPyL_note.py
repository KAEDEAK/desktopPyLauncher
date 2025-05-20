# -*- coding: utf-8 -*-
"""
DPyL_note.py ― NoteItem / NoteEditDialog
◎ Qt6 / PyQt6 専用
--------------------------------------------------------------------
* テキスト or Markdown 表示を切替え可能
  - self.format : "text" / "markdown"
  - self.text   : 本文文字列
* Markdown は python-markdown で HTML へ変換し QTextDocument.setHtml() で描画
  → <span style="color:#ff0000"> のようなインライン CSS も有効
* 実行モード中はドラッグでスクロール
* 編集モード中はダブルクリックで NoteEditDialog
* CanvasResizeGrip に連動してリサイズ可
"""

from __future__ import annotations

import base64
from typing import Any, List

import markdown                         # pip install markdown
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsTextItem,
    QGraphicsSceneMouseEvent, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QSpinBox, QCheckBox,
    QSplitter, QScrollArea, QWidget
)
from PyQt6.QtGui import (
    QColor, QBrush, QPen, QFont, QTextDocument
)
from PyQt6.QtCore import Qt, QPointF, QRectF

# ───────── internal modules ───────────────────────────────────────────
from DPyL_classes import CanvasItem, CanvasResizeGrip
from DPyL_utils   import warn, b64e, b64d                        # 既存 util

# markdown 拡張をまとめておく
MD_EXT: List[str] = [
    "extra", "sane_lists", "smarty", "tables",
]

# =====================================================================
#   NoteItem
# =====================================================================
class NoteItem(CanvasItem):
    TYPE_NAME = "note"

    # --------------------------------------------------------------
    def __init__(self, d: dict[str, Any] | None = None, cb_resize=None):
        super().__init__(d, cb_resize)

        # JSON -> インスタンスプロパティ
        self.format: str  = self.d.get("format",     "text")    # "text"/"markdown"
        self.text:   str  = self.d.get("text",       "New Note")
        self.fill_bg: bool = self.d.get("fill_background", False)

        # スクロール位置
        self.scroll_offset: int = 0

        # サイズ
        w = int(self.d.get("width",  240))
        h = int(self.d.get("height", 120))

        # --- clip 用矩形 (ItemClipsChildrenToShape) ---
        self.clip_item = QGraphicsRectItem(0, 0, w, h, parent=self)
        self.clip_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)

        # --- テキスト本体 ---
        self.txt_item = QGraphicsTextItem(parent=self.clip_item)
        self.txt_item.setPos(0, 0)
        self.txt_item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        # --- 背景矩形 (枠線/塗り) ---
        self._rect_item.setRect(0, 0, w, h)

        # 初回描画
        self._apply_text()

        # 編集/実行モードの切替反映
        self.set_editable(getattr(self, "editable", True))

    # --------------------------------------------------------------
    # public helpers
    # --------------------------------------------------------------
    def resize_content(self, w: int, h: int):
        """CanvasResizeGrip から呼ばれる。"""
        self.clip_item.setRect(0, 0, w, h)
        self._rect_item.setRect(0, 0, w, h)
        self._apply_text()

    # --------------------------------------------------------------
    # internal
    # --------------------------------------------------------------
    def _apply_text(self):
        """self.text / self.format を QTextDocument に反映"""
        w = int(self.d.get("width",  240))
        h = int(self.d.get("height", 120))

        doc: QTextDocument = self.txt_item.document()

        # ユーザ指定の既定フォントカラー
        color_hex: str = self.d.get("color", "#ffffff")

        # ===== 既定色は setHtml / setPlainText より先に仕込む！ =====
        # これを後から呼ぶと HTML 全体が上塗りされて <span style="…"> が死にます
        self.txt_item.setDefaultTextColor(QColor(color_hex))
        # ===========================================================

        if self.format == "markdown":
            # python-markdown → HTML → setHtml()
            html = markdown.markdown(
                self.text,
                extensions=MD_EXT,
                output_format="html5"
            )
            doc.setHtml(html)
        else:
            # プレーンテキスト
            doc.setPlainText(self.text)

        # フォントサイズ
        font = self.txt_item.font()
        font.setPointSize(int(self.d.get("fontsize", 14)))
        self.txt_item.setFont(font)

        # 折り返し幅
        doc.setTextWidth(w)

        # 背景
        if self.fill_bg:
            bgcol = QColor(self.d.get("bgcolor", "#777777"))
            self._rect_item.setBrush(QBrush(bgcol))
            self._rect_item.setPen(QPen(Qt.GlobalColor.black))
            self._rect_item.setZValue(-1)
        else:
            self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._rect_item.setPen(QPen(Qt.PenStyle.NoPen))

        # スクロール最大
        self.scroll_max = max(0, int(doc.size().height()) - h)
        self.set_scroll(self.scroll_offset)

        self.prepareGeometryChange()
        self.update()

    # --------------------------------------------------------------
    # scrolling (run-mode drag)
    # --------------------------------------------------------------
    def set_scroll(self, offset: int):
        offset = max(0, min(offset, getattr(self, "scroll_max", 0)))
        self.scroll_offset = offset
        self.txt_item.setY(-offset)

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent):
        if getattr(self, "run_mode", False) and ev.button() == Qt.MouseButton.LeftButton:
            self._drag_start_y = ev.scenePos().y()
            self._start_offset = self.scroll_offset
            self._dragging = True
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QGraphicsSceneMouseEvent):
        if getattr(self, "_dragging", False) and getattr(self, "run_mode", False):
            dy = ev.scenePos().y() - self._drag_start_y
            self.set_scroll(self._start_offset - int(dy))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QGraphicsSceneMouseEvent):
        if getattr(self, "_dragging", False):
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    # --------------------------------------------------------------
    # double-click = open editor (edit-mode only)
    # --------------------------------------------------------------
    def mouseDoubleClickEvent(self, ev: QGraphicsSceneMouseEvent):
        if getattr(self, "run_mode", False):
            ev.ignore()
            return

        dlg = NoteEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # dialog が self.d を直接更新するので再取り込み
            self.format = self.d.get("format", "text")
            self.text   = self.d.get("text",   self.text)
            self.fill_bg = self.d.get("fill_background", False)
            self._apply_text()

        ev.accept()

    # --------------------------------------------------------------
    # fixed bounding rect (for selection handles etc.)
    # --------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        w = int(self.d.get("width",  240))
        h = int(self.d.get("height", 120))
        return QRectF(0, 0, w, h)

    def shape(self):
        from PyQt6.QtGui import QPainterPath
        p = QPainterPath()
        p.addRect(self.boundingRect())
        return p

    # --------------------------------------------------------------
    # editable flag toggled by CanvasItem / MainWindow
    # --------------------------------------------------------------
    def set_editable(self, editable: bool):
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable,   editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)

        # 背景は常時表示（ラベル ON/OFF は NoteEditDialog 側で制御）
        self._rect_item.setVisible(True)

        # resize grip
        if hasattr(self, "grip"):
            self.grip.setVisible(editable)
        elif hasattr(self, "_grip"):
            self._grip.setVisible(editable)

# =====================================================================
#   NoteEditDialog
# =====================================================================
class NoteEditDialog(QDialog):
    def __init__(self, item: NoteItem):
        super().__init__()
        self.item = item
        self.d = item.d
        self.setWindowTitle("Note 設定")
        self._build_ui()

    # ----------------------------------------------------------
    def _build_ui(self):
        vbox = QVBoxLayout(self)

        # --- フォーマット / 背景 ON/OFF ---
        self.chk_md = QCheckBox("Markdown で表示")
        self.chk_md.setChecked(self.item.format == "markdown")
        vbox.addWidget(self.chk_md)

        self.chk_bg = QCheckBox("背景を塗りつぶす")
        self.chk_bg.setChecked(self.item.fill_bg)
        vbox.addWidget(self.chk_bg)

        # --- 背景色 / テキスト色 / フォントサイズ ---
        def _hl(label:str, widget):
            h = QHBoxLayout(); h.addWidget(QLabel(label)); h.addWidget(widget, 1)
            return h

        self.ed_bg = QLineEdit(self.d.get("bgcolor", "#777777"))
        vbox.addLayout(_hl("背景色 (#RRGGBB)", self.ed_bg))

        self.ed_color = QLineEdit(self.d.get("color", "#ffffff"))
        vbox.addLayout(_hl("テキスト色 (#RRGGBB)", self.ed_color))

        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 72)
        self.spin_font.setValue(int(self.d.get("fontsize", 14)))
        vbox.addLayout(_hl("フォントサイズ", self.spin_font))

        # --- Splitter: 上 = 編集 / 下 = プレビュー ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.txt_edit = QTextEdit()
        self.txt_edit.setAcceptRichText(False)
        self.txt_edit.setPlainText(self.item.text)
        splitter.addWidget(self.txt_edit)

        prev_container = QWidget()
        prev_v = QVBoxLayout(prev_container)
        prev_v.setContentsMargins(0,0,0,0)
        prev_v.setSpacing(0)
        prev_v.addWidget(QLabel("プレビュー"))
        self.lbl_prev = QLabel()
        self.lbl_prev.setWordWrap(True)
        self.lbl_prev.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_prev.setMinimumHeight(120)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.lbl_prev)
        prev_v.addWidget(scroll)
        splitter.addWidget(prev_container)

        splitter.setSizes([260, 180])
        vbox.addWidget(splitter)

        # リアルタイム更新
        self.chk_md.stateChanged.connect(self._update_preview)
        self.txt_edit.textChanged.connect(self._update_preview)
        self._update_preview()

        # --- OK / Cancel ---
        btn_ok = QPushButton("OK");     btn_ok.clicked.connect(self.accept)
        btn_ng = QPushButton("Cancel"); btn_ng.clicked.connect(self.reject)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(btn_ok); row.addWidget(btn_ng)
        vbox.addLayout(row)

    # ----------------------------------------------------------
    def _update_preview(self):
        """エディタ下段のプレビューを更新"""
        txt = self.txt_edit.toPlainText()

        if self.chk_md.isChecked():
            # Markdown プレビュー
            html = markdown.markdown(
                txt,
                extensions=MD_EXT,
                output_format="html5"
            )
            # 既定色はラッピング div で指定（<span> には負ける）
            color_hex = self.ed_color.text().strip() or "#ffffff"
            html_wrapped = f'<div style="color:{color_hex};">{html}</div>'
            self.lbl_prev.setText(html_wrapped)

            # 背景だけ Stylesheet で指定（font-color は触らない！）
            bg = self.ed_bg.text().strip() or "#777777"
            self.lbl_prev.setStyleSheet(f"background:{bg}; padding:6px;")
        else:
            # プレーンテキスト
            esc = (txt.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
            self.lbl_prev.setText(esc)

    # ----------------------------------------------------------
    def accept(self):
        self.d["format"]          = "markdown" if self.chk_md.isChecked() else "text"
        self.d["text"]            = self.txt_edit.toPlainText()
        self.d["fill_background"] = self.chk_bg.isChecked()
        self.d["bgcolor"]         = self.ed_bg.text().strip() or "#777777"
        self.d["fontsize"]        = self.spin_font.value()
        self.d["color"]           = self.ed_color.text().strip() or "#ffffff"

        # 即時反映
        self.item.format   = self.d["format"]
        self.item.text     = self.d["text"]
        self.item.fill_bg  = self.d["fill_background"]

        super().accept()

# ───────────────────────────── __all__ ───────────────────────────────
__all__ = [
    "NoteItem", "NoteEditDialog",
]
