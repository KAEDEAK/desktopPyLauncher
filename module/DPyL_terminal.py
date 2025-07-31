# -*- coding: utf-8 -*-
"""
DPyL_terminal.py ― ターミナルアイテム（直接入力対応版）
◎ Qt6 / PySide6 専用
"""
from __future__ import annotations
import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    Qt, QPointF, QRectF, QSizeF, QTimer, QSize, QProcess, QIODevice, 
    Signal, QObject, QEvent
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QIcon, QFont, 
    QKeyEvent, QTextCursor, QTextCharFormat, QMouseEvent
)
from PySide6.QtWidgets import (
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsItemGroup,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QCheckBox, QSpinBox,
    QGraphicsProxyWidget, QScrollBar, QTextBrowser, QPlainTextEdit,
    QGraphicsItem
)

# プロジェクト内モジュール
try:
    from .DPyL_classes import CanvasItem
    from .DPyL_note import NoteItem
    from .DPyL_utils import warn, debug_print
except ImportError:
    # テスト環境用の代替
    from PySide6.QtWidgets import QGraphicsItemGroup as CanvasItem
    from PySide6.QtWidgets import QGraphicsItemGroup as NoteItem
    def warn(msg): print(f"WARN: {msg}")
    def debug_print(msg): print(f"DEBUG: {msg}")


