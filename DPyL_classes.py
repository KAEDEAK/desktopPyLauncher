# -*- coding: utf-8 -*-
"""
DPyL_classes.py  ―  desktopPyLauncher GUIアイテム/共通ダイアログ
◎ Qt6 / PyQt6 専用
"""
from __future__ import annotations
import os,sys,json,base64
from pathlib import Path
from typing import Callable, Any
from base64 import b64decode            
from shlex import split as shlex_split
from win32com.client import Dispatch
import subprocess
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QSizeF, QTimer, QSize, QFileInfo, QBuffer, QByteArray, QIODevice, QProcess, QCoreApplication
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QPalette, QColor, QBrush, QPen, QIcon, QMovie
)
from PyQt6.QtWidgets import (
    QApplication, QGraphicsItemGroup, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsSceneMouseEvent, QGraphicsItem,QGraphicsTextItem,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QSpinBox, QLineEdit, QColorDialog, QComboBox, QCheckBox,
    QGraphicsProxyWidget, QGraphicsColorizeEffect
)

# ---------------------------------------------------------------------------------------------------- internal util -------------------------------------------------
from DPyL_utils import (
    warn, b64e, ICON_SIZE,IMAGE_EXTS,
    _icon_pixmap,compose_url_icon,
    normalize_unc_path,
    fetch_favicon_base64
)

from DPyL_debug import (my_has_attr,dump_missing_attrs,trace_this)

log_cnt=0
def movie_debug_print(msg: str) -> None:
    global log_cnt
    log_cnt+=1
    print(f"[MOVIE_DEBUG] {log_cnt} {msg}", file=sys.stderr)
