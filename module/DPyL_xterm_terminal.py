# -*- coding: utf-8 -*-
"""
DPyL_xterm_terminal.py ― xterm.js ベースの本格的端末エミュレーター
UglyWidgets からのインスピレーションを受けた実装
"""
from __future__ import annotations
import os
import sys
import json
import subprocess
import threading
import queue
from pathlib import Path
from typing import Any, Callable

# デバッグログの表示/非表示を制御
TERMINAL_DEBUG = False  # Claude CLI問題の詳細調査

# PTY support for Windows
try:
    import winpty
    HAS_WINPTY = True
    if TERMINAL_DEBUG:
        print("winpty imported successfully")
except ImportError:
    HAS_WINPTY = False
    if TERMINAL_DEBUG:
        print("winpty not available, using QProcess fallback")

from PySide6.QtCore import (
    Qt, QObject, Signal, Slot, QTimer, QUrl, QThread, QProcess, QRectF, QProcessEnvironment
)
from PySide6.QtGui import QColor, QBrush, QPen, QKeyEvent
from PySide6.QtWidgets import (
    QGraphicsProxyWidget, QGraphicsRectItem, QGraphicsItem,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QSpinBox, QFormLayout, QGroupBox, QTextEdit
)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebChannel import QWebChannel
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False
    if TERMINAL_DEBUG:
        print("Warning: PySide6WebEngine not available. XTerm Terminal will not work.")

# プロジェクト内モジュール
try:
    from .DPyL_classes import CanvasItem
    from .DPyL_utils import warn, debug_print
except ImportError:
    # テスト環境用の代替
    from PySide6.QtWidgets import QGraphicsItemGroup as CanvasItem
    def warn(msg): 
        if TERMINAL_DEBUG:
            print(f"WARN: {msg}")
    def debug_print(msg): 
        if TERMINAL_DEBUG:
            print(f"DEBUG: {msg}")


