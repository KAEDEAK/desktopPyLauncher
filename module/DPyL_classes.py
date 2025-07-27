# -*- coding: utf-8 -*-
"""
DPyL_classes.py  ―  desktopPyLauncher GUIアイテム/共通ダイアログ
◎ Qt6 / PySide6 専用
"""
from __future__ import annotations
import os,sys,json,base64

# 親ディレクトリからlocalizationをインポート
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from localization import _
from pathlib import Path
from typing import Callable, Any
from base64 import b64decode            
from shlex import split as shlex_split
from win32com.client import Dispatch
import subprocess

from PySide6.QtCore import (
    Qt, QPointF, QRectF, QSizeF, QTimer, QSize, QFileInfo, QBuffer, QByteArray, QIODevice, QProcess, QCoreApplication
)
from PySide6.QtGui import (
    QPixmap, QPainter, QPalette, QColor, QBrush, QPen, QIcon, QMovie
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsItemGroup, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsSceneMouseEvent, QGraphicsItem,QGraphicsTextItem,
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QSpinBox, QLineEdit, QColorDialog, QComboBox, QCheckBox,
    QGraphicsProxyWidget, QGraphicsColorizeEffect
)

# ---------------------------------------------------------------------------------------------------- internal util -------------------------------------------------
from .DPyL_utils import (
    warn, b64e, ICON_SIZE, IMAGE_EXTS,
    _icon_pixmap, compose_url_icon, _load_pix_or_icon,
    normalize_unc_path,
    fetch_favicon_base64,
    detect_image_format,
)

from .DPyL_debug import my_has_attr,dump_missing_attrs,trace_this

log_cnt=0
def movie_debug_print(msg: str) -> None:
    global log_cnt
    log_cnt+=1
    print(f"[MOVIE_DEBUG] {log_cnt} {msg}", file=sys.stderr)
