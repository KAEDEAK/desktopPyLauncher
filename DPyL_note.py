# -*- coding: utf-8 -*-
"""
DPyL_note.py ― NoteItem / NoteEditDialog (Qt6 / PyQt6 専用)
--------------------------------------------------------------------
機能:
  - テキスト/Markdown 表示切替
    * self.format: "text" または "markdown"
    * self.text: 本文
  - Markdown は python-markdown → HTML 変換後に描画
    * インライン CSS（例: <span style="color:#ff0000">）対応
  - 実行モード: ドラッグでスクロール
  - 編集モード: ダブルクリックで編集ダイアログを開く
  - CanvasResizeGrip に連動してリサイズ可能
"""

from __future__ import annotations

import base64
from typing import Any, List
import markdown  # pip install markdown

from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsSceneMouseEvent,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QCheckBox,
    QSplitter,
    QScrollArea,
    QWidget,
)
from PyQt6.QtGui import QColor, QBrush, QPainterPath, QPen, QFont, QTextDocument
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6 import sip

# ------- internal modules -----------------------------------------
from DPyL_classes import CanvasItem, CanvasResizeGrip
from DPyL_utils import warn, b64e, b64d  # 既存ユーティリティ

# Markdown 用拡張リスト
MD_EXT: List[str] = [
    "extra",
    "sane_lists",
    "smarty",
    "tables",
]

