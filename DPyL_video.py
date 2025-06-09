"""
DPyL_video.py  ―  VideoItem / ResizeGrip / ポイント編集ダイアログ
◎ Qt6 / PyQt6 専用


留意事項
・ VideoItem は、CanvasItem を継承してません。
・ メンバーはほとんど同じ。

一部メソッド・プロパティ等は、呼び出しの際の区別のために、以下のように名称を変更しています。

-CamvasItem-   | -VideoItem-         | Note
 grip          |  video_resize_dots  | 変更中
 update_layout | _update_grip_pos    | _update_grip_pos に 戻した


"""

from __future__ import annotations
# ---------------------------
import os, copy
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsRectItem, QToolBar, QMessageBox,
    QFileDialog, QFileIconProvider, QStyleFactory, QDialog,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QMenu, QComboBox, QSpinBox,QCheckBox,
    QWidget, QSlider, QGraphicsProxyWidget
)

from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import (QVideoWidget, QGraphicsVideoItem)
from PyQt6.QtGui import (
    QPixmap, QPainter, QBrush, QColor, QPalette, QAction,
    QIcon, QImage, QPen, QTransform, QFont
)
from PyQt6.QtCore import (
    Qt, QSizeF, QPointF, QFileInfo, QProcess,
    QBuffer, QIODevice, QTimer, 
    QUrl,pyqtSignal
)
from functools import partial

# ------- internal modules -----------------------------------
from DPyL_utils   import warn, debug_print, ms_to_hms, hms_to_ms, VIDEO_EXTS
from DPyL_classes import CanvasResizeGrip
from DPyL_debug import my_has_attr


# ======================================================================
#   ResizeGripItem  (動画のリサイズ用グリップ)
# ======================================================================
class ResizeGripItem(QGraphicsRectItem):
    def __init__(self, target: "VideoItem"):
        super().__init__(target)
        try:
            self.target = target
            self.setRect(0, 0, 12, 12)
            self.setBrush(QBrush(Qt.GlobalColor.darkGray))
            
            # TEST ---
            #枠線 
            #w, h = self.target.size().width(), self.target.size().height()            
            #self.setRect(0, 0, w + 2, h + 2)
            #self.setBrush(Qt.BrushStyle.NoBrush)        # 塗りなし
            #self.setPen(QPen(QColor(200, 200, 200)))    # 枠線だけ描く（任意）
            # TEST ---
            
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            self.setZValue(10_000)
            self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            # Grip自体は動かさない
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self._drag = False
            self._was_movable = False  # ← 親アイテムの可動状態を一時保存
        except Exception as e:
            print(f"[VideoItem] init failed: {e}")        

    # ------------------------------------------------------------------
    def mousePressEvent(self, ev):
        """
        ドラッグ開始処理：
        ・ドラッグ開始位置と、元サイズを記録
        ・親（VideoItem）の可動フラグを一時OFF
        """
        self._drag  = True
        self._start = ev.scenePos()
        self._orig  = self.target.size()

        # 親アイテムの可動フラグ状態を保存してOFF
        f = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        self._was_movable = bool(self.target.flags() & f)
        if self._was_movable:
            self.target.setFlag(f, False)

        ev.accept()

    def mouseMoveEvent(self, ev):
        """
        ドラッグ中のリサイズ処理
        ・サイズ最小値(160x120)を維持
        ・VideoItem側に反映＆レイアウト更新
        """
        if self._drag:
            delta = ev.scenePos() - self._start
            w = max(160, self._orig.width()  + delta.x())
            h = max(120, self._orig.height() + delta.y())
            # --- スナップ適用 ---
            win = getattr(self.target, "win", None)
            if win:
                w, h = win.snap_size(self.target, w, h)
            else:
                my_has_attr(self.target,"win")
                
            self.target.setSize(QSizeF(w, h))
            self.target.d["width"], self.target.d["height"] = w, h
            self.target._update_grip_pos()
        ev.accept()
 
    def mouseReleaseEvent(self, ev):
        """
        ドラッグ終了処理：
        ・親の可動フラグを元に戻す
        """
        self._drag = False

        if self._was_movable:
            self.target.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

        ev.accept()
    def update_zvalue(self):
        """
        グリップのZ値を常に親アイテムの1上に設定
        """
        parent = self.parentItem()
        if parent:
            self.setZValue(parent.zValue() + 1)
