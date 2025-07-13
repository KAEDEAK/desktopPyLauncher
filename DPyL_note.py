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
  - 実行モード: ダブルクリックで WALK → SCROLL → EDIT を循環
  - SCROLL 時はドラッグ/ホイールでスクロール
  - EDIT 時はノート内容を直接編集
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
    QApplication,
    QGraphicsView
    
    
)
from PyQt6.QtGui import QColor, QBrush, QPainterPath, QPen, QFont, QTextDocument, QKeyEvent, QFontMetrics
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QEvent, QFileSystemWatcher
from PyQt6 import sip
import os
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

NOTE_MODE_WALK  = 0
NOTE_MODE_SCROLL= 1 
NOTE_MODE_EDIT  = 2

# =====================================================================
#   NoteItem
# =====================================================================
class NoteItem(CanvasItem):
    TYPE_NAME = "note"
    
    def _clean_path(self, path: str) -> str:
        """strip spaces and surrounding quotes"""
        return path.strip().strip('"').strip()
    
    @property
    def path(self) -> str:
        return getattr(self, "_path", "")

    @path.setter
    def path(self, value: str):
        self._path = self._clean_path(value)
        self.d["path"] = self._path

    def __init__(self, d: dict[str, Any] | None = None, cb_resize=None):
        super().__init__(d, cb_resize)
        try:
            # インタラクションモード管理
            self._mode: int = NOTE_MODE_WALK    # 0=WALK, 1=SCROLL, 2=EDIT
            self._scroll_ready: bool  = False   # クリック済みフラグ
            self._dragging: bool      = False   # 実際にドラッグ中か
            # 「クリック」とみなす距離判定用
            self._press_scene_pos = None        # 押下座標
            self._CLICK_THRESH    = 4           # px 未満ならクリック        
            
            # EDITモード遷移中フラグを追加
            self._entering_edit_mode: bool = False
            # "|" を使った仮キャレットを挿入したかどうか
            self._temp_caret_added: bool = False
            
            #
            # ★好みに応じて True にするとドラッグスクロールを完全に無効化し
            #   “ホイールのみスクロール” になります。
            self.DISABLE_DRAG_SCROLL: bool = False

             # hoverLeaveEvent でモードをリセットするため
            self.setAcceptHoverEvents(True)

            # JSON → インスタンス変数
            self.format: str = self.d.get("format", "text")
            self.text: str = self.d.get("text", "New Note")
            self.fill_bg: bool = self.d.get("fill_background", True)
            
            # ファイル読み込み
            self._path: str = self._clean_path(self.d.get("path", ""))
            self.watch_file: bool = self.d.get("watch_file", False)
            self.reverse_lines: bool = self.d.get("reverse_lines", False)
            self.line_limit: int = int(self.d.get("line_limit", 100))
            self._file_watcher: QFileSystemWatcher | None = None
            # NoteItem is not a QObject, so the timer can't be parented to self
            self._file_watch_retry_timer = QTimer(None)
            self._file_watch_retry_timer.setSingleShot(True)
            self._file_watch_retry_timer.timeout.connect(self._retry_file_watch)
            
            if self.path:
                self.load_from_file()
            self._setup_file_watcher()
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
            
            # ★重要：GraphicsItemフラグを先に設定
            self.txt_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
            self.txt_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)  # 選択は親で制御
            
            # ★その後でTextInteractionFlagsを設定
            self.txt_item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            
            # ★NoteItem自体もフォーカス可能にする（これも順序重要）
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
            
            # 初期状態ではテキストアイテムのマウスイベントを無効化
            self.txt_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            
            # 初期状態では選択枠を非表示
            self._update_selection_frame()
            
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

            # -- モード表示ラベル -----------------
            self._mode_label = QGraphicsTextItem("", self)
            font = self._mode_label.font()
            font.setPointSize(8)
            self._mode_label.setFont(font)
            self._mode_label.setZValue(9999)
            self._mode_label.setVisible(False)
            self._mode_label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        except RuntimeError as e:
            # オブジェクト削除時の例外をキャッチ
            warn(f"[NoteItem] __init__: {e}")
           


    # --------------------------------------------------------------
    #   モード表示ラベル更新
    # --------------------------------------------------------------
    def _update_mode_label_position(self):
        if not hasattr(self, "_mode_label"):
            return
        r = self.boundingRect()
        br = self._mode_label.boundingRect()
        self._mode_label.setPos(r.width() - br.width() - 2, 2)

    def _update_mode_label(self):
        if not hasattr(self, "_mode_label"):
            return
        if self._mode == NOTE_MODE_SCROLL:
            html = '<span style="background:#ffff00;color:#000000;">SCROLL</span>'
        elif self._mode == NOTE_MODE_EDIT:
            if self.path:
                html = '<span style="background:#ff0000;color:#ffff00;">EDIT [FILE - use edit dialog to save -]</span>'
            else:
                html = '<span style="background:#ff0000;color:#ffff00;">EDIT [EMBED - use edit dialog to save -]</span>'
        else:
            html = ""
        self._mode_label.setHtml(html)
        self._mode_label.setVisible(bool(html))
        self._update_mode_label_position()

    def _enter_edit_mode(self, mouse_pos=None):
        """編集モードに入る"""
        if self._mode != NOTE_MODE_EDIT:
            return
            
        warn("[NoteItem] Entering EDIT mode")
        
        # EDITモード遷移中フラグを立てる
        self._entering_edit_mode = True
        
        # 現在の編集状態を確認
        already_editing = bool(
            self.txt_item.textInteractionFlags()
            & Qt.TextInteractionFlag.TextEditorInteraction
        )

        # 既にEDIT中で仮キャレットが残っている場合は削除
        insert_placeholder = False
        if already_editing and self._temp_caret_added:
            text = self.txt_item.toPlainText()
            idx = text.find("|")
            if idx >= 0:
                cursor_cleanup = self.txt_item.textCursor()
                cursor_cleanup.setPosition(idx)
                cursor_cleanup.deleteChar()
            insert_placeholder = True
            self._temp_caret_added = False      
        
        # ★重要：まずGraphicsItemフラグを確認・設定
        self.txt_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        
        # ★その後でTextInteractionFlagsを設定
        self.txt_item.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
        )
        
        if not already_editing:
            # テキストを設定（初回のみ）
            self.txt_item.setPlainText(self.text)
        
        # フォーカスを設定
        self.txt_item.setFocus(Qt.FocusReason.MouseFocusReason)
        
        # カーソル位置を設定
        cursor = self.txt_item.textCursor()
        
        if mouse_pos:
            # マウス位置をテキストアイテム座標系に変換
            local_pos = self.mapFromScene(mouse_pos)
            
            # スクロールオフセットを考慮
            text_pos = QPointF(local_pos.x(), local_pos.y() + self.scroll_offset)
            
            # clip_itemの座標系に変換（txt_itemはclip_itemの子）
            text_local_pos = self.clip_item.mapFromParent(text_pos)
            
            # デバッグ出力
            warn(f"[NoteItem] Mouse pos conversion: scene={mouse_pos}, local={local_pos}, text_local={text_local_pos}")
            
            # ドキュメントレイアウトからカーソル位置を取得
            char_pos = self.txt_item.document().documentLayout().hitTest(
                text_local_pos, 
                Qt.HitTestAccuracy.ExactHit  # FuzzyHitからExactHitに変更
            )
            
            warn(f"[NoteItem] hitTest result: char_pos={char_pos}")
            
            if char_pos >= 0:
                cursor.setPosition(char_pos)
            else:
                # hitTestが失敗した場合、Y座標から行を推定
                doc = self.txt_item.document()
                y = text_local_pos.y()
                
                # 各行の高さを取得して、Y座標から行番号を推定
                block = doc.firstBlock()
                total_height = 0
                target_block = None
                
                while block.isValid():
                    block_height = doc.documentLayout().blockBoundingRect(block).height()
                    if total_height <= y < total_height + block_height:
                        target_block = block
                        break
                    total_height += block_height
                    block = block.next()
                
                if target_block:
                    # 該当行の先頭にカーソルを配置
                    cursor.setPosition(target_block.position())
                    
                    # X座標から行内の位置を推定
                    line_start = target_block.position()
                    text_line = target_block.text()
                    if text_line:
                        # 簡易的な文字幅推定（正確ではないが改善される）
                        font_metrics = self.txt_item.font()
                        char_width = QFontMetrics(font_metrics).averageCharWidth()
                        char_index = min(int(text_local_pos.x() / char_width), len(text_line))
                        cursor.setPosition(line_start + char_index)
        
        # カーソルを設定
        self.txt_item.setTextCursor(cursor)
        
        # 親アイテムのマウスイベントを無効化
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        
        # テキストアイテムをクリッカブルにする
        self.txt_item.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        
        # ★キャレット位置に | を挿入して選択
        cursor.insertText("|")
        # 挿入した | を選択状態にする
        cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor)
        cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor)
        self.txt_item.setTextCursor(cursor)
        
        if not already_editing or insert_placeholder:
            # ★キャレット位置に | を挿入して選択
            cursor.insertText("|")
            cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor)
            cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor)
            self.txt_item.setTextCursor(cursor)
            self._temp_caret_added = True    

        # 選択枠を更新
        self._update_selection_frame()
        
        # フラグクリア（少し遅延）
        QTimer.singleShot(100, lambda: setattr(self, '_entering_edit_mode', False))        
    
    def _exit_edit_mode(self):
        """編集モードを終了"""
        warn("[NoteItem] Exiting EDIT mode")
        
        # テキストを取得
        text = self.txt_item.toPlainText()
        
        # カーソル位置の | を削除
        cursor = self.txt_item.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == "|":
            # 選択されている | を削除
            cursor.removeSelectedText()
            text = self.txt_item.toPlainText()
        elif "|" in text:
            # 選択されていない | がある場合も削除（念のため）
            text = text.replace("|", "")
        self._temp_caret_added = False
        
        # テキストを保存
        self.text = text
        self.d["text"] = self.text
        
        # テキストの編集を無効化
        self.txt_item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        
        # 親アイテムのマウスイベントを復活
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        
        # テキストアイテムのマウスイベントを無効化
        self.txt_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        
        # フォーカスをクリア
        self.txt_item.clearFocus()
        
        # テキストを再描画（背景色も含めて）
        self._apply_text()
        
        # 選択枠を更新（背景色設定後）
        self._update_selection_frame()
        
    def keyPressEvent(self, event):
        """キー入力イベント処理"""
        if self._mode == NOTE_MODE_EDIT:
            # EDITモード時はテキストアイテムにキー入力を転送
            if self._temp_caret_added:
                self._temp_caret_added = False            
            self.txt_item.keyPressEvent(event)
        else:
            super().keyPressEvent(event)
                
    def _cycle_mode(self, mouse_pos=None):  # ★引数を追加
        """モードを循環させる"""
        # 現在のモードを保存（デバッグ用）
        old_mode = self._mode
        
        # 現在EDITモードなら終了処理
        if self._mode == NOTE_MODE_EDIT:
            self._exit_edit_mode()
        
        # モードを循環（0->1->2->0...）
        self._mode = (self._mode + 1) % 3
        
        # 新しいモードがEDITなら開始処理
        if self._mode == NOTE_MODE_EDIT:
            # マウス位置を渡す
            #self._enter_edit_mode(mouse_pos)  # ★マウス位置を渡す
            #QTimer.singleShot(50, lambda: self._enter_edit_mode(mouse_pos))
            QTimer.singleShot(50, lambda: self._enter_edit_mode())
        
        # UIを更新
        self._update_mode_label()
        self._update_selection_frame()
        
        # デバッグ出力
        warn(f"[NoteItem] _cycle_mode: {old_mode} -> {self._mode}")

    # --------------------------------------------------------------
    # public helper: サイズ変更通知
    # --------------------------------------------------------------
    def resize_content(self, w: int, h: int):
        """CanvasResizeGrip から呼ばれる。"""
        # クリップ／背景を更新
        self.clip_item.setRect(0, 0, w, h)
        self._rect_item.setRect(0, 0, w, h)
        self._update_mode_label_position() 
        
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

            # 背景色と枠線設定（ここが重要）
            if self.fill_bg:
                bgcol = QColor(self.d.get("bgcolor", NOTE_BG_COLOR))
                self._rect_item.setBrush(QBrush(bgcol))
                # EDITモード以外では通常の枠線
                if self._mode != NOTE_MODE_EDIT:
                    self._rect_item.setPen(QPen(Qt.GlobalColor.black))
                self._rect_item.setZValue(-1)
                self._rect_item.setVisible(True)  # 確実に表示
            else:
                self._rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                if self._mode != NOTE_MODE_EDIT:
                    self._rect_item.setPen(QPen(Qt.PenStyle.NoPen))
                self._rect_item.setVisible(True)  # 枠は表示（透明でも）

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
                if self.watch_file:
                    lines = f.readlines()
                    limit = self.line_limit if self.line_limit > 0 else len(lines)
                    if self.reverse_lines:
                        selected = lines[:limit]
                    else:
                        selected = lines[-limit:]
                    self.text = "".join(selected)
                else:
                    self.text = f.read()
            self.d["text"] = self.text
        except Exception as e:
            warn(f"[NoteItem] load_from_file failed: {e}")

    def save_to_file(self):
        """self.path にテキストを書き出す"""
        if self.watch_file:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.text)
        except Exception as e:
            warn(f"[NoteItem] save_to_file failed: {e}")

    # --------------------------------------------------------------
    #   ファイル監視
    # --------------------------------------------------------------
    def _setup_file_watcher(self):
        """ファイル更新監視を初期化"""
        if getattr(self, "_file_watcher", None):
            try:
                self._file_watcher.fileChanged.disconnect(self._on_file_changed)
            except Exception:
                pass
            try:
                self._file_watcher.directoryChanged.disconnect(self._on_directory_changed)
            except Exception:
                pass
            self._file_watcher.removePaths(self._file_watcher.files())
            self._file_watcher.deleteLater()
            self._file_watcher = None

        self._file_watch_retry_timer.stop()
        self._watch_dir = None

        if self.watch_file and self.path:
            dir_path = os.path.dirname(self.path) or "."
            paths: list[str] = []
            if os.path.isdir(dir_path):
                paths.append(dir_path)
                self._watch_dir = dir_path
            watch_file = False
            if os.path.exists(self.path):
                paths.append(self.path)
                watch_file = True
            if paths:
                try:
                    self._file_watcher = QFileSystemWatcher()
                    self._file_watcher.addPaths(paths)
                    self._file_watcher.fileChanged.connect(self._on_file_changed)
                    self._file_watcher.directoryChanged.connect(self._on_directory_changed)
                except Exception as e:
                    warn(f"[NoteItem] watcher setup failed: {e}")
                    self._file_watcher = None
            if not watch_file:
                self._schedule_watch_retry()

    def _on_file_changed(self, path: str):
        if path != self.path:
            return
        try:
            self.load_from_file()
            self._apply_text()
            # パスの重複を防ぐために、既に監視されているかチェック
            if self._file_watcher and self.path:
                watched_files = self._file_watcher.files()
                if self.path not in watched_files:
                    self._file_watcher.addPath(self.path)
        except Exception as e:
            warn(f"[NoteItem] reload failed: {e}")
            self._schedule_watch_retry()

    def _on_directory_changed(self, dir_path: str):
        if not self.watch_file:
            return
        if self._watch_dir and dir_path != self._watch_dir:
            return
        if os.path.exists(self.path):
            self._retry_file_watch()

    def set_file_watching(self, enabled: bool):
        self.watch_file = enabled
        self.d["watch_file"] = enabled
        self._setup_file_watcher()

    def _schedule_watch_retry(self):
        """ファイルが存在しない場合に再試行タイマーを開始"""
        if self.watch_file:
            self._file_watch_retry_timer.start(1000)

    def _retry_file_watch(self):
        """タイマーから呼ばれ、ファイルが復活したら再読込"""
        if not self.watch_file or not self.path:
            return
        if os.path.exists(self.path):
            try:
                #self.load_from_file()
                #self._apply_text()
                
                # Delay slightly so apps that recreate the file can finish
                # writing before we reload. Directly reading right away could
                # result in an empty file.                
                QTimer.singleShot(500, lambda: self.load_from_file())
                QTimer.singleShot(750, lambda: self._apply_text())                
            except Exception as e:
                warn(f"[NoteItem] retry load failed: {e}")
            self._setup_file_watcher()
        else:
            self._schedule_watch_retry()

    def delete_self(self):
        """タイマーやウォッチャを停止してから削除"""
        self._file_watch_retry_timer.stop()
        self._file_watch_retry_timer.deleteLater()
        if self._file_watcher:
            try:
                self._file_watcher.fileChanged.disconnect(self._on_file_changed)
            except Exception:
                pass
            try:
                self._file_watcher.directoryChanged.disconnect(self._on_directory_changed)
            except Exception:
                pass
            self._file_watcher.removePaths(self._file_watcher.files())
            self._file_watcher.deleteLater()
            self._file_watcher = None
        super().delete_self()

    # --------------------------------------------------------------
    #   実行モード : マウスハンドリング
    # --------------------------------------------------------------
    def _update_selection_frame(self):
        """選択枠の表示制御"""
        if not hasattr(self, '_rect_item'):
            return
            
        if self._mode == NOTE_MODE_EDIT:
            # EDITモード時のみ点線枠を表示
            pen = QPen()
            pen.setColor(QColor("#ff3355"))  # 編集モード用の色
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)  # 点線
            self._rect_item.setPen(pen)
        else:
            # WALK/SCROLLモード時は背景色設定を維持
            if self.fill_bg:
                # 背景塗りつぶしが有効な場合
                self._rect_item.setPen(QPen(Qt.GlobalColor.black))
            else:
                # 背景塗りつぶしが無効な場合
                self._rect_item.setPen(QPen(Qt.PenStyle.NoPen))
        
        # _rect_itemは常に表示（背景色の表示のため）
        self._rect_item.setVisible(True)

    def mousePressEvent(self, ev: QGraphicsSceneMouseEvent):
        if not getattr(self, "run_mode", False):
            return super().mousePressEvent(ev)

        if ev.button() == Qt.MouseButton.LeftButton:
            if self._mode == NOTE_MODE_EDIT:
                # EDITモード時はテキストアイテムの範囲内かチェック
                local_pos = self.mapFromScene(ev.scenePos())
                text_rect = self.txt_item.boundingRect()
                text_rect.translate(self.txt_item.pos())
                
                if text_rect.contains(local_pos):
                    # テキストエリア内のクリック
                    # 既にEDITモードなので、カーソル位置だけ更新
                    self._temp_caret_added=True
                    self._enter_edit_mode(ev.scenePos())
                    ev.accept()
                    return
                else:
                    # テキストエリア外のクリックは編集モード終了
                    self._exit_edit_mode()
                    self._mode = NOTE_MODE_WALK
                    self._update_mode_label()
                    self._update_selection_frame()
                    ev.accept()
                    return
                    
            elif self._mode == NOTE_MODE_SCROLL:
                if self.DISABLE_DRAG_SCROLL:
                    return super().mousePressEvent(ev)
                self._drag_start_y = ev.scenePos().y()
                self._start_offset = self.scroll_offset
                self._dragging = True
                ev.accept()
                return
            else:
                return super().mousePressEvent(ev)

        super().mousePressEvent(ev)
        
    def focusInEvent(self, event):
        """フォーカスを得た時の処理"""
        warn(f"[NoteItem] focusInEvent, mode={self._mode}")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        """フォーカスを失った時の処理"""
        warn(f"[NoteItem] focusOutEvent, mode={self._mode}, entering_edit={getattr(self, '_entering_edit_mode', False)}")
        
        # EDITモード遷移中の場合は何もしない
        if getattr(self, '_entering_edit_mode', False):
            warn("[NoteItem] focusOutEvent skipped (entering edit mode)")
            super().focusOutEvent(event)
            return
        
        if self._mode == NOTE_MODE_EDIT:
            # 編集モードでフォーカスを失ったら編集終了
            self._exit_edit_mode()
            self._mode = NOTE_MODE_WALK
            self._update_mode_label()
            self._update_selection_frame()
        super().focusOutEvent(event)

    def init_mouse_passthrough(self):
        """マウス透過の初期化をオーバーライド"""
        # NoteItemでは子アイテムへのマウス透過を制御する
        # 編集モード時はテキストアイテムにマウスイベントを通す必要があるため
        # 基底クラスの処理をスキップ
        pass
    # --------------------------------------------------------------
    #   Note からカーソルが離れたら武装解除
    # --------------------------------------------------------------
    def hoverLeaveEvent(self, ev):
        """Noteからカーソルが離れた時の処理"""
        # EDITモード遷移中の場合は何もしない
        if getattr(self, '_entering_edit_mode', False):
            warn("[NoteItem] hoverLeaveEvent skipped (entering edit mode)")
            return super().hoverLeaveEvent(ev)
        
        self._scroll_ready = False
        
        if self._mode == NOTE_MODE_EDIT:
            # EDITモードから抜ける際は必ず_exit_edit_modeを呼ぶ
            self._exit_edit_mode()
        
        self._mode = NOTE_MODE_WALK
        self._update_mode_label()
        
        return super().hoverLeaveEvent(ev)
        
    def mouseMoveEvent(self, ev: QGraphicsSceneMouseEvent):
        if (
            getattr(self, "_dragging", False)
            and getattr(self, "run_mode", False)
            and self._mode == NOTE_MODE_SCROLL
        ):
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
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev: QGraphicsSceneMouseEvent):
        """ダブルクリック時の処理"""
        if getattr(self, "run_mode", False):
            # EDITモードでのダブルクリックは無視
            if self._mode == NOTE_MODE_EDIT:
                warn("[NoteItem] Double click in EDIT mode, ignoring")
                ev.accept()
                return
                
            # 現在のモードを保存
            old_mode = self._mode
            
            # モードを循環
            self._cycle_mode(ev.scenePos())  # ★マウス位置を渡す
            
            # デバッグ出力
            warn(f"[NoteItem] Double click: Mode changed: {old_mode} -> {self._mode}")
            
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

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
            if hasattr(self, "_mode_label"):
                self._update_mode_label_position()
        return super().itemChange(change, value)

    # --------------------------------------------------------------
    #   実行モード : ホイールスクロール
    # --------------------------------------------------------------
    def wheelEvent(self, ev: QGraphicsSceneWheelEvent):
        debug_print(
            f"NoteItem.wheelEvent called: run_mode={getattr(self, 'run_mode', False)}, mode={self._mode}"
        )

        if not getattr(self, "run_mode", False):
            return super().wheelEvent(ev)

        # --- _scroll_ready の状態で分岐（ドラッグと同じロジック） ---
        if self._mode == NOTE_MODE_SCROLL:
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
        elif self._mode == NOTE_MODE_EDIT:
            return super().wheelEvent(ev)
        else:
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
        # 現在読み込まれているパスを保持
        self._orig_path = self._clean_path(self.d.get("path", ""))
        self._loaded_path = self._orig_path        
       
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
        #self._update_path_buttons()

        # ファイル監視チェックボックス
        self.chk_watch = QCheckBox("ファイル更新を監視")
        self.chk_watch.setChecked(self.d.get("watch_file", False))
        vbox.addWidget(self.chk_watch)

        self.chk_reverse = QCheckBox("reverse_lines")
        self.chk_reverse.setChecked(self.d.get("reverse_lines", False))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(1, 100000)
        self.spin_limit.setValue(int(self.d.get("line_limit", 100)))
        limit_layout = _hl("line limit", self.spin_limit)
        vbox.addWidget(self.chk_reverse)
        vbox.addLayout(limit_layout)

        def _update_watch_opts():
            enable = self.chk_watch.isChecked()
            self.chk_reverse.setEnabled(enable)
            self.spin_limit.setEnabled(enable)
            if enable:
                self.btn_save.setEnabled(False)
            else:
                path = self._clean_path(self.ed_path.text())
                self.btn_save.setEnabled(bool(path) and path == self._loaded_path)
        self._update_watch_opts = _update_watch_opts
        self.chk_watch.stateChanged.connect(self._on_watch_toggled)
        self.chk_watch.stateChanged.connect(self._update_watch_opts)
        self._update_watch_opts()

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
        self.btn_ok = btn_ok
        # 初期状態の有効/無効を設定
        self._update_path_buttons()
        
    def _kick_preview_update(self):
        self._prev_timer.start(150)
        
    def _clean_path(self, path: str) -> str:
        """strip spaces and surrounding quotes"""
        return path.strip().strip('"').strip()

    def _on_watch_toggled(self):
        if self.chk_watch.isChecked():
            path = self._clean_path(self.ed_path.text())
            if not os.path.exists(path):
                self.chk_watch.setChecked(False)

    def _update_path_buttons(self):
        path = self._clean_path(self.ed_path.text())
        has_path = bool(path)        
        self.btn_load.setEnabled(has_path)
        #self.btn_ok.setEnabled(path == "" or path == self._loaded_path)
        self.btn_ok.setEnabled(True)
        self.btn_save.setEnabled(has_path and path == self._loaded_path)

        enable_watch = has_path
        self.chk_watch.setEnabled(enable_watch)
        if not enable_watch:
            self.chk_watch.setChecked(False)
        if hasattr(self, "_update_watch_opts"):
            self._update_watch_opts()
            
    def _load_from_path(self):
        path = self._clean_path(self.ed_path.text())
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
            self.txt_edit.setPlainText(txt)
            self._loaded_path = path
            self._kick_preview_update()
            self._update_path_buttons()
        except Exception as e:
            warn(f"[NoteEditDialog] load failed: {e}")

    def _save_to_path(self):
        path = self._clean_path(self.ed_path.text())
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_edit.toPlainText())
            self._loaded_path = path
            self._update_path_buttons()
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
        self.d["path"] = self._clean_path(self.ed_path.text())
        self.d["watch_file"] = self.chk_watch.isChecked()
        self.d["reverse_lines"] = self.chk_reverse.isChecked()
        self.d["line_limit"] = self.spin_limit.value()


        # NoteItem 側に即時反映
        self.item.format = self.d["format"]
        self.item.fill_bg = self.d["fill_background"]
        self.item.path = self.d["path"]
        self.item.reverse_lines = self.d["reverse_lines"]
        self.item.line_limit = self.d["line_limit"]
        self.item.set_file_watching(self.d["watch_file"])
        if self.item.watch_file:
            self.item.load_from_file()
        else:
            self.item.text = self.d["text"]
            if self.item.path:
                self.item.save_to_file()

        super().accept()

# --------------------------- __all__ -----------------------------
__all__ = [
    "NoteItem",
    "NoteEditDialog",
]