NOTE_BG_COLOR = "#323334"
NOTE_FG_COLOR = "#CCCACD"
# =====================================================================
#   NoteItem
# =====================================================================
class NoteItem(CanvasItem):
    TYPE_NAME = "note"

    def __init__(self, d: dict[str, Any] | None = None, cb_resize=None):
        super().__init__(d, cb_resize)
        # -- 追加: スクロール動作のモード管理 -------------
        # 「最初のクリックで武装 → 次のドラッグでスクロール」
        self._scroll_ready: bool  = False   # クリック済みフラグ
        self._dragging: bool      = False   # 実際にドラッグ中か
        # 「クリック」とみなす距離判定用
        self._press_scene_pos = None        # 押下座標
        self._CLICK_THRESH    = 4           # px 未満ならクリック        
        
        #
        # ★好みに応じて True にするとドラッグスクロールを完全に無効化し
        #   “ホイールのみスクロール” になります。
        self.DISABLE_DRAG_SCROLL: bool = False

        # hoverLeaveEvent で _scroll_ready をクリアするため
        self.setAcceptHoverEvents(True)

        # JSON → インスタンス変数
        self.format: str = self.d.get("format", "text")
        self.text: str = self.d.get("text", "New Note")
        self.fill_bg: bool = self.d.get("fill_background", True)
        
        # ファイル読み込み
        self.path: str = self.d.get("path", "")
        if self.path:
            self.load_from_file()

        # スクロール位置
        self.scroll_offset: int = 0

        # 初期サイズ
        w = int(self.d.get("width", 240))
        h = int(self.d.get("height", 120))

        # --- クリップ用矩形 (ItemClipsChildrenToShape) ---
        self.clip_item = QGraphicsRectItem(0, 0, w, h, parent=self)
        self.clip_item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True
        )
        self.clip_item.setPen(QPen(Qt.PenStyle.NoPen))

        # --- テキスト本体 ---
        self.txt_item = QGraphicsTextItem(parent=self.clip_item)
        self.txt_item.setPos(0, 0)
        self.txt_item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        # --- 背景矩形 (枠線／塗りつぶし) ---
        self._rect_item.setRect(0, 0, w, h)

        # 初回描画
        self._apply_text()

        # モード切替反映
        self.set_editable(False)
        
        # リサイズ遅延タイマー
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_text)
        
        try:
            # -- 追加: トグルインジケーター -----------------
            self._IND_SIZE = 8   # px
            self._indicator = QGraphicsRectItem(
                0, 0, self._IND_SIZE, self._IND_SIZE, self
            )
            #以下コメントアウトしないとノートが消えます
            #self._indicator.setPen(Qt.PenStyle.NoPen)
            #self._indicator.setBrush(QColor("#000080"))  # 初期 = OFF
            #self._indicator.setZValue(9999)              # 最前面

            self._update_indicator_position()
        except RuntimeError as e:
            # オブジェクト削除時の例外をキャッチ
            warn(f"[NoteItem] __init__: {e}")
           


    # --------------------------------------------------------------
    #   インジケーターの描画更新
    # --------------------------------------------------------------
    def _update_indicator_position(self):
        """右上に 2px マージンで配置（_indicator 未生成なら無視）"""
        if not hasattr(self, "_indicator"):
            return
        r = self.boundingRect()
        # 右上に 2 px マージン
        self._indicator.setPos(r.width() - self._IND_SIZE - 2, 2)

    def _update_indicator_color(self):
        """ON/OFF に合わせて塗り替え"""
        col = QColor("#008000") if self._scroll_ready else QColor("#000080")
        if hasattr(self,"_indicator"):
            self._indicator.setBrush(col)


    # --------------------------------------------------------------
    # public helper: サイズ変更通知
    # --------------------------------------------------------------
    def resize_content(self, w: int, h: int):
        """CanvasResizeGrip から呼ばれる。"""
        # クリップ／背景を更新
        self.clip_item.setRect(0, 0, w, h)
        self._rect_item.setRect(0, 0, w, h)
        self._update_indicator_position() 
        
        self._update_grip_pos()

        if self.format == "markdown":
            # Markdown は遅延更新（300ms）
            self._resize_timer.start(300)
        else:
            # テキストは即時更新
            self._apply_text()

    # --------------------------------------------------------------
    # internal: テキスト描画更新
    # --------------------------------------------------------------
    def _apply_text(self):
        """self.text / self.format を QTextDocument に反映"""
        try:
            doc: QTextDocument = self.txt_item.document()

            # サイズ取得
            w = int(self.d.get("width", 240))
            h = int(self.d.get("height", 120))

            # テキスト色設定
            color_hex: str = self.d.get("color", "#ffffff")
            self.txt_item.setDefaultTextColor(QColor(color_hex))

            # Markdown / プレーンテキスト切替
            if self.format == "markdown":
                html = markdown.markdown(
                    self.text, extensions=MD_EXT, output_format="html5"
                )
                doc.setHtml(html)
            else:
                doc.setPlainText(self.text)

            # フォントサイズ設定
            font = self.txt_item.font()
            font.setPointSize(int(self.d.get("fontsize", 14)))
            self.txt_item.setFont(font)

            # テキスト幅設定
            doc.setTextWidth(w)

            # 背景色と枠線設定
            if self.fill_bg:
                bgcol = QColor(self.d.get("bgcolor", NOTE_BG_COLOR))
                self._rect_item.setBrush(QBrush(bgcol))
                self._rect_item.setPen(QPen(Qt.GlobalColor.black))
                self._rect_item.setZValue(-1)
            else:
                self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                self._rect_item.setPen(QPen(Qt.PenStyle.NoPen))

            # スクロール上限計算 & 適用
            self.scroll_max = max(0, int(doc.size().height()) - h)
            self.set_scroll(self.scroll_offset)

            # ジオメトリ更新
            self.prepareGeometryChange()
            self.update()

        except RuntimeError as e:
            # オブジェクト削除時の例外をキャッチ
            warn(f"[NoteItem] _apply_text skipped: {e}")

    # --------------------------------------------------------------
    # scrolling (実行モードのドラッグ)
    # --------------------------------------------------------------
    def set_scroll(self, offset: int):
        """スクロール位置を制限付きで設定"""
        offset = max(0, min(offset, getattr(self, "scroll_max", 0)))
        self.scroll_offset = offset
        self.txt_item.setY(-offset)

    # --------------------------------------------------------------
    #   ファイル読み込み/保存
    # --------------------------------------------------------------
    def load_from_file(self):
        """self.path からテキストを読み込む"""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.text = f.read()
            self.d["text"] = self.text
        except Exception as e:
            warn(f"[NoteItem] load_from_file failed: {e}")

    def save_to_file(self):
        """self.path にテキストを書き出す"""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.text)
        except Exception as e:
            warn(f"[NoteItem] save_to_file failed: {e}")

    # --------------------------------------------------------------
    #   実行モード : マウスハンドリング
    # --------------------------------------------------------------
    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent):
        if not getattr(self, "run_mode", False):
            return super().mousePressEvent(ev)

        if ev.button() == Qt.MouseButton.LeftButton:
            # ---- ドラッグスクロール完全禁止モード -------------
            if self.DISABLE_DRAG_SCROLL:
                return super().mousePressEvent(ev)   # 上位へ任せる

            # ↓ 押下位置だけ記録。Release 時の移動量で
            #    “クリック or ドラッグ” を判定する
            self._press_scene_pos = ev.scenePos()

            # 既に _scroll_ready が ON なら「内部スクロール用ドラッグ」
            if self._scroll_ready:
                self._drag_start_y = ev.scenePos().y()
                self._start_offset = self.scroll_offset
                self._dragging     = True
                ev.accept()
            else:
                # まだ武装していない → 通常のクリック扱い
                super().mousePressEvent(ev)
            return

        super().mousePressEvent(ev)
        
    # --------------------------------------------------------------
    #   Note からカーソルが離れたら武装解除
    # --------------------------------------------------------------
    def hoverLeaveEvent(self, ev):
        self._scroll_ready = False
        self._update_indicator_color()
        return super().hoverLeaveEvent(ev)

    def mouseMoveEvent(self, ev: QGraphicsSceneMouseEvent):
        if getattr(self, "_dragging", False) and getattr(self, "run_mode", False):
            # ドラッグ量に応じてスクロール
            dy = ev.scenePos().y() - self._drag_start_y
            self.set_scroll(self._start_offset - int(dy))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QGraphicsSceneMouseEvent):
        # ---- Note 内スクロール終了 ----------------------------
        if self._dragging:
            self._dragging = False
            ev.accept()
            return

        # ---- クリック判定 --------------------------------------
        if (
            self._press_scene_pos is not None
            and ev.button() == Qt.MouseButton.LeftButton
        ):
            moved = (ev.scenePos() - self._press_scene_pos).manhattanLength()
            self._press_scene_pos = None

            if moved < self._CLICK_THRESH:
                # 「クリック」と認定
                self._scroll_ready = not self._scroll_ready
                self._update_indicator_color()

        super().mouseReleaseEvent(ev)

    # --------------------------------------------------------------
    # ダブルクリックで編集ダイアログを開く (編集モードのみ)
    # --------------------------------------------------------------
    def on_edit(self):
        dlg = NoteEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 設定反映
            self.format = self.d.get("format", "text")
            self.text = self.d.get("text", self.text)
            self.fill_bg = self.d.get("fill_background", False)
            self._apply_text()
        win = self.scene().views()[0].window()
        #self.set_run_mode(not win.a_edit.isChecked())
        # ----- Scene / Win が健在か先に確認 -----
        try:
            scene = self.scene()
            if scene and scene.views():
                win = scene.views()[0].window()
                self.set_run_mode(not win.a_edit.isChecked())
        except RuntimeError:
            # NoteItem が削除済みでもここに来る事がある
            pass        
    # --------------------------------------------------------------
    # 選択ハンドル用バウンディング矩形
    # --------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        w = int(self.d.get("width", 240))
        h = int(self.d.get("height", 120))
        return QRectF(0, 0, w, h)

    def shape(self):
        p = QPainterPath()
        p.addRect(self.boundingRect())
        return p
    # --------------------------------------------------------------
    #   位置やサイズが変わったらインジケーターを再配置
    # --------------------------------------------------------------
    def itemChange(self, change, value):
        if change in (
            QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemTransformHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemScaleHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged,
        ):
            # _indicator が出来ていない早期段階もあるのでガード
            if hasattr(self, "_indicator"):
                self._update_indicator_position()
        return super().itemChange(change, value)

    # --------------------------------------------------------------
    #   実行モード : ホイールスクロール
    # --------------------------------------------------------------
    r"""
    def wheelEvent(self, ev: QGraphicsSceneWheelEvent):
        # --- 編集モードは素通り ---
        if not getattr(self, "run_mode", False):
            return super().wheelEvent(ev)

        # --- Shift+ホイール＝横スクロールは親へ ---
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return super().wheelEvent(ev)

        # Qt6 の QGraphicsSceneWheelEvent は delta() だけ
        delta = ev.delta()          # ±120 が 1 ステップ
        if delta == 0:
            return

        step_px = 40                # 1 ステップあたりの移動量
        self.set_scroll(self.scroll_offset - int(delta / 120 * step_px))
        ev.accept()
    """

    def wheelEvent(self, ev: QGraphicsSceneWheelEvent):
        debug_print(f"NoteItem.wheelEvent called: run_mode={getattr(self, 'run_mode', False)}, _scroll_ready={getattr(self, '_scroll_ready', False)}")
        
        # --- 編集モードは素通り ---
        if not getattr(self, "run_mode", False):
            return super().wheelEvent(ev)

        # --- _scroll_ready の状態で分岐（ドラッグと同じロジック） ---
        if self._scroll_ready:
            debug_print("NoteItem: Processing scroll")
            # ノート内容のスクロール
            delta = ev.delta()          # ±120 が 1 ステップ
            if delta == 0:
                return

            step_px = 40                # 1 ステップあたりの移動量
            old_offset = self.scroll_offset
            new_offset = old_offset - int(delta / 120 * step_px)
            self.set_scroll(new_offset)
            debug_print(f"NoteItem: Scrolled from {old_offset} to {new_offset}")
            ev.accept()
        else:
            debug_print("NoteItem: _scroll_ready=False, doing nothing")
            # _scroll_ready=Falseの時は何もしない（CanvasViewの拡大縮小に任せる）
            return