# ======================================================================
#   VideoItem
# ======================================================================
class TimeLabel(QLabel):
    """
    再生時刻表示用ラベル  
    ダブルクリックで現在時刻をコピーできる
    """
    doubleClicked = pyqtSignal()
    # mouseDoubleClickEvent実装は省略・未使用

class VideoItem(QGraphicsVideoItem):
    """
    ・右下にリサイズグリップ付き  
    ・下部に再生/ミュート/スライダー/ジャンプボタン等のコントロール  
    ・Toolbarから一括制御可能（self.btn_play, self.btn_mute公開）
    ・_jump(idx)でジャンプ再生
    """

    TYPE_NAME = "video"
    @classmethod
    def supports_path(cls, path: str) -> bool:
        return Path(path).suffix.lower() in VIDEO_EXTS

    @classmethod
    def create_from_path(cls, path: str, sp, win):
        d = {
            "type": "video",
            "path": path,
            "autoplay": False,
            "x": sp.x(), "y": sp.y(),
            "width": 320, "height": 180
        }
        #from DPyL_video import VideoItem
        return VideoItem(d, win=win), d

    # --------------------------------------------------------------
    def __init__(self, d: dict[str, Any], *, win=None):
        super().__init__()
        self.run_mode = True
        self.d   = d
        self.win = win
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setZValue(d.get("z", 0))

        # ---- サイズ設定 ------------------------------------------
        w = d.get("width", 320)
        h = d.get("height", 180)
        self.setSize(QSizeF(w, h))
    
        # アスペクト固定で外側クロップ（Cover挙動）
        self.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        # 自分自身を形状でクリップ（QGraphicsVideoItemの二重描画対策）
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, True)

        # -- 前回のシーン矩形（残像クリア用）を保持
        self._prev_scene_rect = self.boundingRect().translated(self.pos())

        # ---- player / audio --------------------------------------
        self.player = QMediaPlayer(self)
        self.audio  = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self)

        path = d.get("path", "")
        if path and Path(path).exists():
            self.player.setSource(QUrl.fromLocalFile(path))
        else:
            warn(f"Video path not found: {path}")

        # autoplay時はミュートで再生
        if d.get("autoplay", False):
            self.audio.setMuted(True)
            self.player.play()

        # ---- UI生成 ---------------------------------------------
        self._build_ctrl()
        self.video_resize_dots = ResizeGripItem(self)
        self._update_grip_pos()

        # ---- シグナル接続 ---------------------------------------
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)

        # ---- ジャンプポイント -----------------------------------
        self.points = copy.deepcopy(self.d.get("points", [
            {"start": 0, "end": None, "repeat": False},
            {"start": 0, "end": None, "repeat": False},
            {"start": 0, "end": None, "repeat": False},
        ]))
        self.active_point_index: int | None = None

        # アイテムフラグ（可動・ジオメトリ変更通知）
        self.setFlag(self.flags() | self.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(self.flags() | self.GraphicsItemFlag.ItemSendsGeometryChanges)
            
        # ミュート状態をUIとaudio両方に反映
        muted = self.d.get("muted", False)
        self.btn_mute.setChecked(muted)
        self.audio.setMuted(muted)
        self.btn_mute.clicked.connect(lambda c: (
            self.audio.setMuted(c),
            self.d.__setitem__("muted", c)
        ))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        
        self.set_editable(False)
        self._update_grip_pos()

    # -------------------------------------------------------------
    #   ミュート制御
    # -------------------------------------------------------------
    def set_muted(self, on: bool):
        """
        ミュートON/OFFをUI/プレイヤー/データに反映
        """
        if my_has_attr(self,"btn_mute"):
            self.btn_mute.setChecked(on)
        if my_has_attr(self,"player"):
            self.player.setMuted(on)
        self.d["muted"] = bool(on)

    def on_mute_btn_clicked(self):
        """
        ミュートボタンのトグル切替時処理
        """
        on = not self.d.get("muted", False)
        self.set_muted(on)
    
    # --------------------------------------------------------------
    #   コントロールUI構築
    # --------------------------------------------------------------
    def _build_ctrl(self):
        """
        再生・ジャンプ・編集・ミュートなどのUIを構築
        （VideoItem直下に配置）
        """
        self.ctrl_widget = QWidget()
        self.ctrl_widget.setStyleSheet("QWidget { background:rgba(0,0,0,160); }"
                                       "QLabel, QPushButton { color:#fff; }")
        lay = QVBoxLayout(self.ctrl_widget)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        # --- row1: 再生・スライダー・時刻ラベル ---------------------
        r1 = QHBoxLayout()
        self.btn_play = QPushButton("▶")
        self.btn_play.setCheckable(True)
        self.btn_play.clicked.connect(lambda c: self._toggle_play(c))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        
        # ✅ QLabel→TimeLabelに変更し、信号接続OK
        self.lbl_time = TimeLabel("00:00:00.000 / 00:00:00.000")
        # self.lbl_time.doubleClicked.connect(self._copy_time_to_clipboard)
        
        r1.addWidget(self.btn_play)
        r1.addWidget(self.slider, 1)
        r1.addWidget(self.lbl_time)

        # --- row2: ジャンプ＋編集＋ミュート -------------------------
        r2 = QHBoxLayout()
        self.btn_jump1 = QPushButton("[1]")
        self.btn_jump1.clicked.connect(lambda: self._jump(0))
        self.btn_jump2 = QPushButton("[2]")
        self.btn_jump2.clicked.connect(lambda: self._jump(1))
        self.btn_jump3 = QPushButton("[3]")
        self.btn_jump3.clicked.connect(lambda: self._jump(2))
        self.btn_edit  = QPushButton("Edit")
        self.btn_edit.clicked.connect(self._edit_points)
        self.btn_mute  = QPushButton("Mute")
        self.btn_mute.setCheckable(True)
        self.btn_mute.clicked.connect(lambda c: self.audio.setMuted(c))
        r2.addWidget(self.btn_jump1)
        r2.addWidget(self.btn_jump2)
        r2.addWidget(self.btn_jump3)
        r2.addWidget(self.btn_edit)
        r2.addWidget(self.btn_mute)

        lay.addLayout(r1)
        lay.addLayout(r2)

        self.ctrl_proxy = QGraphicsProxyWidget(self)
        self.ctrl_proxy.setWidget(self.ctrl_widget)

    def _copy_time_to_clipboard(self):
        """
        時刻ラベルの「左側（現在時刻）」をクリップボードにコピー
        """
        text = self.lbl_time.text().split('/', 1)[0].strip()
        QApplication.clipboard().setText(text)

    # --------------------------------------------------------------
    #   VideoItem / レイアウト更新ヘルパ
    # --------------------------------------------------------------
    def _update_grip_pos(self):
        """
        コントロールとグリップの位置をVideoサイズに合わせて再配置
        """
        sz = self.size()
        # コントロールを動画下に配置
        self.ctrl_proxy.setPos(0, sz.height())
        self.ctrl_widget.setFixedWidth(int(sz.width()))
        self.ctrl_widget.adjustSize()
        # グリップを右下へ
        self.video_resize_dots.setPos(sz.width() - self.video_resize_dots.rect().width(),
                                sz.height() - self.video_resize_dots.rect().height())
        self.video_resize_dots.update_zvalue()
    # --------------------------------------------------------------
    #   VideoItem / プレイヤーコールバック
    # --------------------------------------------------------------
    def _on_pos(self, pos: int):
        """
        再生位置変更時のUI更新・ポイント制御
        """
        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)

        dur = self.player.duration() or 1
        cur_txt = ms_to_hms(pos)
        tot_txt = ms_to_hms(dur)
        self.lbl_time.setText(f"{cur_txt} / {tot_txt}")

        # ポイント再生ロジック
        if self.active_point_index is not None:
            pt = self.points[self.active_point_index]
            end = pt.get("end")
            if end is not None and pos >= end:
                if pt.get("repeat", False):
                    self.player.setPosition(pt["start"])
                else:
                    self.player.pause()
                    self.btn_play.setChecked(False)
                    self.btn_play.setText("▶")
                    self.active_point_index = None  # ←絶対必要！

    def _on_dur(self, dur: int):
        """
        動画長さ更新時：スライダー範囲更新
        """
        self.slider.setRange(0, dur)

    # --------------------------------------------------------------
    #   VideoItem / コントロール操作
    # --------------------------------------------------------------
    def _toggle_play(self, checked: bool):
        """
        再生/一時停止ボタンのトグル切替時
        """
        if checked:
            self.player.play()
            self.btn_play.setText("⏸")
        else:
            self.player.pause()
            self.btn_play.setText("▶")
            self.active_point_index = None  # ←これ必須！

    def _jump(self, idx: int):
        """
        ジャンプボタン押下時：該当ポイントから再生開始
        """
        if idx >= len(self.points):
            return
        pt  = self.points[idx]
        pos = pt.get("start", 0)

        # --- 未初期化メディアチェック ---
        if self.player.source().isEmpty():
            warn(f"[video] source not set, can't jump: {self.d.get('file')}")
            return

        # --- WMF/Pause→seek フリーズ対策 -------------------------
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
            QTimer.singleShot(10, lambda: self.player.setPosition(pos))
        else:
            self.player.setPosition(pos)

        self.btn_play.setChecked(True)
        self.btn_play.setText("⏸")
        self.active_point_index = idx


    # --------------------------------------------------------------
    #  VideoItem / ポイント編集ダイアログ
    # --------------------------------------------------------------
    def _edit_points(self):
        """
        ポイント編集ダイアログをノンモーダルで表示
        """
        view = self.scene().views()[0] if self.scene().views() else None

        points = copy.deepcopy(self.d.get("points", [
            {"start": 0, "end": None, "repeat": False},
            {"start": 0, "end": None, "repeat": False},
            {"start": 0, "end": None, "repeat": False},
        ]))

        dlg = VideoEditDialog(points, self.d, video_item=self, parent=view)
        # show()で非同期表示
        dlg.accepted.connect(lambda: self._edit_points_apply(dlg))
        dlg.rejected.connect(lambda: dlg.deleteLater())  # メモリリーク防止
        dlg.show()

    def _edit_points_apply(self, dlg):
        """
        ポイント編集ダイアログからの結果適用
        """
        try:
            result = dlg.get_result()
            if not isinstance(result, list):
                raise TypeError("Invalid result from dialog")

            # 編集結果を反映
            self.points = copy.deepcopy(result)
            self.d["points"] = copy.deepcopy(result)
            self._update_grip_pos()

        except Exception as e:
            #import traceback
            #traceback.print_exc()
            warn(f"[VideoItem] Edit failed: {e}")
        finally:
            dlg.deleteLater()  # メモリ解放

    # --------------------------------------------------------------
    #   itemChange → 位置・サイズ保存
    # --------------------------------------------------------------
    def itemChange(self, change, value):
        """
        QGraphicsItem標準のitemChange拡張  
        ・移動/サイズ変更時に座標・サイズ保存＆シーンを更新
        ・スナップ処理もここで実行
        """
        if change == self.GraphicsItemChange.ItemPositionChange:
            # 移動前の矩形を記録
            self._prev_scene_rect = self.boundingRect().translated(value)

        elif change == self.GraphicsItemChange.ItemPositionHasChanged:
            # 旧位置をシーンからクリア
            if self.scene() and self._prev_scene_rect:
                self.scene().update(self._prev_scene_rect)

            self.d["x"], self.d["y"] = self.pos().x(), self.pos().y()

            # スナップ処理
            view = self.scene().views()[0]
            snapped = view.win.snap_position(self, self.pos())
            if snapped != self.pos():
                self.setPos(snapped)

        elif change == self.GraphicsItemChange.ItemTransformHasChanged:
            # リサイズ後に旧領域クリア
            if self.scene() and self._prev_scene_rect:
                self.scene().update(self._prev_scene_rect)
            self.d["width"], self.d["height"] = self.size().width(), self.size().height()

            # 新しい矩形を記録
            self._prev_scene_rect = self.boundingRect().translated(self.pos())
            self.d["width"], self.d["height"] = self.size().width(), self.size().height()

        return super().itemChange(change, value)
    # --------------------------------------------------------------
    #   ダブルクリックで動画ファイルを外部再生
    # --------------------------------------------------------------
    def mouseDoubleClickEvent(self, ev):
        """
        ダブルクリックでファイルパスが存在すれば既定アプリで開く
        """
        path = self.d.get("path", "")
        if os.path.exists(path):
            os.startfile(path)
        super().mouseDoubleClickEvent(ev)
        ev.accept()

    # --------------------------------------------------------------
    #   VideoItem削除処理
    # --------------------------------------------------------------
    def delete_self(self):
        """
        VideoItemの安全な削除処理

        1) 先にシーンから自分を外して描画ロックを解除
        2) 映像・音声出力をデタッチしてから stop()   ← WMFデッドロック回避 ← MainをSafeApp化した状態だとかえってハングアップする
        3) シグナル切断
        4) コントロール UI（ctrl_proxy / ctrl_widget）を完全破棄
        5) メディアソース解放 → プレイヤ／オーディオを deleteLater
        6) 最後に self を deleteLater
        
        """
        debug_print("STEP-A  remove from scene")
        if self.scene():                             # ① Scene から外す
            self.scene().removeItem(self)

        debug_print("STEP-B  detach outputs")              # ② 出力デタッチ
        #self.player.setVideoOutput(None)            # MainをSafeApp化した状態だとハングアップする
        #self.player.setAudioOutput(None)            # MainをSafeApp化した状態だとハングアップする

        debug_print("STEP-C  stop player")                 # ③ stop()
        #self.player.stop()                          # MainをSafeApp化した状態だとハングアップする

        debug_print("STEP-D  disconnect signals")          # ④ シグナル切断
        try:
            self.player.positionChanged.disconnect()
            self.player.durationChanged.disconnect()
        except TypeError:
            pass

        debug_print("STEP-E  destroy control UI")          # ⑤ UI の後始末
        if getattr(self, "ctrl_proxy", None):
            self.ctrl_proxy.setWidget(None)
            if self.ctrl_proxy.scene():
                self.ctrl_proxy.scene().removeItem(self.ctrl_proxy)
            self.ctrl_proxy.deleteLater()
            self.ctrl_proxy = None

        if getattr(self, "ctrl_widget", None):
            self.ctrl_widget.deleteLater()
            self.ctrl_widget = None

        debug_print("STEP-F  clear source")                # ⑥ メディアソース解放
        self.player.setSource(QUrl())

        debug_print("STEP-G  delete player/audio")         # ⑦ プレイヤ／オーディオ破棄
        self.player.deleteLater()
        self.audio.deleteLater()

        debug_print("STEP-H  delete self")                 # ⑧ 自身を非同期削除
        self.deleteLater()


    # --------------------------------------------------------------
    #   右クリックでメニューをMainWindowに委譲
    # --------------------------------------------------------------
    def contextMenuEvent(self, event):
        """
        右クリック時はMainWindow共通メニューへ委譲。
        削除時はMainWindow._remove_item()経由で完全消去される。
        """
        win = self.scene().views()[0].window()
        win.show_context_menu(self, event)

    # ------------------------------------------------------------------
    #   枠リサイズ：動画フレームをCover＆中央寄せクロップ
    # ------------------------------------------------------------------
    def resize_content(self, w: int, h: int):
        """
        動画フレームを「外側クロップ（Cover）」でリサイズし、中央に寄せる
        ・旧バウンディング矩形を再描画して残像クリア
        ・リサイズ後はグリップ/コントロール再配置
        """
        # ① 旧シーン矩形を保存
        old_rect = self.boundingRect().translated(self.pos())

        ns = self.nativeSize()
        if not ns.isValid() or ns.width() == 0 or ns.height() == 0:
            return

        vw, vh = ns.width(), ns.height()

        # ② Coverスケール計算
        scale = max(w / vw, h / vh)
        sw, sh = vw * scale, vh * scale
        self.setSize(QSizeF(sw, sh))

        # ③ 中央寄せクロップ (負オフセット)
        ox = (sw - w) / 2
        oy = (sh - h) / 2
        self.setOffset(QPointF(-ox, -oy))

        # ⑤ 旧領域を再描画して残像クリア
        if self.scene():
            self.scene().update(old_rect)

        # ⑥ 新しい矩形を記録
        self._prev_scene_rect = self.boundingRect().translated(self.pos())

        # ⑦ グリップとコントロールを再配置
        self._update_grip_pos()

    def get_current_time_ms(self):
        """
        現在の再生位置（ms単位）を返す
        """
        return int(self.player.position())

    def prepare_for_deletion(self):
        """
        削除準備処理（再生停止、メディア解放、シグナル切断）
        """
        self.player.stop()
        self.player.setSource(QUrl())
        try:
            self.player.positionChanged.disconnect()
            self.player.durationChanged.disconnect()
        except TypeError:
            pass

    def finalize_deletion(self):
        """
        実際のオブジェクト削除処理
        """
        self.player.deleteLater()
        self.audio.deleteLater()
        if self.scene():
            self.scene().removeItem(self)
        self.deleteLater()
        

    def set_run_mode(self, run: bool):
        """実行(True)/編集(False)モード切替"""
        self.run_mode = run
        self.set_editable(not run)

    def set_editable(self, editable: bool):
        self.video_resize_dots.setVisible(editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, editable)        
        
    def init_caption(self):
        pass
            