class TerminalWebEnginePage(QWebEnginePage if HAS_WEBENGINE else QObject):
    """
    カスタムWebEnginePageでJavaScriptコンソールメッセージを処理
    """
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        """JavaScript コンソールメッセージを処理"""
        if TERMINAL_DEBUG:
            print(f"JS Console [{level}] Line {line_number}: {message}")
            if "error" in message.lower() or "failed" in message.lower():
                print(f"CRITICAL JS ERROR: {message}")
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class TerminalBackend(QObject):
    """
    xterm.js と通信するためのバックエンドクラス
    winpty と QProcess の両方をサポート
    """
    output_ready = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.process = None
        self.pty_process = None
        self.is_running = False
        self.shell_type = "cmd"
        self.working_directory = os.getcwd()
        self.use_pty = HAS_WINPTY  # PTY が利用可能な場合は優先使用
        self.widget_width = 1000  # ウィジェットの幅
        self.widget_height = 700  # ウィジェットの高さ
        # 初期のターミナルサイズを計算
        self.terminal_cols, self.terminal_rows = self.calculate_terminal_dimensions()
        
    def calculate_terminal_dimensions(self, widget_width=None, widget_height=None):
        """ウィジェットサイズからターミナルの行列数を計算"""
        if widget_width is None:
            widget_width = self.widget_width
        if widget_height is None:
            widget_height = self.widget_height
            
        # 実際のフォントサイズに基づいた正確な計算
        font_size = 14  # CSSで指定されたフォントサイズ
        line_height = 1.2  # CSSで指定された行間
        
        # JavaScriptでの実測値に基づく文字幅
        # JavaScript実測値: 7.70px（Consolas 14px）
        char_width = 7.8  # JavaScriptの実測値に近い値
        char_height = 16.8  # 行の高さ
        
        # パディングを考慮（CSSで10px padding）
        padding = 20  # 左右の合計
        usable_width = widget_width - padding
        usable_height = widget_height - padding
        
        # 行列数を計算（Claude CLI互換性を重視）
        cols = max(120, int(usable_width // char_width))  # Claude CLI用最小120文字
        rows = max(50, int(usable_height // char_height))  # Claude CLI用最小50行
        
        # print(f"Terminal dimensions: {cols}x{rows} (widget: {widget_width}x{widget_height}, usable: {usable_width}x{usable_height}, char: {char_width:.1f}x{char_height:.1f})")
        return (cols, rows)
        
    @Slot(int, int)
    def set_terminal_size(self, width, height):
        """ターミナルサイズを設定"""
        self.widget_width = width
        self.widget_height = height
        self.terminal_cols, self.terminal_rows = self.calculate_terminal_dimensions(width, height)
        
        # PTY プロセスをリサイズ
        if self.pty_process and self.is_running:
            try:
                self.pty_process.setwinsize(self.terminal_rows, self.terminal_cols)
                # print(f"Resized PTY to {self.terminal_cols}x{self.terminal_rows}")
                pass
            except Exception as e:
                # print(f"Failed to resize PTY: {e}")
                pass
        
        # JavaScriptにもサイズ変更を通知
        self.resize_terminal_js()
        
    @Slot(int)
    def update_terminal_columns(self, cols):
        """JavaScriptから計算された正しい列数を受信"""
        # print(f"Received correct column count from JavaScript: {cols}")
        pass
        self.terminal_cols = cols
        
        # PTYプロセスが実行中の場合、サイズを更新
        if HAS_WINPTY and self.pty_process and self.is_running:
            try:
                # print(f"Updating PTY columns to {cols}")
                pass
                self.pty_process.setwinsize(self.terminal_rows, cols)
            except Exception as e:
                # print(f"Failed to update PTY columns: {e}")
                pass
                
        # 環境変数も更新
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            # print(f"Process is running. Updated terminal columns: {cols}")
            pass
            
        # JavaScriptにもサイズを通知
        self.resize_terminal_js()
        
    def resize_terminal_js(self):
        """JavaScriptにターミナルサイズの変更を通知"""
        try:
            # 現在接続されているウィジェットを取得
            if hasattr(self, 'widget') and self.widget:
                self.widget.page().runJavaScript(f'''
                    if (typeof updateTerminalDimensions === 'function') {{
                        updateTerminalDimensions();
                        console.log("Terminal dimensions updated from Python: {self.terminal_cols}x{self.terminal_rows}");
                    }}
                ''')
        except Exception as e:
            if TERMINAL_DEBUG:
                print(f"Failed to notify JavaScript about size change: {e}")
        
    @Slot(str, str, result=bool)
    def start_shell(self, shell_type: str = "cmd", working_dir: str = None):
        """シェルプロセスを開始"""
        if TERMINAL_DEBUG:
            print(f"TerminalBackend.start_shell called: {shell_type}, {working_dir}")
        
        if self.is_running:
            if TERMINAL_DEBUG:
                print("Stopping existing shell")
            self.stop_shell()
            
        if working_dir:
            self.working_directory = working_dir
            if TERMINAL_DEBUG:
                print(f"Working directory set to: {self.working_directory}")
            
        self.shell_type = shell_type
        
        # PTY サポートがある場合は優先使用
        if self.use_pty and HAS_WINPTY:
            return self._start_pty_shell(shell_type)
        else:
            return self._start_qprocess_shell(shell_type)
    
    def _start_pty_shell(self, shell_type: str):
        """winpty を使用してシェルを開始"""
        try:
            if TERMINAL_DEBUG:
                print("Creating winpty process")
            
            # シェルコマンドを設定
            if shell_type == "powershell":
                command = ["powershell.exe", "-NoExit"]
            elif shell_type == "pwsh":
                command = ["pwsh.exe", "-NoExit"]
            elif shell_type == "pwsh (no PSReadLine)":
                command = ["pwsh.exe", "-NoExit", "-Command", "Remove-Module PSReadLine -ErrorAction SilentlyContinue"]
            elif shell_type == "wsl":
                command = ["wsl.exe"]
            else:  # cmd
                command = ["cmd.exe"]
            
            # print(f"Starting PTY shell: {' '.join(command)}")
            pass
            
            # 動的サイズを計算
            self.terminal_cols, self.terminal_rows = self.calculate_terminal_dimensions()
            
            # 環境変数を設定
            env = os.environ.copy()
            env['COLUMNS'] = str(self.terminal_cols)
            env['LINES'] = str(self.terminal_rows) 
            env['TERM'] = 'xterm-256color'
            env['PYTHONUNBUFFERED'] = '1'  # Python出力のバッファリングを無効化
            
            # winpty プロセスを開始
            self.pty_process = winpty.PtyProcess.spawn(
                command,
                cwd=self.working_directory,
                dimensions=(self.terminal_cols, self.terminal_rows),
                env=env
            )
            
            # Windowsターミナルモードを設定
            # print(f"PTY started with dimensions: {self.terminal_cols}x{self.terminal_rows}")
            pass
            if TERMINAL_DEBUG:
                print(f"Working directory: {self.working_directory}")
                print(f"Environment COLUMNS: {env.get('COLUMNS')}")
                print(f"Environment LINES: {env.get('LINES')}")
            
            # print("PTY process started successfully")
            pass
            self.is_running = True
            
            # 出力読み取り用スレッドを開始
            self._start_pty_reader()
            
            # シェルタイプに応じた表示名を設定
            shell_display_names = {
                "cmd": "Command Prompt",
                "powershell": "Windows PowerShell",
                "pwsh": "PowerShell Core",
                "pwsh (no PSReadLine)": "PowerShell Core (no PSReadLine)",
                "wsl": "WSL (Windows Subsystem for Linux)"
            }
            shell_display_name = shell_display_names.get(shell_type, shell_type)
            
            # シェル情報の表示を保存しておく（後で使うため）
            self._shell_info = (shell_display_name, self.working_directory)
            return True
            
        except Exception as e:
            # print(f"PTY start failed: {e}, falling back to QProcess")
            pass
            self.use_pty = False
            return self._start_qprocess_shell(shell_type)
    
    def _start_qprocess_shell(self, shell_type: str):
        """QProcess を使用してシェルを開始（フォールバック）"""
        try:
            if TERMINAL_DEBUG:
                print("Creating QProcess")
            # QProcessを設定
            self.process = QProcess(self)
            self.process.setWorkingDirectory(self.working_directory)
            
            # プロセスチャンネルモードを設定（疑似端末モード）
            self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            
            if TERMINAL_DEBUG:
                print("Connecting signals")
            # シグナル接続
            self.process.readyReadStandardOutput.connect(self._read_stdout)
            self.process.readyReadStandardError.connect(self._read_stderr)
            self.process.finished.connect(self._process_finished)
            self.process.errorOccurred.connect(self._process_error)
            
            # 信号接続確認
            if TERMINAL_DEBUG:
                print("Signal connections established successfully")
            
            # 環境変数設定
            env = self.process.processEnvironment()
            if env.isEmpty():
                env = QProcessEnvironment.systemEnvironment()
            env.insert("TERM", "xterm-256color")
            env.insert("PYTHONUNBUFFERED", "1")
            self.process.setProcessEnvironment(env)
            
            if TERMINAL_DEBUG:
                print(f"Starting shell: {shell_type}")
            
            # シェル起動
            if shell_type == "powershell":
                if TERMINAL_DEBUG:
                    print("Starting powershell.exe")
                self.process.start("powershell.exe", ["-NoExit"])
            elif shell_type == "pwsh":
                if TERMINAL_DEBUG:
                    print("Starting pwsh.exe") 
                self.process.start("pwsh.exe", ["-NoExit"])
            elif shell_type == "pwsh (no PSReadLine)":
                if TERMINAL_DEBUG:
                    print("Starting pwsh.exe without PSReadLine") 
                self.process.start("pwsh.exe", ["-NoExit", "-Command", "Remove-Module PSReadLine -ErrorAction SilentlyContinue"])
            elif shell_type == "wsl":
                if TERMINAL_DEBUG:
                    print("Starting wsl.exe")
                self.process.start("wsl.exe", [])
            else:  # cmd
                if TERMINAL_DEBUG:
                    print("Starting cmd.exe")
                self.process.start("cmd.exe", [])
            
            if TERMINAL_DEBUG:
                print("Waiting for process to start...")
            
            if self.process.waitForStarted(3000):
                if TERMINAL_DEBUG:
                    print(f"Process started successfully. State: {self.process.state()}")
                self.is_running = True
                self.output_ready.emit(f"Started {shell_type} in: {self.working_directory}\\r\\n")
                return True
            else:
                error_msg = self.process.errorString()
                if TERMINAL_DEBUG:
                    print(f"Process failed to start. Error: {error_msg}")
                self.output_ready.emit(f"\\r\\n\\x1b[31mFailed to start {shell_type}: {error_msg}\\x1b[0m\\r\\n")
                return False
                
        except Exception as e:
            if TERMINAL_DEBUG:
                print(f"Exception in start_shell: {e}")
            self.output_ready.emit(f"\\r\\n\\x1b[31mError starting shell: {e}\\x1b[0m\\r\\n")
            return False
    
    def _start_pty_reader(self):
        """PTY の出力を読み取るスレッドを開始"""
        if not self.pty_process:
            return
        
        def read_pty_output():
            try:
                while self.is_running and self.pty_process:
                    try:
                        # PTY から出力を読み取り
                        output = self.pty_process.read()
                        if output:
                            # 文字列の場合はそのまま、バイト列の場合はデコード
                            if isinstance(output, bytes):
                                try:
                                    decoded_output = output.decode('utf-8', errors='replace')
                                except UnicodeDecodeError:
                                    decoded_output = output.decode('cp932', errors='replace')
                            else:
                                decoded_output = output
                            
                            # デバッグ出力
                            if TERMINAL_DEBUG:
                                if len(decoded_output) > 100:
                                    print(f"PTY output: {repr(decoded_output[:100])}... ({len(decoded_output)} chars)")
                                else:
                                    print(f"PTY output: {repr(decoded_output)}")
                                # エスケープシーケンス解析
                                self._log_escape_sequences(decoded_output)
                            
                            # シグナルで GUI スレッドに送信
                            self.output_ready.emit(decoded_output)
                    except Exception as e:
                        # print(f"PTY read error: {e}")
                        pass
                        break
            except Exception as e:
                # print(f"PTY reader thread error: {e}")
                pass
                
        # バックグラウンドスレッドで実行
        self.pty_reader_thread = threading.Thread(target=read_pty_output, daemon=True)
        self.pty_reader_thread.start()
    
    @Slot()
    def stop_shell(self):
        """シェルプロセスを停止"""
        self.is_running = False
        
        # PTY プロセスを停止
        if self.pty_process:
            try:
                self.pty_process.terminate()
                self.pty_process = None
            except Exception as e:
                # print(f"Error stopping PTY process: {e}")
                pass
        
        # QProcess を停止
        if self.process:
            try:
                self.process.kill()
                self.process.waitForFinished(3000)
                self.process = None
            except Exception as e:
                if TERMINAL_DEBUG:
                    print(f"Error stopping QProcess: {e}")
        
        self.output_ready.emit("\\r\\n\\x1b[33mTerminal stopped.\\x1b[0m\\r\\n")
    
    @Slot(str, result=bool)
    def write_to_shell(self, data: str):
        """シェルに文字列を送信（JavaScript から呼び出される）"""
        if TERMINAL_DEBUG:
            print(f"write_to_shell called with data: {repr(data)}")
        
        if not self.is_running:
            if TERMINAL_DEBUG:
                print("Cannot write: shell is not running")
            return False
        
        try:
            # PTY が利用可能な場合は PTY に書き込み
            if self.pty_process:
                # バックスペースの場合は詳細ログ
                if '\b' in data or '\x08' in data or '\x7f' in data:
                    if TERMINAL_DEBUG:
                        print(f"Writing backspace to PTY: {repr(data)}")
                self.pty_process.write(data)
                return True
            
            # フォールバック：QProcess に書き込み
            elif self.process:
                byte_data = data.encode('utf-8')
                if TERMINAL_DEBUG:
                    print(f"Writing to QProcess: {len(byte_data)} bytes")
                bytes_written = self.process.write(byte_data)
                if TERMINAL_DEBUG:
                    print(f"Actually wrote {bytes_written} bytes")
                # 強制的にフラッシュ
                self.process.waitForBytesWritten(1000)
                return True
            
            else:
                if TERMINAL_DEBUG:
                    print("No process available for writing")
                return False
                
        except Exception as e:
            if TERMINAL_DEBUG:
                print(f"Write error: {e}")
            self.output_ready.emit(f"\\r\\n\\x1b[31mWrite error: {e}\\x1b[0m\\r\\n")
            return False
    
    def _read_stdout(self):
        """標準出力を読み取り"""
        if self.process:
            data = self.process.readAllStandardOutput()
            if data:
                try:
                    text = bytes(data).decode('utf-8', errors='replace')
                    if TERMINAL_DEBUG:
                        print(f"_read_stdout: received {len(text)} chars: {repr(text)}")
                        # エスケープシーケンスを詳細ログ出力
                        self._log_escape_sequences(text)
                    # JavaScript で処理しやすいようにエスケープ (二重エスケープを避ける)
                    self.output_ready.emit(text)
                except Exception as e:
                    if TERMINAL_DEBUG:
                        print(f"_read_stdout decode error: {e}")
                    self.output_ready.emit(f"\\r\\n\\x1b[31mDecode error: {e}\\x1b[0m\\r\\n")
            else:
                if TERMINAL_DEBUG:
                    print("_read_stdout: no data available")
    
    def _read_stderr(self):
        """標準エラーを読み取り"""
        if self.process:
            data = self.process.readAllStandardError()
            if data:
                try:
                    text = bytes(data).decode('utf-8', errors='replace')
                    self.output_ready.emit(f"\\x1b[31m{text}\\x1b[0m")
                except Exception as e:
                    self.output_ready.emit(f"\\r\\n\\x1b[31mStderr decode error: {e}\\x1b[0m\\r\\n")
    
    def _process_finished(self, exit_code, exit_status):
        """プロセス終了時の処理"""
        self.is_running = False
        self.output_ready.emit(f"\\r\\n\\x1b[33mProcess finished. Exit code: {exit_code}\\x1b[0m\\r\\n")
    
    def _process_error(self, error):
        """プロセスエラー時の処理"""
        self.is_running = False
        self.output_ready.emit(f"\\r\\n\\x1b[31mProcess error: {error}\\x1b[0m\\r\\n")
    
    def _log_escape_sequences(self, text):
        """エスケープシーケンスを解析してログ出力"""
        import re
        
        # 主要なエスケープシーケンスパターン
        patterns = {
            r'\x1b\[([0-9]+);([0-9]+)H': 'Cursor Position (row {}, col {})',
            r'\x1b\[([0-9]+)A': 'Cursor Up {}',
            r'\x1b\[([0-9]+)B': 'Cursor Down {}', 
            r'\x1b\[([0-9]+)C': 'Cursor Right {}',
            r'\x1b\[([0-9]+)D': 'Cursor Left {}',
            r'\x1b\[H': 'Cursor Home',
            r'\x1b\[2J': 'Clear Screen',
            r'\x1b\[K': 'Clear Line (from cursor)',
            r'\x1b\[0K': 'Clear Line (from cursor to end)',
            r'\x1b\[1K': 'Clear Line (from start to cursor)',
            r'\x1b\[2K': 'Clear Line (entire line)',
            r'\x1b\[([0-9]+)J': 'Clear Display {}',
            r'\x1b\[\?25l': 'Hide Cursor',
            r'\x1b\[\?25h': 'Show Cursor',
        }
        
        sequences_found = []
        for pattern, description in patterns.items():
            matches = re.finditer(pattern, text)
            for match in matches:
                try:
                    if '{}' in description:
                        if len(match.groups()) == 2:
                            desc = description.format(match.group(1), match.group(2))
                        else:
                            desc = description.format(match.group(1))
                    else:
                        desc = description
                    sequences_found.append(f"  {match.group(0)} -> {desc}")
                except:
                    sequences_found.append(f"  {match.group(0)} -> {description}")
        
        if sequences_found:
            print("ESCAPE SEQUENCES DETECTED:")
            for seq in sequences_found:
                print(seq)


class XtermTerminalWidget(QWebEngineView if HAS_WEBENGINE else QObject):
    """
    xterm.js ベースのターミナルウィジェット
    """
    
    def __init__(self, parent=None):
        if not HAS_WEBENGINE:
            raise ImportError("PySide6WebEngine is required for XTerm Terminal")
        super().__init__(parent)
        
        # カスタムページを設定
        self.custom_page = TerminalWebEnginePage(self)
        self.setPage(self.custom_page)
        
        self.backend = TerminalBackend()
        self.backend.widget = self  # widget参照を設定
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.backend)
        self.page().setWebChannel(self.channel)
        
        # ページロード状態を追跡
        self.page_loaded = False
        self.pending_resize = False
        
        # ページ読み込み完了時のシグナル接続
        self.page().loadFinished.connect(self._on_load_finished)
        
        # ローカルHTMLファイルを読み込み
        self._load_local_html()
        
        self.setMinimumSize(400, 300)
    
    def _load_local_html(self):
        """ローカルHTMLファイルを読み込み"""
        try:
            # 現在のスクリプトディレクトリを取得（module/移動に対応）
            script_dir = Path(__file__).parent
            # 親ディレクトリのlibフォルダを参照
            html_path = script_dir.parent / "lib" / "xterm_full.html"
            
            if html_path.exists():
                with open(html_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                if TERMINAL_DEBUG:
                    print(f"Loading local HTML from: {html_path}")
                # ベースURLを設定して相対パスを解決
                base_url = QUrl.fromLocalFile(str(html_path.parent) + '/')
                self.setHtml(html_content, base_url)
            else:
                # フォールバック：シンプルなターミナル
                if TERMINAL_DEBUG:
                    print(f"HTML file not found at {html_path}, using fallback")
                self._create_fallback_html()
                
        except Exception as e:
            if TERMINAL_DEBUG:
                print(f"Error loading local HTML: {e}")
            self._create_fallback_html()
    
    def _create_fallback_html(self):
        """フォールバック用のシンプルなHTML"""
        html_content = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Simple Terminal</title>
    <style>
        body { margin: 0; padding: 10px; background: #000; color: #fff; font-family: monospace; }
        #terminal { white-space: pre-wrap; }
    </style>
</head>
<body>
    <div id="terminal">Terminal loading...</div>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        new QWebChannel(qt.webChannelTransport, function(channel) {
            const backend = channel.objects.backend;
            backend.output_ready.connect(function(data) {
                document.getElementById('terminal').innerHTML += data.replace(/\\r\\n/g, '<br>');
            });
            backend.start_shell("cmd", "");
        });
    </script>
</body>
</html>'''
        # ベースURLを設定（フォールバックでも相対パスを解決できるように）
        base_url = QUrl.fromLocalFile(str(Path(__file__).parent) + '/')
        self.setHtml(html_content, base_url)
    
    def _on_load_finished(self, success):
        """ページの読み込み完了時の処理"""
        if TERMINAL_DEBUG:
            print(f"Page load finished: {success}")
        if success:
            if TERMINAL_DEBUG:
                print("WebEngine page loaded successfully")
            self.page_loaded = True
            # ペンディングのリサイズがあれば実行
            if self.pending_resize:
                self.resize_terminal()
                self.pending_resize = False
        else:
            if TERMINAL_DEBUG:
                print("WebEngine page load failed")
    
    
    def start_shell(self, shell_type: str = "cmd", working_dir: str = None):
        """シェルを開始"""
        if working_dir is None:
            working_dir = os.getcwd()
        
        # JavaScript 関数を呼び出し（関数の存在確認付き）
        escaped_workdir = working_dir.replace(chr(92), chr(92)+chr(92))
        script = f'''
        if (typeof changeShell === 'function') {{
            changeShell("{shell_type}", "{escaped_workdir}");
        }} else if (typeof backend !== 'undefined') {{
            console.log('changeShell not available, calling backend directly');
            backend.start_shell("{shell_type}", "{escaped_workdir}");
        }} else {{
            console.log('Neither changeShell nor backend available yet');
        }}
        '''
        self.page().runJavaScript(script)
    
    def resize_terminal(self):
        """ターミナルサイズを調整"""
        # ページがロードされていない場合は、ペンディングフラグを設定
        if not self.page_loaded:
            self.pending_resize = True
            return
            
        # JavaScript関数の存在確認とサイズ調整
        script = '''
        if (typeof resizeTerminal === 'function') {
            resizeTerminal();
        } else {
            console.log('resizeTerminal function not yet available');
        }
        '''
        self.page().runJavaScript(script)
    
    def resizeEvent(self, event):
        """リサイズイベント処理"""
        super().resizeEvent(event)
        # 新しいサイズを取得
        new_size = event.size()
        if TERMINAL_DEBUG:
            print(f"XtermTerminalWidget resized to {new_size.width()}x{new_size.height()}")
        
        # バックエンドにサイズを通知（遅延実行で重複を避ける）
        QTimer.singleShot(100, lambda: self.backend.set_terminal_size(new_size.width(), new_size.height()))
        
        # 少し遅延させてサイズ調整
        QTimer.singleShot(100, self.resize_terminal)


class XtermTerminalItem(CanvasItem):
    """
    xterm.js ベースのターミナルアイテム
    """
    TYPE_NAME = "xterm_terminal"

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
        
        # ターミナル固有のデフォルト値（Claude CLI対応）
        d.setdefault("width", 1200)  # Claude CLI用により大きなサイズ
        d.setdefault("height", 900)  # 50行をカバーするサイズ
        d.setdefault("workdir", os.getcwd())
        d.setdefault("terminal_type", "cmd")
        d.setdefault("startup_command", "")
        d.setdefault("auto_start", False)
        d.setdefault("caption", "XTerm Terminal")

        # リサイズコールバック
        if cb_resize is None:
            cb_resize = self._default_resize_callback
        
        super().__init__(d, cb_resize, text_color)
        
        # 背景矩形アイテムを作成
        self._rect_item = QGraphicsRectItem(parent=self)
        self._rect_item.setZValue(-1)
        
        # ターミナルウィジェット
        self._terminal_widget = XtermTerminalWidget()
        
        # ウィジェットをGraphicsProxyWidgetでラップ
        self._proxy_widget = QGraphicsProxyWidget(parent=self)
        self._proxy_widget.setWidget(self._terminal_widget)
        
        # フォーカス設定
        self._proxy_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._terminal_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # フォーカス受け取り設定
        self._proxy_widget.setFocus()
        self._terminal_widget.setFocus()
        
        # プロキシウィジェットの設定
        self._proxy_widget.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton | 
            Qt.MouseButton.RightButton | 
            Qt.MouseButton.MiddleButton
        )
        self._proxy_widget.setAcceptHoverEvents(True)
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsSelectable, True)
        self._proxy_widget.setFlag(QGraphicsProxyWidget.GraphicsItemFlag.ItemIsFocusable, True)
        
        # アイテムもフォーカスを受け取れるように設定
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        
        # ターミナルウィジェットを最前面に
        self._proxy_widget.setZValue(1000)
        
        # 背景色設定
        bg_color = QColor("#000000")
        self._rect_item.setBrush(QBrush(bg_color))
        self._rect_item.setPen(QPen(QColor("#333333"), 2))

        # 初期サイズ設定
        self._update_size()
        
        # リサイズイベントの接続
        self.cb_resize = cb_resize or self._default_resize_callback
        
        # 初期リサイズを先に実行（プロジェクトロード時の幅問題対策）
        QTimer.singleShot(1500, lambda: self._update_size())
        
        # リサイズ後にシェルを起動
        # ページロード完了とリサイズ完了を待つため、遅延を増やす
        QTimer.singleShot(2500, self._start_initial_shell)
        
        # 自動実行が有効な場合
        if self.d.get("auto_start", False) and self.d.get("startup_command"):
            QTimer.singleShot(3000, self._auto_execute_command)

    def _default_resize_callback(self, w: int, h: int):
        """デフォルトのリサイズコールバック（プログラムからのリサイズ用）"""
        if TERMINAL_DEBUG:
            print(f"XtermTerminalItem _default_resize_callback: {w}x{h}")
        # これはCanvasItemのitemChange由来のコールバック
        # resize_contentと同じ処理を行う
        self.d["width"] = w
        self.d["height"] = h
        self._update_size()

    def resize_content(self, w: int, h: int):
        """グリップリサイズに対応する標準メソッド"""
        if TERMINAL_DEBUG:
            print(f"XtermTerminalItem.resize_content called: {w}x{h}")
        # dの更新はCanvasItemのグリップ処理で行われる
        self.d["width"], self.d["height"] = w, h
        self._update_size()
        
    def on_resized(self, w: int, h: int):
        """リサイズ後の処理"""
        if TERMINAL_DEBUG:
            print(f"XtermTerminalItem.on_resized called: {w}x{h}")
        # グリップ位置を更新
        self._update_grip_pos()
        # 必要に応じて追加処理
        pass
        
    def snap_resize_size(self, w: int, h: int):
        """リサイズ時のサイズ調整"""
        # Claude CLI用最小サイズを強制
        min_width = 1000   # 120文字をカバー
        min_height = 850   # 50行をカバー
        
        w = max(min_width, w)
        h = max(min_height, h)
        
        if TERMINAL_DEBUG:
            print(f"XtermTerminalItem.snap_resize_size: {w}x{h}")
        return w, h
        
    def _update_size(self):
        """サイズを更新"""
        width = self.d.get("width", 800)
        height = self.d.get("height", 600)
        
        # 背景矩形のサイズ
        self._rect_item.setRect(0, 0, width, height)
        
        # プロキシウィジェットのサイズ
        self._proxy_widget.resize(width - 4, height - 4)
        self._proxy_widget.setPos(2, 2)
        
        # バックエンドにサイズを通知
        self._terminal_widget.backend.set_terminal_size(width - 4, height - 4)
        
        # ターミナルウィジェットのリサイズを即座に実行
        self._terminal_widget.resize_terminal()
        
        # キャンバスアイテムのサイズ
        self.setPos(self.pos())

    def _start_initial_shell(self):
        """初期シェルを起動"""
        print("=" * 60)
        print("XTERM TERMINAL STARTING WITH CLAUDE CLI DEBUG")
        print("All escape sequences will be logged to this console")
        print("=" * 60)
        if TERMINAL_DEBUG:
            print("_start_initial_shell called")
            print(f"Current terminal settings: {self.d}")
            print(f"Terminal type from settings: {self.d.get('terminal_type', 'NOT SET')}")
        
        # 既にシェルが起動されている場合はスキップ
        if self._terminal_widget.backend.is_running:
            if TERMINAL_DEBUG:
                print("Shell is already running, skipping initial start")
            return
            
        terminal_type = self.d.get("terminal_type", "cmd")
        working_dir = self.d.get("workdir", os.getcwd())
        
        if TERMINAL_DEBUG:
            print(f"Starting initial shell: {terminal_type} in {working_dir}")
        self._terminal_widget.start_shell(terminal_type, working_dir)
        
        # シェル起動後、少し待ってからシェル情報を表示
        def show_shell_info():
            if hasattr(self._terminal_widget.backend, '_shell_info'):
                shell_name, work_dir = self._terminal_widget.backend._shell_info
                info = f"\r\n[{shell_name}] {work_dir}\r\n\r\n"
                self._terminal_widget.backend.output_ready.emit(info)
        
        QTimer.singleShot(1500, show_shell_info)
    
    def _auto_execute_command(self):
        """自動実行コマンドを実行"""
        if TERMINAL_DEBUG:
            print("_auto_execute_command called")
        startup_cmd = self.d.get("startup_command", "")
        if startup_cmd and self._terminal_widget.backend.is_running:
            if TERMINAL_DEBUG:
                print(f"Executing startup command: {startup_cmd}")
            # 複数のコマンドを改行で区切って実行
            commands = startup_cmd.split('\n')
            for cmd in commands:
                cmd = cmd.strip()
                if cmd:
                    self._execute_command(cmd)
        else:
            if TERMINAL_DEBUG:
                print(f"Cannot execute startup command: cmd='{startup_cmd}', running={self._terminal_widget.backend.is_running}")
    
    def _execute_command(self, command: str):
        """コマンドを実行"""
        if TERMINAL_DEBUG:
            print(f"Executing command: {command}")
        if self._terminal_widget.backend.is_running:
            # コマンドの最後に改行を追加
            if not command.endswith('\n'):
                command += '\r\n'
            self._terminal_widget.backend.write_to_shell(command)
    
    def on_edit(self):
        """編集ダイアログを表示"""
        dialog = XtermTerminalEditDialog(self.d)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.d.update(dialog.get_data())
            self._update_terminal_settings()
    
    def _update_terminal_settings(self):
        """ターミナル設定を更新"""
        # ターミナルタイプや作業ディレクトリが変更された場合は再起動
        terminal_type = self.d.get("terminal_type", "cmd")
        working_dir = self.d.get("workdir", os.getcwd())
        
        # 必要に応じてシェルを再起動
        if self._terminal_widget.backend.is_running:
            self._terminal_widget.backend.stop_shell()
            QTimer.singleShot(500, lambda: self._terminal_widget.start_shell(terminal_type, working_dir))

    def contextMenuEvent(self, ev):
        """右クリックメニュー"""
        from PySide6.QtWidgets import QMenu
        
        menu = QMenu()
        
        # カスタムアクション
        start_cmd_action = menu.addAction("Start CMD")
        start_cmd_action.triggered.connect(lambda: self._terminal_widget.start_shell("cmd", self.d.get("workdir", os.getcwd())))
        
        start_ps_action = menu.addAction("Start PowerShell")
        start_ps_action.triggered.connect(lambda: self._terminal_widget.start_shell("powershell", self.d.get("workdir", os.getcwd())))
        
        start_pwsh_action = menu.addAction("Start PowerShell Core")
        start_pwsh_action.triggered.connect(lambda: self._terminal_widget.start_shell("pwsh", self.d.get("workdir", os.getcwd())))
        
        start_wsl_action = menu.addAction("Start WSL")
        start_wsl_action.triggered.connect(lambda: self._terminal_widget.start_shell("wsl", self.d.get("workdir", os.getcwd())))
        
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
                # フォーカスを設定
                self._proxy_widget.setFocus()
                self._terminal_widget.setFocus()
                
                # WebEngineViewにフォーカスを確実に移す
                self._terminal_widget.activateWindow()
                event.accept()
                return
        
        super().mousePressEvent(event)
    
    def keyPressEvent(self, event: QKeyEvent):
        """キーイベントをターミナルウィジェットに転送"""
        try:
            # フォーカス状態を確認
            has_focus = (self._proxy_widget.hasFocus() or 
                        self._terminal_widget.hasFocus() or
                        self.hasFocus())
            
            if TERMINAL_DEBUG:
                print(f"Key event: {event.key()}, has_focus: {has_focus}")
            
            if has_focus:
                # WebEngineViewにフォーカスを移してキーイベントを送る
                self._terminal_widget.setFocus()
                self._terminal_widget.keyPressEvent(event)
                event.accept()
            else:
                # フォーカスがない場合は親に転送
                super().keyPressEvent(event)
        except Exception as e:
            # キーイベント処理でエラーが発生した場合は警告を出して続行
            if TERMINAL_DEBUG:
                print(f"Key event handling failed: {e}")
            super().keyPressEvent(event)

    def delete_self(self):
        """XTermターミナル削除時のクリーンアップ処理"""
        try:
            # バックエンドのシェルプロセスを停止
            if hasattr(self, '_terminal_widget') and self._terminal_widget:
                if hasattr(self._terminal_widget, 'backend') and self._terminal_widget.backend:
                    # シェルプロセスが実行中の場合は停止
                    if self._terminal_widget.backend.is_running:
                        self._terminal_widget.backend.stop_shell()
                    
                    # バックエンドの各種シグナル切断
                    try:
                        if hasattr(self._terminal_widget.backend, 'output_ready'):
                            self._terminal_widget.backend.output_ready.disconnect()
                    except Exception:
                        pass
                    
                    # winptyプロセスとQProcessの強制終了
                    if hasattr(self._terminal_widget.backend, 'pty_process') and self._terminal_widget.backend.pty_process:
                        try:
                            self._terminal_widget.backend.pty_process.terminate()
                        except Exception:
                            pass
                        self._terminal_widget.backend.pty_process = None
                    
                    if hasattr(self._terminal_widget.backend, 'process') and self._terminal_widget.backend.process:
                        try:
                            self._terminal_widget.backend.process.kill()
                            self._terminal_widget.backend.process.waitForFinished(3000)
                        except Exception:
                            pass
                        self._terminal_widget.backend.process = None
                    
                    self._terminal_widget.backend = None
                
                # WebEngineページの削除
                if hasattr(self._terminal_widget, 'page'):
                    try:
                        page = self._terminal_widget.page()
                        if page:
                            # WebChannelのクリーンアップ
                            if hasattr(page, 'setWebChannel'):
                                page.setWebChannel(None)
                            # ページを削除
                            page.deleteLater()
                    except Exception:
                        pass
                
                self._terminal_widget = None
            
            # プロキシウィジェットのクリーンアップ
            if hasattr(self, '_proxy_widget') and self._proxy_widget:
                if self._proxy_widget.scene():
                    self._proxy_widget.scene().removeItem(self._proxy_widget)
                self._proxy_widget = None
            
        except Exception as e:
            warn(f"Error during XtermTerminalItem cleanup: {e}")
        
        # 基底クラスの削除処理を呼び出し
        super().delete_self()


class XtermTerminalEditDialog(QDialog):
    """XTerm ターミナル設定編集ダイアログ"""
    
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XTerm Terminal Settings")
        self.setMinimumSize(450, 400)
        
        self.data = data.copy()
        
        layout = QVBoxLayout(self)
        
        # Terminal settings group
        terminal_group = QGroupBox("Terminal Settings")
        terminal_layout = QFormLayout()
        
        # Terminal Type
        self.terminal_type_combo = QComboBox()
        self.terminal_type_combo.addItems(["cmd", "powershell", "pwsh", "pwsh (no PSReadLine)", "wsl"])
        self.terminal_type_combo.setCurrentText(self.data.get("terminal_type", "cmd"))
        terminal_layout.addRow("Terminal Type:", self.terminal_type_combo)
        
        # Working Directory
        self.workdir_edit = QLineEdit(self.data.get("workdir", os.getcwd()))
        terminal_layout.addRow("Working Directory:", self.workdir_edit)
        
        # Startup Command
        self.startup_command_edit = QTextEdit()
        self.startup_command_edit.setMaximumHeight(60)
        self.startup_command_edit.setPlainText(self.data.get("startup_command", ""))
        terminal_layout.addRow("Startup Command:", self.startup_command_edit)
        
        # Auto Start
        self.auto_start_check = QCheckBox("Auto-start command on project load")
        self.auto_start_check.setChecked(self.data.get("auto_start", False))
        terminal_layout.addRow("", self.auto_start_check)
        
        terminal_group.setLayout(terminal_layout)
        layout.addWidget(terminal_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
    
    def get_data(self) -> dict:
        """編集されたデータを返す"""
        self.data["terminal_type"] = self.terminal_type_combo.currentText()
        self.data["workdir"] = self.workdir_edit.text()
        self.data["startup_command"] = self.startup_command_edit.toPlainText()
        self.data["auto_start"] = self.auto_start_check.isChecked()
        return self.data