def movie_debug_print(msg: str) -> None:
    pass
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
        
    r"""
    def hoverEnterEvent(self, event):
        super().hoverEnterEvent(event)
        main_window = self.scene().views()[0].window()
        if hasattr(main_window, 'effect_manager'):
            main_window.effect_manager.enable_hover_effects(self)

    def hoverLeaveEvent(self, event):
        super().hoverLeaveEvent(event)
        main_window = self.scene().views()[0].window()
        if hasattr(main_window, 'effect_manager'):
            main_window.effect_manager.disable_hover_effects(self)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        main_window = self.scene().views()[0].window()
        if hasattr(main_window, 'effect_manager'):
            main_window.effect_manager.trigger_click_effect(self)
    """    

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

    def _scale_pixmap_with_quality_base_CUSTOM(self, pixmap: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        プラットフォーム非依存の高品質ピクスマップスケーリング
        Windowsでも確実に動作する独自の高品質アルゴリズム
        """
        if pixmap.isNull():
            return pixmap
            
        src_w, src_h = pixmap.width(), pixmap.height()
        
        # アスペクト比を保持して拡張するサイズを計算
        src_ratio = src_w / src_h
        tgt_ratio = target_w / target_h
        
        if src_ratio > tgt_ratio:
            scale_w = target_w
            scale_h = int(target_w / src_ratio)
        else:
            scale_h = target_h
            scale_w = int(target_h * src_ratio)
        
        # 縮小比率を計算
        scale_factor_x = scale_w / src_w
        scale_factor_y = scale_h / src_h
        
        # 縮小時は独自の高品質アルゴリズムを使用
        if scale_factor_x < 1.0 or scale_factor_y < 1.0:
            return self._custom_high_quality_downscale_CUSTOM(pixmap, scale_w, scale_h)
        else:
            # 拡大時は標準のスムーズスケーリング
            return pixmap.scaled(
                scale_w, scale_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
    
    def _custom_high_quality_downscale_CUSTOM(self, pixmap: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        実用的な高品質縮小アルゴリズム
        段階的縮小 + QPainter高品質レンダリングの組み合わせ
        """
        src_w, src_h = pixmap.width(), pixmap.height()
        current = pixmap
        
        # 段階的縮小（75%ずつ、より滑らか）
        curr_w, curr_h = src_w, src_h
        while curr_w > target_w * 1.5 or curr_h > target_h * 1.5:
            curr_w = max(target_w, int(curr_w * 0.75))
            curr_h = max(target_h, int(curr_h * 0.75))
            
            # QPainterを使った高品質レンダリング
            scaled_pixmap = QPixmap(curr_w, curr_h)
            scaled_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(scaled_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            
            # 高品質描画
            painter.drawPixmap(
                0, 0, curr_w, curr_h,
                current, 
                0, 0, current.width(), current.height()
            )
            painter.end()
            
            current = scaled_pixmap
        
        # 最終調整（目標サイズぴったりに）
        if current.width() != target_w or current.height() != target_h:
            final_pixmap = QPixmap(target_w, target_h)
            final_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            
            painter.drawPixmap(
                0, 0, target_w, target_h,
                current,
                0, 0, current.width(), current.height()
            )
            painter.end()
            
            current = final_pixmap
            
        return current

    def _scale_pixmap_with_quality_base(self, pixmap: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        Qt標準のスケーリング（現在有効）
        LODシステムと組み合わせてQt標準の品質をテスト
        
        カスタム版に切り替える場合:
        return self._scale_pixmap_with_quality_base_CUSTOM(pixmap, target_w, target_h)
        """
        if pixmap.isNull():
            return pixmap
            
        src_w, src_h = pixmap.width(), pixmap.height()
        
        # アスペクト比を保持して拡張するサイズを計算
        src_ratio = src_w / src_h
        tgt_ratio = target_w / target_h
        
        if src_ratio > tgt_ratio:
            scale_w = target_w
            scale_h = int(target_w / src_ratio)
        else:
            scale_h = target_h
            scale_w = int(target_h * src_ratio)
        
        # Qt標準のSmoothTransformationを使用
        return pixmap.scaled(
            scale_w, scale_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    # CanvasItem _apply_pixmap
    def _apply_pixmap(self) -> None:
        """
        ImageItem/JSONItem共通：ピクスマップ表示＋枠サイズ設定
        - 新フィールドから画像取得
        - d['width'],d['height']でスケーリング
        - 明るさ補正
        - 子の_pix_item/_rect_item更新
        """
        # 1) ピクスマップ取得
        pix = QPixmap()
        
        # 新フィールドから埋め込みデータを取得
        if self.d.get("image_embedded") and self.d.get("image_embedded_data"):
            try:
                pix.loadFromData(b64decode(self.d["image_embedded_data"]))
            except Exception as e:
                warn(f"[CanvasItem] Failed to load embed data: {e}")
                pix = None
        else:
            # パスから画像を取得
            icon_path = self.d.get("icon") or self.d.get("path", "")
            if icon_path:
                pix = QPixmap(icon_path)
                
        # 2) 代替アイコン
        if pix.isNull():
            path = self.d.get("path", "")
            idx = self.d.get("icon_index", 0)
            pix = _icon_pixmap(path, idx, ICON_SIZE)

        # オリジナルを保持
        self._src_pixmap = pix.copy()

        # 3) サイズ指定でスケーリング（cover）- 高品質スケーリング使用
        tgt_w = int(self.d.get("width", pix.width()))
        tgt_h = int(self.d.get("height", pix.height()))
        scaled = self._scale_pixmap_with_quality_base(self._src_pixmap, tgt_w, tgt_h)
        crop_x = max(0, (scaled.width() - tgt_w) // 2)
        crop_y = max(0, (scaled.height() - tgt_h) // 2)
        pix = scaled.copy(crop_x, crop_y, tgt_w, tgt_h)

        # 4) 明るさ補正（brightnessがある場合のみ）
        bri = self.d.get("brightness")
        if bri is not None and bri != 50:
            level = bri - 50
            alpha = int(abs(level) / 50 * 255)
            overlay = QPixmap(pix.size())
            overlay.fill(Qt.GlobalColor.transparent)
            painter = QPainter(overlay)
            col = QColor(255, 255, 255, alpha) if level > 0 else QColor(0, 0, 0, alpha)
            painter.fillRect(overlay.rect(), col)
            painter.end()
            
            result = QPixmap(pix.size())
            result.fill(Qt.GlobalColor.transparent)
            painter = QPainter(result)
            painter.drawPixmap(0, 0, pix)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver if level > 0
                else QPainter.CompositionMode.CompositionMode_Multiply
            )
            painter.drawPixmap(0, 0, overlay)
            painter.end()
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
            if hasattr(self, "cap_item") and self.cap_item:
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
        
        # 高品質スケーリング実行 - QImage経由でより美しく
        image = frame.toImage()
        if not image.isNull():
            scaled_image = image.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # 縮小時はQPainterで追加の品質向上
            if scaled_w < orig_w or scaled_h < orig_h:
                scaled = QPixmap(scaled_w, scaled_h)
                scaled.fill(Qt.GlobalColor.transparent)
                painter = QPainter(scaled)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                painter.drawImage(0, 0, scaled_image)
                painter.end()
            else:
                scaled = QPixmap.fromImage(scaled_image)
        else:
            # フォールバック
            scaled = frame.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
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
    EDITABLE_LIKE = (".txt", ".json", ".yaml", ".yml", ".md", ".bat", ".ini")
    SHORTCUT_LIKE = (".lnk", ".url")
    
    # ターミナルとLauncherItemの近接判定距離の定数
    PROXIMITY_DISTANCE = 1000.0  # 1000px範囲

    @classmethod
    def supports_path(cls, path: str) -> bool:
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
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
            cls.EDITABLE_LIKE
        )

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
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
            workdir = str(Path(path).parent)
            # Windows では forward slash を backslash に正規化
            if os.name == 'nt':
                workdir = os.path.normpath(workdir)
            d["workdir"] = workdir

        return cls(d, win.text_color), d

    def __init__(self, d: dict, cb_resize=None, text_color=None):
        super().__init__(d, cb_resize, text_color)
        
        # 基本属性
        self.icon = self.d.get("icon", "")
        self.workdir = self.d.get("workdir", "")
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
        self._pix_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        
        # LOD (Level of Detail) を有効にしてキャンバスズーム時の品質向上
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self._current_lod_scale = 1.0
        
        self._refresh_icon()
        
    @property
    def path(self):
        return self.d.get("path", "")

    def _refresh_icon(self):
        """アイコン画像を更新（GIF対応）- 新フィールド版"""
        try:
            self._stop_movie()
            
            # GIF処理を試行
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
        """GIFの読み込みを試行 - 詳細なエラーログ付き"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        
        # デバッグ情報を出力
        caption = self.d.get("caption", "<no caption>")
        item_type = self.d.get("type", "<no type>")
        
        # 新フィールドから埋め込みデータを取得
        if self.d.get("image_embedded") and self.d.get("image_embedded_data"):
            try:
                embed_data = self.d.get("image_embedded_data")
                
                # データ型をチェック
                if not isinstance(embed_data, str):
                    warn(f"[GIF] Invalid embed data type for '{caption}' (type={item_type}): "
                         f"expected str, got {type(embed_data).__name__} = {repr(embed_data)[:50]}")
                    return False
                    
                raw = base64.b64decode(embed_data)
                if self.load_gif(raw=raw):
                    self.d["width"], self.d["height"] = tgt_w, tgt_h
                    return True
                    
            except Exception as e:
                warn(f"[GIF] Embed load failed for '{caption}' (type={item_type}): {e}")
                warn(f"      embed_data type: {type(self.d.get('image_embedded_data')).__name__}")
                warn(f"      image_embedded: {self.d.get('image_embedded')}")
                warn(f"      image_format: {self.d.get('image_format', 'not set')}")
        
        # ファイルパスからGIF読み込み
        src_path = self.d.get("icon") or self.path
        if src_path and src_path.lower().endswith(".gif"):
            if self.load_gif(path=src_path):
                self.d["width"], self.d["height"] = tgt_w, tgt_h
                return True
            else:
                warn(f"[GIF] File load failed for '{caption}' (path={src_path})")
                
        return False

    def _load_static_image(self):
        """静止画の読み込み処理 - 詳細なエラーログ付き"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        
        caption = self.d.get("caption", "<no caption>")
        item_type = self.d.get("type", "<no type>")
        
        pix = None
        
        # 新フィールドから埋め込みデータを取得
        if self.d.get("image_embedded") and self.d.get("image_embedded_data"):
            pix = QPixmap()
            try:
                embed_data = self.d.get("image_embedded_data")
                
                # データ型をチェック
                if not isinstance(embed_data, str):
                    warn(f"[STATIC] Invalid embed data type for '{caption}' (type={item_type}): "
                         f"expected str, got {type(embed_data).__name__} = {repr(embed_data)[:50]}")
                    pix = None
                else:
                    pix.loadFromData(base64.b64decode(embed_data))
                    if pix.isNull():
                        warn(f"[STATIC] Pixmap load returned null for '{caption}'")
                        
            except Exception as e:
                warn(f"[STATIC] Embed load failed for '{caption}' (type={item_type}): {e}")
                warn(f"         embed_data type: {type(self.d.get('image_embedded_data')).__name__}")
                warn(f"         image_embedded: {self.d.get('image_embedded')}")
                warn(f"         image_format: {self.d.get('image_format', 'not set')}")
                pix = None
        
        # ファイルパスから読み込み
        if not pix or pix.isNull():
            src = self.d.get("icon") or self.path
            if src:
                idx = self.d.get("icon_index", 0)
                pix = _icon_pixmap(src, idx, max(tgt_w, tgt_h, ICON_SIZE))
                if pix.isNull():
                    warn(f"[STATIC] Failed to load from path for '{caption}': {src}")
            else:
                warn(f"[STATIC] No path available for '{caption}' (type={item_type})")
                warn(f"         path: {self.path}")
                warn(f"         icon: {self.d.get('icon', 'not set')}")
        
        # フォールバック
        if not pix or pix.isNull():
            warn(f"[STATIC] Using fallback icon for '{caption}'")
            pix = _icon_pixmap("", 0, ICON_SIZE)
            
        # 以下既存の処理...
        self._src_pixmap = pix.copy()
        scaled = self._apply_scaling_and_crop(pix, tgt_w, tgt_h)
        final_pix = self._apply_brightness_to_pixmap(scaled)
        
        self._pix_item.setPixmap(final_pix)
        self._rect_item.setRect(0, 0, tgt_w, tgt_h)
        self.d["width"], self.d["height"] = tgt_w, tgt_h
        
        if hasattr(self, "cap_item") and self.cap_item:
            self.cap_item.setPos(0, tgt_h)

    def _load_fallback_icon(self):
        """フォールバックアイコン読み込み"""
        tgt_w = int(self.d.get("width", ICON_SIZE))
        tgt_h = int(self.d.get("height", ICON_SIZE))
        
        pix = _icon_pixmap("", 0, ICON_SIZE)
        self._src_pixmap = pix.copy()
        scaled = self._apply_scaling_and_crop(pix, tgt_w, tgt_h)
        final_pix = self._apply_brightness_to_pixmap(scaled)
        
        self._pix_item.setPixmap(final_pix)
        self._rect_item.setRect(0, 0, tgt_w, tgt_h)
        self.d["width"], self.d["height"] = tgt_w, tgt_h

    def _apply_scaling_and_crop(self, pix: QPixmap, tgt_w: int, tgt_h: int) -> QPixmap:
        """スケーリングとクロップ処理 - 高品質スケーリング使用"""
        scaled = self._scale_pixmap_with_quality_base(pix, tgt_w, tgt_h)
        crop_x = max(0, (scaled.width() - tgt_w) // 2)
        crop_y = max(0, (scaled.height() - tgt_h) // 2)
        return scaled.copy(crop_x, crop_y, tgt_w, tgt_h)

    def _apply_brightness_to_pixmap(self, pix: QPixmap) -> QPixmap:
        """明るさ調整を適用"""
        bri = self.brightness
        if bri is None or bri == 50:
            return pix
            
        level = bri - 50
        alpha = int(abs(level) / 50 * 255)
        overlay = QPixmap(pix.size())
        overlay.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(overlay)
        col = QColor(255, 255, 255, alpha) if level > 0 else QColor(0, 0, 0, alpha)
        painter.fillRect(overlay.rect(), col)
        painter.end()
        
        result = QPixmap(pix.size())
        result.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pix)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver if level > 0
            else QPainter.CompositionMode.CompositionMode_Multiply
        )
        painter.drawPixmap(0, 0, overlay)
        painter.end()
        
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

    def paint(self, painter, option, widget=None):
        """
        カスタムペイント - LOD (Level of Detail) 実装
        キャンバスズーム時に動的にアイコン品質を調整
        """
        # 現在のスケール因子を取得
        current_scale = option.levelOfDetailFromTransform(painter.worldTransform())
        
        # スケール因子が大きく変わった場合のみピクスマップを再生成
        scale_threshold = 0.2  # 20%以上の変化で再生成
        if abs(current_scale - self._current_lod_scale) > scale_threshold:
            self._current_lod_scale = current_scale
            self._update_icon_for_lod(current_scale)
        
        # 標準の描画処理
        super().paint(painter, option, widget)
    
    def _update_icon_for_lod(self, scale_factor):
        """
        LOD用のアイコン更新
        キャンバスのスケール因子に応じて最適な解像度のアイコンを生成
        """
        if not hasattr(self, '_src_pixmap') or not self._src_pixmap or self._src_pixmap.isNull():
            return
            
        # 現在の表示サイズ
        current_w = int(self.d.get("width", ICON_SIZE))
        current_h = int(self.d.get("height", ICON_SIZE))
        
        # スケール因子を考慮した最適サイズを計算
        optimal_w = max(16, int(current_w * scale_factor))  # 最小16px
        optimal_h = max(16, int(current_h * scale_factor))
        
        # 最適スケーリング実行
        scaled = self._apply_scaling_and_crop(self._src_pixmap, optimal_w, optimal_h)
        
        # 表示サイズに最終調整
        if scaled.width() != current_w or scaled.height() != current_h:
            scaled = self._apply_scaling_and_crop(scaled, current_w, current_h)
        
        # 明るさ調整適用
        final_pix = self._apply_brightness_to_pixmap(scaled)
        
        self._pix_item.setPixmap(final_pix)

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
        """EDITラベルの位置を更新"""
        if hasattr(self, "_edit_label") and self._edit_label:
            self._edit_label.setPos(2, 2)

    def on_edit(self):
        """編集ダイアログを開く"""
        win = self.scene().views()[0].window()
        from .DPyL_classes import LauncherEditDialog
        dlg = LauncherEditDialog(self.d, win)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # ★修正点：編集結果を反映する前に既存のGIFアニメーションを停止
            self._stop_movie()
            
            # 新フィールドでの更新チェック
            self.workdir = self.d.get("workdir", "")
            
            # プレビューのサイズで width/height を保存
            # LauncherEditDialogのプレビューはQLabelの lbl_prev
            r"""
            if hasattr(dlg, "lbl_prev") and dlg.lbl_prev:
                pix = dlg.lbl_prev.pixmap()
                if pix and not pix.isNull():
                    self.d["width"], self.d["height"] = pix.width(), pix.height()
            """        
            # アイコンを再読み込み
            self._refresh_icon()
            
            # キャプションを更新
            if hasattr(self, "cap_item") and self.cap_item:
                self.cap_item.setPlainText(self.d.get("caption", ""))
                
        # 編集可能フラグの更新
        self.is_editable = self.d.get("is_editable", False)
        if hasattr(self, "_edit_label"):
            self._edit_label.setVisible(self.is_editable)
            self._update_edit_label_pos()
            
        # 実行モードの設定
        self.set_run_mode(not win.a_edit.isChecked())

    def on_activate(self):
        """
        実行モード時のダブルクリック起動処理  
        フォルダ → エクスプローラーで開く  
        拡張子に応じて subprocess / QProcess / os.startfile を使い分け
        """
       
        path = self.d.get("path", "")
        if not path:
            warn("[LauncherItem] path が設定されていません")
            self._show_execution_notification(False, _("path_not_set"))
            return
        
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        
        warn(f"on_activate: {path}")
        
        # --- フォルダなら explorer で開く ---
        if os.path.isdir(path):
            try:
                # ディレクトリの場合は明示的にexplorerコマンドを使用して開く
                # これにより同名のバッチファイルが誤って実行されることを防ぐ
                import subprocess
                subprocess.run(['explorer', path], check=False)
                self._show_execution_notification(True, _("folder_opened"))
            except Exception as e:
                warn(f"[LauncherItem] フォルダオープン失敗: {e}")
                # フォールバック: 従来の方法を試す
                try:
                    os.startfile(path)
                    self._show_execution_notification(True, _("folder_opened"))
                except Exception as e2:
                    warn(f"[LauncherItem] フォルダオープン(フォールバック)失敗: {e2}")
                    self._show_execution_notification(False, _("folder_open_failed"))
            return

        ext = Path(path).suffix.lower()
        
        # ------------------------------------------------------
        # 編集可能フラグ付きテキスト系ファイルは OS の編集モードで開く (仮)
        # ------------------------------------------------------
        is_edit = self.d.get("is_editable", False)
        if is_edit and ext in self.EDITABLE_LIKE:
            import ctypes #ここでいい
            # Windows ShellExecute の "edit" 動詞で既定のエディタを起動
            try:
                # 第5引数はウィンドウ表示モード(1=標準ウィンドウ)
                ctypes.windll.shell32.ShellExecuteW(None, "edit", path, None, None, 1)
                self._show_execution_notification(True, _("executed_in_edit_mode"))
            except Exception as e:
                warn(f"[LauncherItem] 編集モード起動失敗: {e}")
                # フォールバックで通常の open
                try:
                    os.startfile(path)
                    self._show_execution_notification(True, _("executed"))
                except Exception as e2:
                    warn(f"[LauncherItem] フォールバック起動失敗: {e2}")
                    self._show_execution_notification(False, _("execution_failed"))
            return
        # ------------------------------------------------------
        
        # --- URL ならブラウザで開く（例: https://example.com/ など） ---
        if isinstance(path, str) and path.lower().startswith(("http://", "https://")):
            try:
                os.startfile(path)  # Windows なら既定のブラウザで開く
                self._show_execution_notification(True, _("url_opened"))
            except Exception as e:
                warn(f"[LauncherItem.on_activate] URLオープン失敗: {e}")
                self._show_execution_notification(False, _("url_open_failed"))
            return
            
        # --- 作業ディレクトリの初期化 ---
        workdir = (self.d.get("workdir") or "").strip()
        if not workdir:
            workdir = str(Path(path).parent)
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            workdir = os.path.normpath(workdir)
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
            
            # --- バッチファイル・PowerShellスクリプトの実行 ---
            if ext in ('.bat', '.cmd', '.ps1') and not is_edit:
                run_hidden = self.d.get("run_hidden", False)
                
                if run_hidden:
                    # 非表示で実行 - 現状通りターミナルまたはQProcessで実行
                    warn(f"[LauncherItem] 非表示実行でターミナル実行を試行: {path}")
                    if self.execute_in_nearest_terminal():
                        warn(f"[LauncherItem] ターミナルで実行成功: {path}")
                        self._show_execution_notification(True, _("executed_in_terminal"))
                        return
                    warn(f"[LauncherItem] ターミナル実行失敗、フォールバック: {path}")
                    # 失敗した場合は従来の実行方法にフォールバック
                else:
                    # 表示実行 - OSの標準機能を使用（コマンドプロンプトウィンドウが表示される）
                    try:
                        warn(f"[LauncherItem] 表示実行でOS標準機能を使用: {path}")
                        os.startfile(path)
                        self._show_execution_notification(True, _("executed"))
                        return
                    except Exception as e:
                        warn(f"[LauncherItem] OS標準実行失敗: {e}")
                        self._show_execution_notification(False, _("execution_failed"))
                        return

            # --- Pythonスクリプト ---
            if ext == ".py" and not is_edit:
                try:
                    py_exec = sys.executable
                    ok = QProcess.startDetached(py_exec, [path], workdir)
                    if not ok:
                        warn(f"QProcess 起動失敗: {py_exec} {path}")
                        self._show_execution_notification(False, _("python_script_execution_failed"))
                    else:
                        self._show_execution_notification(True, _("python_script_executed"))
                    return
                except Exception as e:
                    warn(f"[LauncherItem.on_activate] .py 起動エラー: {e}")
                    self._show_execution_notification(False, _("python_script_execution_failed"))
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
                # バッチファイルの場合は run_hidden フラグを考慮
                if ext in (".bat", ".cmd"):
                    run_hidden = self.d.get("run_hidden", False)
                    if run_hidden:
                        # 非表示実行 - QProcessで実行（従来通り）
                        ok = QProcess.startDetached("cmd", ["/c", path], workdir)
                        if not ok:
                            warn(f"QProcess 起動失敗: cmd /c {path} (workdir: {workdir})")
                            # フォールバック: os.startfile
                            os.startfile(path)
                            self._show_execution_notification(True, _("executed"))
                        else:
                            self._show_execution_notification(True, _("executed"))
                    else:
                        # 表示実行 - OSの標準機能で実行（コマンドプロンプトが表示される）
                        os.startfile(path)
                        self._show_execution_notification(True, _("executed"))
                else:
                    os.startfile(path)
                    self._show_execution_notification(True, _("executed"))
            except Exception as e:
                warn(f"[LauncherItem.on_activate] startfile 失敗: {e}")
                self._show_execution_notification(False, "実行に失敗しました")
        finally:
            # ここで必ず元の CWD へ戻す（プロジェクト保存に影響させない）
            if cwd_changed:
                os.chdir(orig_cwd)

    def _show_execution_notification(self, success: bool, message: str):
        """LauncherItemの実行結果を通知表示する"""
        try:
            # シーンからメインウィンドウを取得
            scene = self.scene()
            if not scene:
                return
                
            views = scene.views()
            if not views:
                return
                
            main_window = views[0].window()
            if not hasattr(main_window, 'notification_manager'):
                return
                
            # 成功/失敗に応じて通知を表示
            if success:
                main_window.notification_manager.show_success(message)
            else:
                main_window.notification_manager.show_error(message)
        except Exception as e:
            warn(f"[LauncherItem] 通知表示エラー: {e}")

    def execute_in_nearest_terminal(self):
        """最寄りのターミナルでファイルを実行"""
        try:
            warn("[LauncherItem] execute_in_nearest_terminal 開始")
            # キャンバス上の全アイテムから最寄りのターミナルを検索
            nearest_terminal = self._find_nearest_terminal()
            if not nearest_terminal:
                warn("[LauncherItem] 最寄りのターミナルが見つかりません")
                # ターミナルが見つからない場合はLauncherItemのworkdirで直接実行
                return self._execute_directly_with_workdir()
                
            
            warn(f"[LauncherItem] 最寄りターミナル発見: {nearest_terminal.__class__.__name__}")
            
            # 拡張子に応じたターミナル種別の判定
            path = self.d.get("path", "")
            # Windows では forward slash を backslash に正規化
            if os.name == 'nt':
                path = os.path.normpath(path)
            ext = Path(path).suffix.lower()
            
            # 拡張子とターミナル種別のマッピング
            required_terminal_type = self._get_required_terminal_type(ext)
            if not required_terminal_type:
                warn(f"[LauncherItem] 対応していない拡張子です: {ext}")
                return False
            
            # ターミナルの種別が一致するかチェック
            terminal_type = getattr(nearest_terminal, 'terminal_type', None) or \
                           nearest_terminal.d.get('terminal_type', 'cmd')
            
            if not self._is_compatible_terminal(required_terminal_type, terminal_type):
                warn(f"[LauncherItem] ターミナル種別が一致しません: 必要={required_terminal_type}, 現在={terminal_type}")
                return False
            
            # ターミナルでファイルを実行
            return self._execute_in_terminal(nearest_terminal, path)
            
        except Exception as e:
            warn(f"[LauncherItem] execute_in_nearest_terminal エラー: {e}")
            return False
    
    def _find_nearest_terminal(self):
        """最寄りのターミナルアイテムを検索"""
        try:
            scene = self.scene()
            if not scene:
                warn("[LauncherItem] シーンが見つかりません")
                return None
            
            my_pos = self.pos()
            my_center = QPointF(my_pos.x() + self.d.get("width", 32)/2, 
                               my_pos.y() + self.d.get("height", 32)/2)
            
            warn(f"[LauncherItem] 自分の位置: {my_center.x()}, {my_center.y()}")
            
            nearest_terminal = None
            min_distance = float('inf')
            terminal_count = 0
            
            # 全てのアイテムをチェック
            for item in scene.items():
                # ターミナル系アイテムかチェック
                if self._is_terminal_item(item):
                    terminal_count += 1
                    item_pos = item.pos()
                    item_center = QPointF(item_pos.x() + getattr(item.d, 'get', lambda k, d: d)("width", 100)/2,
                                         item_pos.y() + getattr(item.d, 'get', lambda k, d: d)("height", 100)/2)
                    
                    # 距離を計算
                    distance = ((my_center.x() - item_center.x()) ** 2 + 
                              (my_center.y() - item_center.y()) ** 2) ** 0.5
                    
                    warn(f"[LauncherItem] ターミナル {item.__class__.__name__} 位置: {item_center.x()}, {item_center.y()}, 距離: {distance}")
                    
                    # 近接距離内で最も近いものを選択
                    if distance <= self.PROXIMITY_DISTANCE and distance < min_distance:
                        min_distance = distance
                        nearest_terminal = item
                        warn(f"[LauncherItem] 新しい最寄りターミナル: {item.__class__.__name__}, 距離: {distance}")
            
            warn(f"[LauncherItem] 見つかったターミナル数: {terminal_count}")
            if nearest_terminal:
                warn(f"[LauncherItem] 最終選択ターミナル: {nearest_terminal.__class__.__name__}, 距離: {min_distance}")
            
            return nearest_terminal
            
        except Exception as e:
            warn(f"[LauncherItem] _find_nearest_terminal エラー: {e}")
            return None
    
    def _is_terminal_item(self, item):
        """アイテムがターミナルかどうかを判定"""
        try:
            # TYPE_NAMEで判定
            type_name = getattr(item, 'TYPE_NAME', None)
            class_name = item.__class__.__name__
            
            warn(f"[LauncherItem] アイテムチェック: {class_name}, TYPE_NAME: {type_name}")
            
            # CommandWidgetを除外（これはターミナル起動のための機能）
            if class_name == 'CommandWidget':
                warn(f"[LauncherItem] CommandWidgetを除外: {class_name}")
                return False
            
            if type_name in ['embedded_terminal', 'terminal_manager', 'terminal']:
                warn(f"[LauncherItem] TYPE_NAMEでターミナル判定: {type_name}")
                return True
            
            # クラス名で判定（CommandWidgetは除外済み）
            if any(keyword in class_name.lower() for keyword in ['terminal']):
                warn(f"[LauncherItem] クラス名でターミナル判定: {class_name}")
                return True
            
            return False
            
        except Exception as e:
            warn(f"[LauncherItem] _is_terminal_item エラー: {e}")
            return False
    
    def _get_required_terminal_type(self, ext):
        """拡張子に応じて必要なターミナル種別を返す"""
        if ext in ('.bat', '.cmd'):
            return 'cmd'
        elif ext == '.ps1':
            return 'powershell'
        else:
            return None  # 対応していない拡張子
    
    def _is_compatible_terminal(self, required_type, terminal_type):
        """ターミナル種別の互換性をチェック"""
        if required_type == terminal_type:
            return True
        
        # PowerShellはcmdコマンドも実行可能
        if required_type == 'cmd' and terminal_type in ['powershell', 'pwsh']:
            return True
        
        return False
    
    def _execute_in_terminal(self, terminal_item, file_path):
        """指定されたターミナルでファイルを実行"""
        try:
            # ターミナルタイプを確認
            terminal_type = getattr(terminal_item, 'terminal_type', None) or \
                           terminal_item.d.get('terminal_type', 'cmd')
            warn(f"[LauncherItem] ターミナルタイプ: {terminal_type}")
            
            # バッチファイル実行用に専用メソッドを追加
            if hasattr(terminal_item, 'execute_file_in_terminal'):
                warn("[LauncherItem] execute_file_in_terminalメソッド使用")
                return terminal_item.execute_file_in_terminal(file_path)
            
            # TerminalItemに動的にメソッドを追加
            self._add_execute_method_to_terminal(terminal_item)
            
            if hasattr(terminal_item, 'execute_file_in_terminal'):
                warn("[LauncherItem] 動的追加したexecute_file_in_terminalメソッド使用")
                return terminal_item.execute_file_in_terminal(file_path)
            
            # フォールバック: 従来の方法
            warn("[LauncherItem] フォールバック: 従来の実行方法")
            return False
            
        except Exception as e:
            warn(f"[LauncherItem] _execute_in_terminal エラー: {e}")
            return False
    
    def _execute_directly_with_workdir(self):
        """ターミナルが見つからない場合にLauncherItemのworkdirで直接実行"""
        try:
            path = self.d.get("path", "")
            if not path:
                warn("[LauncherItem] path が設定されていません")
                return False
            
            # Windows では forward slash を backslash に正規化
            if os.name == 'nt':
                path = os.path.normpath(path)
            
            # LauncherItemのworkdirを取得
            workdir = self.d.get("workdir", "")
            if not workdir:
                workdir = Path(path).parent
            
            # Windows では forward slash を backslash に正規化
            if os.name == 'nt':
                workdir = os.path.normpath(workdir)
            workdir = os.path.abspath(workdir)
            
            warn(f"[LauncherItem] 直接実行: {path} (workdir: {workdir})")
            
            # QProcessで実行
            ext = Path(path).suffix.lower()
            if ext in (".bat", ".cmd"):
                ok = QProcess.startDetached("cmd", ["/c", path], workdir)
                if not ok:
                    warn(f"QProcess 起動失敗: cmd /c {path} (workdir: {workdir})")
                    return False
                return True
            elif ext == ".ps1":
                ok = QProcess.startDetached("powershell", ["-ExecutionPolicy", "Bypass", "-File", path], workdir)
                if not ok:
                    warn(f"QProcess 起動失敗: powershell -File {path} (workdir: {workdir})")
                    return False
                return True
            
            return False
        except Exception as e:
            warn(f"[LauncherItem] _execute_directly_with_workdir エラー: {e}")
            return False
    
    def _add_execute_method_to_terminal(self, terminal_item):
        """TerminalItemに実行メソッドを動的に追加"""
        try:
            def execute_file_in_terminal(file_path):
                """ファイルをターミナルで直接実行"""
                try:
                    import subprocess
                    from pathlib import Path
                    
                    # 作業ディレクトリを設定（ターミナルのworkdirを優先）
                    workdir = terminal_item.d.get('workdir', '') or getattr(terminal_item, 'workdir', '')
                    if not workdir:
                        workdir = Path(file_path).parent
                    
                    # ターミナルタイプに応じて実行
                    terminal_type = getattr(terminal_item, 'terminal_type', None) or \
                                   terminal_item.d.get('terminal_type', 'cmd')
                    
                    # ターミナルウィジェット内でファイルを直接実行
                    if hasattr(terminal_item, '_terminal_widget'):
                        widget = terminal_item._terminal_widget
                        
                        # 直接実行（TerminalItemの_on_command_executedを回避）
                        try:
                            from PySide6.QtCore import QTimer
                            import threading
                            
                            # 結果を保存する変数
                            execution_result = {"completed": False, "output": "", "error": "", "returncode": 0}
                            
                            def run_in_background():
                                try:
                                    if terminal_type == "cmd":
                                        # バッチファイルを直接実行（エンコーディング対応＋curl進捗無効化）
                                        env = os.environ.copy()
                                        env['CURL_PROGRESS_BAR'] = '0'  # curlの進捗バーを無効化
                                        env['CURL_SILENT'] = '1'       # curlをサイレントモードに
                                        result = subprocess.run(
                                            [file_path],
                                            cwd=workdir,
                                            capture_output=True,
                                            text=True,
                                            shell=True,
                                            timeout=60,
                                            env=env,
                                            encoding='utf-8',
                                            errors='replace'  # デコードエラーを回避
                                        )
                                    elif terminal_type == "powershell":
                                        # PowerShellでスクリプトを実行（エンコーディング対応）
                                        result = subprocess.run(
                                            ["powershell", "-ExecutionPolicy", "Bypass", "-File", file_path],
                                            cwd=workdir,
                                            capture_output=True,
                                            text=True,
                                            timeout=60,
                                            encoding='utf-8',
                                            errors='replace'
                                        )
                                    else:
                                        # デフォルト実行（エンコーディング対応）
                                        result = subprocess.run(
                                            [file_path],
                                            cwd=workdir,
                                            capture_output=True,
                                            text=True,
                                            shell=True,
                                            timeout=60,
                                            encoding='utf-8',
                                            errors='replace'
                                        )
                                    
                                    # 結果を保存
                                    execution_result["output"] = result.stdout
                                    execution_result["error"] = result.stderr
                                    execution_result["returncode"] = result.returncode
                                    execution_result["completed"] = True
                                    
                                    # デバッグ情報
                                    warn(f"[LauncherItem] 実行結果 - stdout: {repr(result.stdout)}")
                                    warn(f"[LauncherItem] 実行結果 - stderr: {repr(result.stderr)}")
                                    warn(f"[LauncherItem] 実行結果 - returncode: {result.returncode}")
                                        
                                except subprocess.TimeoutExpired:
                                    execution_result["error"] = "Timeout: 実行時間が長すぎます"
                                    execution_result["completed"] = True
                                except Exception as bg_e:
                                    execution_result["error"] = f"実行エラー: {bg_e}"
                                    execution_result["completed"] = True
                            
                            # バックグラウンドで実行開始
                            thread = threading.Thread(target=run_in_background)
                            thread.daemon = True
                            thread.start()
                            
                            # 定期的に結果をチェックしてUI更新
                            def check_result():
                                if execution_result["completed"]:
                                    # 出力を一度に表示（プロンプトの重複を防ぐ）
                                    all_output = ""
                                    if execution_result["output"]:
                                        stdout_content = execution_result["output"].strip()
                                        warn(f"[LauncherItem] stdout処理前: {repr(stdout_content)}")
                                        all_output += stdout_content
                                    
                                    if execution_result["error"]:
                                        stderr_content = execution_result["error"]
                                        warn(f"[LauncherItem] stderr処理前: {repr(stderr_content)}")
                                        
                                        # curlの進捗表示を完全にフィルタリング
                                        error_lines = stderr_content.split('\n')
                                        filtered_errors = []
                                        for line in error_lines:
                                            # curlの進捗表示を完全に除去
                                            if not any(keyword in line for keyword in [
                                                "% Total", "% Received", "% Xferd", "Average Speed",
                                                "Dload", "Upload", "Total", "Spent", "Left", "Speed",
                                                "--:--:--", "0:00:", "Current", "Time"
                                            ]) and line.strip() and not line.strip().isspace():
                                                # 空行や数字のみの行も除去
                                                if not (line.strip().replace(' ', '').replace('0', '').replace('100', '') == ''):
                                                    filtered_errors.append(line)
                                        
                                        filtered_error = '\n'.join(filtered_errors).strip()
                                        warn(f"[LauncherItem] stderr処理後: {repr(filtered_error)}")
                                        if filtered_error:
                                            if all_output:
                                                all_output += "\n"
                                            all_output += filtered_error
                                    
                                    warn(f"[LauncherItem] 最終出力: {repr(all_output)}")
                                    
                                    if all_output:
                                        # エスケープシーケンスを処理してから出力
                                        processed_output = self._process_ansi_escape_sequences(all_output)
                                        # カスタムメソッドで出力（プロンプト重複回避）
                                        self._add_output_without_prompt(widget, processed_output)
                                    
                                    if execution_result["returncode"] == 0:
                                        self._add_output_without_prompt(widget, "実行完了")
                                    elif execution_result["returncode"] != 0 and not all_output:
                                        self._add_output_without_prompt(widget, f"終了コード: {execution_result['returncode']}")
                                else:
                                    # まだ完了していない場合は100ms後に再チェック
                                    QTimer.singleShot(100, check_result)
                            
                            # 結果チェック開始
                            QTimer.singleShot(100, check_result)
                                
                        except Exception as exec_e:
                            widget.add_output(f"実行エラー: {exec_e}")
                    
                    return True
                    
                except Exception as e:
                    warn(f"[TerminalItem] execute_file_in_terminal エラー: {e}")
                    return False
            
            # メソッドを動的に追加
            terminal_item.execute_file_in_terminal = execute_file_in_terminal
            
        except Exception as e:
            warn(f"[LauncherItem] _add_execute_method_to_terminal エラー: {e}")
    
    def _send_command_to_terminal_widget(self, widget, command):
        """TerminalWidgetにコマンドを直接送信"""
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtGui import QTextCursor
            
            warn(f"[LauncherItem] ターミナルに送信するコマンド: {command}")
            
            # カーソルを最後の行の末尾に移動
            cursor = widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            # プロンプトの後にコマンドを挿入
            cursor.insertText(command)
            widget.setTextCursor(cursor)
            
            # コマンドを実行
            def execute_command():
                try:
                    warn(f"[LauncherItem] コマンド実行中: {command}")
                    # _execute_current_commandメソッドを直接呼び出し
                    if hasattr(widget, '_execute_current_command'):
                        widget._execute_current_command()
                    # またはcommand_executedシグナルを発行
                    elif hasattr(widget, 'command_executed'):
                        widget.command_executed.emit(command)
                    else:
                        warn("[LauncherItem] 実行メソッドが見つかりません")
                except Exception as ex:
                    warn(f"[LauncherItem] コマンド実行エラー: {ex}")
            
            # 少し遅延してからコマンドを実行
            QTimer.singleShot(100, execute_command)
            
        except Exception as e:
            warn(f"[LauncherItem] _send_command_to_terminal_widget エラー: {e}")
    
    def _add_output_without_prompt(self, widget, text):
        """プロンプトを重複させずに出力を追加（HTML対応）"""
        try:
            from PySide6.QtGui import QTextCursor
            
            # カーソルを最後の行に移動
            cursor = widget.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            # 現在の行がプロンプトのみの場合は、プロンプトの前に挿入
            current_line = cursor.block().text()
            if current_line.strip() == widget.prompt.strip():
                # プロンプトの前に移動
                cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
                # HTMLを含む場合はHTML形式で挿入
                if '<span' in text or '&' in text:
                    cursor.insertHtml(text + "<br>")
                else:
                    cursor.insertText(text + "\n")
                # 新しいプロンプトは追加しない（元のプロンプトが残る）
            else:
                # 通常の出力追加
                if '<span' in text or '&' in text:
                    cursor.insertHtml("<br>" + text + "<br>" + widget.prompt)
                else:
                    cursor.insertText("\n" + text + "\n" + widget.prompt)
            
            widget.setTextCursor(cursor)
            widget.ensureCursorVisible()
            
        except Exception as e:
            warn(f"[LauncherItem] _add_output_without_prompt エラー: {e}")
            # フォールバック
            widget.add_output(text)
    
    def _process_ansi_escape_sequences(self, text):
        """ANSIエスケープシーケンスを処理してHTMLに変換"""
        try:
            import re
            
            # ANSIカラーコードとHTMLカラーのマッピング
            ansi_colors = {
                '30': '#000000',  # 黒
                '31': '#FF0000',  # 赤
                '32': '#00FF00',  # 緑
                '33': '#FFFF00',  # 黄
                '34': '#0000FF',  # 青
                '35': '#FF00FF',  # マゼンタ
                '36': '#00FFFF',  # シアン
                '37': '#FFFFFF',  # 白
                '90': '#808080',  # 明るい黒（グレー）
                '91': '#FF8080',  # 明るい赤
                '92': '#80FF80',  # 明るい緑
                '93': '#FFFF80',  # 明るい黄
                '94': '#8080FF',  # 明るい青
                '95': '#FF80FF',  # 明るいマゼンタ
                '96': '#80FFFF',  # 明るいシアン
                '97': '#FFFFFF',  # 明るい白
            }
            
            # ANSIエスケープシーケンスのパターン
            ansi_pattern = re.compile(r'\x1b\[([0-9;]*)m')
            
            # テキストを処理
            result = ""
            last_end = 0
            current_color = None
            
            for match in ansi_pattern.finditer(text):
                # マッチ前のテキストを追加
                before_text = text[last_end:match.start()]
                if current_color:
                    result += f'<span style="color: {current_color};">{self._escape_html(before_text)}</span>'
                else:
                    result += self._escape_html(before_text)
                
                # ANSIコードを解析
                codes = match.group(1).split(';') if match.group(1) else ['0']
                
                for code in codes:
                    if code == '0' or code == '':  # リセット
                        current_color = None
                    elif code in ansi_colors:  # カラーコード
                        current_color = ansi_colors[code]
                
                last_end = match.end()
            
            # 残りのテキストを追加
            remaining_text = text[last_end:]
            if current_color:
                result += f'<span style="color: {current_color};">{self._escape_html(remaining_text)}</span>'
            else:
                result += self._escape_html(remaining_text)
            
            return result
            
        except Exception as e:
            warn(f"[LauncherItem] ANSIエスケープシーケンス処理エラー: {e}")
            # エラー時は元のテキストをそのまま返す（エスケープシーケンスを除去）
            import re
            return re.sub(r'\x1b\[[0-9;]*m', '', text)
    
    def _escape_html(self, text):
        """HTMLエスケープ処理"""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))
    
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
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico")

    @classmethod
    def supports_path(cls, path: str) -> bool:
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        suffix = Path(path).suffix.lower()
        return suffix in cls.IMAGE_EXTS

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        d = {
            "type": "image",
            "path": path,
            "image_embedded": False,  # 新フィールド：デフォルトは参照
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
        # 古いembedフィールドは使用しない
        self._pix_item = QGraphicsPixmapItem(parent=self)
        # QGraphicsPixmapItemにスムーズトランスフォームを設定
        self._pix_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        
        # LOD (Level of Detail) を有効にしてキャンバスズーム時の品質向上
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        
        self._apply_pixmap()
        self._orig_pixmap = self._src_pixmap
        self._update_grip_pos()
        
        # 現在のスケール因子を追跡
        self._current_lod_scale = 1.0

    def _scale_pixmap_with_quality_CUSTOM(self, pixmap: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        高品質なピクスマップスケーリング - ImageItem用カスタム版（テスト用に無効化）
        """
        return self._scale_pixmap_with_quality_base_CUSTOM(pixmap, target_w, target_h)
    
    def _scale_pixmap_with_quality(self, pixmap: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        高品質なピクスマップスケーリング - ImageItem用（現在Qt標準版を使用）
        """
        return self._scale_pixmap_with_quality_base(pixmap, target_w, target_h)

    def _apply_pixmap(self):
        """画像を適用 - 新フィールド対応"""
        pix = QPixmap()
        
        # 新フィールドから埋め込みデータを取得
        if self.d.get("image_embedded") and self.d.get("image_embedded_data"):
            try:
                pix.loadFromData(b64decode(self.d["image_embedded_data"]))
            except Exception as e:
                warn(f"[IMAGE] Failed to load embed data: {e}")
                pix = None
        elif self.path:
            pix = QPixmap(self.path)

        if pix.isNull():
            pix = _icon_pixmap(self.path or "", 0, ICON_SIZE)

        self._src_pixmap = pix.copy()
        tgt_w = int(self.d.get("width", pix.width()))
        tgt_h = int(self.d.get("height", pix.height()))
        
        # スケーリング処理 - 縮小時は平均近傍を使用
        scaled = self._scale_pixmap_with_quality(self._src_pixmap, tgt_w, tgt_h)
        crop_x = max(0, (scaled.width()  - tgt_w) // 2)
        crop_y = max(0, (scaled.height() - tgt_h) // 2)
        pix = scaled.copy(crop_x, crop_y, tgt_w, tgt_h)

        # 明るさ調整
        bri = self.brightness
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
            painter = QPainter(result)
            painter.drawPixmap(0, 0, pix)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver if level > 0
                else QPainter.CompositionMode.CompositionMode_Multiply
            )
            painter.drawPixmap(0, 0, overlay)
            painter.end()
            pix = result

        self._pix_item.setPixmap(pix)
        self._rect_item.setRect(0, 0, tgt_w, tgt_h)

    def paint(self, painter, option, widget=None):
        """
        カスタムペイント - LOD (Level of Detail) 実装
        キャンバスズーム時に動的にピクスマップ品質を調整
        """
        # 現在のスケール因子を取得
        current_scale = option.levelOfDetailFromTransform(painter.worldTransform())
        
        # スケール因子が大きく変わった場合のみピクスマップを再生成
        scale_threshold = 0.2  # 20%以上の変化で再生成
        if abs(current_scale - self._current_lod_scale) > scale_threshold:
            self._current_lod_scale = current_scale
            self._update_pixmap_for_lod(current_scale)
        
        # 標準の描画処理
        super().paint(painter, option, widget)
    
    def _update_pixmap_for_lod(self, scale_factor):
        """
        LOD用のピクスマップ更新
        キャンバスのスケール因子に応じて最適な解像度のピクスマップを生成
        """
        if not hasattr(self, '_src_pixmap') or self._src_pixmap.isNull():
            return
            
        # 現在の表示サイズ
        current_w = int(self.d.get("width", 200))
        current_h = int(self.d.get("height", 200))
        
        # スケール因子を考慮した最適サイズを計算
        optimal_w = max(32, int(current_w * scale_factor))  # 最小32px
        optimal_h = max(32, int(current_h * scale_factor))
        
        # 元画像からの最適スケーリング実行
        scaled = self._scale_pixmap_with_quality(self._src_pixmap, optimal_w, optimal_h)
        
        # 表示サイズに最終調整
        if scaled.width() != current_w or scaled.height() != current_h:
            final_scaled = scaled.scaled(
                current_w, current_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            crop_x = max(0, (final_scaled.width() - current_w) // 2)
            crop_y = max(0, (final_scaled.height() - current_h) // 2)
            scaled = final_scaled.copy(crop_x, crop_y, current_w, current_h)
        
        # 明るさ調整
        bri = self.brightness
        if bri is not None and bri != 50:
            level = bri - 50
            alpha = int(abs(level) / 50 * 255)
            overlay = QPixmap(scaled.size())
            overlay.fill(Qt.GlobalColor.transparent)
            painter = QPainter(overlay)
            col = QColor(255,255,255,alpha) if level>0 else QColor(0,0,0,alpha)
            painter.fillRect(overlay.rect(), col)
            painter.end()
            
            result = QPixmap(scaled.size())
            result.fill(Qt.GlobalColor.transparent)
            painter = QPainter(result)
            painter.drawPixmap(0, 0, scaled)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver if level > 0
                else QPainter.CompositionMode.CompositionMode_Multiply
            )
            painter.drawPixmap(0, 0, overlay)
            painter.end()
            scaled = result
        
        self._pix_item.setPixmap(scaled)

    def resize_content(self, w: int, h: int):
        src = getattr(self, "_src_pixmap", None)
        if not src or src.isNull():
            return
        # 高品質スケーリングを使用
        scaled = self._scale_pixmap_with_quality(src, w, h)
        cx = max(0, (scaled.width()  - w) // 2)
        cy = max(0, (scaled.height() - h) // 2)
        pm = scaled.copy(cx, cy, w, h)
        self._pix_item.setPixmap(pm)

    def on_edit(self):
        """編集ダイアログ起動"""
        dlg = ImageEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 更新された値を反映
            self.caption = self.d.get("caption", "")
            self.brightness = int(self.d.get("brightness", 50))
            self.path = self.d.get("path", "")
            
            self.init_caption()  # _apply_caption() → init_caption()に修正
            self._apply_pixmap()
            
        # 編集モード判定をメインウィンドウと同期
        win = self.scene().views()[0].window()
        self.set_run_mode(not win.a_edit.isChecked())

    def on_activate(self):
        try:
            if self.path:
                os.startfile(self.path)
        except Exception:
            warn("Exception at on_activate")
            pass

# --------------------------------------------------
#  GifItem (GifMixin + ImageItem)
# --------------------------------------------------
class GifItem(GifMixin, ImageItem):
    TYPE_NAME = "gif"

    @classmethod
    def supports_path(cls, path: str) -> bool:
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        return path.lower().endswith(".gif")

    @classmethod
    def create_from_path(cls, path, sp, win):
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        d = {
            "type": cls.TYPE_NAME,
            "caption": Path(path).stem,
            "path": path,
            "image_embedded": False,  # 新フィールド
            "x": sp.x(),
            "y": sp.y(),
            "width": 200,
            "height": 200,
            "brightness": 50,
        }
        item = cls(d, win.text_color)
        return item, d

    def __init__(self, d, cb_resize=None, text_color=None):
        # ImageItemの__init__を呼ぶ前に必要な初期化
        self._movie = None
        self._gif_buffer = None
        
        super().__init__(d, cb_resize, text_color)
        
        # GIF読み込みと開始
        self._load_gif_content()

    def _load_gif_content(self):
        """GIFコンテンツの読み込み"""
        tgt_w = int(self.d.get("width", 200))
        tgt_h = int(self.d.get("height", 200))
        
        # 埋め込みデータから読み込み
        if self.d.get("image_embedded") and self.d.get("image_embedded_data"):
            try:
                raw = base64.b64decode(self.d["image_embedded_data"])
                if self.load_gif(raw=raw):
                    self.d["width"], self.d["height"] = tgt_w, tgt_h
                    return
            except Exception as e:
                warn(f"[GIF] Failed to load embed data: {e}")
        
        # ファイルから読み込み
        if self.path and Path(self.path).exists():
            if self.load_gif(path=self.path):
                self.d["width"], self.d["height"] = tgt_w, tgt_h
            else:
                warn(f"Failed to load GIF: {self.path}")

    def _apply_pixmap(self):
        """GifItemでは_on_movie_frameで処理するのでオーバーライド"""
        if not self._movie:
            # GIFとして読み込めなかった場合は親クラスの処理を使用
            super()._apply_pixmap()

    def on_edit(self):
        """編集ダイアログ起動 - 新フィールド対応"""
        # ダイアログ実行前の状態を記憶
        old_path = self.path
        old_embedded = self.d.get("image_embedded", False)
        old_data = self.d.get("image_embedded_data")

        dlg = ImageEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # メタ情報を反映
            self.caption = self.d.get("caption", "")
            self.brightness = int(self.d.get("brightness", 50))
            self.init_caption()  # _apply_caption() → init_caption()に修正

            # パス／埋め込み状態の更新チェック
            new_path = self.d.get("path", "")
            new_embedded = self.d.get("image_embedded", False)
            new_data = self.d.get("image_embedded_data")

            # 変更があればGIFを再読み込み
            if (new_path != old_path or 
                new_embedded != old_embedded or 
                new_data != old_data):
                
                self.path = new_path
                self._stop_movie()
                self._load_gif_content()

            # 再描画 & 明るさ補正
            self._update_frame_display()
            self._apply_brightness()

        # 編集モード判定をメインウィンドウと同期
        win = self.scene().views()[0].window()
        self.set_run_mode(not win.a_edit.isChecked())

    def resize_to(self, w, h):
        """サイズ変更"""
        self.d["width"] = w
        self.d["height"] = h
        
        if self._movie:
            # GIFの場合は手動でリサイズ
            self._on_movie_frame()
        else:
            # 静止画の場合は親クラスの処理
            super().resize_content(w, h)
            
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
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pix)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver if level > 0
            else QPainter.CompositionMode.CompositionMode_Multiply
        )
        painter.drawPixmap(0, 0, overlay)
        painter.end()
        
        return result

    def _update_frame_display(self):
        """現在のフレームを再描画（明るさ適用なし）"""
        if self._movie:
            self._on_movie_frame()

    def _apply_brightness(self):
        """明るさのみを更新"""
        if self._movie:
            # 現在のフレームに明るさを適用して再描画
            self._on_movie_frame()
            
# ==================================================================
#  JSONItem
# ==================================================================
class JSONItem(LauncherItem):
    TYPE_NAME = "json"

    @classmethod
    def supports_path(cls, path: str) -> bool:
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
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
        """
        ・desktopPyLauncher プロジェクトならロード
        ・それ以外の JSON は、編集フラグに応じて OS の編集モード or 通常オープン
        """
        import ctypes
        win = self.scene().views()[0].window()
        p = Path(self.path)

        # 通常の JSON ファイルは is_editable フラグで編集モード or オープン
        if self.d.get("is_editable", False):
            try:
                # ShellExecute の "edit" で既定エディタを「編集モード」で起動したいが
                # .json の verb は "open"
                ctypes.windll.shell32.ShellExecuteW(None, "open", str(p), None, None, 1)
                return
            except Exception as e:
                warn(f"[JSONItem] 編集モード起動失敗: {e}")

        # プロジェクトファイルなら内部ロード
        if self._is_launcher_project():
            win._load_json(p)
            return

        # フォールバック：通常オープン
        try:
            os.startfile(str(p))
        except Exception:
            warn("[JSONItem] on_activate 失敗")


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
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
        p = Path(path)
        return p.exists()

    # ② ファクトリ
    @classmethod
    def create_from_path(cls, path: str, sp, win):
        # Windows では forward slash を backslash に正規化
        if os.name == 'nt':
            path = os.path.normpath(path)
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

        # 埋め込み(image_embedded)／参照 切替プルダウン
        h2 = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Reference", "Embed"])
        is_embedded = self.item.d.get("image_embedded", False)
        mode = "Embed" if is_embedded else "Reference"
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

        self.item.d["brightness"] = self.spin_bri.value()

        mode = self.combo_mode.currentText()
        path = self.ed_path.text().strip()
        self.item.d["path"] = path

        if mode == "Embed":
            self.item.d["image_embedded"] = True
            if path:  # パスが空でなければ再取得
                try:
                    with open(path, "rb") as fp:
                        raw_data = fp.read()
                    
                    self.item.d["image_embedded_data"] = base64.b64encode(raw_data).decode("ascii")
                    self.item.d["image_path_last_embedded"] = path
                    
                    # バイナリデータから実際のフォーマットを検出
                    self.item.d["image_format"] = detect_image_format(raw_data)
                    
                    # 静止画の場合は寸法情報も保存
                    pm = QPixmap(path)
                    if not pm.isNull():
                        self.item.d["image_width"] = pm.width()
                        self.item.d["image_height"] = pm.height()
                        self.item.d["image_bits"] = pm.depth()
                    
                except Exception as e:
                    warn(f"embed failed: {e}")
                    self.item.d["image_embedded"] = False
                    self.item.d.pop("image_embedded_data", None)
            # パスが空でも既存の埋め込みデータは保持
        else:
            # 参照モード - 埋め込み関連フィールドをすべて削除
            self.item.d["image_embedded"] = False
            self.item.d.pop("image_embedded_data", None)
            self.item.d.pop("image_format", None)
            self.item.d.pop("image_path_last_embedded", None)
            self.item.d.pop("image_width", None)
            self.item.d.pop("image_height", None)
            self.item.d.pop("image_bits", None)

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

        # -- Icon Type (Default/Embed) --
        h = QHBoxLayout()
        h.addWidget(QLabel("Icon Type"))
        self.combo_icon_type = QComboBox()
        self.combo_icon_type.addItems(["Default", "Embed"])
        # JSON に icon_embed または icon_embed_data があれば Embed を選択
        is_embedded = data.get("image_embedded", False) or data.get("icon_embed", False)
        self.combo_icon_type.setCurrentIndex(0 if not is_embedded else 1)
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
        
        # -- 非表示で実行 flag --
        self.chk_hidden = QCheckBox("非表示で実行（バッチファイル用）")
        self.chk_hidden.setChecked(data.get("run_hidden", False))
        layout.addWidget(self.chk_hidden)

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
        self.data["image_embedded"] = False
        self.data.pop("image_embedded_data", None)
        self.data.pop("image_format", None)
        self.data.pop("image_path_last_embedded", None)

        path = self.le_path.text().strip().lower()
        if path.startswith("http://") or path.startswith("https://"):
            fav = fetch_favicon_base64(path) or None
            if fav:
                self.data["image_embedded"] = True
                self.data["image_embedded_data"] = fav
                
                # faviconのフォーマットを検出
                try:
                    raw = base64.b64decode(fav)
                    self.data["image_format"] = detect_image_format(raw)
                except:
                    self.data["image_format"] = "data:image/png;base64,"
                    
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
        if icon_type == "Embed" and not path_txt and self.data.get("image_embedded_data"):
            pm = QPixmap()
            try:
                pm.loadFromData(b64decode(self.data["image_embedded_data"]))
            except Exception as e:
                warn(f"[PREVIEW] Failed to decode embed data: {e}")
                pm = QPixmap()
                    
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
        # 基本フィールド
        self.data["caption"] = self.le_caption.text()
        self.data["path"] = self.le_path.text()
        self.data["workdir"] = self.le_workdir.text()
        self.data["icon_index"] = self.spin_index.value()
        self.data["runas"] = self.chk_runas.isChecked()
        self.data["is_editable"] = self.chk_exe.isChecked()
        self.data["run_hidden"] = self.chk_hidden.isChecked()

        icon_type = self.combo_icon_type.currentText()
        icon_path = self.le_icon.text().strip()

        if icon_type == "Default":
            # Default モード - 埋め込みをクリア
            self.data["image_embedded"] = False
            self.data.pop("image_embedded_data", None)
            self.data.pop("image_format", None)
            self.data.pop("image_path_last_embedded", None)
            self.data.pop("image_width", None)
            self.data.pop("image_height", None)
            self.data.pop("image_bits", None)
            
            if icon_path:
                self.data["icon"] = icon_path
            else:
                self.data.pop("icon", None)

        else:  # Embed モード
            self.data.pop("icon", None)
            self.data["image_embedded"] = True
            
            # 既存の埋め込みデータを仮保持
            embed_b64 = self.data.get("image_embedded_data", "")
            
            # ユーザーが新規指定した場合
            if icon_path:
                try:
                    p = Path(icon_path)
                    idx = self.spin_index.value()
                    pm = None
                    if p.suffix.lower() in IMAGE_EXTS:
                        with open(icon_path, "rb") as fp:
                            raw = fp.read()
                        embed_b64 = base64.b64encode(raw).decode("ascii")
                        self.data["image_format"] = detect_image_format(raw)
                        pm = QPixmap(icon_path)
                    else:
                        pm = _load_pix_or_icon(icon_path, idx, ICON_SIZE)
                        if pm and not pm.isNull():
                            buf = QBuffer()
                            buf.open(QIODevice.OpenModeFlag.WriteOnly)
                            pm.save(buf, "PNG")
                            raw = buf.data()
                            embed_b64 = base64.b64encode(raw).decode("ascii")
                            self.data["image_format"] = "data:image/png;base64,"
                        else:
                            with open(icon_path, "rb") as fp:
                                raw = fp.read()
                            embed_b64 = base64.b64encode(raw).decode("ascii")
                            self.data["image_format"] = detect_image_format(raw)

                    if pm and not pm.isNull():
                        self.data["image_width"] = pm.width()
                        self.data["image_height"] = pm.height()
                        self.data["image_bits"] = pm.depth()

                except Exception as e:
                    warn(f"[EMBED] Failed to read file '{icon_path}': {e}")

                self.data["image_path_last_embedded"] = icon_path

            # プレビュー画像からキャプチャ
            elif not embed_b64:
                pm = self.lbl_prev.pixmap()
                if pm and not pm.isNull():
                    buf = QBuffer()
                    buf.open(QIODevice.OpenModeFlag.WriteOnly)
                    pm.save(buf, "PNG")
                    raw_data = buf.data()
                    embed_b64 = base64.b64encode(raw_data).decode("ascii")
                    
                    # PNG形式で保存されるのでPNGフォーマット
                    self.data["image_format"] = "data:image/png;base64,"
                    
                    # 画像情報を保存
                    self.data["image_width"] = pm.width()
                    self.data["image_height"] = pm.height()
                    self.data["image_bits"] = pm.depth()

            # 最終決定
            if embed_b64:
                self.data["image_embedded_data"] = embed_b64
                # image_formatが設定されていない場合のフォールバック
                if "image_format" not in self.data:
                    try:
                        raw = base64.b64decode(embed_b64)
                        self.data["image_format"] = detect_image_format(raw)
                    except:
                        self.data["image_format"] = "data:image/png;base64,"
            else:
                self.data["image_embedded"] = False
                self.data.pop("image_embedded_data", None)
                self.data.pop("image_format", None)

        super().accept()


    def _paste_icon(self):
        """GIFアニメーションを維持しつつ貼り付け - 新フィールド対応"""
        cb = QApplication.clipboard()
        mime = cb.mimeData()

        current_w = int(self.data.get("width", ICON_SIZE))
        current_h = int(self.data.get("height", ICON_SIZE))

        if mime.hasUrls():
            for qurl in mime.urls():
                path = qurl.toLocalFile()
                if path.lower().endswith(".gif"):
                    # GIF処理
                    with open(path, "rb") as fp:
                        gif_data = fp.read()
                    
                    # ★修正: 新フィールドのみを使用
                    self.data["image_embedded"] = True
                    self.data["image_embedded_data"] = base64.b64encode(gif_data).decode("ascii")
                    self.data["image_format"] = detect_image_format(gif_data)
                    self.data["image_path_last_embedded"] = path
                    
                    self.combo_icon_type.setCurrentText("Embed")
                    self.le_icon.clear()
                    
                    # プレビュー更新
                    self._update_preview()
                    self.data["width"], self.data["height"] = current_w, current_h
                    return

        # 静止画の場合
        if mime.hasImage():
            img = cb.image()
            if not img.isNull():
                pix = QPixmap.fromImage(img)

                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                pix.save(buf, "PNG")
                raw_data = buf.data()
                b64 = base64.b64encode(raw_data).decode("ascii")

                self.data["image_embedded"] = True
                self.data["image_embedded_data"] = b64
                self.data["image_format"] = "data:image/png;base64,"
                self.data["image_width"] = pix.width()
                self.data["image_height"] = pix.height()
                self.data["image_bits"] = pix.depth()

                self.combo_icon_type.setCurrentText("Embed")
                self.le_icon.clear()

                # プレビュー更新
                self._update_preview()
                return

        warn("Clipboardに画像またはGIFファイルが見つかりません")

# -------------------------------------------------- __all__ export --------------------------------------------------
__all__ = [
    "CanvasItem", "LauncherItem", "ImageItem", "JSONItem", 
    "CanvasResizeGrip",
    "ImageEditDialog", "BackgroundDialog","LauncherEditDialog"
]