# ==================================================================
#  CanvasItem（基底クラス）
# ==================================================================
class CanvasItem(QGraphicsItemGroup):
    """
    キャンバス上の全アイテムの基底クラス:
      - run_mode管理
      - キャプション自動生成
      - 子要素マウス透過
      - 位置/サイズの self.d 同期
      - リサイズコールバック＆on_resizedフック
    """
    TYPE_NAME = "base"
    # --- 自動登録レジストリ -------------------------------
    ITEM_CLASSES: list["CanvasItem"] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # 派生クラスを自動登録（TYPE_NAME が base 以外）
        if getattr(cls, "TYPE_NAME", None) not in (None, "", "base"):
            CanvasItem.ITEM_CLASSES.append(cls)

    # --- ドロップ対応ファクトリ API ------------------------
    @classmethod
    def supports_path(cls, path: str) -> bool:
        """このクラスが `path` を扱えるなら True"""
        return False  # 派生で override する

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        """
        supports_path が True の時に呼び出されるコンストラクタラッパ
        * sp  : QPointF  (ドロップ座標)
        * win : MainWindow インスタンス
        戻り値: (item_instance, json_dict)
        """
        raise NotImplementedError
        
    def __init__(
        self,
        d: dict[str, Any] | None = None,
        cb_resize: Callable[[int, int], None] | None = None,
        text_color: QColor | None = None
    ):
        super().__init__()
        self._movie = None
        self._destroying=False
        movie_debug_print("CanvasItem.__init__")
        # --- 枠用の矩形アイテムを先に生成 ---
        self._rect_item = QGraphicsRectItem(parent=self)
        self._rect_item.setRect(0, 0, 0, 0)

        # 選択/移動/ジオメトリ変更通知を有効化
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        # 状態管理
        self.d = d or {}
        self._cb_resize = cb_resize
        self.run_mode = True
        self.text_color = text_color or QColor(Qt.GlobalColor.black)

        # 共通初期化
        self.init_mouse_passthrough()
        self.init_caption()
        
        self.grip = CanvasResizeGrip()
        self.grip._parent = self
        #self.grip.setParentItem(self)
        self.grip._parent = self
        #self.grip.setZValue(9999)
        self.grip.update_zvalue()  
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.set_editable(False)
        self._update_grip_pos()

    def init_mouse_passthrough(self):
        # 子アイテムのマウス透過（グリップ除く）
        for child in self.childItems():
            if isinstance(child, CanvasResizeGrip):
                continue
            child.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def set_editable(self, editable: bool):
        # 編集モード切り替え（選択/移動/枠/グリップ表示）
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, editable)
        # 背景は常時表示（ラベル ON/OFF は NoteEditDialog 側で制御）
        if my_has_attr(self, "fill_bg"):
            self._rect_item.setVisible(self.fill_bg or editable)
        else:
            self._rect_item.setVisible(editable)
        
        # resize grip
        if my_has_attr(self, "grip"):
            self.grip.setVisible(editable)
        if my_has_attr(self, "_update_grip_pos"):
            self._update_grip_pos()
            
    def init_caption(self):
        """キャプションがあればQGraphicsTextItem生成/再配置"""
        if "caption" not in self.d:
            return

        # テーマに合わせたテキスト色
        app = QApplication.instance()
        text_color = app.palette().color(QPalette.ColorRole.WindowText)

        # cap_itemがなければ生成
        if not my_has_attr(self, "cap_item"):
            cap = QGraphicsTextItem(self.d["caption"], parent=self)
            cap.setDefaultTextColor(text_color)
            font = cap.font()
            font.setPointSize(8)
            cap.setFont(font)
            self.cap_item = cap

        # 常に枠の下端に配置
        rect = self._rect_item.rect()
        pix_h = 0
        if my_has_attr(self, "_pix_item") and self._pix_item.pixmap().isNull() is False:
            pix_h = self._pix_item.pixmap().height()
        self.cap_item.setPos(0, pix_h)

    def set_run_mode(self, run: bool):
        """実行(True)/編集(False)モード切替"""
        self.run_mode = run
        self.set_editable(not run)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any):
        if self._destroying:
            movie_debug_print("CanvasItem.itemChange !!! destroying A (guard hit)")
            return        
        # 選択状態変化で枠の色変更
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            pen = self._rect_item.pen()
            pen.setColor(QColor("#ff3355") if self.isSelected() else QColor("#888"))
            self._rect_item.setPen(pen)

        # 位置変更時はスナップ補正
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # === グループ移動中はスナップしない ===
            if getattr(self, '_group_moving', False):
                return value
            # =======================================
            
            # ロード中のスナップを無効化
            if (my_has_attr(self.scene(), "views") and self.scene().views() and
                not getattr(self.scene().views()[0].window(), "_loading_in_progress", False)):
                view = self.scene().views()[0]
                if my_has_attr(view, "win") and my_has_attr(view.win, "snap_position"):
                    return view.win.snap_position(self, value)

        # 位置確定時はself.dへ座標保存＋グリップ位置更新
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # 浮動小数点のまま保存
            pos = self.pos()
            self.d["x"], self.d["y"] = pos.x(), pos.y()
            self._update_grip_pos()

        # 変形（リサイズ）時のコールバック処理
        elif change == QGraphicsItem.GraphicsItemChange.ItemTransformHasChanged:
            if callable(self._cb_resize) and not getattr(self, "_in_resize", False):
                self._in_resize = True
                r = self._rect_item.rect()
                w, h = int(r.width()), int(r.height())
                self.d["width"], self.d["height"] = w, h
                self._cb_resize(w, h)
                self.on_resized(w, h)
                self.init_caption()
                self._in_resize = False

        # シーン追加時にグリップも追加
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneChange:
            if value and self.grip.scene() is None:
                value.addItem(self.grip)

        return super().itemChange(change, value)


    def _update_grip_pos(self):
        # グリップを矩形右下へ配置
        # --- Grip を Scene 座標で再配置 ---
        r = self._rect_item.rect()
        scene_tl = self.mapToScene(QPointF(0, 0))
        self.grip.setPos(
            scene_tl.x() + r.width()  - self.grip.rect().width(),
            scene_tl.y() + r.height() - self.grip.rect().height()
        )

    def get_resize_target_rect(self) -> QRectF:
        """リサイズ対象矩形を返す（グリップ用）"""
        return self._rect_item.rect()
        
    def on_resized(self, w: int, h: int):
        # 派生用: リサイズ後にグリップ再配置
        self._update_grip_pos()

    def boundingRect(self) -> QRectF:
        return self._rect_item.boundingRect()

    def paint(self, *args, **kwargs):
        # グループ自身は描画しない
        return None

    # CanvasItem _apply_pixmap
    def _apply_pixmap(self) -> None:
        """
        ImageItem/JSONItem共通：ピクスマップ表示＋枠サイズ設定
          - self.pathやself.embedから画像取得
          - d['width'],d['height']でスケーリング
          - 明るさ補正
          - 子の_pix_item/_rect_item更新
        """
        # 1) ピクスマップ取得
        pix = QPixmap()
        if my_has_attr(self, "embed") and self.embed:
            pix.loadFromData(b64decode(self.embed))
        #elif my_has_attr(self, "path") and self.path:
        #    pix = QPixmap(self.path)
        else:
            icon_path = getattr(self, "icon", None) or getattr(self, "path", "")
            if icon_path:
                pix = QPixmap(icon_path)
                
        # 2) 代替アイコン
        if pix.isNull():
            pix = _icon_pixmap(getattr(self, "path", "") or "", 0, ICON_SIZE)

        # オリジナルを保持
        self._src_pixmap = pix.copy()

        # 3) サイズ指定でスケーリング（cover）
        tgt_w = int(self.d.get("width",  pix.width()))
        tgt_h = int(self.d.get("height", pix.height()))
        scaled = self._src_pixmap.scaled(tgt_w, tgt_h,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        crop_x = max(0, (scaled.width()  - tgt_w) // 2)
        crop_y = max(0, (scaled.height() - tgt_h) // 2)
        pix = scaled.copy(crop_x, crop_y, tgt_w, tgt_h)

        # 4) 明るさ補正
        bri = getattr(self, "brightness", None)
        if bri is not None and bri != 50:
            level = bri - 50
            alpha = int(abs(level) / 50 * 255)
            overlay = QPixmap(pix.size())
            overlay.fill(Qt.GlobalColor.transparent)
            painter = QPainter(overlay)
            col = QColor(255,255,255,alpha) if level>0 else QColor(0,0,0,alpha)
            painter.fillRect(overlay.rect(), col)
            painter.end()
            result = QPixmap(pix.size())
            result.fill(Qt.GlobalColor.transparent)
            p2 = QPainter(result)
            p2.drawPixmap(0,0,pix)
            p2.drawPixmap(0,0,overlay)
            p2.end()
            pix = result

        # 5) ピクスマップ反映
        self._pix_item.setPixmap(pix)
        self._rect_item.setRect(0, 0, pix.width(), pix.height())
        self._orig_pixmap = self._src_pixmap
        self.init_caption()

        # 6) キャプション分だけ枠を拡張
        caption_h = 0
        if "caption" in self.d:
            self.init_caption()
            caption_h = self.cap_item.boundingRect().height()

        self._rect_item.setRect(0, 0, pix.width(), pix.height() + caption_h)

        if "caption" in self.d:
            self.init_caption()  # 2回目は位置再計算のみ

        # 7) 再描画
        self.prepareGeometryChange()
        self.update()

    def on_edit(self):
        #raise NotImplementedError("You must override on_edit in subclass")
        pass
    def on_activate(self):
        #raise NotImplementedError("You must override on_activate in subclass")
        pass

    def mouseDoubleClickEvent(self, ev: QGraphicsSceneMouseEvent):
        """
        ダブルクリック時の共通動作:
          - 実行モード: 派生on_activate()
          - 編集モード: 派生on_edit()
        """
        
        #print ("run_mode",hasattr(self,"run_mode"),self.run_mode)

        if getattr(self, "run_mode", False):
            if my_has_attr(self, "on_activate"):
                self.on_activate()
            ev.accept()
            return
        else:
            if my_has_attr(self, "on_edit"):
                self.on_edit()
            ev.accept()
            return
            
        # ダブルクリック伝播防止
        super().mouseDoubleClickEvent(ev)
        ev.accept()

    def contextMenuEvent(self, ev):
        """右クリック: MainWindowの共通メニューを表示"""
        win = self.scene().views()[0].window()
        win.show_context_menu(self, ev)
        
    def snap_resize_size(self, w, h, threshold=10):
        """
        他のオブジェクトの端にサイズを吸着する（デフォルト実装）
        - threshold: 吸着判定のピクセル数
        """
        # === グループ移動中はスナップしない ===
        if getattr(self, '_group_moving', False):
            return w, h
        # =======================================
        
        #print(f"[snap_resize_size] called: w={w} h={h}")
        scene = self.scene()
        if not scene:
            return w, h
        my_rect = self.get_resize_target_rect()  # 現在リサイズターゲットの矩形
        x0, y0 = self.pos().x(), self.pos().y()
        best_w, best_h = w, h
        best_dw, best_dh = threshold, threshold
        for item in scene.items():
            if item is self or not my_has_attr(item, "boundingRect"):
                continue
            r2 = item.mapToScene(item.boundingRect()).boundingRect()
            # 横端吸着
            for ox in [r2.left(), r2.right()]:
                dw = abs((x0 + w) - ox)
                if dw < best_dw:
                    best_dw = dw
                    best_w = ox - x0
            # 縦端吸着
            for oy in [r2.top(), r2.bottom()]:
                dh = abs((y0 + h) - oy)
                if dh < best_dh:
                    best_dh = dh
                    best_h = oy - y0
        return best_w, best_h
        
    def setZValue(self, z: float):
        """
        Z 値変更時にグリップも追従させる
        """
        super().setZValue(z)
        # グリップの前面維持
        if my_has_attr(self, "grip") and self.grip:
            self.grip.update_zvalue()
            
    def delete_self(self):
        self._destroying=True
        movie_debug_print("CanvasItem.delete_self")
        r"""
        共通の削除処理（サブクラスでオーバーライド可）
        ・グリップ／キャプション／ピクスマップを先にシーンから除去
        ・最後に自身をシーンから removeItem して参照を断つ        
        """
        # 1) グリップ除去
        if hasattr(self, "grip") and self.grip and self.grip.scene():
            self.grip.scene().removeItem(self.grip)
        self.grip = None

        # 2) キャプション除去
        if hasattr(self, "cap_item") and self.cap_item and self.cap_item.scene():
            self.cap_item.scene().removeItem(self.cap_item)
        self.cap_item = None

        # 3) ピクスマップ除去
        if hasattr(self, "_pix_item") and self._pix_item and self._pix_item.scene():
            self._pix_item.scene().removeItem(self._pix_item)
        self._pix_item = None

        # 4) 自身をシーンから除去
        if self.scene():
            self.scene().removeItem(self)

        
# --------------------------------------------------
#  GifMixin  :  QMovie ライフサイクルを隠蔽
# --------------------------------------------------

class GifMixin:
    """
    多重継承するだけで GIF が動く Mixin。
    CanvasItem 側で用意される以下のメンバーに依存する。

        self.d            : dict  … width/height 等のメタ
        self._pix_item    : QGraphicsPixmapItem
        self._rect_item   : QGraphicsRectItem（無くても可）

    継承順は「GifMixin, CanvasItem」を推奨。
    """

    # ---------------------------------------------------
    #   ライフサイクル
    # ---------------------------------------------------
    def __init__(self, *args, **kwargs):
        self._movie: Optional[QMovie] = None
        self._gif_buffer: Optional[QBuffer] = None
        super().__init__(*args, **kwargs)

    def __del__(self):
        self._stop_movie()

    # ---------------------------------------------------
    #   公開 API
    # ---------------------------------------------------
    def load_gif(
        self,
        *,
        path: str | None = None,
        raw: bytes | None = None,
        scaled_w: int | None = None,
        scaled_h: int | None = None
    ) -> bool:
        """
        GIF をセットアップして再生開始。戻り値 True＝GIF として扱えた。
        path または raw（base64 等を decode 済みバイト列）を渡す。
        """
        if not self._is_gif_source(path, raw):
            return False                          # GIF ではない

        self._stop_movie()                       # 既存を完全停止

        # QMovie 構築
        if raw:
            self._gif_buffer = QBuffer()
            self._gif_buffer.setData(QByteArray(raw))
            self._gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self._movie = QMovie()
            self._movie.setDevice(self._gif_buffer)
        else:
            self._movie = QMovie(path)

        if scaled_w and scaled_h:
            self._movie.setScaledSize(QSize(scaled_w, scaled_h))

        self._movie.frameChanged.connect(self._on_movie_frame)
        self._movie.start()
        self._on_movie_frame()                   # 1 フレーム目即描画
        return True

    # ---------------------------------------------------
    #   内部ユーティリティ
    # ---------------------------------------------------
    @staticmethod
    def _is_gif_source(path: str | None, raw: bytes | None) -> bool:
        if path and path.lower().endswith(".gif") and Path(path).exists():
            return True
        if raw and raw[:6] in (b"GIF87a", b"GIF89a"):
            return True
        return False

    def _stop_movie(self):
        """再生中 GIF を安全に破棄"""
        if self._movie:
            try:
                self._movie.frameChanged.disconnect(self._on_movie_frame)
            except Exception:
                pass
            self._movie.stop()
            self._movie = None
        if self._gif_buffer:
            try:
                self._gif_buffer.close()
            except Exception:
                pass
            self._gif_buffer = None

    # ------------------------------------------------------------------
    #   フレーム更新スロット
    # ------------------------------------------------------------------
    def _on_movie_frame(self):
        if not self._movie or not hasattr(self, "_pix_item"):
            return
        frame: QPixmap = self._movie.currentPixmap()
        if frame.isNull():
            return

        tgt_w = int(self.d.get("width",  frame.width()))
        tgt_h = int(self.d.get("height", frame.height()))
        scaled = frame.scaled(
            tgt_w, tgt_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = max(0, (scaled.width()  - tgt_w) // 2)
        cy = max(0, (scaled.height() - tgt_h) // 2)
        pm_final = scaled.copy(cx, cy, tgt_w, tgt_h)

        self._pix_item.setPixmap(pm_final)
        if hasattr(self, "_rect_item"):
            self._rect_item.setRect(0, 0, tgt_w, tgt_h)

            
# ==================================================================
#  LauncherItem ― exe / url
# ==================================================================

def quote_if_needed(path: str) -> str:
    path = path.strip()
    return f'"{path}"' if " " in path and not (path.startswith('"') and path.endswith('"')) else path

# --------------------------------------------------
#  GifMixin  :  QMovie ライフサイクルを隠蔽
# --------------------------------------------------
class GifMixin:
    """
    多重継承するだけで GIF が動く Mixin。
    CanvasItem 側で用意される以下のメンバーに依存する。
        self.d            : dict  … width/height 等のメタ
        self._pix_item    : QGraphicsPixmapItem
        self._rect_item   : QGraphicsRectItem（無くても可）
    継承順は「GifMixin, CanvasItem」を推奨。
    """
    # ---------------------------------------------------
    #   ライフサイクル
    # ---------------------------------------------------
    def __init__(self, *args, **kwargs):
        self._movie: Optional[QMovie] = None
        self._gif_buffer: Optional[QBuffer] = None
        super().__init__(*args, **kwargs)
        
    def __del__(self):
        try:
            self._stop_movie()
        except Exception:
            pass  # デストラクタでは例外を抑制
        
    # ---------------------------------------------------
    #   公開 API
    # ---------------------------------------------------
    def load_gif(
        self,
        *,
        path: str | None = None,
        raw: bytes | None = None,
        scaled_w: int | None = None,
        scaled_h: int | None = None
    ) -> bool:
        """
        GIF をセットアップして再生開始。戻り値 True＝GIF として扱えた。
        path または raw（base64 等を decode 済みバイト列）を渡す。
        """
        if not self._is_gif_source(path, raw):
            return False                          # GIF ではない
            
        self._stop_movie()                       # 既存を完全停止
        
        # QMovie 構築
        if raw:
            self._gif_buffer = QBuffer()
            self._gif_buffer.setData(QByteArray(raw))
            self._gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self._movie = QMovie()
            self._movie.setDevice(self._gif_buffer)
        else:
            self._movie = QMovie(path)
            
        # QMovieのスケーリングは使用しない（オリジナルサイズのまま取得）
        # 手動でスケーリングとクロップを行うため
            
        self._movie.frameChanged.connect(self._on_movie_frame)
        self._movie.start()
        self._on_movie_frame()                   # 1 フレーム目即描画
        return True
        
    def toggle_gif_playback(self):
        """GIFの再生/停止をトグル"""
        if not self._movie:
            return
            
        if self._movie.state() == QMovie.MovieState.Running:
            self._movie.setPaused(True)
        else:
            self._movie.start()
            
    def is_gif_playing(self) -> bool:
        """GIFが再生中かどうか"""
        return self._movie and self._movie.state() == QMovie.MovieState.Running
        
    def stop_gif(self):
        """GIF再生を停止"""
        if self._movie:
            self._movie.stop()
            
    def start_gif(self):
        """GIF再生を開始"""
        if self._movie:
            self._movie.start()
            
    # ---------------------------------------------------
    #   内部ユーティリティ
    # ---------------------------------------------------
    @staticmethod
    def _is_gif_source(path: str | None, raw: bytes | None) -> bool:
        if path and path.lower().endswith(".gif") and Path(path).exists():
            return True
        if raw and raw[:6] in (b"GIF87a", b"GIF89a"):
            return True
        return False
        
    def _stop_movie(self):
        """再生中 GIF を安全に破棄"""
        try:
            if self._movie:
                try:
                    self._movie.frameChanged.disconnect(self._on_movie_frame)
                except (TypeError, RuntimeError):
                    pass  # 既に切断済みまたはオブジェクト削除済み
                try:
                    self._movie.stop()
                except RuntimeError:
                    pass  # オブジェクト削除済み
                self._movie = None
        except Exception:
            pass  # デストラクタ時の安全性を最優先
            
        try:
            if self._gif_buffer:
                try:
                    self._gif_buffer.close()
                except RuntimeError:
                    pass  # オブジェクト削除済み
                self._gif_buffer = None
        except Exception:
            pass  # デストラクタ時の安全性を最優先
            
    # ------------------------------------------------------------------
    #   フレーム更新スロット
    # ------------------------------------------------------------------
    def _on_movie_frame(self):
        if not self._movie or not hasattr(self, "_pix_item"):
            return
            
        frame: QPixmap = self._movie.currentPixmap()
        if frame.isNull():
            return
            
        # 目標サイズ（アイコンの描画領域）
        tgt_w = int(self.d.get("width",  frame.width()))
        tgt_h = int(self.d.get("height", frame.height()))
        
        # オリジナルGIFフレームサイズ
        orig_w = frame.width()
        orig_h = frame.height()
        
        if orig_w == 0 or orig_h == 0:
            return
            
        # 縦横比を維持しつつ、短い方の辺を目標サイズにフィットさせるスケール比を計算
        # max() を使うことで、必ず目標サイズを覆うようにスケーリング（Cover動作）
        scale_x = tgt_w / orig_w
        scale_y = tgt_h / orig_h
        scale = max(scale_x, scale_y)  # 短い方の辺をフィット
        
        # スケーリング後のサイズ
        scaled_w = int(orig_w * scale)
        scaled_h = int(orig_h * scale)
        
        # スケーリング実行
        scaled = frame.scaled(
            scaled_w, scaled_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,  # 計算済みなので比率は無視
            Qt.TransformationMode.SmoothTransformation,
        )
        
        # 中央部分をクロップ（はみ出した部分を切り取り）
        cx = max(0, (scaled_w - tgt_w) // 2)
        cy = max(0, (scaled_h - tgt_h) // 2)
        pm_final = scaled.copy(cx, cy, tgt_w, tgt_h)
        
        # 明るさ補正を適用（継承クラスで実装される場合）
        if hasattr(self, '_apply_brightness_to_pixmap'):
            pm_final = self._apply_brightness_to_pixmap(pm_final)
            
        self._pix_item.setPixmap(pm_final)
        
        if hasattr(self, "_rect_item"):
            self._rect_item.setRect(0, 0, tgt_w, tgt_h)
            
        # キャプション位置を更新（GIF フレーム高さに合わせて）
        if hasattr(self, "cap_item") and self.cap_item:
            self.cap_item.setPos(0, tgt_h)
            
        # グリップ位置更新（継承クラスで実装される場合）
        if hasattr(self, "_update_grip_pos"):
            self._update_grip_pos()
            
        # EDITラベル位置更新（LauncherItem用）
        if hasattr(self, "_edit_label") and self._edit_label:
            self._edit_label.setPos(2, 2)


# --------------------------------------------------
#  改良された LauncherItem (GifMixin + CanvasItem)
# --------------------------------------------------
class LauncherItem(GifMixin, CanvasItem):
    TYPE_NAME = "launcher"
    
    # 実行系拡張子
    SCRIPT_LIKE = (".bat", ".cmd", ".ps1", ".py", ".js", ".vbs", ".wsf")
    EXE_LIKE    = (".exe", ".com", ".jar", ".msi")
    EDITABLE_LIKE = (".txt", ".json", ".yaml", ".yml", ".md")
    SHORTCUT_LIKE = (".lnk", ".url")

    @classmethod
    def supports_path(cls, path: str) -> bool:
        ext = Path(path).suffix.lower()
        # JSONプロジェクトファイルは除外
        if ext == ".json":
            try:
                with open(path, encoding="utf-8") as f:
                    fi = json.load(f).get("fileinfo", {})
                    if fi.get("name") == "desktopPyLauncher.py":
                        return False
            except Exception:
                pass
                
        return ext in (
            cls.SHORTCUT_LIKE +
            cls.EXE_LIKE +
            cls.SCRIPT_LIKE +
            cls.EDITABLE_LIKE +
            (".gif",)  # GIFもサポート
        )

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        ext = Path(path).suffix.lower()
        d = {
            "type": "launcher",
            "caption": Path(path).stem,
            "x": sp.x(), "y": sp.y()
        }
        
        if ext in cls.EDITABLE_LIKE:
            d["is_editable"] = True
        else:
            d["is_editable"] = False

        if ext == ".url":
            url, icon_file, icon_index = cls.parse_url_shortcut(path)
            if url:
                d["path"] = url
                d["shortcut"] = path
                if icon_file:
                    d["icon"] = icon_file
                if icon_index is not None:
                    d["icon_index"] = icon_index
            else:
                d["path"] = path
        elif ext == ".lnk":
            target, workdir, iconloc = cls.parse_lnk_shortcut(path)
            if target:
                d["path"] = target
                d["shortcut"] = path
                if workdir:
                    d["workdir"] = workdir
                if iconloc:
                    parts = iconloc.split(",", 1)
                    icon_path = parts[0].strip()
                    d["icon"] = icon_path or target
                    if len(parts) > 1:
                        try:
                            d["icon_index"] = int(parts[1])
                        except Exception:
                            d["icon_index"] = 0
                else:
                    d["icon"] = target
                    d["icon_index"] = 0
            else:
                d["path"] = path
        else:
            d["path"] = path
            d["workdir"] = str(Path(path).parent)

        return cls(d, win.text_color), d

    def __init__(self, d: dict, cb_resize=None, text_color=None):
        super().__init__(d, cb_resize, text_color)
        
        # 基本属性
        self.icon = self.d.get("icon", "")
        self.workdir = self.d.get("workdir", "")
        self.embed = self.d.get("icon_embed")
        self.is_editable = self.d.get("is_editable", False)
        self.runas = self.d.get("runas", False)
        self.brightness = self.d.get("brightness", 50)
        
        # EDITラベル作成
        self._edit_label = QGraphicsTextItem("EDIT", self)
        self._edit_label.setDefaultTextColor(QColor("#cc3333"))
        font = self._edit_label.font()
        font.setPointSize(8)
        self._edit_label.setFont(font)
        self._edit_label.setZValue(9999)
        self._edit_label.setHtml('<span style="background-color:#0044cc;color:#ffff00;">EDIT</span>')
        self._edit_label.setVisible(self.is_editable)
        
        # ピクスマップアイテム
        self._pix_item = QGraphicsPixmapItem(parent=self)
        self._refresh_icon()

    @property
    def path(self):
        return self.d.get("path", "")

    def _refresh_icon(self):
        """アイコン画像を更新（GIF対応）"""
        try:
            # GIF処理を最初に試行
            if self._try_load_gif():
                self._update_caption_and_grip()
                return
                
            # 通常の静止画処理
            self._load_static_image()
            self._update_caption_and_grip()
            
        except Exception as e:
            warn(f"_refresh_icon failed: {e}")
            self._load_fallback_icon()
            self._update_caption_and_grip()

    def _update_caption_and_grip(self):
        """キャプションとグリップ位置を更新"""
        # キャプション位置を更新
        self.init_caption()
        
        # グリップ位置を更新
        self._update_grip_pos()
        
        # EDITラベル位置を更新
        if hasattr(self, "_edit_label") and self._edit_label:
            self._edit_label.setVisible(self.is_editable)
            self._edit_label.setPos(2, 2)

    def _try_load_gif(self) -> bool:
        """GIFの読み込みを試行"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        
        # embed データからGIF読み込み
        if self.embed:
            try:
                raw = base64.b64decode(self.embed)
                if self.load_gif(raw=raw):  # スケーリングパラメータを削除
                    self.d["width"], self.d["height"] = tgt_w, tgt_h
                    return True
            except Exception as e:
                warn(f"GIF embed load failed: {e}")
        
        # ファイルパスからGIF読み込み
        src_path = self.d.get("icon") or self.path
        if src_path and src_path.lower().endswith(".gif"):
            if self.load_gif(path=src_path):  # スケーリングパラメータを削除
                self.d["width"], self.d["height"] = tgt_w, tgt_h
                return True
                
        return False

    def _load_static_image(self):
        """静止画の読み込み処理"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        
        pix = None
        
        # embed データから読み込み
        if self.embed:
            pix = QPixmap()
            try:
                pix.loadFromData(base64.b64decode(self.embed))
            except Exception as e:
                warn(f"Static image embed load failed: {e}")
                pix = None
        
        # ファイルパスから読み込み
        if not pix or pix.isNull():
            src = self.d.get("icon") or self.path
            if src:
                idx = self.d.get("icon_index", 0)
                pix = _icon_pixmap(src, idx, max(tgt_w, tgt_h, ICON_SIZE))
        
        # フォールバック
        if not pix or pix.isNull():
            pix = _icon_pixmap("", 0, ICON_SIZE)
            
        # スケーリングと明るさ調整
        self._src_pixmap = pix.copy()
        scaled = self._apply_scaling_and_crop(pix, tgt_w, tgt_h)
        final_pix = self._apply_brightness_to_pixmap(scaled)
        
        self._pix_item.setPixmap(final_pix)
        self._rect_item.setRect(0, 0, tgt_w, tgt_h)
        self.d["width"], self.d["height"] = tgt_w, tgt_h
        
        # キャプション位置を手動設定（静止画の場合）
        if hasattr(self, "cap_item") and self.cap_item:
            self.cap_item.setPos(0, tgt_h)

    def _load_fallback_icon(self):
        """フォールバックアイコン読み込み"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        pix = _icon_pixmap("", 0, ICON_SIZE)
        self._pix_item.setPixmap(pix)
        self._rect_item.setRect(0, 0, tgt_w, tgt_h)

    def _apply_scaling_and_crop(self, pix: QPixmap, w: int, h: int) -> QPixmap:
        """スケーリングとクロップを適用"""
        scaled = pix.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cx = max(0, (scaled.width() - w) // 2)
        cy = max(0, (scaled.height() - h) // 2)
        return scaled.copy(cx, cy, w, h)

    def _apply_brightness_to_pixmap(self, pix: QPixmap) -> QPixmap:
        """明るさ補正を適用"""
        if self.brightness == 50 or pix.isNull():
            return pix
            
        level = self.brightness - 50
        alpha = int(abs(level) / 50 * 255)
        
        overlay = QPixmap(pix.size())
        overlay.fill(Qt.GlobalColor.transparent)
        painter = QPainter(overlay)
        col = QColor(255, 255, 255, alpha) if level > 0 else QColor(0, 0, 0, alpha)
        painter.fillRect(overlay.rect(), col)
        painter.end()
        
        result = QPixmap(pix.size())
        result.fill(Qt.GlobalColor.transparent)
        p2 = QPainter(result)
        p2.drawPixmap(0, 0, pix)
        p2.drawPixmap(0, 0, overlay)
        p2.end()
        return result

    def resize_content(self, w: int, h: int):
        """リサイズ処理"""
        self.d["width"], self.d["height"] = w, h
        
        if self._movie:
            # GIFの場合は現在フレームを手動でリサイズ
            # QMovieのスケーリングは使用せず、_on_movie_frame()で処理
            self._on_movie_frame()
        else:
            # 静止画の場合は通常のリサイズ
            if hasattr(self, "_src_pixmap") and not self._src_pixmap.isNull():
                scaled = self._apply_scaling_and_crop(self._src_pixmap, w, h)
                final_pix = self._apply_brightness_to_pixmap(scaled)
                self._pix_item.setPixmap(final_pix)
            
            # 静止画の場合はキャプション位置を手動更新
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPos(0, h)
            
        self._rect_item.setRect(0, 0, w, h)
        self._update_grip_pos()

    def mousePressEvent(self, ev):
        """
        クリック処理
        - 左クリック: GIFがある場合は再生/停止トグル
        - その他: 通常の処理（選択等）
        """
        if ev.button() == Qt.MouseButton.LeftButton and self._movie:
            # GIFの場合は再生/停止トグル（シングルクリック）
            self.toggle_gif_playback()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        """
        ダブルクリック処理
        - 実行モード: on_activate() を呼び出し
        - 編集モード: on_edit() を呼び出し
        """
        if getattr(self, "run_mode", False):
            # 実行モード
            self.on_activate()
        else:
            # 編集モード
            self.on_edit()
        ev.accept()

    # 既存のメソッド（parse_url_shortcut, parse_lnk_shortcut, on_edit, on_activate等）
    # は変更なしでそのまま使用...
    
    @staticmethod
    def parse_url_shortcut(path: str) -> tuple[str|None, str|None, int|None]:
        """URLショートカットファイルの解析"""
        url = None
        icon_file = None
        icon_index = None
        for enc in ("utf-8", "shift_jis", "cp932"):
            try:
                with open(path, encoding=enc) as f:
                    for line in f:
                        line = line.strip()
                        if line.lower().startswith("url="):
                            url = line[4:]
                        elif line.lower().startswith("iconfile="):
                            icon_file = line[9:]
                        elif line.lower().startswith("iconindex="):
                            try:
                                icon_index = int(line[10:])
                            except Exception:
                                pass
                if url:
                    break
            except Exception:
                continue
        return url, icon_file, icon_index

    @staticmethod
    def parse_lnk_shortcut(path: str) -> tuple[str | None, str | None, str | None]:
        """.lnkショートカットファイルの解析"""
        try:
            from win32com.client import Dispatch
            shell = Dispatch("WScript.Shell")
            link = shell.CreateShortcut(path)
            target = link.TargetPath or ""
            args = link.Arguments or ""
            workdir = link.WorkingDirectory or None
            iconloc = link.IconLocation or None
            full_target = f"{target} {args}".strip() if args else target
            return full_target, workdir, iconloc
        except Exception as e:
            warn(f"[parse_lnk_shortcut] {e}")
            return None, None, None

    def _update_edit_label_pos(self):
        """EDITラベルの位置更新"""
        if hasattr(self, "_edit_label") and self._edit_label:
            self._edit_label.setPos(2, 2)

    def on_edit(self):
        """編集ダイアログを開く"""
        win = self.scene().views()[0].window()
        from DPyL_classes import LauncherEditDialog
        dlg = LauncherEditDialog(self.d, win)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.embed   = self.d.get("icon_embed")   # 更新された可能性
            self.workdir = self.d.get("workdir", "")
            # 一時プレビューのサイズで width/height を保存
            if hasattr(dlg, "preview") and isinstance(dlg.preview, QGraphicsPixmapItem):
                pix = dlg.preview.pixmap()
                if not pix.isNull():
                    self.d["width"], self.d["height"] = pix.width(), pix.height()

            self._refresh_icon()
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPlainText(self.d.get("caption", ""))
        self.is_editable = self.d.get("is_editable", False)
        if hasattr(self, "_edit_label"):
            self._edit_label.setVisible(self.is_editable)
            self._update_edit_label_pos()
        self.set_run_mode(not win.a_edit.isChecked())

    def on_activate(self):
        """
        実行モード時のダブルクリック起動処理  
        フォルダ → エクスプローラーで開く  
        拡張子に応じて subprocess / QProcess / os.startfile を使い分け
        """
        import os
        import sys
        import subprocess
        from pathlib import Path
        from shlex import split as shlex_split
        from PyQt6.QtCore import QProcess
        
        path = self.d.get("path", "")
        if not path:
            warn("[LauncherItem] path が設定されていません")
            return

        # --- フォルダなら explorer で開く ---
        if os.path.isdir(path):
            try:
                os.startfile(path)
            except Exception as e:
                warn(f"[LauncherItem] フォルダオープン失敗: {e}")
            return

        ext = Path(path).suffix.lower()
        
        # --- URL ならブラウザで開く（例: https://example.com/ など） ---
        if isinstance(path, str) and path.lower().startswith(("http://", "https://")):
            try:
                os.startfile(path)  # Windows なら既定のブラウザで開く
            except Exception as e:
                warn(f"[LauncherItem.on_activate] URLオープン失敗: {e}")
            return
            
        # --- 作業ディレクトリの初期化 ---
        workdir = (self.d.get("workdir") or "").strip()
        if not workdir:
            workdir = str(Path(path).parent)
        workdir = os.path.abspath(workdir)

        # CWD を workdir にスワップ（os.startfile 用）
        orig_cwd = os.getcwd()
        cwd_changed = False
        if workdir and os.path.isdir(workdir):
            try:
                os.chdir(workdir)
                cwd_changed = True
            except Exception as e:
                warn(f"[LauncherItem] chdir failed: {e}")

        try:
            is_edit = self.d.get("is_editable", False)

            # --- Pythonスクリプト ---
            if ext == ".py" and not is_edit:
                try:
                    py_exec = sys.executable
                    ok = QProcess.startDetached(py_exec, [path], workdir)
                    if not ok:
                        warn(f"QProcess 起動失敗: {py_exec} {path}")
                    return
                except Exception as e:
                    warn(f"[LauncherItem.on_activate] .py 起動エラー: {e}")
                    return

            # --- Node.js スクリプト ---
            if ext == ".js" and not is_edit:
                try:
                    ok = QProcess.startDetached("node", [path], workdir)
                    if not ok:
                        warn(f"QProcess 起動失敗: node {path}")
                    return
                except Exception as e:
                    warn(f"[LauncherItem.on_activate] .js 起動エラー: {e}")
                    return
                    
            # --- .vbs スクリプト ---
            if ext in (".vbs", ".wsf"):
                try:
                    ok = QProcess.startDetached("wscript", [path], workdir)
                    if not ok:
                        warn(f"QProcess 起動失敗: wscript {path}")
                    return
                except Exception as e:
                    warn(f"[LauncherItem.on_activate] .vbs 起動エラー: {e}")
                return
                
            # --- 実行ファイル系 (.exe, .com, .jar, .msi) ---
            if ext in self.EXE_LIKE:
                try:
                    def quote_if_needed(path: str) -> str:
                        path = path.strip()
                        return f'"{path}"' if " " in path and not (path.startswith('"') and path.endswith('"')) else path

                    args = shlex_split(quote_if_needed(path), posix=False)
                    if not args:
                        warn(f"引数分解に失敗: {path}")
                        return

                    exe = args[0]
                    exe_args = [a[1:-1] if a.startswith('"') and a.endswith('"') else a for a in args[1:]]

                    if self.d.get("runas", False):
                        exe = os.path.abspath(exe)
                        quoted_args = " ".join(f'"{a}"' for a in exe_args)
                        full_cmd = f'cd /d "{workdir}" && "{exe}" {quoted_args}'
                        ps_script = f'Start-Process cmd.exe -ArgumentList \'/c {full_cmd}\' -Verb RunAs'
                        ps_cmd = ["powershell", "-NoProfile", "-Command", ps_script]
                        subprocess.run(ps_cmd, shell=False)
                    else:
                        ok = QProcess.startDetached(exe, exe_args, workdir)
                        if not ok:
                            warn(f"QProcess 起動失敗: {exe} {exe_args}")
                except Exception as e:
                    warn(f"[LauncherItem.on_activate] 起動エラー: {e}")
                return

            # --- その他（is_editableなファイル等） ---
            try:
                os.startfile(path)
            except Exception as e:
                warn(f"[LauncherItem.on_activate] startfile 失敗: {e}")
        finally:
            # ここで必ず元の CWD へ戻す（プロジェクト保存に影響させない）
            if cwd_changed:
                os.chdir(orig_cwd)
    
    def __del__(self):
        """デストラクタでGIFリソースをクリーンアップ"""
        try:
            self._stop_movie()
        except Exception:
            pass  # デストラクタでは例外を抑制
        try:
            super().__del__()
        except Exception:
            pass  # 多重継承時の安全性確保


# --------------------------------------------------
#  改良された GifItem (GifMixin + CanvasItem)
# --------------------------------------------------
class GifItem(GifMixin, CanvasItem):
    TYPE_NAME = "gif"

    @classmethod
    def supports_path(cls, path: str) -> bool:
        return path.lower().endswith(".gif")

    @classmethod
    def create_from_path(cls, path, sp, win):
        d = {
            "type": cls.TYPE_NAME,
            "caption": Path(path).stem,
            "path": path,
            "x": sp.x(),
            "y": sp.y(),
            "width": 200,
            "height": 200,
            "brightness": 50,
        }
        item = cls(d)
        return item, d

    def __init__(self, d):
        super().__init__(d)
        self.path = d.get("path")
        self.brightness = int(d.get("brightness", 50))
        
        # ピクスマップアイテム
        self._pix_item = QGraphicsPixmapItem(parent=self)
        
        # GIF読み込みと開始
        tgt_w = d.get("width", 200)
        tgt_h = d.get("height", 200)
        
        if self.path and Path(self.path).exists():
            if not self.load_gif(path=self.path):  # スケーリングパラメータを削除
                warn(f"Failed to load GIF: {self.path}")
        
        self.resize_to(tgt_w, tgt_h)

    def resize_to(self, w, h):
        """サイズ変更"""
        self.d["width"] = w
        self.d["height"] = h
        
        if self._movie:
            # GIFの場合は手動でリサイズ（QMovieのスケーリングは使用しない）
            self._on_movie_frame()
        else:
            # 静止画の場合はキャプション位置を手動更新
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPos(0, h)
            
        self._update_grip_pos()
        self.init_caption()

    def resize_content(self, w: int, h: int):
        """CanvasItemからのリサイズ処理"""
        self.resize_to(w, h)

    def _apply_brightness_to_pixmap(self, pix: QPixmap) -> QPixmap:
        """明るさ補正を適用（GifMixinから呼び出される）"""
        if self.brightness == 50 or pix.isNull():
            return pix
            
        level = self.brightness - 50
        alpha = int(abs(level) / 50 * 255)
        
        overlay = QPixmap(pix.size())
        overlay.fill(Qt.GlobalColor.transparent)
        painter = QPainter(overlay)
        col = QColor(255, 255, 255, alpha) if level > 0 else QColor(0, 0, 0, alpha)
        painter.fillRect(overlay.rect(), col)
        painter.end()
        
        result = QPixmap(pix.size())
        result.fill(Qt.GlobalColor.transparent)
        p2 = QPainter(result)
        p2.drawPixmap(0, 0, pix)
        p2.drawPixmap(0, 0, overlay)
        p2.end()
        return result

    def mousePressEvent(self, ev):
        """クリックでGIFのトグル再生"""
        if ev.button() == Qt.MouseButton.LeftButton:
            self.toggle_gif_playback()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def on_activate(self):
        """ダブルクリックでファイルを開く"""
        try:
            import os
            if self.path:
                os.startfile(self.path)
        except Exception as e:
            warn(f"Failed to open file: {e}")

    def on_edit(self):
        """編集ダイアログを開く"""
        from DPyL_classes import ImageEditDialog
        dlg = ImageEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.caption = self.d.get("caption", "")
            self.brightness = int(self.d.get("brightness", 50))
            
            # パスが変更された場合、GIFを再読み込み
            new_path = self.d.get("path", "")
            if new_path and new_path != self.path:
                self.path = new_path
                tgt_w = int(self.d.get("width", 200))
                tgt_h = int(self.d.get("height", 200))
                self.load_gif(path=self.path)  # スケーリングパラメータを削除
                
            self.init_caption()
            
        # モード切替
        win = self.scene().views()[0].window()
        self.set_run_mode(not win.a_edit.isChecked())

    def __del__(self):
        """デストラクタでGIFリソースをクリーンアップ"""
        try:
            self._stop_movie()
        except Exception:
            pass  # デストラクタでは例外を抑制
        try:
            super().__del__()
        except Exception:
            pass  # 多重継承時の安全性確保
# ==================================================================
#  ImageItem
# ==================================================================

class ImageItem(CanvasItem):
    TYPE_NAME = "image"
    @classmethod
    def supports_path(cls, path: str) -> bool:
        return Path(path).suffix.lower() in IMAGE_EXTS

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        d = {
            "type": "image",
            "path": path,
            "store": "reference",
            "brightness": 50,
            "x": sp.x(), "y": sp.y(),
            "width": 200, "height": 200
        }
        return cls(d, win.text_color), d

    def __init__(
        self,
        d: dict[str, Any] | None = None,
        cb_resize: Callable[[int,int],None] | None = None,
        text_color: QColor | None = None
    ):
        super().__init__(d, cb_resize, text_color)
        self.brightness = self.d.get("brightness", 50)
        self.path = self.d.get("path", "")
        self.embed = self.d.get("embed")
        self._pix_item = QGraphicsPixmapItem(parent=self)
        self._apply_pixmap()
        self._orig_pixmap = self._src_pixmap
        self._update_grip_pos()

    def resize_content(self, w: int, h: int):
        src = getattr(self, "_src_pixmap", None)
        if not src or src.isNull():
            return
        scaled = src.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        cx = max(0, (scaled.width()  - w) // 2)
        cy = max(0, (scaled.height() - h) // 2)
        pm = scaled.copy(cx, cy, w, h)
        self._pix_item.setPixmap(pm)

    def on_edit(self):
        """
        編集ダイアログでキャプション／パス／明るさを編集後、
        新しい GIF を再ロードして表示を更新するっす！
        """
        # ダイアログ実行前のソースを記憶
        old_path  = getattr(self, "path", "")
        old_embed = getattr(self, "embed", None)

        dlg = ImageEditDialog(self)                     # 既存ダイアログを再利用
        if dlg.exec() == QDialog.DialogCode.Accepted:

            # 1) メタ情報（caption / brightness）を反映
            self.caption         = self.d.get("caption", "")
            self.brightness      = int(self.d.get("brightness", 50))
            self._apply_caption()                       # ← 既存ヘルパー
            #   ※ ここではまだフレーム再描画しない

            # 2) パス／Embed 更新チェック
            new_path  = self.d.get("path", "")
            new_embed = self.d.get("embed", None)       # store == "embed" のときのみ存在

            # 変更があれば QMovie を作り直す
            if (new_path != old_path) or (new_embed != old_embed):
                self.path  = new_path
                self.embed = new_embed

                if self.embed:                          # embed 優先
                    raw = base64.b64decode(self.embed)
                    self._setup_movie(raw=raw)          # ← mixin API
                else:
                    self._setup_movie(path=self.path)

            # 3) 再描画 & 明るさ補正
            self._update_frame_display()                # 現在フレームを再描画
            self._apply_brightness()                    # 明るさだけ単独変更もある

        # 4) 編集モード判定をメインウィンドウと同期
        win = self.scene().views()[0].window()
        self.set_run_mode(not win.a_edit.isChecked())

        
    def on_activate(self):
        try:
            if self.path:
                os.startfile(self.path)
        except Exception:
            warn("Exception at on_activate")
            pass

    # ImageItem _apply_pixmap
    def _apply_pixmap(self):
        pix = QPixmap()
        if self.embed:
            pix.loadFromData(b64decode(self.embed))
        elif self.path:
            pix = QPixmap(self.path)

        if pix.isNull():
            pix = _icon_pixmap(getattr(self, "path", "") or "", 0, ICON_SIZE)

        self._src_pixmap = pix.copy()
        tgt_w = int(self.d.get("width", pix.width()))
        tgt_h = int(self.d.get("height", pix.height()))
        scaled = self._src_pixmap.scaled(
            tgt_w, tgt_h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        crop_x = max(0, (scaled.width()  - tgt_w) // 2)
        crop_y = max(0, (scaled.height() - tgt_h) // 2)
        pix = scaled.copy(crop_x, crop_y, tgt_w, tgt_h)

        bri = getattr(self, "brightness", None)
        if bri is not None and bri != 50:
            level = bri - 50
            alpha = int(abs(level) / 50 * 255)
            overlay = QPixmap(pix.size())
            overlay.fill(Qt.GlobalColor.transparent)
            painter = QPainter(overlay)
            col = QColor(255,255,255,alpha) if level>0 else QColor(0,0,0,alpha)
            painter.fillRect(overlay.rect(), col)
            painter.end()
            result = QPixmap(pix.size())
            result.fill(Qt.GlobalColor.transparent)
            p2 = QPainter(result)
            p2.drawPixmap(0,0,pix)
            p2.drawPixmap(0,0,overlay)
            p2.end()
            pix = result

        self._pix_item.setPixmap(pix)
        self._rect_item.setRect(0, 0, pix.width(), pix.height())
        self._orig_pixmap = self._src_pixmap

        cap = self.d.get("caption", "")
        caption_h = 0
        if cap:
            self.init_caption()
            caption_h = self.cap_item.boundingRect().height()
        else:
            if my_has_attr(self, "cap_item"):
                self.cap_item.setPlainText("")
                self.cap_item.setPos(0, 0)

        self._rect_item.setRect(0, 0, pix.width(), pix.height() + caption_h)
        if cap:
            self.init_caption()

        self.prepareGeometryChange()
        self.update()

# ==================================================================
#  JSONItem
# ==================================================================
class JSONItem(LauncherItem):
    TYPE_NAME = "json"

    @classmethod
    def supports_path(cls, path: str) -> bool:
        # .json 拡張子のみ担当
        return Path(path).suffix.lower() == ".json"

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        """
        LauncherItem.create_from_path を呼び出し、
        戻り値の辞書 d['type'] を 'json' に書き換えて返す。
        """
        # 親クラスでアイテム生成
        item, d = super().create_from_path(path, sp, win)
        if item is None:
            return None, None

        # JSONItem 固有の TYPE_NAME を反映
        d["type"] = cls.TYPE_NAME
        item.TYPE_NAME = cls.TYPE_NAME
        return item, d

    def __init__(self, d, cb_resize=None, text_color=None):
        # LauncherItem の __init__ に処理を委譲
        super().__init__(d, cb_resize, text_color)


    def _is_launcher_project(self) -> bool:
        """
        JSONファイルが desktopPyLauncher のプロジェクトファイルかを判定する
        """
        try:
            if not self.path or not os.path.exists(self.path):
                return False
            with open(self.path, encoding="utf-8") as f:
                j = json.load(f)
            fi = j.get("fileinfo", {})

            # --- 文字列→数値タプルへ変換して厳密比較 ---
            def _v(s: str) -> tuple[int, ...]:
                return tuple(int(p) for p in s.split(".") if p.isdigit())

            return (
                fi.get("name") == "desktopPyLauncher.py" and
                _v(fi.get("version", "0")) >= (1, 0)
            )
        except Exception as e:
            warn(f"[JSONItem] _is_launcher_project failed: {e}")
            return False
    # --------------------------------------------------------------
    # ダブルクリック時動作
    # --------------------------------------------------------------
    def on_activate(self):
        win = self.scene().views()[0].window()
        p = Path(self.path)
        if self._is_launcher_project():
            win._load_json(p)
            return
        try:
            os.startfile(str(p))
        except Exception:
            warn("Exception at on_activate")
            pass


    def on_edit(self):
        # 編集ダイアログ起動・編集結果反映
        win = self.scene().views()[0].window()
        dlg = LauncherEditDialog(self.d, win)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.embed = self.d.get("icon_embed")
            self._refresh_icon()
            if my_has_attr(self, "cap_item"):
                self.cap_item.setPlainText(self.d.get("caption", ""))
        self.set_run_mode(not win.a_edit.isChecked())

# ==================================================================        
#  GenericFileItem
# ==================================================================
class GenericFileItem(LauncherItem):
    """
    既存クラスが supports_path() で蹴った “その他ファイル” 用。
    * .txt .vbs .csv .md … 何でもドロップ可能
    * LauncherItem の機能（ダブルクリックで関連付けアプリ起動など）そのまま利用
    """
    TYPE_NAME = "file"

    # ① 常に True だが “最後に登録” されるので優先度は最下位
    @classmethod
    def supports_path(cls, path: str) -> bool:
        p = Path(path)
        return p.exists()

    # ② ファクトリ
    @classmethod
    def create_from_path(cls, path: str, sp, win):
        p = Path(path)
        d = {
            "type": "launcher",
            "caption": p.name,
            "path": path,
            "workdir": path if p.is_dir() else "",
            "icon": path,
            "icon_index": 0,
            "x": sp.x(), "y": sp.y()
        }
        return cls(d, win.text_color), d

        
# ==================================================================
#  CanvasResizeGrip（リサイズグリップ）
# ==================================================================
class CanvasResizeGrip(QGraphicsRectItem):
    def __init__(self):
        super().__init__()
        self.setRect(0, 0, 10, 10)
        self.setBrush(QBrush(QColor("#ccc")))
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setZValue(9999)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self._drag = False
        self._start = QPointF()
        self._orig  = QRectF()
        self.setEnabled(True)

    def mousePressEvent(self, ev):
        # リサイズ開始

        self._drag  = True
        self._start = ev.scenePos()
        self._orig  = self._parent._rect_item.rect()
        self._was_movable = bool(
            self._parent.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        if self._was_movable:
            self._parent.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self._drag:
            return
        delta = ev.scenePos() - self._start
        w = max(32, self._orig.width()  + delta.x())
        h = max(24, self._orig.height() + delta.y())
        # ==========================
        # ★スナップ呼び出し追加
        # ==========================
        parent = getattr(self, "_parent", None) or getattr(self, "target", None)
        if parent and my_has_attr(parent, "snap_resize_size"):
            w, h = parent.snap_resize_size(w, h)

        parent.prepareGeometryChange()
        parent._rect_item.setRect(0, 0, w, h)
        parent.d["width"], parent.d["height"] = int(w), int(h)
        if my_has_attr(parent, "resize_content"):
            parent.resize_content(int(w), int(h))
        if my_has_attr(parent, "_update_grip_pos"):
            parent._update_grip_pos()
        parent.init_caption()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        # リサイズ終了
        self._drag = False
        if getattr(self, "_was_movable", False):
            self._parent.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        ev.accept()

    def resize_content(self, w: int, h: int):
        # 汎用：画像・テキスト拡大（未使用時もあり）
        if my_has_attr(self, "_pix_item") and my_has_attr(self, "_orig_pixmap"):
            pm = self._orig_pixmap.scaled(w, h,
                  Qt.AspectRatioMode.KeepAspectRatio,
                  Qt.TransformationMode.SmoothTransformation)
            self._pix_item.setPixmap(pm)
        elif my_has_attr(self, "_txt_item"):
            self._txt_item.document().setTextWidth(w)
    def update_zvalue(self):
        """
        親アイテムより常に 1 上に配置して
        「最前面／最背面」操作に追従させる。
        """
        if my_has_attr(self, "_parent") and self._parent:
            self.setZValue(self._parent.zValue() + 1)
# ==================================================================
#  dialogs（各種ダイアログ）
# ==================================================================
class ImageEditDialog(QDialog):
    def __init__(self, item: ImageItem):
        super().__init__()
        self.setWindowTitle("Image Settings")
        self.item = item
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)

        # caption入力
        h0 = QHBoxLayout()
        self.ed_caption = QLineEdit(self.item.d.get("caption", ""))
        h0.addWidget(QLabel("Caption:"))
        h0.addWidget(self.ed_caption)
        v.addLayout(h0)

        # Path設定
        h1 = QHBoxLayout()
        self.ed_path = QLineEdit(self.item.path)
        btn_b = QPushButton("Browse…"); btn_b.clicked.connect(self._browse)
        h1.addWidget(QLabel("Path:")); h1.addWidget(self.ed_path, 1); h1.addWidget(btn_b)
        v.addLayout(h1)

        # Embed/参照切替（プルダウン）
        h2 = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["参照", "Embed"])
        mode = "Embed" if self.item.d.get("store") == "embed" else "参照"
        self.combo_mode.setCurrentText(mode)
        h2.addWidget(QLabel("保存方法:"))
        h2.addWidget(self.combo_mode)
        v.addLayout(h2)

        # Brightness設定
        h3 = QHBoxLayout()
        self.spin_bri = QSpinBox(); self.spin_bri.setRange(0, 100)
        self.spin_bri.setValue(self.item.brightness if my_has_attr(self.item, "brightness") else 50)        
        h3.addWidget(QLabel("Brightness:")); h3.addWidget(self.spin_bri)
        v.addLayout(h3)

        # ボタン
        h4 = QHBoxLayout(); h4.addStretch(1)
        ok = QPushButton("OK"); ok.clicked.connect(self.accept)
        ng = QPushButton("Cancel"); ng.clicked.connect(self.reject)
        h4.addWidget(ok); h4.addWidget(ng); v.addLayout(h4)
        self.resize(460, 180)

    def _browse(self):
        """
        Browse ダイアログの拡張子フィルタを
        GifItem vs ImageItem で切り替えっす。
        """
        # フィルタ設定
        if isinstance(self.item, GifItem):
            file_filter = "GIF files (*.gif)"
        elif isinstance(self.item, ImageItem):
            file_filter = "Images (*.png *.jpg *.jpeg *.bmp)"
        else:
            file_filter = "All Files (*)"

        # ファイル選択
        f, _ = QFileDialog.getOpenFileName(self, "Select Image", "", file_filter)
        if f:
            self.ed_path.setText(f)
            
    # ImageEditDialog accept
    def accept(self):
        cap = self.ed_caption.text()
        self.item.d["caption"] = cap

        self.item.brightness = self.spin_bri.value()
        self.item.d["brightness"] = self.item.brightness

        mode = self.combo_mode.currentText()
        self.item.d["store"] = "embed" if mode == "Embed" else "reference"

        path = self.ed_path.text().strip()
        self.item.d["path"] = path
        self.item.path = path

        if self.item.d["store"] == "embed":
            if path:  # パスが空でなければ再取得
                try:
                    with open(path, "rb") as fp:
                        self.item.embed = base64.b64encode(fp.read()).decode("ascii")
                        self.item.d["embed"] = self.item.embed
                        self.item.d["path_last_embedded"] = path
                except Exception as e:
                    warn(f"embed failed: {e}")
                    self.item.embed = None
                    self.item.d.pop("embed", None)
            # パスが空ならembedは変更しない（何もしない）
        else:
            self.item.embed = None
            self.item.d.pop("embed", None)
            self.item.d.pop("path_last_embedded", None)

        super().accept()
        
class BackgroundDialog(QDialog):
    def __init__(self, mode="clear", value=""):
        super().__init__()
        self.setWindowTitle("Background")
        self.mode, self.value = mode, value
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        # 色/画像/クリア
        btn_c = QPushButton("Color…");  btn_c.clicked.connect(self._pick_color)
        btn_i = QPushButton("Image…");  btn_i.clicked.connect(self._pick_image)
        btn_n = QPushButton("Clear");   btn_n.clicked.connect(self._pick_clear)
        v.addWidget(btn_c); v.addWidget(btn_i); v.addWidget(btn_n)
        # 背景ダイアログUI構築部
        self.spin_bri = QSpinBox()
        self.spin_bri.setRange(0, 100)
        self.spin_bri.setValue(50)  # 初期値（あとでsetで更新）
        v.addWidget(QLabel("Brightness"))
        v.addWidget(self.spin_bri)
        # OK/Cancel
        h = QHBoxLayout(); h.addStretch(1)
        ok = QPushButton("OK"); ok.clicked.connect(self.accept)
        ng = QPushButton("Cancel"); ng.clicked.connect(self.reject)
        h.addWidget(ok); h.addWidget(ng); v.addLayout(h)

    def _pick_color(self):
        # 色選択ダイアログ
        col = QColorDialog.getColor(QColor(self.value) if self.value else QColor("#ffffff"),
                                    self, "Color")
        if col.isValid():
            self.mode, self.value = "color", col.name()

    def _pick_image(self):
        # 画像選択ダイアログ
        f, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.gif *.jpg *.jpeg *.bmp)")
        if f: self.mode, self.value = "image", f

    def _pick_clear(self): self.mode, self.value = "clear", ""

    @staticmethod
    def get(mode="clear", value="", brightness=50):
        dlg = BackgroundDialog(mode, value)
        dlg.spin_bri.setValue(brightness)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return ok, dlg.mode, dlg.value, dlg.spin_bri.value()

# ==================================================================
#  LauncherEditDialog
# ==================================================================
_PREV_SIZE = ICON_SIZE * 2
class LauncherEditDialog(QDialog):
    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.setWindowTitle("Launcher 編集")
        layout = QVBoxLayout(self)

        # -- Caption --
        h = QHBoxLayout()
        h.addWidget(QLabel("Caption"))
        self.le_caption = QLineEdit(data.get("caption", ""))
        h.addWidget(self.le_caption)
        layout.addLayout(h)

        # -- Path / URL --
        h = QHBoxLayout()
        h.addWidget(QLabel("Path/URL"))
        self.le_path = QLineEdit(data.get("path", ""))
        btn_p = QPushButton("Browse…")
        btn_p.clicked.connect(self._browse_path)
        h.addWidget(self.le_path, 1)
        h.addWidget(btn_p)
        layout.addLayout(h)

        # -- WorkDir（復活済み） --
        h = QHBoxLayout()
        h.addWidget(QLabel("WorkDir"))
        self.le_workdir = QLineEdit(data.get("workdir", ""))
        btn_wd = QPushButton("Browse…")
        btn_wd.clicked.connect(self._browse_workdir)
        h.addWidget(self.le_workdir, 1)
        h.addWidget(btn_wd)
        layout.addLayout(h)

        # -- Icon Type --
        h = QHBoxLayout()
        h.addWidget(QLabel("Icon Type"))
        self.combo_icon_type = QComboBox()
        self.combo_icon_type.addItems(["Default", "Embed"])
        self.combo_icon_type.setCurrentIndex(0 if not data.get("icon_embed") else 1)
        self.combo_icon_type.currentIndexChanged.connect(self._update_preview)
        h.addWidget(self.combo_icon_type)
        layout.addLayout(h)

        # -- Icon File + Default --
        h = QHBoxLayout()
        h.addWidget(QLabel("Icon File"))
        self.le_icon = QLineEdit(data.get("icon", ""))
        self.le_icon.textChanged.connect(self._update_preview)
        btn_if = QPushButton("Browse…")
        btn_if.clicked.connect(self._browse_icon)
        btn_def = QPushButton("Default")
        btn_paste = QPushButton("Paste"); btn_paste.clicked.connect(self._paste_icon)
        btn_def.clicked.connect(self._use_default_icon)
        h.addWidget(self.le_icon, 1)
        h.addWidget(btn_if)
        h.addWidget(btn_def)
        h.addWidget(btn_paste)
        layout.addLayout(h)

        # -- Icon Index --
        h = QHBoxLayout()
        h.addWidget(QLabel("Icon Index"))
        self.spin_index = QSpinBox()
        self.spin_index.setRange(0, 300)
        self.spin_index.setValue(data.get("icon_index", 0))
        self.spin_index.valueChanged.connect(self._on_icon_index_changed)
        self.spin_index.valueChanged.connect(self._update_preview)
        h.addWidget(self.spin_index)
        layout.addLayout(h)

        # -- Preview --
        h = QHBoxLayout()
        h.addWidget(QLabel("Preview"))
        self.lbl_prev = QLabel()
        self.lbl_prev.setFixedSize(_PREV_SIZE, _PREV_SIZE)
        self.lbl_prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prev.setStyleSheet("border:1px solid #888;")  # 視認しやすく
        h.addWidget(self.lbl_prev, 1)
        layout.addLayout(h)

        # -- Run as Admin --
        self.chk_runas = QCheckBox("管理者として実行（runas）")
        self.chk_runas.setChecked(data.get("runas", False))
        layout.addWidget(self.chk_runas)

        # -- Executable flag --
        self.chk_exe = QCheckBox("編集で開く")
        self.chk_exe.setChecked(data.get("is_editable", False))
        layout.addWidget(self.chk_exe)

        # -- OK / Cancel --
        h = QHBoxLayout(); h.addStretch(1)
        ok = QPushButton("OK"); ok.clicked.connect(self.accept)
        ng = QPushButton("Cancel"); ng.clicked.connect(self.reject)
        h.addWidget(ok); h.addWidget(ng)
        layout.addLayout(h)

        # 初期プレビュー
        self._update_preview()
        #QTimer.singleShot(0, self._update_preview)

    # ---------------- browse helpers ----------------
    def _browse_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select File or URL", "", "All Files (*)")
        if p: self.le_path.setText(p)

    def _browse_workdir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Working Directory", "")
        if d: self.le_workdir.setText(d)

    def _browse_icon(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Icon File",
            "", "Images (*.ico *.png *.gif *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if f: 
            self.le_icon.setText(f)
            self._update_preview()

    def _use_default_icon(self):
        """
        Default ボタン：
        * icon/icon_embed を一旦クリア
        * https://～ の Path/URL が設定されている場合は favicon を取得して Embed 化
        * それ以外は IconType=Default のまま
        * いずれもプレビューを即更新
        """
        self.le_icon.clear()
        self.data.pop("icon", None)
        self.data.pop("icon_embed", None)

        path = self.le_path.text().strip().lower()
        if path.startswith("http://") or path.startswith("https://"):
            fav = fetch_favicon_base64(path) or None
            if fav:
                self.data["icon_embed"] = fav
                self.combo_icon_type.setCurrentText("Embed")
            else:
                self.combo_icon_type.setCurrentText("Default")
        else:
            self.combo_icon_type.setCurrentText("Default")

        self._update_preview()

    # ---------------- auto-insert & preview ----------------
    def _on_icon_index_changed(self, _):
        if (not self.le_icon.text().strip()
                and self.combo_icon_type.currentText() == "Default"):
            sysroot = os.environ.get("SystemRoot", r"C:\Windows")
            dll = os.path.join(sysroot, "System32", "imageres.dll")
            if os.path.exists(dll):
                self.le_icon.setText(dll)

    def _update_preview(self):
        """IconPath / Index / Type 変更時のリアルタイムプレビュー"""
        icon_type = self.combo_icon_type.currentText()
        path_txt  = self.le_icon.text().strip() 

        # --- Embed (base64) ---
        if icon_type == "Embed" and not path_txt and self.data.get("icon_embed"):
            pm = QPixmap()
            pm.loadFromData(b64decode(self.data["icon_embed"]))

        # --- Default / Embed(まだ未保存) ---
        else:
            path = (path_txt
                    or self.data.get("icon")
                    or self.le_path.text().strip()
                    or "")
            idx = self.spin_index.value()

            # 画像ファイルならダイレクトに読む！
            if path and Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                pm = QPixmap(path)
            else:
                pm = _icon_pixmap(path, idx, _PREV_SIZE)

        # ---- 共通スケール & セット ----
        if not pm.isNull():
            pm = pm.scaled(
                _PREV_SIZE, _PREV_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.lbl_prev.setPixmap(pm)


    # LauncherEditDialog accept
    def accept(self):
        # -------- 基本フィールド --------
        self.data["caption"] = self.le_caption.text()
        self.data["path"]    = self.le_path.text()
        self.data["workdir"] = self.le_workdir.text()
        self.data["icon_index"] = self.spin_index.value()
        self.data["runas"] = self.chk_runas.isChecked()
        self.data["is_editable"] = self.chk_exe.isChecked()

        icon_type = self.combo_icon_type.currentText()
        icon_path = self.le_icon.text().strip()

        if icon_type == "Default":
            # --- Default モード ---
            self.data.pop("icon_embed", None)
            if icon_path:
                self.data["icon"] = icon_path
            else:
                self.data.pop("icon", None)

        else:  # ---------- Embed モード ----------
            # 参照パスは使わない
            self.data.pop("icon", None)

            # １）既存 embed を仮保持
            embed_b64 = self.data.get("icon_embed", "")

            # ２）ユーザーが Browse で新規指定した場合
            if icon_path:
                suffix = Path(icon_path).suffix.lower()
                if suffix == ".gif":
                    # GIF は生バイトをそのまま埋め込む
                    with open(icon_path, "rb") as fp:
                        raw = fp.read()
                    embed_b64 = base64.b64encode(raw).decode("ascii")
                else:
                    # 静止画は従来どおり PNG 変換
                    pm = QPixmap(icon_path)
                    if not pm.isNull():
                        buf = QBuffer()
                        buf.open(QIODevice.OpenModeFlag.WriteOnly)
                        if pm.save(buf, "PNG"):
                            embed_b64 = base64.b64encode(buf.data()).decode("ascii")

            # ３）まだ embed_b64 が空なら、プレビュー画像からキャプチャ
            if not embed_b64:
                pm = self.lbl_prev.pixmap()
                if pm and not pm.isNull():
                    buf = QBuffer()
                    buf.open(QIODevice.OpenModeFlag.WriteOnly)
                    pm.save(buf, "PNG")
                    embed_b64 = base64.b64encode(buf.data()).decode("ascii")

            # ４）最終決定：embed_b64 があればセット、なければ削除
            if embed_b64:
                self.data["icon_embed"] = embed_b64
            else:
                self.data.pop("icon_embed", None)

        super().accept()


    def SIMPLE_VER_paste_icon(self):
        """GIFのアニメーションを維持しつつ縦横比クロップで貼り付け"""
        cb = QApplication.clipboard()
        mime = cb.mimeData()

        current_w = int(self.data.get("width", ICON_SIZE))
        current_h = int(self.data.get("height", ICON_SIZE))

        if mime.hasUrls():
            for qurl in mime.urls():
                path = qurl.toLocalFile()
                if path.lower().endswith(".gif") and Path(path).exists():
                    with open(path, "rb") as f:
                        gif_data = f.read()

                    # 保存対象は元のGIF（アニメーション維持）
                    b64 = base64.b64encode(gif_data).decode("ascii")

                    # モデルに埋め込み
                    self.data["icon_embed"] = b64
                    self.combo_icon_type.setCurrentText("Embed")
                    self.le_icon.clear()
                    self.spin_index.setValue(0)

                    # 表示はクロップ＆縦横比維持で
                    self._update_preview()
                    return


        # 画像
        if mime.hasImage():
            img = cb.image()
            if img.isNull():
                return
            pix = QPixmap.fromImage(img)
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            pix.save(buf, "PNG")
            self.data["icon_embed"] = base64.b64encode(buf.data()).decode("ascii")
            self.combo_icon_type.setCurrentText("Embed")
            self.le_icon.clear()
            self._update_preview()
            return
            
            
    def _paste_icon(self):
        """クリップボードから画像 or GIFファイルを貼り付け（中央クロップ＋cover対応）"""
        cb = QApplication.clipboard()
        mime = cb.mimeData()

        # GIFファイルの場合
        if mime.hasUrls():
            for qurl in mime.urls():
                path = qurl.toLocalFile()
                if path.lower().endswith(".gif") and Path(path).exists():
                    with open(path, "rb") as f:
                        gif_data = f.read()

                    gif_bytes = QByteArray(gif_data)
                    gif_buffer = QBuffer(gif_bytes)
                    gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly)

                    movie = QMovie()
                    movie.setDevice(gif_buffer)
                    movie.start()
                    movie.jumpToFrame(0)
                    orig_pix = movie.currentPixmap()
                    movie.stop()

                    current_w = int(self.data.get("width", ICON_SIZE))
                    current_h = int(self.data.get("height", ICON_SIZE))

                    # 中央クロップ＋cover
                    scaled = orig_pix.scaled(
                        current_w, current_h,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    cx = max(0, (scaled.width() - current_w) // 2)
                    cy = max(0, (scaled.height() - current_h) // 2)
                    cropped = scaled.copy(cx, cy, current_w, current_h)

                    # 埋め込むのは元データだが、プレビューにはcover表示
                    buf = QBuffer()
                    buf.open(QIODevice.OpenModeFlag.WriteOnly)
                    cropped.save(buf, "PNG")
                    preview_b64 = base64.b64encode(buf.data()).decode("ascii")

                    self.data["icon_embed"] = base64.b64encode(gif_data).decode("ascii")
                    self.combo_icon_type.setCurrentText("Embed")
                    self.le_icon.clear()

                    # Previewを「coverクロップ版」に置き換え
                    self._preview_override_pixmap = QPixmap()
                    self._preview_override_pixmap.loadFromData(base64.b64decode(preview_b64))
                    self._update_preview()
                    self.data["width"], self.data["height"] = current_w, current_h

                    return

        # 静止画の場合
        if mime.hasImage():
            img = cb.image()
            if img.isNull():
                warn("Clipboardに有効な画像がありません")
                return

            pix = QPixmap.fromImage(img)
            current_w = int(self.data.get("width", ICON_SIZE))
            current_h = int(self.data.get("height", ICON_SIZE))

            scaled = pix.scaled(
                current_w, current_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            cx = max(0, (scaled.width() - current_w) // 2)
            cy = max(0, (scaled.height() - current_h) // 2)
            cropped = scaled.copy(cx, cy, current_w, current_h)

            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            cropped.save(buf, "PNG")
            b64 = base64.b64encode(buf.data()).decode("ascii")

            self.data["icon_embed"] = b64
            self.combo_icon_type.setCurrentText("Embed")
            self.le_icon.clear()

            # Previewもクロップ版
            self._preview_override_pixmap = QPixmap()
            self._preview_override_pixmap.loadFromData(buf.data())
            self._update_preview()
            return

        warn("Clipboardに画像またはGIFファイルが見つかりません")

# -------------------------------------------------- __all__ export --------------------------------------------------
__all__ = [
    "CanvasItem", "LauncherItem", "ImageItem", "JSONItem", 
    "CanvasResizeGrip",
    "ImageEditDialog", "BackgroundDialog","LauncherEditDialog"
]
