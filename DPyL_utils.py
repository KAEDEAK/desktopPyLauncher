# -*- coding: utf-8 -*-
"""
共通ユーティリティ（GUI非依存、PySide6前提）
"""

from __future__ import annotations

import os,sys,io
import base64
import ctypes
from ctypes import wintypes
from PIL import Image
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from pathlib import Path
from PySide6.QtGui     import QPixmap, QPainter, QImage, QImageReader, QIcon, QPalette, QColor
from PySide6.QtGui     import QBrush, QPen
from PySide6.QtCore    import Qt, QSize, QFileInfo, QIODevice, QBuffer
from PySide6.QtWidgets import QApplication, QFileIconProvider
  
from DPyL_debug import my_has_attr


# ------------------------------ 定数 ------------------------------
DEBUG_MODE = any(arg == "-debug" for arg in sys.argv)
if DEBUG_MODE:
    print("DEBUG_MODE")

ICON_SIZE          = 48
IMAGE_EXTS         = (".png", ".jpg", ".jpeg", ".bmp", ".gif")
#VIDEO_EXTS         = (".wav",".mp3",".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv")
VIDEO_EXTS         = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv")
EXECUTE_EXTS       = (".lnk", ".bat", ".txt", ".html", ".htm", ".url")
PYTHON_SCRIPT_EXT  = ".py"
ICON_PROVIDER = QFileIconProvider()

# ------------------------------ 基本ユーティリティ ------------------------------
def warn(msg: str) -> None:
    if not DEBUG_MODE:
        return
    if msg.startswith(("[LOAD]", "[SCROLL]")):
        return
    print(f"[WARN] {msg}", file=sys.stderr)

def debug_print(msg: str) -> None:
    """-debug指定時のみstderrへ警告出力"""
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}", file=sys.stderr)

b64e = lambda s: base64.b64encode(s.encode("utf-8")).decode("ascii")

def b64d(s: str) -> str:
    """Base64文字列→UTF-8。失敗時は入力を返す"""
    try:
        return base64.b64decode(s.encode("ascii")).decode("utf-8")
    except Exception as e:
        warn(f"b64decode failed: {e}")
        return s

# -- 時間変換 -------------------------------------------
def ms_to_hms_ms(ms: int) -> str:
    """ミリ秒を 'hh:mm:ss.zzz' 形式に変換"""
    s = ms // 1000
    z = ms % 1000
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{z:03d}"

def hms_to_ms(s: str) -> int:
    """'hh:mm:ss.zzz'または'hh:mm:ss:zzz'形式文字列→ミリ秒"""
    try:
        s = s.strip()
        if "." in s:
            time_part, ms_part = s.split(".", 1)
        elif ":" in s and s.count(":") == 3:
            parts = s.rsplit(":", 1)
            time_part, ms_part = parts[0], parts[1]
        else:
            time_part, ms_part = s, "0"
        z = int(ms_part.ljust(3, "0")[:3])
        parts = [int(p) for p in time_part.split(":")]
        if len(parts) == 1:
            h, m, sec = 0, 0, parts[0]
        elif len(parts) == 2:
            h, m, sec = 0, parts[0], parts[1]
        elif len(parts) == 3:
            h, m, sec = parts
        else:
            return 0
        return ((h * 3600 + m * 60 + sec) * 1000 + z)
    except Exception as e:
        warn(f"[WARN] hms_to_ms failed: '{s}' → {e}")
        return 0

def ms_to_hms(ms: int) -> str:
    """ミリ秒→ 'hh:mm:ss.zzz' へ変換"""
    s, z = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}.{z:03}"

# -- パス判定 -------------------------------------------
def is_network_drive(path: str) -> bool:
    """UNC/ネットワークドライブか判定"""
    return path.startswith("\\\\") or path.startswith("//")
    
