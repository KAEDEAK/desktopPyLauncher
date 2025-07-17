# -*- coding: utf-8 -*-
"""
DPyL_interactive_terminal.py ― 双方向通信対応ターミナルアイテム
◎ Qt6 / PySide6 専用
◎ QProcess を使用した双方向通信対応
◎ ANSI エスケープシーケンス対応
◎ pythonやclaudeなどの対話型プログラムで固まらない設計
"""
from __future__ import annotations
import os
import sys
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

from PySide6.QtCore import (
    Qt, QPointF, QRectF, QSizeF, QTimer, QSize, QProcess, QIODevice, 
    Signal, QObject, QEvent, QThread, QMutex, QMutexLocker
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QBrush, QPen, QIcon, QFont, 
    QKeyEvent, QTextCursor, QTextCharFormat, QMouseEvent,
    QTextDocument, QTextBlockFormat
)
# QGraphicsSceneMouseEventはQtGuiにある
# from PySide6.QtWidgets import QGraphicsSceneMouseEvent
from PySide6.QtWidgets import (
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsItemGroup,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QCheckBox, QSpinBox,
    QGraphicsProxyWidget, QScrollBar, QTextBrowser, QPlainTextEdit,
    QGraphicsItem, QGroupBox, QFormLayout
)

# プロジェクト内モジュール
try:
    from DPyL_classes import CanvasItem
    from DPyL_note import NoteItem
    from DPyL_utils import warn, debug_print
except ImportError:
    # テスト環境用の代替
    from PySide6.QtWidgets import QGraphicsItemGroup as CanvasItem
    from PySide6.QtWidgets import QGraphicsItemGroup as NoteItem
    def warn(msg): print(f"WARN: {msg}")
    def debug_print(msg): print(f"DEBUG: {msg}")


