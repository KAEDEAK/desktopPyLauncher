# -*- coding: utf-8 -*-
"""
DPyL_command_widget.py - Command/Terminal Widget for desktopPyLauncher
Implements a widget that can launch various terminals (cmd, PowerShell, WSL, git bash)
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QPixmap, QIcon, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QFileDialog, QSpinBox,
    QGroupBox, QTextEdit
)

from .DPyL_classes import LauncherItem
from .DPyL_utils import _icon_pixmap, ICON_SIZE


class CommandWidgetSettingsDialog(QDialog):
    """Command Widget settings dialog"""
    
    def __init__(self, item_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.item_data = item_data.copy()
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        self.setWindowTitle("Command Widget Settings")
        self.setMinimumSize(400, 500)
        
        layout = QVBoxLayout(self)
        
        # Basic settings group
        basic_group = QGroupBox("Basic Settings")
        basic_layout = QVBoxLayout(basic_group)
        
        # Caption
        caption_layout = QHBoxLayout()
        caption_layout.addWidget(QLabel("Caption:"))
        self.caption_edit = QLineEdit()
        caption_layout.addWidget(self.caption_edit)
        basic_layout.addLayout(caption_layout)
        
        # Working Directory
        workdir_layout = QHBoxLayout()
        workdir_layout.addWidget(QLabel("Working Directory:"))
        self.workdir_edit = QLineEdit()
        workdir_browse_btn = QPushButton("Browse...")
        workdir_browse_btn.clicked.connect(self.browse_workdir)
        workdir_layout.addWidget(self.workdir_edit)
        workdir_layout.addWidget(workdir_browse_btn)
        basic_layout.addLayout(workdir_layout)
        
        layout.addWidget(basic_group)
        
        # Terminal settings group
        terminal_group = QGroupBox("Terminal Settings")
        terminal_layout = QVBoxLayout(terminal_group)
        
        # Terminal Type
        terminal_type_layout = QHBoxLayout()
        terminal_type_layout.addWidget(QLabel("Terminal Type:"))
        self.terminal_combo = QComboBox()
        self.terminal_combo.addItems([
            "Command Prompt (cmd)",
            "PowerShell",
            "PowerShell Core (pwsh)",
            "WSL (Windows Subsystem for Linux)",
            "Git Bash",
            "Custom Command"
        ])
        terminal_type_layout.addWidget(self.terminal_combo)
        terminal_layout.addLayout(terminal_type_layout)
        
        # Custom command (for Custom Command option)
        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("Custom Command:"))
        self.custom_command_edit = QLineEdit()
        self.custom_command_edit.setPlaceholderText("e.g., C:\\Program Files\\Git\\bin\\bash.exe")
        custom_layout.addWidget(self.custom_command_edit)
        terminal_layout.addLayout(custom_layout)
        
        # Startup Command
        startup_layout = QVBoxLayout()
        startup_layout.addWidget(QLabel("Startup Command:"))
        self.startup_command_edit = QTextEdit()
        self.startup_command_edit.setMaximumHeight(60)
        self.startup_command_edit.setPlaceholderText("Commands to run on startup (optional)")
        startup_layout.addWidget(self.startup_command_edit)
        terminal_layout.addLayout(startup_layout)
        
        # Admin privileges
        self.admin_checkbox = QCheckBox("Run as Administrator")
        terminal_layout.addWidget(self.admin_checkbox)
        
        layout.addWidget(terminal_group)
        
        # Icon settings group
        icon_group = QGroupBox("Icon Settings")
        icon_layout = QVBoxLayout(icon_group)
        
        icon_path_layout = QHBoxLayout()
        icon_path_layout.addWidget(QLabel("Icon Path:"))
        self.icon_path_edit = QLineEdit()
        icon_browse_btn = QPushButton("Browse...")
        icon_browse_btn.clicked.connect(self.browse_icon)
        icon_path_layout.addWidget(self.icon_path_edit)
        icon_path_layout.addWidget(icon_browse_btn)
        icon_layout.addLayout(icon_path_layout)
        
        layout.addWidget(icon_group)
        
        # Size settings
        size_group = QGroupBox("Size Settings")
        size_layout = QHBoxLayout(size_group)
        
        size_layout.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(16, 512)
        self.width_spin.setValue(64)
        size_layout.addWidget(self.width_spin)
        
        size_layout.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(16, 512)
        self.height_spin.setValue(64)
        size_layout.addWidget(self.height_spin)
        
        layout.addWidget(size_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
    def load_settings(self):
        """Load settings from item_data"""
        self.caption_edit.setText(self.item_data.get("caption", "Terminal"))
        self.workdir_edit.setText(self.item_data.get("workdir", os.getcwd()))
        
        terminal_type = self.item_data.get("terminal_type", "cmd")
        terminal_map = {
            "cmd": 0,
            "powershell": 1,
            "pwsh": 2,
            "wsl": 3,
            "git_bash": 4,
            "custom": 5
        }
        self.terminal_combo.setCurrentIndex(terminal_map.get(terminal_type, 0))
        
        self.custom_command_edit.setText(self.item_data.get("custom_command", ""))
        self.startup_command_edit.setPlainText(self.item_data.get("startup_command", ""))
        self.admin_checkbox.setChecked(self.item_data.get("run_as_admin", False))
        self.icon_path_edit.setText(self.item_data.get("icon", ""))
        self.width_spin.setValue(self.item_data.get("width", 64))
        self.height_spin.setValue(self.item_data.get("height", 64))
        
    def save_settings(self):
        """Save settings to item_data"""
        self.item_data["caption"] = self.caption_edit.text()
        self.item_data["workdir"] = self.workdir_edit.text()
        
        terminal_types = ["cmd", "powershell", "pwsh", "wsl", "git_bash", "custom"]
        self.item_data["terminal_type"] = terminal_types[self.terminal_combo.currentIndex()]
        
        self.item_data["custom_command"] = self.custom_command_edit.text()
        self.item_data["startup_command"] = self.startup_command_edit.toPlainText()
        self.item_data["run_as_admin"] = self.admin_checkbox.isChecked()
        self.item_data["icon"] = self.icon_path_edit.text()
        self.item_data["width"] = self.width_spin.value()
        self.item_data["height"] = self.height_spin.value()
        
    def browse_workdir(self):
        """Browse for working directory"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Working Directory", self.workdir_edit.text()
        )
        if dir_path:
            self.workdir_edit.setText(dir_path)
            
    def browse_icon(self):
        """Browse for icon file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Icon File", "",
            "Icon Files (*.ico *.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if file_path:
            self.icon_path_edit.setText(file_path)
            
    def accept(self):
        """Override accept to save settings"""
        self.save_settings()
        super().accept()


class CommandWidget(LauncherItem):
    """Command/Terminal widget that can launch various shells"""
    
    TYPE_NAME = "command_widget"
    
    @classmethod
    def supports_path(cls, path: str) -> bool:
        """This widget doesn't support drag & drop files"""
        return False
    
    def __init__(self, d: dict = None, cb_resize=None, text_color=None):
        # Set default values if not provided
        if d is None:
            d = {}
            
        # Set default command widget values
        d.setdefault("type", "command_widget")
        d.setdefault("caption", "Terminal")
        d.setdefault("workdir", os.getcwd())
        d.setdefault("terminal_type", "cmd")
        d.setdefault("custom_command", "")
        d.setdefault("startup_command", "")
        d.setdefault("run_as_admin", False)
        d.setdefault("width", 64)
        d.setdefault("height", 64)
        
        # Set default icon if not specified
        if not d.get("icon"):
            d["icon"] = self._get_default_icon(d.get("terminal_type", "cmd"))
            
        super().__init__(d, cb_resize, text_color)
        
    def _get_default_icon(self, terminal_type: str) -> str:
        """Get default icon path for terminal type"""
        # Try to find system icons for different terminal types
        system_icons = {
            "cmd": "C:\\Windows\\System32\\cmd.exe",
            "powershell": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "pwsh": "C:\\Program Files\\PowerShell\\7\\pwsh.exe",
            "wsl": "C:\\Windows\\System32\\wsl.exe",
            "git_bash": "C:\\Program Files\\Git\\git-bash.exe"
        }
        
        icon_path = system_icons.get(terminal_type, "")
        if icon_path and Path(icon_path).exists():
            return icon_path
            
        # Fallback to system shell icon
        return "C:\\Windows\\System32\\cmd.exe"
        
    def on_activate(self):
        """Launch the configured terminal when double-clicked"""
        if not self.run_mode:
            return
            
        try:
            self._launch_terminal()
        except Exception as e:
            print(f"Error launching terminal: {e}")
            
    def _launch_terminal(self):
        """Launch the terminal based on configuration"""
        terminal_type = self.d.get("terminal_type", "cmd")
        workdir = self.d.get("workdir", os.getcwd())
        startup_cmd = self.d.get("startup_command", "")
        run_as_admin = self.d.get("run_as_admin", False)
        
        # Ensure working directory exists
        if not Path(workdir).exists():
            workdir = os.getcwd()
            
        if terminal_type == "cmd":
            self._launch_cmd(workdir, startup_cmd, run_as_admin)
        elif terminal_type == "powershell":
            self._launch_powershell(workdir, startup_cmd, run_as_admin)
        elif terminal_type == "pwsh":
            self._launch_pwsh(workdir, startup_cmd, run_as_admin)
        elif terminal_type == "wsl":
            self._launch_wsl(workdir, startup_cmd, run_as_admin)
        elif terminal_type == "git_bash":
            self._launch_git_bash(workdir, startup_cmd, run_as_admin)
        elif terminal_type == "custom":
            self._launch_custom(workdir, startup_cmd, run_as_admin)
            
    def _launch_cmd(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch Command Prompt"""
        cmd = ["cmd.exe", "/k"]
        if startup_cmd:
            cmd.append(f"cd /d \"{workdir}\" && {startup_cmd}")
        else:
            cmd.append(f"cd /d \"{workdir}\"")
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _launch_powershell(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch Windows PowerShell"""
        cmd = ["powershell.exe", "-NoExit", "-Command"]
        if startup_cmd:
            cmd.append(f"Set-Location '{workdir}'; {startup_cmd}")
        else:
            cmd.append(f"Set-Location '{workdir}'")
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _launch_pwsh(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch PowerShell Core"""
        pwsh_path = "pwsh.exe"
        # Try to find PowerShell Core
        possible_paths = [
            "C:\\Program Files\\PowerShell\\7\\pwsh.exe",
            "C:\\Program Files\\PowerShell\\6\\pwsh.exe",
            "pwsh.exe"
        ]
        
        for path in possible_paths:
            if Path(path).exists() or path == "pwsh.exe":
                pwsh_path = path
                break
                
        cmd = [pwsh_path, "-NoExit", "-Command"]
        if startup_cmd:
            cmd.append(f"Set-Location '{workdir}'; {startup_cmd}")
        else:
            cmd.append(f"Set-Location '{workdir}'")
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _launch_wsl(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch WSL"""
        cmd = ["wsl.exe"]
        if startup_cmd:
            cmd.extend(["-e", "bash", "-c", f"cd '{workdir}'; {startup_cmd}; exec bash"])
        else:
            cmd.extend(["-e", "bash", "-c", f"cd '{workdir}'; exec bash"])
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _launch_git_bash(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch Git Bash"""
        # Try Git Bash executable first, then fall back to bash.exe
        git_bash_paths = [
            "C:\\Program Files\\Git\\git-bash.exe",
            "C:\\Program Files (x86)\\Git\\git-bash.exe",
            "C:\\Program Files\\Git\\bin\\bash.exe",
            "C:\\Program Files (x86)\\Git\\bin\\bash.exe",
            "C:\\Git\\git-bash.exe",
            "C:\\Git\\bin\\bash.exe"
        ]
        
        bash_path = None
        for path in git_bash_paths:
            if Path(path).exists():
                bash_path = path
                break
                
        if not bash_path:
            raise FileNotFoundError("Git Bash not found")
            
        # Use git-bash.exe if available (opens in new window), otherwise bash.exe
        if "git-bash.exe" in bash_path:
            # git-bash.exe opens in its own window
            cmd = [bash_path]
            if startup_cmd:
                cmd.extend(["-c", f"cd '{workdir}' && {startup_cmd}"])
        else:
            # bash.exe with --login to start in new window
            cmd = [bash_path, "--login", "-i"]
            if startup_cmd:
                cmd.extend(["-c", f"cd '{workdir}' && {startup_cmd} && exec bash --login -i"])
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _launch_custom(self, workdir: str, startup_cmd: str, run_as_admin: bool):
        """Launch custom command"""
        custom_cmd = self.d.get("custom_command", "")
        if not custom_cmd:
            raise ValueError("Custom command not specified")
            
        cmd = [custom_cmd]
        if startup_cmd:
            cmd.append(startup_cmd)
            
        self._execute_command(cmd, workdir, run_as_admin)
        
    def _execute_command(self, cmd: list, workdir: str, run_as_admin: bool):
        """Execute the command with proper handling"""
        if run_as_admin:
            # Use Windows 'runas' for admin privileges - this will open a new window
            admin_cmd = ["runas", "/user:Administrator"] + cmd
            subprocess.Popen(admin_cmd, cwd=workdir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            # CREATE_NEW_CONSOLE flag creates a new console window
            subprocess.Popen(cmd, cwd=workdir, creationflags=subprocess.CREATE_NEW_CONSOLE)
            
    def on_edit(self):
        """Open settings dialog in edit mode"""
        dialog = CommandWidgetSettingsDialog(self.d, parent=None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update the widget with new settings
            self.d.update(dialog.item_data)
            
            # Update icon if changed
            if dialog.item_data.get("icon") != self.d.get("icon"):
                self.d["icon"] = dialog.item_data["icon"]
                
            # Refresh display
            self._refresh_icon()
            self.init_caption()
            self._update_grip_pos()
            
            # Update size if changed
            new_width = dialog.item_data.get("width", 64)
            new_height = dialog.item_data.get("height", 64)
            if new_width != self.d.get("width") or new_height != self.d.get("height"):
                self.d["width"] = new_width
                self.d["height"] = new_height
                self._refresh_icon()