def normalize_unc_path(path: str) -> str:
    r"""
    Windows UNCパスを正規化する  
    (例: //server/share → \\server\share)
    """
    if path.startswith("//") or path.startswith(r"\\"):
        return r"\\" + path.lstrip("/\\").replace("/", "\\")
    elif path.startswith("/"):
        parts = path.strip("/").split("/", 1)
        if len(parts) == 2:
            return rf"\\{parts[0]}\{parts[1].replace('/', '\\')}"
        else:
            return rf"\\{parts[0]}"
    return path.replace("/", "\\")  # 通常パスも\に統一

def compose_url_icon(favicon_b64: str, size: int = ICON_SIZE) -> QPixmap:
    """
    .urlファイル用の白紙＋favicon合成アイコンを生成（中央配置・スケーリング対応）
    """
    icon_size = size
    overlay_size = int(icon_size * 0.6)

    base = QPixmap(icon_size, icon_size)
    base.fill(Qt.GlobalColor.white)

    painter = QPainter(base)
    painter.setPen(QColor("#888"))
    painter.drawRect(0, 0, icon_size - 1, icon_size - 1)

    try:
        raw = base64.b64decode(favicon_b64)
        fav = QPixmap()
        fav.loadFromData(raw)
        if not fav.isNull():
            fav = fav.scaled(overlay_size, overlay_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            # 中央に描画
            x = (icon_size - fav.width()) // 2
            y = (icon_size - fav.height()) // 2
            painter.drawPixmap(x, y, fav)
    except Exception as e:
        warn(f"compose_url_icon failed: {e}")

    painter.end()
    return base

def b64encode_pixmap(pixmap: QPixmap) -> str:
    """QPixmap→Base64(PNG)文字列へ変換"""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return base64.b64encode(buffer.data()).decode("utf-8")

def detect_image_format(data: bytes) -> str:
    """
    バイナリデータから画像フォーマットを検出してData URLのプレフィックスを返す
    """
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return "data:image/png;base64,"
    elif data.startswith(b'\xff\xd8\xff'):
        return "data:image/jpeg;base64,"
    elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return "data:image/gif;base64,"
    elif data.startswith(b'<svg') or b'<svg' in data[:100]:
        return "data:image/svg+xml;base64,"
    else:
        # デフォルトはPNG
        return "data:image/png;base64,"

# -- favicon取得 -------------------------------------------
def fetch_favicon_base64(domain_or_url: str, target_size: int = 64) -> str | None:
    def _to_base64(data: bytes) -> str:
        return base64.b64encode(data).decode("utf-8")

    def get_nearest_icon(image, target_size):
        sizes = image.ico.sizes()
        nearest = min(sizes, key=lambda sz: abs(sz[0] - target_size))
        warn(f"選択されたサイズ: {nearest}")
        return image.ico.getimage(nearest)

    if not domain_or_url:
        warn("URLが空です")
        return None

    try:
        url = urlparse(domain_or_url)
        scheme = url.scheme or "http"
        host = url.netloc or url.path
        favicon_url = f"{scheme}://{host}/favicon.ico"
        warn(f"→ scheme={scheme}, host={host}, favicon_url={favicon_url}")
    except Exception as e:
        warn(f"[favicon] parse failed: {e}")
        return None

    # STEP-1: favicon.ico を直接取得して指定サイズに一番近い画像を選択
    try:
        req = Request(favicon_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=2) as resp:
            ico_data = resp.read()

        image = Image.open(io.BytesIO(ico_data))
        nearest_image = get_nearest_icon(image, target_size)

        buffer = io.BytesIO()
        nearest_image.save(buffer, format="PNG")
        return _to_base64(buffer.getvalue())

    except Exception as e:
        warn(f"[favicon] direct fetch failed: {e}")

    # STEP-2: Google Favicon API fallback
    try:
        google_url = f"https://www.google.com/s2/favicons?sz={target_size}&domain={host}"
        with urlopen(google_url, timeout=2) as resp:
            gdata = resp.read()
        return _to_base64(gdata)

    except Exception as e:
        warn(f"[favicon] google fetch failed: {e}")
        return None
        
# -- アイコン抽出 -------------------------------------------
def _extract_hicon(path: str, index: int) -> QPixmap | None:
    """
    Windowsリソース(HICON)からQPixmap生成  
    成功: QPixmap, 失敗: None
    """
    arr = (wintypes.HICON * 1)()
    if ctypes.windll.shell32.ExtractIconExW(path, index, arr, None, 1) > 0 and arr[0]:
        hicon = arr[0]
        img   = QImage.fromHICON(hicon)
        ctypes.windll.user32.DestroyIcon(hicon)
        if not img.isNull():
            return QPixmap.fromImage(img)
    return None

def get_fixed_local_icon(index: int, size: int = ICON_SIZE) -> QPixmap:
    r"""
    C:\Windows\System32\imageres.dllからリソース番号指定でアイコン取得  
    例: 28=ネットワークドライブ用
    """
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    dll_path = os.path.join(windir, "System32", "imageres.dll")
    arr = (wintypes.HICON * 1)()
    if ctypes.windll.shell32.ExtractIconExW(dll_path, index, arr, None, 1) > 0 and arr[0]:
        hicon = arr[0]
        image = QImage.fromHICON(hicon)
        ctypes.windll.user32.DestroyIcon(hicon)
        if not image.isNull():
            return QPixmap.fromImage(image).scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
    return QPixmap()

def _default_icon(size: int = ICON_SIZE) -> QPixmap:
    """汎用 “?” フォールバックアイコン（テーマカラー反映）"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    palette    = QApplication.instance().palette()
    text_color = palette.color(QPalette.ColorRole.Text)
    painter = QPainter(pm)
    painter.setPen(text_color)
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return pm

def _icon_pixmap(path: str, index: int = 0, size: int = ICON_SIZE) -> QPixmap:
    return _icon_pixmap_full(path, index, size)
    
    
def _icon_pixmap_basic(path: str, index: int = 0, size: int = ICON_SIZE) -> QPixmap:
    """
    DLL/EXE/ICOファイルから、指定サイズに最も近いアイコンを抽出する
    """
    if not path:
        print("path is empty")
        return _default_icon(size)
        
    # 1. ICOファイル
    if path.lower().endswith(".ico"):
        try:
            # PILで全サイズ調査
            with open(path, "rb") as f:
                img = Image.open(f)
                if my_has_attr(img, "ico"):
                    sizes = img.ico.sizes()
                    # 一番近いサイズ
                    nearest = min(sizes, key=lambda sz: abs(sz[0] - size))
                    img2 = img.ico.getimage(nearest)
                    buffer = io.BytesIO()
                    img2.save(buffer, format="PNG")
                    qimg = QImageReader().readFromData(buffer.getvalue())
                    pm = QPixmap()
                    pm.loadFromData(buffer.getvalue())
                    return pm
        except Exception as e:
            warn(f"_icon_pixmap ICO failed: {e}")
    # 2. DLL/EXE/その他（Windowsアイコン）
    try:
        # ctypesでHICON抽出（拡張可）
        arr = (wintypes.HICON * 1)()
        # ExtractIconExW: size引数は無いので、まず全部のアイコンを取得
        num_icons = ctypes.windll.shell32.ExtractIconExW(path, index, arr, None, 1)
        if num_icons > 0 and arr[0]:
            hicon = arr[0]
            # QImage.fromHICONで読み込めるすべてのサイズを取得して最大サイズまたは最も近いサイズを選ぶ
            qimg = QImage.fromHICON(hicon)
            # ↓ここで強制的にresize
            pm = QPixmap.fromImage(qimg)
            pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            ctypes.windll.user32.DestroyIcon(hicon)
            return pm
    except Exception as e:
        warn(f"_icon_pixmap ctypes ExtractIconExW failed: {e}")

    # 3. QFileIconProviderで取得（ファイルタイプごとの既定アイコン）
    try:
        provider = QFileIconProvider()
        icon = provider.icon(QFileInfo(path))
        pm = icon.pixmap(QSize(size, size))
        return pm
    except Exception as e:
        warn(f"_icon_pixmap QFileIconProvider failed: {e}")

    # 4. フォールバック：空アイコン
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm

def _icon_pixmap_full(path: str, idx: int = 0, size: int = ICON_SIZE) -> QPixmap:
    """
    ファイルパスから適切なアイコン QPixmap を返す  
      * 画像ファイル (.png .jpg .bmp .gif …) : そのまま読み込み  
      * DLL / EXE / ICO : WindowsAPI (ExtractIconExW) で抽出  
      * .url などその他 : QFileIconProvider に委任  
      * **空パス**           : imageres.dll から idx 指定で取得（Windows 既定アイコン）  
      * いずれも失敗したら最後に _default_icon() で “?” を返す
    """
    # -- ① パスが空 → Windows 既定アイコン --
    if not path:
        pix = get_fixed_local_icon(idx, size)
        if not pix.isNull():
            return pix
        return _default_icon(size)

    ext = Path(path).suffix.lower()

    # -- ② 画像ファイル系 --
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        real = os.path.abspath(os.path.expandvars(path))
        if os.path.exists(real):
            pix = QPixmap(real)
            if not pix.isNull():
                return pix.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    # -- ③ DLL / EXE / ICO リソース抽出 --
    if ext in (".dll", ".exe", ".ico"):
        try:
            real = os.path.normpath(os.path.expandvars(path))
            pix = _extract_hicon(real, idx)
            if pix and not pix.isNull():
                return pix.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception as e:
            warn(f"_icon_pixmap ExtractIconExW failed: {e}")

    # -- ④ .url 他は QFileIconProvider --
    try:
        fi = QFileInfo(path)
        icon = ICON_PROVIDER.icon(fi)
        pix = icon.pixmap(size, size)
        if not pix.isNull():
            return pix
    except Exception as e:
        warn(f"QFileIconProvider failed for {path}: {e}")

    # -- ⑤ どれも取れなかったらもう一度 imageres.dll を試行 --
    pix = get_fixed_local_icon(idx, size)
    if not pix.isNull():
        return pix

    # -- ⑥ 最終手段 “?” --
    return _default_icon(size)
    
def _load_pix_or_icon(src: str, idx: int = 0, icon_sz: int = ICON_SIZE) -> QPixmap:
    """
    * 画像ファイル (.png .jpg .jpeg .bmp .gif …) が存在する → **リサイズせず原寸で返す**
    * それ以外 / 読み込み失敗                     → 既存 _icon_pixmap() にフォールバック
    """
    if not src:
        return _icon_pixmap("", idx, icon_sz)  # “?” フォールバック
    p = Path(src)
    if p.suffix.lower() in IMAGE_EXTS and p.exists():
        pm = QPixmap(str(p))
        if not pm.isNull():
            return pm          # ★ここで縦横比・解像度そのまま
    return _icon_pixmap(src, idx, icon_sz)
# ------------------------------ __all__ ------------------------------
__all__ = [
    # 基本ユーティリティ
    "warn", "debug_print", "b64e", "b64d",
    "ms_to_hms_ms", "hms_to_ms", "ms_to_hms",
    "is_network_drive", "fetch_favicon_base64",
    "detect_image_format",
    # アイコン関連
    "get_fixed_local_icon", "_default_icon", "_icon_pixmap","_load_pix_or_icon",
    # 定数群（利便用）
    "ICON_SIZE", "IMAGE_EXTS", "VIDEO_EXTS",
    "EXECUTE_EXTS", "PYTHON_SCRIPT_EXT",
]