class AnsiEscapeHandler:
    """
    ANSI エスケープシーケンスを解析してQTextCharFormatに変換するハンドラ
    """
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """状態をリセット"""
        self.current_format = QTextCharFormat()
        self._setup_default_colors()
    
    def _setup_default_colors(self):
        """デフォルトカラーパレットを設定"""
        # ANSI 標準色（0-15）
        self.color_map = {
            # 標準色（暗い）
            30: QColor(0, 0, 0),        # 黒
            31: QColor(128, 0, 0),      # 赤
            32: QColor(0, 128, 0),      # 緑
            33: QColor(128, 128, 0),    # 黄
            34: QColor(0, 0, 128),      # 青
            35: QColor(128, 0, 128),    # マゼンタ
            36: QColor(0, 128, 128),    # シアン
            37: QColor(192, 192, 192),  # 白
            
            # 明るい色
            90: QColor(128, 128, 128),  # 明るい黒（グレー）
            91: QColor(255, 0, 0),      # 明るい赤
            92: QColor(0, 255, 0),      # 明るい緑
            93: QColor(255, 255, 0),    # 明るい黄
            94: QColor(0, 0, 255),      # 明るい青
            95: QColor(255, 0, 255),    # 明るいマゼンタ
            96: QColor(0, 255, 255),    # 明るいシアン
            97: QColor(255, 255, 255),  # 明るい白
        }
        
        # 背景色マップ（40-47, 100-107）
        self.bg_color_map = {}
        for fg_code, color in self.color_map.items():
            if 30 <= fg_code <= 37:
                self.bg_color_map[fg_code + 10] = color  # 40-47
            elif 90 <= fg_code <= 97:
                self.bg_color_map[fg_code + 10] = color  # 100-107
    
    def parse_text(self, text: str) -> list[tuple[str, QTextCharFormat]]:
        """
        テキストを解析してANSIエスケープシーケンスを処理
        戻り値: [(テキスト, フォーマット), ...] のリスト
        """
        result = []
        current_pos = 0
        current_format = QTextCharFormat(self.current_format)
        
        # ANSI エスケープシーケンスのパターン
        ansi_pattern = re.compile(r'\x1b\[[0-9;]*[mK]')
        
        for match in ansi_pattern.finditer(text):
            # エスケープシーケンス前のテキスト
            if match.start() > current_pos:
                plain_text = text[current_pos:match.start()]
                if plain_text:
                    result.append((plain_text, QTextCharFormat(current_format)))
            
            # エスケープシーケンスを処理
            sequence = match.group()
            current_format = self._process_escape_sequence(sequence, current_format)
            current_pos = match.end()
        
        # 残りのテキスト
        if current_pos < len(text):
            remaining_text = text[current_pos:]
            if remaining_text:
                result.append((remaining_text, QTextCharFormat(current_format)))
        
        # 現在のフォーマットを保存
        self.current_format = current_format
        
        return result
    
    def _process_escape_sequence(self, sequence: str, format: QTextCharFormat) -> QTextCharFormat:
        """ANSIエスケープシーケンスを処理してフォーマットを更新"""
        new_format = QTextCharFormat(format)
        
        # \x1b[ を除去して数値部分を取得
        codes_str = sequence[2:-1]  # \x1b[ と最後の文字を除去
        
        if not codes_str:  # 空の場合はリセット
            codes = [0]
        else:
            try:
                codes = [int(x) if x else 0 for x in codes_str.split(';')]
            except ValueError:
                return new_format
        
        i = 0
        while i < len(codes):
            code = codes[i]
            
            if code == 0:  # リセット
                new_format = QTextCharFormat()
            elif code == 1:  # 太字
                new_format.setFontWeight(QFont.Weight.Bold)
            elif code == 3:  # 斜体
                new_format.setFontItalic(True)
            elif code == 4:  # 下線
                new_format.setFontUnderline(True)
            elif code == 22:  # 太字解除
                new_format.setFontWeight(QFont.Weight.Normal)
            elif code == 23:  # 斜体解除
                new_format.setFontItalic(False)
            elif code == 24:  # 下線解除
                new_format.setFontUnderline(False)
            elif code in self.color_map:  # 前景色
                new_format.setForeground(QBrush(self.color_map[code]))
            elif code in self.bg_color_map:  # 背景色
                new_format.setBackground(QBrush(self.bg_color_map[code]))
            elif code == 38:  # 256色/RGB前景色
                if i + 2 < len(codes) and codes[i + 1] == 5:  # 256色
                    color_index = codes[i + 2]
                    if color_index < 256:
                        color = self._get_256_color(color_index)
                        new_format.setForeground(QBrush(color))
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:  # RGB
                    r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                    color = QColor(r, g, b)
                    new_format.setForeground(QBrush(color))
                    i += 4
            elif code == 48:  # 256色/RGB背景色
                if i + 2 < len(codes) and codes[i + 1] == 5:  # 256色
                    color_index = codes[i + 2]
                    if color_index < 256:
                        color = self._get_256_color(color_index)
                        new_format.setBackground(QBrush(color))
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:  # RGB
                    r, g, b = codes[i + 2], codes[i + 3], codes[i + 4]
                    color = QColor(r, g, b)
                    new_format.setBackground(QBrush(color))
                    i += 4
            
            i += 1
        
        return new_format
    
    def _get_256_color(self, index: int) -> QColor:
        """256色パレットから色を取得"""
        if index < 16:
            # 標準16色
            if index < 8:
                return list(self.color_map.values())[index]
            else:
                return list(self.color_map.values())[index - 8 + 8]
        elif index < 232:
            # 216色キューブ (16-231)
            index -= 16
            r = (index // 36) * 51
            g = ((index % 36) // 6) * 51
            b = (index % 6) * 51
            return QColor(r, g, b)
        else:
            # グレースケール (232-255)
            gray = 8 + (index - 232) * 10
            return QColor(gray, gray, gray)


class InteractiveTerminalWidget(QTextEdit):
    """
    双方向通信対応のターミナルウィジェット
    QProcessを使用して外部プロセスと通信
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # プロセス管理
        self.process = None
        self.is_process_running = False
        
        # ANSI エスケープシーケンス処理
        self.ansi_handler = AnsiEscapeHandler()
        
        # 入力制御
        self.input_start_position = 0
        self.command_history = []
        self.history_index = -1
        self.current_input = ""
        
        # 設定
        self.prompt = "$ "
        self.working_directory = os.getcwd()
        self.shell_command = self._get_default_shell()
        
        # 外観設定
        self._setup_appearance()
        
        # 初期プロンプト表示
        self._append_prompt()
        
        # フォーカス設定
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    
    def _get_default_shell(self) -> list[str]:
        """デフォルトシェルコマンドを取得"""
        if os.name == 'nt':  # Windows
            return ["cmd.exe"]
        else:  # Unix系
            return ["/bin/bash", "-i"]
    
    def set_terminal_type(self, terminal_type: str):
        """ターミナルタイプを設定"""
        if terminal_type == "cmd":
            self.shell_command = ["cmd.exe", "/K", "chcp 65001"]  # UTF-8対応
        elif terminal_type == "powershell":
            # Windows PowerShell (古い方)
            self.shell_command = ["powershell.exe", "-NoExit", "-Command", "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"]
        elif terminal_type == "pwsh":
            # PowerShell Core (新しい方)
            self.shell_command = ["pwsh.exe", "-NoExit"]
        elif terminal_type == "wsl":
            self.shell_command = ["wsl.exe"]
        elif terminal_type == "custom":
            # カスタムコマンドは別途設定
            pass
        else:
            self.shell_command = self._get_default_shell()
    
    def _setup_appearance(self):
        """外観を設定"""
        # 日本語対応フォント設定
        fonts_to_try = [
            "BIZ UDゴシック",     # Windows 10/11 標準の日本語等幅フォント
            "MS ゴシック",         # 従来の日本語等幅フォント
            "Consolas",          # 英語等幅フォント
            "Courier New",       # フォールバック
            "monospace"          # システムデフォルト
        ]
        
        font = None
        for font_name in fonts_to_try:
            test_font = QFont(font_name, 10)
            if test_font.exactMatch() or font_name == "monospace":
                font = test_font
                break
        
        if font is None:
            font = QFont("Courier New", 10)
        
        self.setFont(font)
        
        # 色設定
        self.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #264f78;
            }
        """)
        
        # その他設定
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setUndoRedoEnabled(False)
    
    def start_process(self, command: list[str] = None, working_dir: str = None):
        """プロセスを開始"""
        if self.is_process_running:
            self.stop_process()
        
        if command is None:
            command = self.shell_command
        if working_dir is None:
            working_dir = self.working_directory
        
        self.process = QProcess(self)
        self.process.setWorkingDirectory(working_dir)
        
        # 日本語対応：環境変数を設定
        from PySide6.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        
        # UTF-8エンコーディングを強制
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("LANG", "ja_JP.UTF-8")
        env.insert("LC_ALL", "ja_JP.UTF-8")
        # Windows用
        env.insert("CHCP", "65001")
        self.process.setProcessEnvironment(env)
        
        # シグナル接続
        self.process.readyReadStandardOutput.connect(self._handle_stdout)
        self.process.readyReadStandardError.connect(self._handle_stderr)
        self.process.finished.connect(self._handle_process_finished)
        self.process.errorOccurred.connect(self._handle_process_error)
        
        # プロセス開始
        try:
            self.process.start(command[0], command[1:])
            if self.process.waitForStarted(3000):
                self.is_process_running = True
                self._append_text(f"Started: {' '.join(command)}\n", QColor(0, 255, 0))
            else:
                self._append_text(f"Failed to start: {' '.join(command)}\n", QColor(255, 0, 0))
        except Exception as e:
            self._append_text(f"Error starting process: {str(e)}\n", QColor(255, 0, 0))
    
    def stop_process(self):
        """プロセスを停止"""
        if self.process and self.is_process_running:
            self.process.kill()
            self.process.waitForFinished(3000)
            self.is_process_running = False
            self._append_text("Process terminated.\n", QColor(255, 255, 0))
    
    def _handle_stdout(self):
        """標準出力を処理"""
        if not self.process:
            return
        
        data = self.process.readAllStandardOutput()
        # 複数のエンコーディングを試行
        text = self._decode_with_fallback(data.data())
        self._append_ansi_text(text)
    
    def _handle_stderr(self):
        """標準エラー出力を処理"""
        if not self.process:
            return
        
        data = self.process.readAllStandardError()
        # 複数のエンコーディングを試行
        text = self._decode_with_fallback(data.data())
        self._append_ansi_text(text, error=True)
    
    def _decode_with_fallback(self, data: bytes) -> str:
        """複数のエンコーディングを試行してデコード"""
        encodings = ['utf-8', 'cp932', 'shift_jis', 'euc-jp', 'iso-2022-jp']
        
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # すべて失敗した場合はUTF-8でエラーを置換
        return data.decode('utf-8', errors='replace')
    
    def _handle_process_finished(self, exit_code: int):
        """プロセス終了を処理"""
        self.is_process_running = False
        self._append_text(f"\nProcess finished with exit code {exit_code}\n", QColor(255, 255, 0))
        self._append_prompt()
    
    def _handle_process_error(self, error):
        """プロセスエラーを処理"""
        self.is_process_running = False
        error_msg = f"Process error: {error}\n"
        self._append_text(error_msg, QColor(255, 0, 0))
        self._append_prompt()
    
    def _append_ansi_text(self, text: str, error: bool = False):
        """ANSIエスケープシーケンス対応テキストを追加"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # ANSI エスケープシーケンスを解析
        segments = self.ansi_handler.parse_text(text)
        
        for segment_text, format in segments:
            if error and not format.foreground().color().isValid():
                # エラー出力で色が指定されていない場合は赤色に
                format.setForeground(QBrush(QColor(255, 100, 100)))
            
            cursor.insertText(segment_text, format)
        
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        
        # 入力位置を更新
        self.input_start_position = cursor.position()
    
    def _append_text(self, text: str, color: QColor = None):
        """色付きテキストを追加"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if color:
            format = QTextCharFormat()
            format.setForeground(QBrush(color))
            cursor.insertText(text, format)
        else:
            cursor.insertText(text)
        
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        
        # 入力位置を更新
        self.input_start_position = cursor.position()
    
    def _append_prompt(self):
        """プロンプトを追加"""
        if not self.is_process_running:
            self._append_text(self.prompt, QColor(100, 255, 100))
            self.input_start_position = self.textCursor().position()
    
    def keyPressEvent(self, event: QKeyEvent):
        """キー入力処理"""
        # カーソル位置制御
        cursor = self.textCursor()
        if cursor.position() < self.input_start_position:
            cursor.setPosition(self.input_start_position)
            self.setTextCursor(cursor)
        
        key = event.key()
        modifiers = event.modifiers()
        
        # 特別なキー処理
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._handle_return()
            return
        elif key == Qt.Key.Key_Up:
            self._handle_history_up()
            return
        elif key == Qt.Key.Key_Down:
            self._handle_history_down()
            return
        elif key == Qt.Key.Key_Tab:
            if self.is_process_running:
                self._send_to_process("\t")
            return
        elif key == Qt.Key.Key_C and modifiers == Qt.KeyboardModifier.ControlModifier:
            if self.is_process_running:
                self._send_to_process("\x03")  # Ctrl+C
            return
        elif key == Qt.Key.Key_D and modifiers == Qt.KeyboardModifier.ControlModifier:
            if self.is_process_running:
                self._send_to_process("\x04")  # Ctrl+D
            return
        elif key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            if self.is_process_running:
                self._send_to_process("\x1a")  # Ctrl+Z
            return
        elif key == Qt.Key.Key_Backspace:
            if cursor.position() <= self.input_start_position:
                return
        elif key == Qt.Key.Key_Left:
            if cursor.position() <= self.input_start_position:
                return
        elif key == Qt.Key.Key_Home:
            cursor.setPosition(self.input_start_position)
            self.setTextCursor(cursor)
            return
        
        # 通常のキー入力
        super().keyPressEvent(event)
    
    def _handle_return(self):
        """Enterキー処理"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        # 現在の入力を取得
        cursor.setPosition(self.input_start_position, QTextCursor.MoveMode.MoveAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        input_text = cursor.selectedText()
        
        # 履歴に追加
        if input_text.strip() and (not self.command_history or self.command_history[-1] != input_text):
            self.command_history.append(input_text)
        self.history_index = len(self.command_history)
        
        # 改行を追加
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\n")
        self.setTextCursor(cursor)
        
        if self.is_process_running:
            # プロセスに送信
            self._send_to_process(input_text + "\n")
        else:
            # プロセスが実行されていない場合はシェルコマンドとして処理
            self._execute_shell_command(input_text.strip())
        
        self.input_start_position = cursor.position()
    
    def _handle_history_up(self):
        """履歴を戻る"""
        if not self.command_history:
            return
        
        if self.history_index > 0:
            self.history_index -= 1
            self._replace_current_input(self.command_history[self.history_index])
    
    def _handle_history_down(self):
        """履歴を進む"""
        if not self.command_history:
            return
        
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self._replace_current_input(self.command_history[self.history_index])
        elif self.history_index == len(self.command_history) - 1:
            self.history_index = len(self.command_history)
            self._replace_current_input("")
    
    def _replace_current_input(self, text: str):
        """現在の入力を置換"""
        cursor = self.textCursor()
        cursor.setPosition(self.input_start_position)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)
    
    def _send_to_process(self, text: str):
        """プロセスにテキストを送信"""
        if self.process and self.is_process_running:
            # Windows環境では複数のエンコーディングを試行
            if os.name == 'nt':
                encodings = ['utf-8', 'cp932', 'shift_jis']
                for encoding in encodings:
                    try:
                        data = text.encode(encoding)
                        self.process.write(data)
                        break
                    except UnicodeEncodeError:
                        continue
                else:
                    # すべて失敗した場合はUTF-8でエラーを置換
                    data = text.encode('utf-8', errors='replace')
                    self.process.write(data)
            else:
                # Unix系はUTF-8
                data = text.encode('utf-8')
                self.process.write(data)
    
    def _execute_shell_command(self, command: str):
        """シェルコマンドを実行"""
        if not command:
            self._append_prompt()
            return
        
        if command.lower() in ['exit', 'quit']:
            return
        elif command.startswith('cd '):
            # ディレクトリ変更
            path = command[3:].strip()
            if path:
                try:
                    if os.path.isdir(path):
                        self.working_directory = os.path.abspath(path)
                        os.chdir(self.working_directory)
                        self._append_text(f"Changed directory to: {self.working_directory}\n")
                    else:
                        self._append_text(f"Directory not found: {path}\n", QColor(255, 0, 0))
                except Exception as e:
                    self._append_text(f"Error changing directory: {str(e)}\n", QColor(255, 0, 0))
            self._append_prompt()
        elif command in ['python', 'python3', 'node', 'claude']:
            # 対話型プログラムを開始
            if command in ['python', 'python3']:
                self.start_process([command, '-u'], self.working_directory)
            else:
                self.start_process([command], self.working_directory)
        else:
            # 通常のコマンドを実行
            if os.name == 'nt':
                self.start_process(['cmd', '/c', command], self.working_directory)
            else:
                self.start_process(['bash', '-c', command], self.working_directory)
    
    def clear_terminal(self):
        """ターミナルをクリア"""
        self.clear()
        self.ansi_handler.reset()
        self._append_prompt()
    
    def set_working_directory(self, path: str):
        """作業ディレクトリを設定"""
        if os.path.isdir(path):
            self.working_directory = path
            os.chdir(path)
            # プロンプトを更新
            dir_name = os.path.basename(path) or path
            self.prompt = f"{dir_name}$ "


class InteractiveTerminalItem(NoteItem):
    """
    双方向通信対応ターミナルアイテム
    """
    TYPE_NAME = "interactive_terminal"

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
        d.setdefault("width", 600)
        d.setdefault("height", 400)
        d.setdefault("workdir", os.getcwd())
        d.setdefault("terminal_type", "cmd")  # cmd, powershell, pwsh, wsl, custom
        d.setdefault("shell_command", "")
        d.setdefault("auto_start", False)
        d.setdefault("font_size", 10)
        d.setdefault("background_color", "#1e1e1e")
        d.setdefault("text_color", "#ffffff")
        d.setdefault("caption", "Interactive Terminal")

        # リサイズコールバックが設定されていない場合はデフォルトのコールバックを作成
        if cb_resize is None:
            cb_resize = self._default_resize_callback
        
        super().__init__(d, cb_resize)
        
        # NoteItemが期待する属性を設定
        self.text = ""
        self.format = "text"
        
        # 双方向通信対応ターミナルウィジェット
        self._terminal_widget = InteractiveTerminalWidget()
        
        # ウィジェットをGraphicsProxyWidgetでラップ
        self._proxy_widget = QGraphicsProxyWidget(parent=self)
        self._proxy_widget.setWidget(self._terminal_widget)
        
        # フォーカス設定
        self._proxy_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._terminal_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # プロキシウィジェットの設定
        self._proxy_widget.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | 
            Qt.MouseButton.RightButton | 
            Qt.MouseButton.MiddleButton
        )
        self._proxy_widget.setAcceptHoverEvents(True)
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsSelectable, True)
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsFocusable, True)
        
        # 背景色設定
        bg_color = QColor(self.d.get("background_color", "#1e1e1e"))
        self._rect_item.setBrush(QBrush(bg_color))
        self._rect_item.setPen(QPen(QColor("#555555"), 2))

        # 設定を適用
        self._apply_settings()
        
        # 初期サイズ設定
        self._update_size()
        
        # 自動起動が有効な場合
        if self.d.get("auto_start", False) and self.d.get("shell_command"):
            QTimer.singleShot(1000, self._auto_start_command)

    def _default_resize_callback(self, w: int, h: int):
        """デフォルトのリサイズコールバック"""
        pass
    
    def _apply_settings(self):
        """設定をターミナルウィジェットに適用"""
        self._terminal_widget.set_working_directory(self.d.get("workdir", os.getcwd()))
        
        # ターミナルタイプの設定
        terminal_type = self.d.get("terminal_type", "cmd")
        self._terminal_widget.set_terminal_type(terminal_type)
        
        # カスタムシェルコマンドの設定（terminal_type が custom の場合）
        if terminal_type == "custom":
            shell_cmd = self.d.get("shell_command", "")
            if shell_cmd:
                if isinstance(shell_cmd, str):
                    shell_cmd = shell_cmd.split()
                self._terminal_widget.shell_command = shell_cmd

    def _update_size(self):
        """ターミナルのサイズを更新"""
        w = self.d.get("width", 600)
        h = self.d.get("height", 400)
        
        # 背景矩形のサイズ設定
        self._rect_item.setRect(0, 0, w, h)
        
        # ターミナルウィジェットのサイズ設定（マージン考慮）
        margin = 5
        widget_w = max(200, w - margin * 2)
        widget_h = max(100, h - margin * 2)
        
        if self._terminal_widget:
            self._terminal_widget.setFixedSize(widget_w, widget_h)
            
        if self._proxy_widget:
            self._proxy_widget.setPos(margin, margin)
            self._proxy_widget.resize(widget_w, widget_h)

    def _auto_start_command(self):
        """自動実行コマンドを実行"""
        terminal_type = self.d.get("terminal_type", "cmd")
        if terminal_type == "custom":
            shell_cmd = self.d.get("shell_command", "")
            if shell_cmd:
                if isinstance(shell_cmd, str):
                    shell_cmd = shell_cmd.split()
                self._terminal_widget.start_process(shell_cmd, self.d.get("workdir", os.getcwd()))
        else:
            # ターミナルタイプに応じたシェルを起動
            self._terminal_widget.start_process(None, self.d.get("workdir", os.getcwd()))

    def on_resized(self, w: int, h: int):
        """リサイズ時の処理"""
        super().on_resized(w, h)
        self.d["width"] = w
        self.d["height"] = h
        self._update_size()
    
    def boundingRect(self):
        """バウンディング矩形を返す"""
        w = self.d.get("width", 600)
        h = self.d.get("height", 400)
        return QRectF(0, 0, w, h)
    
    def resize_content(self, w: int, h: int):
        """リサイズグリップによるリサイズ処理"""
        self.d["width"] = w
        self.d["height"] = h
        self._update_size()
        
        if callable(self._cb_resize):
            self._cb_resize(w, h)
        
        self.on_resized(w, h)

    def on_edit(self):
        """編集ダイアログを表示"""
        dialog = InteractiveTerminalEditDialog(self.d)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.d.update(dialog.get_data())
            self._update_appearance()

    def _update_appearance(self):
        """外観を更新"""
        self._apply_settings()
        
        # 背景色更新
        bg_color = QColor(self.d.get("background_color", "#1e1e1e"))
        self._rect_item.setBrush(QBrush(bg_color))
        
        self._update_size()

    def contextMenuEvent(self, ev):
        """右クリックメニュー"""
        from PySide6.QtWidgets import QMenu
        
        menu = QMenu()
        
        # カスタムアクション
        clear_action = menu.addAction("Clear Terminal")
        clear_action.triggered.connect(lambda: self._terminal_widget.clear_terminal())
        
        if self._terminal_widget.is_process_running:
            stop_action = menu.addAction("Stop Process")
            stop_action.triggered.connect(lambda: self._terminal_widget.stop_process())
        else:
            start_action = menu.addAction("Start Shell")
            start_action.triggered.connect(lambda: self._terminal_widget.start_process())
        
        menu.addSeparator()
        
        # 共通メニューも表示
        super().contextMenuEvent(ev)

    def mousePressEvent(self, event):
        """マウスクリック時にターミナルにフォーカスを移す"""
        if event.button() == Qt.MouseButton.LeftButton:
            # ターミナル領域内のクリックかチェック
            proxy_rect = self._proxy_widget.boundingRect()
            proxy_pos = self._proxy_widget.pos()
            terminal_area = QRectF(proxy_pos, proxy_rect.size())
            
            if terminal_area.contains(event.pos()):
                # フォーカス設定
                if self.scene():
                    self.scene().clearSelection()
                
                # プロキシウィジェットとターミナルウィジェットにフォーカスを設定
                QTimer.singleShot(0, lambda: self._set_terminal_focus())
                event.accept()
                return
        
        super().mousePressEvent(event)
    
    def _set_terminal_focus(self):
        """ターミナルにフォーカスを設定（遅延実行用）"""
        try:
            self._proxy_widget.setSelected(True)
            self._proxy_widget.setFocus()
            self._terminal_widget.setFocus()
        except Exception as e:
            # フォーカス設定が失敗しても致命的ではないので警告のみ
            print(f"Focus setting failed: {e}")
    
    def mouseDoubleClickEvent(self, event):
        """ダブルクリック時の処理を改善"""
        if event.button() == Qt.MouseButton.LeftButton:
            proxy_rect = self._proxy_widget.boundingRect()
            proxy_pos = self._proxy_widget.pos()
            terminal_area = QRectF(proxy_pos, proxy_rect.size())
            
            if terminal_area.contains(event.pos()):
                # ターミナルにフォーカスを設定
                QTimer.singleShot(0, lambda: self._set_terminal_focus())
                event.accept()
                return
        
        super().mouseDoubleClickEvent(event)
    
    def keyPressEvent(self, event):
        """キーイベントをターミナルウィジェットに転送"""
        try:
            if self._proxy_widget.hasFocus() or self._terminal_widget.hasFocus():
                # ターミナルウィジェットにキーイベントを送る
                self._terminal_widget.keyPressEvent(event)
                event.accept()
            else:
                super().keyPressEvent(event)
        except Exception as e:
            # キーイベント処理でエラーが発生した場合は警告を出して続行
            print(f"Key event handling failed: {e}")
            super().keyPressEvent(event)


class InteractiveTerminalEditDialog(QDialog):
    """双方向通信ターミナル設定編集ダイアログ"""
    
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data.copy()
        self.setWindowTitle("Interactive Terminal Settings")
        self.setModal(True)
        self.resize(500, 600)
        
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
        group = QGroupBox("Basic Settings")
        layout = QFormLayout()
        
        self.caption_edit = QLineEdit()
        layout.addRow("Caption:", self.caption_edit)
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(300, 2000)
        layout.addRow("Width:", self.width_spin)
        
        self.height_spin = QSpinBox()
        self.height_spin.setRange(200, 1500)
        layout.addRow("Height:", self.height_spin)
        
        group.setLayout(layout)
        return group

    def _create_terminal_group(self):
        group = QGroupBox("Terminal Settings")
        layout = QFormLayout()
        
        self.terminal_type_combo = QComboBox()
        self.terminal_type_combo.addItems(["cmd", "powershell", "pwsh", "wsl", "custom"])
        self.terminal_type_combo.currentTextChanged.connect(self._on_terminal_type_changed)
        layout.addRow("Terminal Type:", self.terminal_type_combo)
        
        self.workdir_edit = QLineEdit()
        layout.addRow("Working Directory:", self.workdir_edit)
        
        self.shell_command_edit = QLineEdit()
        self.shell_command_label = QLabel("Custom Shell Command:")
        layout.addRow(self.shell_command_label, self.shell_command_edit)
        
        self.auto_start_check = QCheckBox("Auto-start on project load")
        layout.addRow("", self.auto_start_check)
        
        group.setLayout(layout)
        return group
    
    def _on_terminal_type_changed(self, terminal_type: str):
        """ターミナルタイプ変更時の処理"""
        is_custom = terminal_type == "custom"
        self.shell_command_edit.setEnabled(is_custom)
        self.shell_command_label.setEnabled(is_custom)
        
        if not is_custom:
            self.shell_command_edit.clear()

    def _create_appearance_group(self):
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
        self.caption_edit.setText(self.data.get("caption", "Interactive Terminal"))
        self.width_spin.setValue(self.data.get("width", 600))
        self.height_spin.setValue(self.data.get("height", 400))
        
        terminal_type = self.data.get("terminal_type", "cmd")
        index = self.terminal_type_combo.findText(terminal_type)
        if index >= 0:
            self.terminal_type_combo.setCurrentIndex(index)
        
        self.workdir_edit.setText(self.data.get("workdir", os.getcwd()))
        self.shell_command_edit.setText(self.data.get("shell_command", ""))
        self.auto_start_check.setChecked(self.data.get("auto_start", False))
        
        # ターミナルタイプ変更処理を呼び出してUI状態を更新
        self._on_terminal_type_changed(terminal_type)
        
        self.font_size_spin.setValue(self.data.get("font_size", 10))
        self.bg_color_edit.setText(self.data.get("background_color", "#1e1e1e"))
        self.text_color_edit.setText(self.data.get("text_color", "#ffffff"))

    def get_data(self) -> dict:
        """UI設定を辞書として返す"""
        return {
            "caption": self.caption_edit.text(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "terminal_type": self.terminal_type_combo.currentText(),
            "workdir": self.workdir_edit.text(),
            "shell_command": self.shell_command_edit.text(),
            "auto_start": self.auto_start_check.isChecked(),
            "font_size": self.font_size_spin.value(),
            "background_color": self.bg_color_edit.text(),
            "text_color": self.text_color_edit.text(),
        }