class TerminalWidget(QPlainTextEdit):
    """
    直接入力可能なターミナルウィジェット
    """
    command_executed = Signal(str)  # コマンド実行時のシグナル
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # ターミナル設定
        self.command_history = []
        self.history_index = -1
        self.current_line_start = 0
        self.prompt = "> "
        
        # フォーカス設定
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTabChangesFocus(False)
        
        # 外観設定
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #000000;
                color: #ffffff;
                border: 1px solid #555555;
                font-family: 'Consolas', monospace;
                font-size: 12px;
            }
        """)
        
        # 初期プロンプト表示
        self.setPlainText(self.prompt)
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.current_line_start = len(self.prompt)

    def focusInEvent(self, event):
        """フォーカスイン時の処理"""
        super().focusInEvent(event)
        # カーソルを末尾に移動
        self.moveCursor(QTextCursor.MoveOperation.End)

    def mousePressEvent(self, event):
        """マウスクリック時の処理"""
        # スクロールバー領域のクリックかチェック
        if self._is_scrollbar_area(event.pos()):
            # スクロールバー操作の場合は親クラスに処理を委譲
            super().mousePressEvent(event)
            return
        
        super().mousePressEvent(event)
        # ターミナルが確実にフォーカスを得るように
        if not self.hasFocus():
            self.setFocus()
    
    def mouseReleaseEvent(self, event):
        """マウスリリース時の処理"""
        # スクロールバー操作を確実に処理
        super().mouseReleaseEvent(event)
    
    def mouseMoveEvent(self, event):
        """マウス移動時の処理"""
        # スクロールバーのドラッグ操作を確実に処理
        super().mouseMoveEvent(event)
    
    def wheelEvent(self, event):
        """マウスホイールイベント処理"""
        # スクロール操作を確実に処理
        super().wheelEvent(event)
    
    def _is_scrollbar_area(self, pos):
        """指定された位置がスクロールバー領域かどうかを判定"""
        try:
            # 垂直スクロールバーの領域をチェック
            vscrollbar = self.verticalScrollBar()
            if vscrollbar and vscrollbar.isVisible():
                scrollbar_width = vscrollbar.width()
                widget_width = self.width()
                # 右端のスクロールバー領域かチェック
                if pos.x() >= widget_width - scrollbar_width - 5:  # 5pxのマージンを追加
                    return True
            
            # 水平スクロールバーの領域をチェック
            hscrollbar = self.horizontalScrollBar()
            if hscrollbar and hscrollbar.isVisible():
                scrollbar_height = hscrollbar.height()
                widget_height = self.height()
                # 下端のスクロールバー領域かチェック
                if pos.y() >= widget_height - scrollbar_height - 5:  # 5pxのマージンを追加
                    return True
            
            return False
        except Exception:
            return False

    def keyPressEvent(self, event: QKeyEvent):
        """キー入力イベント処理"""
        cursor = self.textCursor()
        
        # 現在の行の開始位置を計算
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        line_start = cursor.position()
        prompt_end = line_start + len(self.prompt)
        
        # カーソルが入力可能エリア外の場合は末尾に移動
        if self.textCursor().position() < prompt_end:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
        
        key = event.key()
        
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            # Enterキー: コマンド実行
            self._execute_current_command()
            event.accept()
            return
            
        elif key == Qt.Key.Key_Up:
            # 上矢印: コマンド履歴を戻る
            self._navigate_history(-1)
            event.accept()
            return
            
        elif key == Qt.Key.Key_Down:
            # 下矢印: コマンド履歴を進む
            self._navigate_history(1)
            event.accept()
            return
            
        elif key == Qt.Key.Key_Left:
            # 左矢印: プロンプト内での移動制限
            if self.textCursor().position() <= prompt_end:
                event.accept()
                return
                
        elif key == Qt.Key.Key_Home:
            # Homeキー: プロンプト後の先頭に移動
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.movePosition(QTextCursor.MoveOperation.Right, 
                              QTextCursor.MoveMode.MoveAnchor, len(self.prompt))
            self.setTextCursor(cursor)
            event.accept()
            return
            
        elif key == Qt.Key.Key_Backspace:
            # Backspace: プロンプト部分の削除を防ぐ
            if self.textCursor().position() <= prompt_end:
                event.accept()
                return
        
        # その他のキーは通常処理
        super().keyPressEvent(event)

    def _execute_current_command(self):
        """現在の行のコマンドを実行"""
        # 現在の行からコマンドを取得
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.Right, 
                          QTextCursor.MoveMode.MoveAnchor, len(self.prompt))
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, 
                          QTextCursor.MoveMode.KeepAnchor)
        
        command = cursor.selectedText().strip()
        
        if command:
            # コマンド履歴に追加
            if not self.command_history or self.command_history[-1] != command:
                self.command_history.append(command)
            self.history_index = len(self.command_history)
            
            # コマンド実行シグナルを発行（出力はadd_outputで処理される）
            self.command_executed.emit(command)
        else:
            # コマンドが空の場合はそのまま新しいプロンプトを追加
            self._add_new_prompt()

    def _navigate_history(self, direction):
        """コマンド履歴をナビゲート"""
        if not self.command_history:
            return
            
        # 履歴インデックスを更新
        new_index = self.history_index + direction
        if new_index < 0:
            new_index = 0
        elif new_index >= len(self.command_history):
            new_index = len(self.command_history)
            
        self.history_index = new_index
        
        # 現在の行のコマンド部分を置換
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.Right, 
                          QTextCursor.MoveMode.MoveAnchor, len(self.prompt))
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, 
                          QTextCursor.MoveMode.KeepAnchor)
        
        if self.history_index < len(self.command_history):
            cursor.insertText(self.command_history[self.history_index])
        else:
            cursor.insertText("")

    def add_output(self, text: str):
        """出力テキストを追加"""
        # カーソルを末尾に移動
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # 改行してから出力を追加
        cursor.insertText("\n" + text)
        
        # 出力の後に新しいプロンプトを追加
        self._add_new_prompt()
        
        # テキスト行数制限
        self.limit_text_lines(500)  # 最大500行に制限
        
        # 自動スクロール
        self.ensureCursorVisible()

    def _add_new_prompt(self):
        """新しいプロンプトを追加"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\n" + self.prompt)
        self.setTextCursor(cursor)

    def clear_terminal(self):
        """ターミナルをクリア"""
        self.setPlainText(self.prompt)
        self.moveCursor(QTextCursor.MoveOperation.End)

    def set_working_directory(self, path: str):
        """作業ディレクトリ表示を更新"""
        self.prompt = f"{os.path.basename(path)}> "
        # 現在の行のプロンプトも更新
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, 
                          QTextCursor.MoveMode.KeepAnchor)
        line_text = cursor.selectedText()
        if line_text.startswith("> "):
            cursor.insertText(self.prompt + line_text[2:])

    def set_terminal_font(self, font_size: int):
        """フォントサイズを設定"""
        font = self.font()
        font.setPointSize(font_size)
        font.setFamily("Consolas")
        self.setFont(font)

    def set_terminal_colors(self, bg_color: str, text_color: str):
        """ターミナルの色を設定"""
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {bg_color};
                color: {text_color};
                border: 1px solid #555555;
                font-family: 'Consolas', monospace;
            }}
            QScrollBar:vertical {{
                background-color: {bg_color};
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: #666666;
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #888888;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
            }}
        """)

    def limit_text_lines(self, max_lines: int = 1000):
        """テキストの行数を制限してメモリ使用量を管理"""
        text = self.toPlainText()
        lines = text.split('\n')
        
        if len(lines) > max_lines:
            # 古い行を削除して新しい行を保持
            keep_lines = lines[-max_lines:]
            new_text = '\n'.join(keep_lines)
            
            # カーソル位置を保存
            cursor_pos = self.textCursor().position()
            
            # テキストを更新
            self.setPlainText(new_text)
            
            # カーソルを末尾に移動
            self.moveCursor(QTextCursor.MoveOperation.End)


class TerminalItem(NoteItem):
    """
    ターミナルアイテム - キャンバス上に配置できる直接入力対応ターミナル
    """
    TYPE_NAME = "terminal"

    @classmethod
    def supports_path(cls, path: str) -> bool:
        """このクラスは特定のファイルパスをサポートしない（メニューから作成）"""
        return False

    def __init__(
        self,
        d: dict[str, Any] | None = None,
        cb_resize: Callable[[int, int], None] | None = None,
        text_color: QColor | None = None
    ):
        # デフォルト設定
        if d is None:
            d = {}
        
        # ターミナル固有のデフォルト値
        d.setdefault("width", 400)
        d.setdefault("height", 300)
        d.setdefault("workdir", os.getcwd())
        d.setdefault("terminal_type", "cmd")  # cmd, powershell, wsl
        d.setdefault("startup_command", "")
        d.setdefault("auto_start", False)
        d.setdefault("font_size", 12)
        d.setdefault("background_color", "#000000")
        d.setdefault("text_color", "#ffffff")
        d.setdefault("caption", "Terminal")

        # リサイズコールバックが設定されていない場合はデフォルトのコールバックを作成
        if cb_resize is None:
            cb_resize = self._default_resize_callback
        
        super().__init__(d, cb_resize)
        
        # NoteItemが期待する属性を設定
        self.text = ""  # NoteItemのテキスト内容
        self.format = "text"  # NoteItemのフォーマット
        
        # ターミナル独自のモード管理（NoteItemの_modeと区別）
        self._terminal_mode = 0  # 0=WALK, 1=SCROLL
        self._scroll_ready = False
        
        # 直接入力対応ターミナルウィジェット
        self._terminal_widget = TerminalWidget()
        self._terminal_widget.command_executed.connect(self._on_command_executed)
        
        # ウィジェットをGraphicsProxyWidgetでラップ
        self._proxy_widget = QGraphicsProxyWidget(parent=self)
        self._proxy_widget.setWidget(self._terminal_widget)
        
        # ダブルクリック検出は on_activate メソッドで処理
        
        # フォーカス設定
        self._proxy_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._terminal_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # プロキシウィジェットでターミナルのマウス・キーボードイベントを処理
        self._proxy_widget.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | 
            Qt.MouseButton.RightButton | 
            Qt.MouseButton.MiddleButton
        )
        self._proxy_widget.setAcceptHoverEvents(True)
        
        # プロキシウィジェットでフォーカスを受け取る
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsSelectable, True)
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsFocusable, True)
        
        # ターミナルウィジェットが正常に動作するようにする
        self._terminal_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        # 一時的にプロキシウィジェットを非表示にしてテスト
        # self._proxy_widget.setVisible(False)  # テスト用：プロキシウィジェット非表示
        
        # 背景色設定
        bg_color = QColor(self.d.get("background_color", "#000000"))
        self._rect_item.setBrush(QBrush(bg_color))
        self._rect_item.setPen(QPen(QColor("#555555"), 2))

        # プロセス管理
        self._process = None
        
        # 設定を適用
        self._apply_settings()
        
        # 初期サイズ設定
        self._update_size()
        
        # マウス透過設定を調整
        self.init_mouse_passthrough()
        
        # 自動起動が有効な場合
        if self.d.get("auto_start", False) and self.d.get("startup_command"):
            QTimer.singleShot(1000, self._auto_start_command)

    def _default_resize_callback(self, w: int, h: int):
        """デフォルトのリサイズコールバック"""
        # 特に何もしない（on_resizedが呼ばれるだけで十分）
        pass
    
    def _setup_terminal_event_handling(self):
        """ターミナルウィジェットのイベントハンドリング設定"""
        # NoteItemと同様にCanvasItemレベルでダブルクリックを処理するため、
        # ここでは特別な設定は不要
        pass

    def init_mouse_passthrough(self):
        """マウス透過設定を調整（プロキシウィジェットは除外）"""
        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                # プロキシウィジェットはマウスイベントを受け取る（ターミナル操作のため）
                pass
                continue
            elif hasattr(child, 'setAcceptedMouseButtons'):
                # その他の子アイテムはマウス透過
                child.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def _apply_settings(self):
        """設定をターミナルウィジェットに適用"""
        self._terminal_widget.set_terminal_font(self.d.get("font_size", 12))
        self._terminal_widget.set_terminal_colors(
            self.d.get("background_color", "#000000"),
            self.d.get("text_color", "#ffffff")
        )
        self._terminal_widget.set_working_directory(self.d.get("workdir", os.getcwd()))

    def _update_size(self):
        """ターミナルのサイズを更新"""
        w = self.d.get("width", 400)
        h = self.d.get("height", 300)
        
        # 背景矩形のサイズ設定
        self._rect_item.setRect(0, 0, w, h)
        
        # ターミナルウィジェットのサイズ設定（マージン考慮）
        margin = 5
        widget_w = max(100, w - margin * 2)  # 最小サイズを確保
        widget_h = max(50, h - margin * 2)   # 最小サイズを確保
        
        if self._terminal_widget:
            self._terminal_widget.setFixedSize(widget_w, widget_h)
            
        if self._proxy_widget:
            self._proxy_widget.setPos(margin, margin)
            # プロキシウィジェットのサイズも明示的に設定
            self._proxy_widget.resize(widget_w, widget_h)
            # 最小・最大サイズも設定
            self._proxy_widget.setMinimumSize(widget_w, widget_h)
            self._proxy_widget.setMaximumSize(widget_w, widget_h)

    def _auto_start_command(self):
        """自動実行コマンドを実行"""
        startup_cmd = self.d.get("startup_command", "")
        if startup_cmd:
            self._on_command_executed(startup_cmd)

    def _on_command_executed(self, command: str):
        """コマンド実行時の処理"""
        try:
            terminal_type = self.d.get("terminal_type", "cmd")
            workdir = self.d.get("workdir", os.getcwd())
            
            
            # ターミナルタイプに応じてコマンドを調整
            if terminal_type == "cmd":
                full_command = ["cmd", "/c", command]
            elif terminal_type == "powershell":
                # PowerShellの実行を改善
                full_command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
            elif terminal_type == "wsl":
                full_command = ["wsl", "-e", "bash", "-c", command]
            else:
                full_command = ["cmd", "/c", command]
            
            # プロセス実行（エンコーディング対応）
            result = subprocess.run(
                full_command,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace'
            )
            
            
            # 結果をターミナルに表示
            output = ""
            if result.stdout:
                output += result.stdout.strip()
            if result.stderr:
                if output:
                    output += "\n"
                output += f"Error: {result.stderr.strip()}"
            
            if output:
                self._terminal_widget.add_output(output)
            elif result.returncode == 0:
                # 出力がない場合でも成功を示す
                self._terminal_widget.add_output("(コマンド実行完了)")
            else:
                # エラーコードがある場合
                self._terminal_widget.add_output(f"終了コード: {result.returncode}")
            
        except subprocess.TimeoutExpired:
            self._terminal_widget.add_output("Timeout: Command took too long")
        except Exception as e:
            self._terminal_widget.add_output(f"Error: {str(e)}")
    
    def wheelEvent(self, event):
        """マウスホイールイベントの処理"""
        if not getattr(self, "run_mode", False):
            return super().wheelEvent(event)
        
        if self._terminal_mode == 1:  # SCROLL
            # スクロールモードでは ターミナルウィジェットにホイールイベントを転送
            if self._terminal_widget:
                self._terminal_widget.wheelEvent(event)
                event.accept()
                return
        
        # WALKモードでは通常のキャンバス処理
        super().wheelEvent(event)
    
    # NoteItemのダブルクリック機能を継承して使用
    
    def mousePressEvent(self, event):
        """マウスプレスイベントの処理"""
        pass
        if not getattr(self, "run_mode", False):
            return super().mousePressEvent(event)
        
        if event.button() == Qt.MouseButton.LeftButton:
            if self._terminal_mode == 1:  # SCROLL
                # スクロールモードでは親の処理を呼ぶ
                return super().mousePressEvent(event)
            else:
                # WALKモードでは通常のキャンバス処理
                return super().mousePressEvent(event)
        
        super().mousePressEvent(event)
    
    def _update_mode_indication(self):
        """モード表示を更新"""
        # 簡単なモード表示（将来的にはラベルを追加可能）
        if self._terminal_mode == 1:
            # SCROLLモード：ターミナルウィジェットにフォーカスを設定
            if self._terminal_widget:
                self._terminal_widget.setFocus()
        else:
            # WALKモード：フォーカスを外す
            if self._terminal_widget:
                self._terminal_widget.clearFocus()

    def on_resized(self, w: int, h: int):
        """リサイズ時の処理"""
        super().on_resized(w, h)
        self.d["width"] = w
        self.d["height"] = h
        
        # サイズ更新
        self._update_size()
        
        # 強制的にウィジェットを更新
        if self._terminal_widget:
            self._terminal_widget.update()
        if self._proxy_widget:
            self._proxy_widget.update()
            
        # boundingRectの更新を通知
        self.prepareGeometryChange()
    
    def boundingRect(self):
        """バウンディング矩形を返す"""
        w = self.d.get("width", 400)
        h = self.d.get("height", 300)
        return QRectF(0, 0, w, h)
    
    def resize_content(self, w: int, h: int):
        """リサイズグリップによるリサイズ処理"""
        # サイズをdictに保存
        self.d["width"] = w
        self.d["height"] = h
        
        # ターミナルウィジェットのサイズを更新
        self._update_size()
        
        # コールバック呼び出し
        if callable(self._cb_resize):
            self._cb_resize(w, h)
        
        # on_resized呼び出し
        self.on_resized(w, h)

    def on_edit(self):
        """編集ダイアログを表示"""
        dialog = TerminalEditDialog(self.d)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 設定を更新
            self.d.update(dialog.get_data())
            self._update_appearance()

    def _update_appearance(self):
        """外観を更新"""
        # 設定を再適用
        self._apply_settings()
        
        # 背景色更新
        bg_color = QColor(self.d.get("background_color", "#000000"))
        self._rect_item.setBrush(QBrush(bg_color))
        
        # サイズ更新
        self._update_size()

    def contextMenuEvent(self, ev):
        """右クリックメニュー"""
        from PySide6.QtWidgets import QMenu
        
        menu = QMenu()
        
        # カスタムアクション
        clear_action = menu.addAction("Clear Terminal")
        clear_action.triggered.connect(self._clear_terminal)
        
        focus_action = menu.addAction("Focus Terminal")
        focus_action.triggered.connect(lambda: self._terminal_widget.setFocus())
        
        menu.addSeparator()
        
        # 共通メニューも表示
        super().contextMenuEvent(ev)

    def _clear_terminal(self):
        """ターミナルをクリア"""
        self._terminal_widget.clear_terminal()

    def mousePressEvent(self, event):
        """マウスクリック時にターミナルにフォーカスを移す"""
        if event.button() == Qt.MouseButton.LeftButton:
            # ターミナル領域内のクリックかチェック
            proxy_rect = self._proxy_widget.boundingRect()
            proxy_pos = self._proxy_widget.pos()
            terminal_area = QRectF(proxy_pos, proxy_rect.size())
            
            if terminal_area.contains(event.pos()):
                # ターミナルウィジェットにフォーカスを設定
                self._terminal_widget.setFocus()
                self._proxy_widget.setFocus()
                event.accept()
                return
        
        # 通常のマウスイベント処理
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """ダブルクリック時の処理"""
        if event.button() == Qt.MouseButton.LeftButton:
            # ターミナル領域内のダブルクリックかチェック
            proxy_rect = self._proxy_widget.boundingRect()
            proxy_pos = self._proxy_widget.pos()
            terminal_area = QRectF(proxy_pos, proxy_rect.size())
            
            if terminal_area.contains(event.pos()):
                # ターミナルにフォーカスを移す
                self._terminal_widget.setFocus()
                self._proxy_widget.setFocus()
                event.accept()
                return
        
        # 通常のダブルクリック処理
        super().mouseDoubleClickEvent(event)

    def focusInEvent(self, event):
        """フォーカスイン時の処理"""
        super().focusInEvent(event)
        # ターミナルウィジェットにもフォーカスを渡す
        self._terminal_widget.setFocus()

    def keyPressEvent(self, event):
        """キーイベントをターミナルウィジェットに転送"""
        if self._terminal_widget.hasFocus() or self._proxy_widget.hasFocus():
            # ターミナルウィジェットにキーイベントを送る
            self._terminal_widget.keyPressEvent(event)
            event.accept()
        else:
            super().keyPressEvent(event)

    def delete_self(self):
        """ターミナル削除時のクリーンアップ処理"""
        try:
            # プロセスを確実に終了
            if hasattr(self, '_process') and self._process:
                if self._process.state() != QProcess.ProcessState.NotRunning:
                    self._process.kill()
                    self._process.waitForFinished(3000)  # 3秒待機
                self._process = None
            
            # ターミナルウィジェットのクリーンアップ
            if hasattr(self, '_terminal_widget') and self._terminal_widget:
                # QProcess系のシグナル切断
                try:
                    if hasattr(self._terminal_widget, 'command_executed'):
                        self._terminal_widget.command_executed.disconnect()
                except Exception:
                    pass
                self._terminal_widget = None
            
            # プロキシウィジェットのクリーンアップ
            if hasattr(self, '_proxy_widget') and self._proxy_widget:
                if self._proxy_widget.scene():
                    self._proxy_widget.scene().removeItem(self._proxy_widget)
                self._proxy_widget = None
            
        except Exception as e:
            warn(f"Error during TerminalItem cleanup: {e}")
        
        # 基底クラスの削除処理を呼び出し
        super().delete_self()


class TerminalEditDialog(QDialog):
    """ターミナル設定編集ダイアログ"""
    
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data.copy()
        self.setWindowTitle("Terminal Settings")
        self.setModal(True)
        self.resize(400, 500)
        
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout()
        
        # 基本設定
        basic_group = self._create_basic_group()
        layout.addWidget(basic_group)
        
        # ターミナル設定
        terminal_group = self._create_terminal_group()
        layout.addWidget(terminal_group)
        
        # 外観設定
        appearance_group = self._create_appearance_group()
        layout.addWidget(appearance_group)
        
        # ボタン
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _create_basic_group(self):
        from PySide6.QtWidgets import QGroupBox, QFormLayout
        
        group = QGroupBox("Basic Settings")
        layout = QFormLayout()
        
        self.caption_edit = QLineEdit()
        layout.addRow("Caption:", self.caption_edit)
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(200, 2000)
        layout.addRow("Width:", self.width_spin)
        
        self.height_spin = QSpinBox()
        self.height_spin.setRange(150, 1500)
        layout.addRow("Height:", self.height_spin)
        
        group.setLayout(layout)
        return group

    def _create_terminal_group(self):
        from PySide6.QtWidgets import QGroupBox, QFormLayout
        
        group = QGroupBox("Terminal Settings")
        layout = QFormLayout()
        
        self.terminal_type_combo = QComboBox()
        self.terminal_type_combo.addItems(["cmd", "powershell", "wsl"])
        layout.addRow("Terminal Type:", self.terminal_type_combo)
        
        self.workdir_edit = QLineEdit()
        layout.addRow("Working Directory:", self.workdir_edit)
        
        self.startup_command_edit = QTextEdit()
        self.startup_command_edit.setMaximumHeight(60)
        layout.addRow("Startup Command:", self.startup_command_edit)
        
        self.auto_start_check = QCheckBox("Auto-start command on project load")
        layout.addRow("", self.auto_start_check)
        
        group.setLayout(layout)
        return group

    def _create_appearance_group(self):
        from PySide6.QtWidgets import QGroupBox, QFormLayout
        
        group = QGroupBox("Appearance")
        layout = QFormLayout()
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        layout.addRow("Font Size:", self.font_size_spin)
        
        self.bg_color_edit = QLineEdit()
        layout.addRow("Background Color:", self.bg_color_edit)
        
        self.text_color_edit = QLineEdit()
        layout.addRow("Text Color:", self.text_color_edit)
        
        group.setLayout(layout)
        return group

    def _load_data(self):
        """データをUIに読み込み"""
        self.caption_edit.setText(self.data.get("caption", "Terminal"))
        self.width_spin.setValue(self.data.get("width", 400))
        self.height_spin.setValue(self.data.get("height", 300))
        
        terminal_type = self.data.get("terminal_type", "cmd")
        index = self.terminal_type_combo.findText(terminal_type)
        if index >= 0:
            self.terminal_type_combo.setCurrentIndex(index)
        
        self.workdir_edit.setText(self.data.get("workdir", os.getcwd()))
        self.startup_command_edit.setPlainText(self.data.get("startup_command", ""))
        self.auto_start_check.setChecked(self.data.get("auto_start", False))
        
        self.font_size_spin.setValue(self.data.get("font_size", 12))
        self.bg_color_edit.setText(self.data.get("background_color", "#000000"))
        self.text_color_edit.setText(self.data.get("text_color", "#ffffff"))

    def get_data(self) -> dict:
        """UI設定を辞書として返す"""
        return {
            "caption": self.caption_edit.text(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "terminal_type": self.terminal_type_combo.currentText(),
            "workdir": self.workdir_edit.text(),
            "startup_command": self.startup_command_edit.toPlainText(),
            "auto_start": self.auto_start_check.isChecked(),
            "font_size": self.font_size_spin.value(),
            "background_color": self.bg_color_edit.text(),
            "text_color": self.text_color_edit.text(),
        }