# =====================================================================
#   NoteEditDialog
# =====================================================================
class ZoomableEdit(QPlainTextEdit):
    _MIN = 6
    _MAX = 72

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 1 if ev.angleDelta().y() > 0 else -1
            f = self.font()
            size = max(self._MIN, min(self._MAX, f.pointSize() + step))
            if size != f.pointSize():
                f.setPointSize(size)
                self.setFont(f)
                # 既に導入済みのデバウンス関数を呼ぶ
                if hasattr(self.parent(), "_kick_preview_update"):
                    self.parent()._kick_preview_update()
            ev.accept()
        else:
            super().wheelEvent(ev)
class NoteEditDialog(QDialog):
    def __init__(self, item: NoteItem):
        super().__init__()  # QDialog の初期化
        self.item = item
        self.d = item.d
        self.setWindowTitle("Note 設定")
        self._build_ui()    # UI 部品の構築

    # --------------------------------------------------------------
    # UI の組み立て
    # --------------------------------------------------------------
    def _build_ui(self):
        vbox = QVBoxLayout(self)

        # --- フォーマット選択 & 背景塗りつぶし ON/OFF ---
        self.chk_md = QCheckBox("Markdown で表示")
        self.chk_md.setChecked(self.item.format == "markdown")
        vbox.addWidget(self.chk_md)

        self.chk_bg = QCheckBox("背景を塗りつぶす")
        self.chk_bg.setChecked(self.item.fill_bg)
        vbox.addWidget(self.chk_bg)

        # --- 背景色 / テキスト色 / フォントサイズ の入力欄 ---
        def _hl(label: str, widget):
            h = QHBoxLayout()
            h.addWidget(QLabel(label))
            h.addWidget(widget, 1)
            return h

        self.ed_bg = QLineEdit(self.d.get("bgcolor", NOTE_BG_COLOR))
        vbox.addLayout(_hl("背景色 (#RRGGBB)", self.ed_bg))

        self.ed_color = QLineEdit(self.d.get("color", "#ffffff"))
        vbox.addLayout(_hl("テキスト色 (#RRGGBB)", self.ed_color))

        self.spin_font = QSpinBox()
        self.spin_font.setRange(6, 72)
        self.spin_font.setValue(int(self.d.get("fontsize", 14)))
        vbox.addLayout(_hl("フォントサイズ", self.spin_font))

        # --- ファイルパス欄と読込/保存ボタン ---
        self.ed_path = QLineEdit(self.d.get("path", ""))
        btn_load = QPushButton("読み込み")
        btn_save = QPushButton("保存")
        btn_load.clicked.connect(self._load_from_path)
        btn_save.clicked.connect(self._save_to_path)
        self.ed_path.textChanged.connect(self._update_path_buttons)
        self.btn_load = btn_load
        self.btn_save = btn_save
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("path"))
        path_layout.addWidget(self.ed_path, 1)
        path_layout.addWidget(btn_load)
        path_layout.addWidget(btn_save)
        vbox.addLayout(path_layout)
        self._update_path_buttons()

        # --- Splitter: 上部=編集エリア / 下部=プレビュー ---
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 編集用テキストエリア
        #self.txt_edit = QTextEdit()
        #self.txt_edit.setAcceptRichText(False)
        self.txt_edit = ZoomableEdit(self)
        
        self.txt_edit.setPlainText(self.item.text)
        splitter.addWidget(self.txt_edit)

        # プレビュー表示用ウィジェット
        prev_container = QWidget()
        prev_layout = QVBoxLayout(prev_container)
        prev_layout.setContentsMargins(0, 0, 0, 0)
        prev_layout.setSpacing(0)
        prev_layout.addWidget(QLabel("プレビュー"))

        self.lbl_prev = QLabel()
        self.lbl_prev.setWordWrap(True)
        self.lbl_prev.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_prev.setMinimumHeight(120)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.lbl_prev)
        prev_layout.addWidget(scroll)

        splitter.addWidget(prev_container)
        splitter.setSizes([260, 180])
        vbox.addWidget(splitter)

        # --- リアルタイムプレビュー更新 ---
        #self.chk_md.stateChanged.connect(self._update_preview)
        #self.txt_edit.textChanged.connect(self._update_preview)
        #self._update_preview()
        
        # -- 150 ms デバウンス -------------------
        self._prev_timer = QTimer(self)
        self._prev_timer.setSingleShot(True)
        self._prev_timer.timeout.connect(self._update_preview)

        self.chk_md.stateChanged.connect(self._kick_preview_update)
        self.txt_edit.textChanged.connect(self._kick_preview_update)
        self._update_preview()

        # --- OK / Cancel ボタン ---
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        vbox.addLayout(btn_layout)

    def _kick_preview_update(self):
        self._prev_timer.start(150)
        
    def _update_path_buttons(self):
        has_path = bool(self.ed_path.text().strip())
        self.btn_load.setEnabled(has_path)
        self.btn_save.setEnabled(has_path)

    def _load_from_path(self):
        path = self.ed_path.text().strip()
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
            self.txt_edit.setPlainText(txt)
            self._kick_preview_update()
        except Exception as e:
            warn(f"[NoteEditDialog] load failed: {e}")

    def _save_to_path(self):
        path = self.ed_path.text().strip()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_edit.toPlainText())
        except Exception as e:
            warn(f"[NoteEditDialog] save failed: {e}")
            
    # --------------------------------------------------------------
    # プレビュー更新処理
    # --------------------------------------------------------------
    def _update_preview(self):
        """編集エリアの内容を下部プレビューに反映"""
        txt = self.txt_edit.toPlainText()

        if self.chk_md.isChecked():
            # Markdown 形式なら HTML 変換して表示
            html = markdown.markdown(
                txt,
                extensions=MD_EXT,
                output_format="html5"
            )
            # テキスト色はラッピング div で指定
            color_hex = self.ed_color.text().strip() or "#ffffff"
            wrapped = f'<div style="color:{color_hex};">{html}</div>'
            self.lbl_prev.setText(wrapped)
            # 背景色はスタイルシートで指定
            bg = self.ed_bg.text().strip() or NOTE_BG_COLOR
            self.lbl_prev.setStyleSheet(f"background:{bg}; padding:6px;")
        else:
            # プレーンテキストの場合はエスケープして表示
            esc = (txt.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
            self.lbl_prev.setText(esc)
            # 背景／文字色はプレビューには反映されない

    # --------------------------------------------------------------
    # OK 押下時の処理
    # --------------------------------------------------------------
    def accept(self):
        # ユーザー設定を辞書に保存
        self.d["format"] = "markdown" if self.chk_md.isChecked() else "text"
        self.d["text"] = self.txt_edit.toPlainText()
        self.d["fill_background"] = self.chk_bg.isChecked()
        self.d["bgcolor"] = self.ed_bg.text().strip() or NOTE_BG_COLOR
        self.d["fontsize"] = self.spin_font.value()
        self.d["color"] = self.ed_color.text().strip() or "#ffffff"
        self.d["path"] = self.ed_path.text().strip()

        # NoteItem 側に即時反映
        self.item.format = self.d["format"]
        self.item.text = self.d["text"]
        self.item.fill_bg = self.d["fill_background"]
        self.item.path = self.d["path"]

        super().accept()

# --------------------------- __all__ -----------------------------
__all__ = [
    "NoteItem",
    "NoteEditDialog",
]