class VideoItemController:
    """
    VideoItemの削除を同期/非同期で実行するコントローラ
    実装保留
    """
    def __init__(self, item: VideoItem):
        self.item = item

    async def delete_async(self):
        self.item.prepare_for_deletion()
        await asyncio.sleep(0.05)
        self.item.finalize_deletion()

    def delete(self):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.delete_async())
        except RuntimeError:
            self.item.prepare_for_deletion()
            self.item.finalize_deletion()

# ======================================================================
#   VideoEditDialog
# ======================================================================
class VideoEditDialog(QDialog):
    """
    3つのジャンプポイント (start / end / repeat) を編集できるダイアログ
    * 時間表記は "hh:mm:ss:zzz" または "mm:ss:zzz" もOK
    """
    def __init__(self, pts: list[dict], d: dict, video_item=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("編集：再生ポイント")
        self.points = copy.deepcopy(pts)
        self.data   = d
        self.video_item = video_item 
        self._build_ui()

    def _build_ui(self):
        """
        ダイアログUI（各ポイント行＋OK/Cancel）
        """
        lay = QVBoxLayout(self)
        self._rows = []
        for i in range(3):
            row = QHBoxLayout()
            start = QLineEdit(ms_to_hms(self.points[i].get("start", 0)))
            btn_start = QPushButton("SET")
            btn_start.clicked.connect(partial(self._copy_current_time, i, "start"))

            end_v = self.points[i].get("end")
            end   = QLineEdit("" if end_v is None else ms_to_hms(end_v))
            btn_end = QPushButton("SET")
            btn_end.clicked.connect(partial(self._copy_current_time, i, "end"))

            rep   = QPushButton("repeat")
            rep.setCheckable(True)
            rep.setChecked(self.points[i].get("repeat", False))
            row.addWidget(QLabel(f"[{i+1}]"))
            row.addWidget(start)
            row.addWidget(btn_start)
            row.addWidget(QLabel("～"))
            row.addWidget(end)
            row.addWidget(btn_end)
            row.addWidget(rep)
            lay.addLayout(row)
            self._rows.append((start, end, rep))

        bot = QHBoxLayout()
        bot.addStretch(1)
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        ng = QPushButton("Cancel")
        ng.clicked.connect(self.reject)
        bot.addWidget(ok)
        bot.addWidget(ng)
        lay.addLayout(bot)
        self.resize(480, 210)

    def _copy_current_time(self, idx, kind):
        """
        SETボタン押下時に現在動画位置(ms)を取得し、該当欄へコピー
        """
        ms = self._get_current_video_time_ms()
        text = ms_to_hms(ms)
        if kind == "start":
            self._rows[idx][0].setText(text)
        else:
            self._rows[idx][1].setText(text)

    def _get_current_video_time_ms(self):
        """
        VideoItemから現在位置(ms)を取得
        """
        if self.video_item is not None:
            return self.video_item.get_current_time_ms()
        return 0
    
    def _load_current(self):
        """
        現在再生位置を [1] start へコピー
        （※未使用／旧実装の名残）
        """
        win = self.parent()
        pos = 0
        if win and my_has_attr(win, "parent") and callable(win.parent):
            pass
        try:
            video_item = self.parent().parent().parent()
            pos = video_item.player.position()
        except Exception:
            return
        self._rows[0][0].setText(ms_to_hms(pos))

    # --------------------------------------------------------------
    def accept(self):
        """
        OKボタン時、各フィールドの内容をmsへ変換・pointsへ反映
        """
        for i, (st_edit, ed_edit, rep_btn) in enumerate(self._rows):
            try:
                st_text = st_edit.text().strip()
                ed_text = ed_edit.text().strip()
                st_ms = hms_to_ms(st_text) if st_text else 0
                ed_ms = hms_to_ms(ed_text) if ed_text else None
            except Exception as e:
                warn(f"[VideoEditDialog] 時刻変換失敗: {e}")
                st_ms = 0
                ed_ms = None

            self.points[i]["start"]  = st_ms
            self.points[i]["end"]    = ed_ms
            self.points[i]["repeat"] = rep_btn.isChecked()

        super().accept()

    def get_result(self) -> list[dict]:
        """
        編集ダイアログの各ポイント内容をdictリストで返す
        """
        new_points = []
        for start_edit, end_edit, repeat_check in self._rows:
            try:
                start = hms_to_ms(start_edit.text().strip())
            except Exception as e:
                warn(f"[WARN] start parse failed: {e}")
                start = 0
            try:
                end_txt = end_edit.text().strip()
                end = hms_to_ms(end_txt) if end_txt else None
            except Exception as e:
                warn(f"[WARN] end parse failed: {e}")
                end = None
            repeat = repeat_check.isChecked()
            new_points.append({"start": start, "end": end, "repeat": repeat})
        return new_points

# ======================================================================
#   exports
# ======================================================================
__all__ = [
    "VideoItem",
]
