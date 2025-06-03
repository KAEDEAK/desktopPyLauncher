# -*- coding: utf-8 -*-
"""
desktopPyLauncher.py ― エントリポイント
◎ Qt6 / PyQt6 専用
"""
from __future__ import annotations

# --- 標準・サードパーティライブラリ ---
import sys, json, base64, os, inspect, traceback
from datetime import datetime
from pathlib import Path

    
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsRectItem, QToolBar, QMessageBox,
    QFileDialog, QFileIconProvider, QStyleFactory, QDialog,
    QLabel, QLineEdit, QTextEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QToolButton, QMenu, QComboBox, QSpinBox, QCheckBox, QSizePolicy,
    QWidget, QSlider, QGraphicsProxyWidget
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem
from PyQt6.QtGui import (
    QPixmap, QPainter, QBrush, QColor, QPalette, QAction,
    QIcon, QImage, QPen, QTransform, QFont
)
from PyQt6.QtCore import (
    Qt, QRectF, QSizeF, QPointF, QFileInfo, QProcess,
    QBuffer, QIODevice, QTimer, 
    QUrl
)
# --- プロジェクト内モジュール ---
from DPyL_utils   import (
    warn, b64e, fetch_favicon_base64,
    compose_url_icon, b64encode_pixmap, normalize_unc_path, 
    is_network_drive, _icon_pixmap, _default_icon, _load_pix_or_icon, ICON_SIZE
)
from DPyL_classes import (
    LauncherItem, JSONItem, ImageItem, GifItem,
    CanvasItem, CanvasResizeGrip,
    BackgroundDialog
)


from DPyL_note    import NoteItem
from DPyL_video   import VideoItem
from DPyL_marker import MarkerItem
from configparser import ConfigParser
from urllib.parse import urlparse

from DPyL_debug import (my_has_attr,dump_missing_attrs,trace_this)

EXPAND_STEP = 500  # 端に到達したときに拡張する幅・高さ（px）

# ==============================================================
# ミニマップ
# ==============================================================
class MiniMapWidget(QWidget):
    """
    ミニマップを表示するためのカスタムウィジェット。
    - 親として MainWindow インスタンスを受け取り、その scene や view の情報を参照して描画を行う。
    - 表示されたあと、一定時間（ここでは3秒）経過すると自動的に非表示になるタイマーを持つ。
    """
    def __init__(self, win: "MainWindow", parent=None):
        super().__init__(parent)
        self.win = win
        # ミニマップ自体の固定サイズ（お好みで変更可）
        self.setFixedSize(200, 200)
        # 背景を半透明の黒（やや暗め）、境界線を黒 1px で設定
        #self.setStyleSheet("background-color: rgba(0, 0, 0, 150); border: 1px solid black;")
        # 境界線だけはスタイルシートで指定（背景は paintEvent で自力塗りつぶす）
        self.setStyleSheet("border: 1px solid black;")

        # --- 3秒後に自動的に hide() するためのタイマーを用意 ---
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        # タイマーが期限切れになったら this.hide() を呼ぶ
        self._hide_timer.timeout.connect(self.hide)

    def updateVisibility(self):
        """
        現在のビューポートがシーン全体をほぼ覆っているかを判定し、
        『ほぼ全体（90%以上）をカバー＋位置的に10%マージン内』の場合は非表示にし、
        それ以外の場合は表示して「3秒後に自動非表示タイマー」をスタートする。
        """
        # -- scene が既に破棄されている場合に備えて例外キャッチする --
        try:
            scene = self.win.scene
            scene_rect: QRectF = scene.sceneRect()
        except Exception:
            # QGraphicsScene が削除済みなどでアクセスできない場合は何もしない
            return
        view = self.win.view
        if scene_rect.isEmpty():
            # シーンサイズが空ならミニマップ自体を非表示
            self._hide_timer.stop()
            self.hide()
            return

        # ビューポート内の矩形領域（シーン座標）を取得
        visible_scene_rect: QRectF = view.mapToScene(view.viewport().rect()).boundingRect()

        # 「表示範囲がシーン全体の90%以上をカバーしていれば非表示」とするマージン付き判定
        #   動作イメージ：幅・高さそれぞれについて 0.9（＝90%） のしきい値を設ける
        threshold = 0.5
        w_scene = scene_rect.width()
        h_scene = scene_rect.height()
        w_vis   = visible_scene_rect.width()
        h_vis   = visible_scene_rect.height()

        # ① 幅・高さとも「ビューポートのサイズがしきい値×シーンサイズ以上」であれば大きさ的にはOK
        cond_size = (w_vis >= w_scene * threshold) and (h_vis >= h_scene * threshold)
        # ② 位置的にも「ビューポートの左端／上端がシーンの左端／上端よりはみ出していない」
        #    かつ「ビューポートの右端／下端がシーンの右端／下端よりはみ出していない」かどうかをチェック
        #    ここでは、許容マージンを幅・高さ各 10% として算出する
        margin_w = w_scene * (1 - threshold)  # 例：幅の10%分
        margin_h = h_scene * (1 - threshold)  # 例：高さの10%分
        cond_pos = (
            (visible_scene_rect.left()   <= scene_rect.left() + margin_w) and
            (visible_scene_rect.top()    <= scene_rect.top()  + margin_h) and
            (visible_scene_rect.right()  >= scene_rect.right()  - margin_w) and
            (visible_scene_rect.bottom() >= scene_rect.bottom() - margin_h)
        )

        # -------------- 判定結果に応じて表示／タイマー制御 --------------
        if cond_size and cond_pos:
            # 「ほぼ全体をカバーしている」と判断 → 非表示
            self._hide_timer.stop()
            self.hide()
        else:
            # それ以外 → 表示し、3秒後に自動非表示タイマーをスタート
            # （既にタイマーが動いている場合はリスタート）
            self.show()
            self.update()
            self._hide_timer.start(3000)

    def paintEvent(self, event):
        #painter = QPainter(self)
        #painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # ① 背景を自力で半透明黒に塗りつぶす
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))        

        scene = self.win.scene
        view = self.win.view

        # シーン全体の矩形を取得
        scene_rect: QRectF = scene.sceneRect()
        if scene_rect.isEmpty():
            painter.end()
            return

        # ミニマップ描画領域の大きさ
        w_map = self.width()
        h_map = self.height()

        # シーン全体を縮小してミニマップ内に収めるためのスケールを算出
        scale_x = w_map / scene_rect.width()
        scale_y = h_map / scene_rect.height()
        scale = min(scale_x, scale_y)

        # 縮小後、ミニマップ中央に余白をつくるためのオフセット
        offset_x = (w_map - scene_rect.width() * scale) / 2
        offset_y = (h_map - scene_rect.height() * scale) / 2

        # 1) シーン内のオブジェクトを青の半透過矩形で描画
        pen_item = QPen(QColor(0, 0, 255))
        brush_item = QBrush(QColor(0, 0, 255, 100))
        for item in scene.items():
            try:
                rect: QRectF = item.sceneBoundingRect()
            except Exception:
                continue
            x = (rect.x() - scene_rect.x()) * scale + offset_x
            y = (rect.y() - scene_rect.y()) * scale + offset_y
            w = rect.width() * scale
            h = rect.height() * scale
            painter.setPen(pen_item)
            painter.setBrush(brush_item)
            painter.drawRect(QRectF(x, y, w, h))

        # 2) 現在のビューポート範囲を赤い枠で描画
        visible_scene_rect: QRectF = view.mapToScene(view.viewport().rect()).boundingRect()
        vx = (visible_scene_rect.x() - scene_rect.x()) * scale + offset_x
        vy = (visible_scene_rect.y() - scene_rect.y()) * scale + offset_y
        vw = visible_scene_rect.width() * scale
        vh = visible_scene_rect.height() * scale
        pen_view = QPen(QColor(255, 0, 0), 2)
        painter.setPen(pen_view)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(vx, vy, vw, vh))

        painter.end()
        
# ==============================================================
#  CanvasView - キャンバス表示・ドラッグ&ドロップ対応
# ==============================================================
class CanvasView(QGraphicsView):
    def __init__(self, scene, win):
        super().__init__(scene, win)
        self.win = win
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setRenderHint(self.renderHints() | self.renderHints().Antialiasing)

        # --- スクロールバー端到達時のシーン拡張 ---
        self.horizontalScrollBar().valueChanged.connect(self._on_hscroll)
        self.verticalScrollBar().valueChanged.connect(self._on_vscroll)
        
    def dragEnterEvent(self, e): 
        # ファイルやURLドロップの受付
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)
        
    def dragMoveEvent(self, e):  
        e.acceptProposedAction()
        
    def dropEvent(self, e):      
        self.win.handle_drop(e)
    
    def mouseMoveEvent(self, ev):
        # 親のマウスムーブイベント（＝スクロール処理など）を先に実行
        super().mouseMoveEvent(ev)

        # ビューポートに映っているシーン領域を取得
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        scene = self.scene()
        if scene:
            scene_rect = scene.sceneRect()
            # ビューに映る領域がシーン外ならシーンを拡張
            if not scene_rect.contains(rect):
                new_rect = scene_rect.united(rect)
                scene.setSceneRect(new_rect)

    def mousePressEvent(self, ev):
        # 右クリック時、空白エリアならペーストメニュー表示
        if ev.button() == Qt.MouseButton.RightButton:
            pos = ev.position().toPoint()
            scene_pos = self.mapToScene(pos)
            items = self.items(pos)
            if not items:
                menu = QMenu(self)
                act_paste = menu.addAction("ペースト")

                # --- クリップボードの内容を判定して有効/無効を切替 ---
                cb = QApplication.clipboard()
                can_paste = False

                try:
                    js = json.loads(cb.text())
                    if isinstance(js, dict):
                        can_paste = "items" in js and isinstance(js["items"], list)
                    elif isinstance(js, list):
                        can_paste = all(isinstance(d, dict) for d in js)
                except Exception:
                    pass

                # 静止画 or GIFファイルURL を貼れるように判定
                if not can_paste:
                    mime = cb.mimeData()
                    if mime.hasImage():
                        can_paste = True
                    elif mime.hasUrls() and any(
                        u.isLocalFile() and u.toLocalFile().lower().endswith(".gif")
                        for u in mime.urls()
                    ):
                        can_paste = True                    
                act_paste.setEnabled(can_paste)

                sel = menu.exec(ev.globalPosition().toPoint())
                if sel == act_paste:
                    pasted_items = []
                    mime = cb.mimeData()
                    # 1) クリップボードにGIFファイルURLがあれば優先貼り付け
                    if mime.hasUrls():
                        for u in mime.urls():
                            if u.isLocalFile() and u.toLocalFile().lower().endswith(".gif"):
                                path = u.toLocalFile()
                                # ファクトリ経由でGifItemを生成・追加
                                item, d = self.win._create_item_from_path(path, scene_pos)
                                if item:
                                    self.win.scene.addItem(item)
                                    self.win.data["items"].append(d)
                                    pasted_items.append(item)
                                break
                    # 2) GIFがなければ従来の画像／JSON貼り付け
                    if not pasted_items:
                        self.win._paste_image_if_available(scene_pos)
                        pasted_items = self.win._paste_items_at(scene_pos)
                    if pasted_items:
                        for item in pasted_items:
                            item.set_editable(True)
                            item.set_run_mode(False)
                ev.accept()
                return
        super().mousePressEvent(ev)
        
    def _on_vscroll(self, value: int):
        vbar = self.verticalScrollBar()
        scene = self.scene()
        if not scene:
            return
        rect = scene.sceneRect()
        # 「下端」に達したら下方向に領域を広げる
        if value >= vbar.maximum():
            new_rect = QRectF(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height() + EXPAND_STEP
            )
            scene.setSceneRect(new_rect)
            # スクロールバー範囲を更新
            new_max = int(new_rect.height() - self.viewport().height())
            if new_max < 0:
                new_max = 0
            vbar.setRange(int(new_rect.y()), int(new_rect.y() + new_max))
        # 「上端」に達したら上方向に領域を広げる
        elif value <= vbar.minimum():
            new_rect = QRectF(
                rect.x(),
                rect.y() - EXPAND_STEP,
                rect.width(),
                rect.height() + EXPAND_STEP
            )
            scene.setSceneRect(new_rect)
            # 上方向に広げたぶん、スクロール位置をシフトさせる
            vbar.setRange(int(new_rect.y()), int(new_rect.y() + new_rect.height() - self.viewport().height()))
            vbar.setValue(vbar.minimum() + EXPAND_STEP)
            
    def _on_hscroll(self, value: int):
        hbar = self.horizontalScrollBar()
        scene = self.scene()
        if not scene:
            return
        rect = scene.sceneRect()
        # 「右端」に達したら右方向に領域を広げる
        if value >= hbar.maximum():
            new_rect = QRectF(
                rect.x(),
                rect.y(),
                rect.width() + EXPAND_STEP,
                rect.height()
            )
            scene.setSceneRect(new_rect)
            # スクロールバー範囲を更新
            new_max = int(new_rect.width() - self.viewport().width())
            if new_max < 0:
                new_max = 0
            hbar.setRange(int(new_rect.x()), int(new_rect.x() + new_max))
        # 「左端」に達したら左方向に領域を広げる
        elif value <= hbar.minimum():
            new_rect = QRectF(
                rect.x() - EXPAND_STEP,
                rect.y(),
                rect.width() + EXPAND_STEP,
                rect.height()
            )
            scene.setSceneRect(new_rect)
            # 左方向に広げたぶん、スクロール位置をシフトさせる
            hbar.setRange(int(new_rect.x()), int(new_rect.x() + new_rect.width() - self.viewport().width()))
            hbar.setValue(hbar.minimum() + EXPAND_STEP)

# ==============================================================
#  MainWindow - メインウィンドウ
# ==============================================================
class MainWindow(QMainWindow):
    def __init__(self, json_path: Path):
        super().__init__()
        self.loading_label = QLabel("LOADING...", self)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet(
            "font-size: 32px; color: white; background-color: rgba(0, 0, 0, 160);"
        )
        self.loading_label.setGeometry(self.rect())
        self.loading_label.setVisible(False)

        self.json_path = json_path.expanduser().resolve()
        os.chdir(self.json_path.parent)
        self.data: dict = {"items": []}
        self.text_color = self.palette().color(QPalette.ColorRole.Text)
        self._ignore_window_geom = False
        self.bg_pixmap = None

        # --- 履歴（ツールバーより先に初期化） ---
        self.history: list[Path] = []
        self.hidx: int = -1

        # --- シーンとビューのセットアップ ---
        self.scene = QGraphicsScene(self)
        self.view  = CanvasView(self.scene, self)
        self.setCentralWidget(self.view)
        self.scene.sceneRectChanged.connect(lambda _: self._apply_background())

        # --- 背景リサイズ用タイマー ---
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_background)

        # --- UI初期化 ---
        self._toolbar()
        self.setWindowTitle(f"desktopPyLauncher - {self.json_path.name}")
        self.resize(900, 650)
        
        # --- ミニマップを生成して右上に配置 ---
        self.minimap = MiniMapWidget(self)
        self.minimap.setParent(self)          # MainWindow 上に重ねる
        self.minimap.show()
        # 初回配置：ウィンドウ幅・高さが確定してから move したいので、
        # 少し遅延させるか、resizeEvent 内で配置し直すのが確実
        self._position_minimap()        

        # --- 履歴エントリ追加 ---
        self._push_history(self.json_path)

        # --- データ読み込み＆編集モード初期化 ---
        self._load()
        self._set_mode(edit=False)
        
        #self.view.installEventFilter(self)
        
        # --- スクロールやシーン変更時にミニマップを再描画 / スクロールやシーン変更時に「表示／非表示判定」を行う ---
        self.view.horizontalScrollBar().valueChanged.connect(self.minimap.updateVisibility)
        self.view.verticalScrollBar().valueChanged.connect(self.minimap.updateVisibility)
        self.scene.sceneRectChanged.connect(self.minimap.updateVisibility)

        # ウィンドウサイズ変更時にも「表示／非表示判定」を行う
        self.resizeEvent  # ← resizeEvent の中で _position_minimap() と一緒に判定されるので不要な場合もある

        # --- アプリ起動直後に一度、ミニマップの表示判定を実行 ---
        QTimer.singleShot(0, self.minimap.updateVisibility)

    def _position_minimap(self):
        """
        ミニマップを常にウィンドウの右上に配置する。
        余白（マージン）を 10px 程度にして配置。
        """
        margin = 10
        # フレーム幅などを考慮して、QMainWindow のクライアント領域の右上に合わせる
        # self.width(), self.height() はウィンドウ全体サイズなので、
        # 必要に応じてフレーム幅を差し引くか、中央ウィジェットの座標系で計算してもよい。
        x = self.width() - self.minimap.width() - margin
        y = margin
        self.minimap.move(x, y)

    def resizeEvent(self, event):
        """
        ウィンドウやビューのリサイズ時に背景を再適用
        """
        super().resizeEvent(event)
        self._position_minimap()
        self._resize_timer.start(100)
                
        
    def mouseReleaseEvent(self, ev):
        """
        5ボタンマウス（XButton1/XButton2）に対応して、
        戻る／進むを実行する。
        PyQt6 は mousePressEvent より、こっちのほうが安定するらしい 。
        """
        # XButton1 → 戻る（_go_prev）、XButton2 → 進む（_go_next）
        if ev.button() == Qt.MouseButton.XButton1:
            # 戻るボタンが押されたら _go_prev を呼ぶっす
            self._go_prev()
            return
        elif ev.button() == Qt.MouseButton.XButton2:
            # 進むボタンが押されたら _go_next を呼ぶっす
            self._go_next()
            return
        elif ev.button() == Qt.MouseButton.MiddleButton:
            # 中央のボタンで編集/実行切り替え
            # これが、mousePressEventではなく releaseEventでやらないと、偶数回目のトグルでダブルクリックが必要になる
            self.a_run.trigger()
            return
        
        super().mouseReleaseEvent(ev)
        
    # --- CanvasItem レジストリ経由でアイテム生成 ----------
    def _create_item_from_path(self, path, sp):
        """
        ドロップされたファイルから対応するアイテムを生成する。
        VideoItem は CanvasItem に含まれないので、特別扱いする。
        """
        ext = Path(path).suffix.lower()

        # --- VideoItem 特別対応 ---
        if VideoItem.supports_path(path):
            try:
                return VideoItem.create_from_path(path, sp, self)
            except Exception as e:
                warn(f"[drop] VideoItem creation failed: {e}")

        # --- 通常の CanvasItem 方式 ---
        for cls in CanvasItem.ITEM_CLASSES:
            try:
                if cls.supports_path(path):
                    return cls.create_from_path(path, sp, self)
            except Exception as e:
                warn(f"[factory] {cls.__name__}: {e}")
        return None, None


    def _get_item_class_by_type(self, t: str):
        for i in range(len(CanvasItem.ITEM_CLASSES)):
            c = CanvasItem.ITEM_CLASSES[i]
            if getattr(c, "TYPE_NAME", None) == t:
                return c

        # --- 特例: CanvasItem を継承していない VideoItem を手動で対応 ---
        if t == "video":
            from DPyL_video import VideoItem
            return VideoItem

        return None

    def _new_project(self):
        # 新規プロジェクト作成
        path, _ = QFileDialog.getSaveFileName(
            self, "新規Jsonプロジェクト作成", "", "JSONファイル (*.json)"
        )
        if not path:
            return
        new_data = {
            "fileinfo": {
                "name": "desktopPyLauncher.py",
                "info": "project data file",
                "version": "1.0"
            },
            "items": []
        }
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        d = {
            "type": "json",
            "caption": Path(path).stem,
            "path": str(path),
            "x": 100,
            "y": 100
        }
        item = JSONItem(d, self.text_color)
        self.scene.addItem(item)
        self.data["items"].append(d)
        item.set_run_mode(False)

    # --- ツールバー構築 ---
    def _toolbar(self):
        tb = QToolBar("Main", self); self.addToolBar(tb)
        def act(text, slot, *, chk=False):
            a = QAction(text, self, checkable=chk); a.triggered.connect(slot)
            tb.addAction(a); return a
        
        act("🌱NEW", self._new_project)
        
        act("💾SAVE", self._save)
        act("🔁LOAD", lambda: (self._load(), self._set_mode(edit=False)))        
        tb.addSeparator()
        
        spacer1 = QWidget()
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer1.setFixedWidth(24)
        tb.addWidget(spacer1)
        
        self.a_home = act("🏠HOME",    self._go_home)
        self.a_prev = act("⏪️PREV",    self._go_prev)
        self.a_next = act("⏩NEXT",    self._go_next)
        
        # 5 button mouse --
        self.prev_action = QAction("PREV", self)
        self.next_action = QAction("NEXT", self)
        self.prev_action.triggered.connect(self._go_prev)
        self.next_action.triggered.connect(self._go_next)
        # ---
        
        self.add_toolbar_spacer(tb, width=24)

        self.a_edit = act("編集モード", lambda c: self._set_mode(edit=c), chk=True)
        self.a_run  = act("実行モード", lambda c: self._set_mode(edit=not c), chk=True)
        #self.a_edit = act("編集モード", self._on_edit_mode_toggled, chk=True)
        #self.a_run  = act("実行モード", self._on_run_mode_toggled, chk=True)
        
        self.add_toolbar_spacer(tb, width=24)

        # 「オブジェクト追加」ボタン
        menu_obj = QMenu(self)
        act_marker = menu_obj.addAction("マーカー追加")
        act_note   = menu_obj.addAction("NOTE追加")
        act_marker.triggered.connect(self._add_marker)
        act_note.triggered.connect(self._add_note)

        btn_obj  = QToolButton(self)
        btn_obj.setText("オブジェクト追加")
        btn_obj.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn_obj.setMenu(menu_obj)
        tb.addWidget(btn_obj)

        act("背景", self._background_dialog)
        
        self.add_toolbar_spacer(tb, width=24)

        act("▶一括再生",   self._play_all_videos)
        act("⏸一括停止",   self._pause_all_videos)
        act("🔇一括ミュート", self._mute_all_videos)
        
        self.add_toolbar_spacer(tb, width=24)
         
        act("[-1-]", lambda: self._jump_all_videos(0))
        act("[-2-]", lambda: self._jump_all_videos(1))
        act("[-3-]", lambda: self._jump_all_videos(2))
        
        self.add_toolbar_spacer(tb, width=24)

        act("Exit", self.close)
        
        self._update_nav()
        
    r"""
    def _on_edit_mode_toggled(self, checked: bool):
        print(f"[DEBUG] 編集モード toggled: {checked}")
        self._set_mode(edit=checked)

    def _on_run_mode_toggled(self, checked: bool):
        print(f"[DEBUG] 実行モード toggled: {checked}")
        self._set_mode(edit=not checked)
    """
    def add_toolbar_spacer(self, tb: QToolBar, width: int = 24):
        """
        ツールバーに区切り線と幅固定スペーサーを挿入
        """
        tb.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer.setFixedWidth(width)
        tb.addWidget(spacer)
        tb.addSeparator()

    # --- 編集モード限定の共通コンテキストメニュー ---
    def show_context_menu(self, item: QGraphicsItem, ev):
        if not self.a_edit.isChecked():
            return
        is_vid = isinstance(item, VideoItem)
        is_pix = isinstance(item, (ImageItem, GifItem, JSONItem, LauncherItem))
        menu = QMenu(self)
        
        act_copy = menu.addAction("コピー")
        act_cut  = menu.addAction("カット")
        
        menu.addSeparator()
        
        act_front = menu.addAction("最前面へ")
        act_back  = menu.addAction("最背面へ")
        menu.addSeparator()

        act_fit_orig = act_fit_inside_v = act_fit_inside_h = None
        if is_pix or is_vid:
            act_fit_orig   = menu.addAction("元のサイズに合わせる")
            act_fit_inside_v = menu.addAction("内側（上下）にフィット")
            act_fit_inside_h = menu.addAction("内側（左右）にフィット")
            menu.addSeparator()

        act_del = menu.addAction("Delete")
        sel = menu.exec(ev.screenPos())

        # --- コピー（複数選択対応） ---
        if sel == act_copy:
            items = self.scene.selectedItems()
            ds = [it.d for it in items if isinstance(it, (CanvasItem, VideoItem))]
            if ds:
                min_x = min(d.get("x", 0) for d in ds)
                min_y = min(d.get("y", 0) for d in ds)
                clipboard_data = {
                    "base": [min_x, min_y],
                    "items": ds
                }
                QApplication.clipboard().setText(json.dumps(clipboard_data, ensure_ascii=False, indent=2))
            ev.accept()
            return

        # --- カット（複数選択対応） ---
        if sel == act_cut:
            items = self.scene.selectedItems()
            ds = [it.d for it in items if isinstance(it, (CanvasItem, VideoItem))]
            if ds:
                min_x = min(d.get("x", 0) for d in ds)
                min_y = min(d.get("y", 0) for d in ds)
                clipboard_data = {
                    "base": [min_x, min_y],
                    "items": ds
                }
                QApplication.clipboard().setText(json.dumps(clipboard_data, ensure_ascii=False, indent=2))
                for it in items:
                    # 型ごとに削除方法を切り替える場合の例
                    r"""
                    if isinstance(it, VideoItem):
                        it.delete_self()
                    else:
                        self._remove_item(it)
                    """
                    self._remove_item(it)
            ev.accept()
            return
        
        # --- Zオーダー変更 ---
        if sel == act_front:
            item.setZValue(max((i.zValue() for i in self.scene.items()), default=0) + 1)
        elif sel == act_back:
            item.setZValue(min((i.zValue() for i in self.scene.items()), default=0) - 1)

        # --- 元のサイズに合わせる 
        elif sel == act_fit_orig:
            if is_pix:
                if isinstance(item, GifItem):
                    pix = item.movie.currentPixmap()
                    if pix.isNull():
                        warn("GIFフレーム取得失敗")
                        return
                    w = pix.width()
                    h = pix.height()
                    item._pix_item.setPixmap(pix)
                else:
                    # ▷ あらゆるソースからピクスマップを復元（順に検査）
                    pix = None
                    src_pix = None

                    # 1) embed: icon_embed or embed
                    embed_data = item.d.get("icon_embed") or item.d.get("embed")
                    if embed_data:
                        pix = QPixmap()
                        try:
                            pix.loadFromData(base64.b64decode(embed_data))
                        except Exception as e:
                            warn(f"Base64デコード失敗: {e}")
                            pix = None

                    # 2) icon/path から取得（embed なければ）
                    if not pix or pix.isNull():
                        src = item.d.get("icon") or item.d.get("path") or ""
                        idx = item.d.get("icon_index", 0)
                        if src:
                            pix = _load_pix_or_icon(src, idx, ICON_SIZE)

                    # 3) 最終手段: _default_icon
                    if not pix or pix.isNull():
                        warn("画像ソース取得に失敗（embed/icon/path 無効）")
                        pix = _default_icon(ICON_SIZE)

                    # --- サイズ判定 ---
                    w = max(pix.width(), ICON_SIZE)
                    h = max(pix.height(), ICON_SIZE)

                    item._src_pixmap = pix.copy()
                    item._pix_item.setPixmap(pix)

                # --- 共通処理（画像・GIF） ---
                item.prepareGeometryChange()
                item._rect_item.setRect(0, 0, w, h)
                item.d["width"], item.d["height"] = w, h
                item.resize_content(w, h)
                item._update_grip_pos()
                item.init_caption()

            elif is_vid:
                ns = item.nativeSize()
                if not ns.isValid():
                    warn("動画サイズ取得失敗: nativeSize が無効")
                    return
                w, h = int(ns.width()), int(ns.height())
                item.prepareGeometryChange()
                item.setSize(QSizeF(w, h))
                item.d["width"], item.d["height"] = w, h
                item.resize_content(w, h)
                item._update_grip_pos()
                item.init_caption()



        # --- 内側フィット（上下／左右） --------------------------
        elif sel in (act_fit_inside_v, act_fit_inside_h):
            fit_axis = "v" if sel == act_fit_inside_v else "h"
            # 1) 現在の表示領域サイズを取得
            cur_w = int(item.boundingRect().width())
            cur_h = int(item.boundingRect().height())

            # 2) ソース元サイズの取得（全タイプ網羅）
            if isinstance(item, GifItem):
                frame_rect = item.movie.frameRect()
                if not frame_rect.isValid():
                    warn("GIFフレームサイズ取得失敗")
                    return
                orig_w, orig_h = frame_rect.width(), frame_rect.height()
                src_pix = item.movie.currentPixmap()
                if src_pix.isNull():
                    warn("GIFフレーム取得失敗")
                    return

            elif is_vid:
                ns = item.nativeSize()
                if not ns.isValid():
                    warn("動画サイズ取得失敗: nativeSizeが無効")
                    return
                orig_w, orig_h = ns.width(), ns.height()
                src_pix = None  # 動画はpixmap不要

            elif is_pix:
                # ✅ embed/icon/path の順に取得を試みる
                pix = None
                embed_data = item.d.get("icon_embed") or item.d.get("embed")
                if embed_data:
                    pix = QPixmap()
                    try:
                        pix.loadFromData(base64.b64decode(embed_data))
                    except Exception as e:
                        warn(f"Base64デコード失敗: {e}")
                        pix = None

                if not pix or pix.isNull():
                    src = item.d.get("icon") or item.d.get("path") or ""
                    idx = item.d.get("icon_index", 0)
                    if src:
                        pix = _load_pix_or_icon(src, idx, ICON_SIZE)

                if not pix or pix.isNull():
                    warn("画像取得失敗: embed/icon/path 無効")
                    pix = _default_icon(ICON_SIZE)

                orig_w, orig_h = pix.width(), pix.height()
                src_pix = pix

            else:
                warn("未対応のアイテムタイプ")
                return

            # 3) アスペクト比を保って縮小（軸別フィット）
            if orig_w <= 0 or orig_h <= 0:
                warn("元サイズが無効")
                return

            if fit_axis == "v":            # ★ 高さ基準
                scale = cur_h / orig_h
                w, h = int(orig_w * scale), int(cur_h)
            else:                          # ★ 幅基準
                scale = cur_w / orig_w
                w, h = int(cur_w), int(orig_h * scale)

            # 4) 描画とリサイズ（静止画と動画で処理分岐）
            item.prepareGeometryChange()

            if is_pix:
                pm = src_pix.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                item._rect_item.setRect(0, 0, w, h)
                item._pix_item.setPixmap(pm)
            else:
                item.setSize(QSizeF(w, h))

            # 5) 共通後処理
            item.d["width"], item.d["height"] = w, h
            item.resize_content(w, h)
            item._update_grip_pos()
            item.init_caption()
             
            #return
        # --- 削除 ---
        elif sel == act_del:
            self._remove_item(item)

        ev.accept()

    # --- 選択アイテムのコピー／カット ---
    def copy_or_cut_selected_items(self, cut=False):
        items = self.scene.selectedItems()
        ds = [it.d for it in items if isinstance(it, (CanvasItem, VideoItem))]
        if not ds:
            return
        min_x = min(d.get("x", 0) for d in ds)
        min_y = min(d.get("y", 0) for d in ds)
        clipboard_data = {
            "base": [min_x, min_y],
            "items": ds
        }
        QApplication.clipboard().setText(json.dumps(clipboard_data, ensure_ascii=False, indent=2))
        if cut:
            for it in items:
                self._remove_item(it)

    # --- 指定座標へペースト ---
    def _paste_items_at(self, scene_pos):
        """
        クリップボードデータを現在座標へ貼り付け  
        * 新形式 (base/items) → 相対配置  
        * 旧形式 (単一/複数)  → そのまま配置  
        戻り値: List[QGraphicsItem]
        """
        txt = QApplication.clipboard().text()
        pasted_items = []
        try:
            js = json.loads(txt)
            items = []

            # --- 新形式 ---
            if isinstance(js, dict) and "items" in js and "base" in js:
                base_x, base_y = js["base"]
                for d in js["items"]:
                    items.append((d, d.get("x", 0) - base_x, d.get("y", 0) - base_y))
            else:  # --- 旧形式 ---
                js_list = js if isinstance(js, list) else [js]
                items = [(d, 0, 0) for d in js_list]

            for d, dx, dy in items:
                cls = self._get_item_class_by_type(d.get("type"))
                if cls is None:
                    warn(f"[paste] unknown type: {d.get('type')}")
                    continue
                d_new      = d.copy()
                d_new["x"] = int(scene_pos.x()) + dx
                d_new["y"] = int(scene_pos.y()) + dy

                item = cls(d_new, self.text_color) if cls.TYPE_NAME != "video" else cls(d_new, win=self)
                self.scene.addItem(item)
                self.data["items"].append(d_new)
                pasted_items.append(item)

        except Exception as e:
            warn(f"ペースト失敗: {e}")

        return pasted_items  # ←←← これが重要！


    # --- 画像ペースト処理 ---
    def _paste_image_if_available(self, scene_pos):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        if mime.hasImage():
            img = clipboard.image()
            if img.isNull():
                warn("クリップボード画像が null です")
                return

            pixmap = QPixmap.fromImage(img)
            # base64エンコードして保存用に変換
            embed = b64encode_pixmap(pixmap)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            d = {
                "type": "image",
                "caption": now_str,
                "embed": embed,
                "store": "embed",
                "x": int(scene_pos.x()),
                "y": int(scene_pos.y()),
                "width": pixmap.width(),
                "height": pixmap.height()
            }

            item = ImageItem(d, text_color=self.text_color)
            self.scene.addItem(item)
            self.data["items"].append(d)
           
            # ドロップした直後は編集モードON
            item.set_run_mode(False)
            item.grip.setVisible(True)
            item._grip.setVisible(True)     
            
        else:
            warn("画像データがクリップボードにありません")
    # --- アイテム削除とJSON同期 ---
    def remove_item(self, item: QGraphicsItem):
        """
        VideoItem.delete_self() 互換API
        _remove_item()の安全ラッパー
        """
        self._remove_item(item)
        
    def _remove_item(self, item: QGraphicsItem):
        # VideoItemなら後始末
        if isinstance(item, VideoItem):
            item.delete_self()
            if item.video_resize_dots.scene():
                item.video_resize_dots.scene().removeItem(item.video_resize_dots)
            item.video_resize_dots = None

        # 関連Gripを削除
        if isinstance(item, CanvasItem):
            if item.grip.scene():
                item.grip.scene().removeItem(item.grip)
            item.grip = None
            
        # シーンから本体除去
        if item.scene():
            item.scene().removeItem(item)
            
        # JSONから辞書データ削除
        if my_has_attr(item, "d") and item.d in self.data.get("items", []):
            self.data["items"].remove(item.d)


    # --- 動画一括操作 ---
    def _play_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                it.player.play(); it.btn_play.setChecked(True); it.btn_play.setText("⏸")
            elif isinstance(it, GifItem):
                it.play() 

    def _pause_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                # 再生中のときだけ Pause（Stopped への余計な遷移を防止）
                if it.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    it.player.pause()
                # ▶/⏸ ボタンと内部フラグを同期
                it.btn_play.setChecked(False)
                it.btn_play.setText("▶")
                it.active_point_index = None
            elif isinstance(it, GifItem):
                it.pause() 

    def _mute_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                new_mute = not it.audio.isMuted()
                it.audio.setMuted(new_mute)
                it.btn_mute.setChecked(new_mute)
                it.d["muted"] = new_mute

    def _jump_all_videos(self, idx: int):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                it._jump(idx)

    # --- 背景設定ダイアログ ---
    def _background_dialog(self):
        # 現在の背景設定取得
        cur = self.data.get("background", {})
        if cur.get("path"):                    # 画像
            def_mode, def_val = "image", cur["path"]
        elif cur.get("mode") == "color":       # 単色
            def_mode, def_val = "color", cur.get("color", "")
        else:                                  # クリア
            def_mode, def_val = "clear", ""

        def_bri = cur.get("brightness", 50)  # 既存の明るさ or デフォルト50

        # 明るさ付きで取得
        ok, mode, value, bri = BackgroundDialog.get(def_mode, def_val, def_bri)
        if not ok:
            return

        if mode == "image":
            self.data["background"] = {"path": value, "brightness": bri}
        elif mode == "color":
            self.data["background"] = {"mode": "color", "color": value}
        else:
            self.data.pop("background", None)

        self._apply_background()

    def _apply_background(self):
        """
        背景画像・単色・クリアを描画
        """
        bg = self.data.get("background")

        # --- 単色背景モード ---
        if bg and bg.get("mode") == "color":
            self.bg_pixmap = None
            self.scene.setBackgroundBrush(QBrush(QColor(bg.get("color", "#000000"))))
            self.view.viewport().update()
            return

        # --- 背景設定なしまたは画像パス未指定 ---
        if not bg or not bg.get("path"):
            self.bg_pixmap = None
            self.scene.setBackgroundBrush(QBrush())
            self.view.viewport().update()
            return

        # --- 画像背景モード ---
        src = QPixmap(bg["path"])
        if not src.isNull():
            vw = self.view.viewport().width()
            vh = self.view.viewport().height()
            scaled = src.scaled(vw, vh,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x_off = (scaled.width()  - vw)//2
            y_off = (scaled.height() - vh)//2
            pm = scaled.copy(x_off, y_off, vw, vh)

            # 明暗補正（50=標準, <50暗く, >50明るく）
            b = bg.get("brightness", 50)
            if b != 50:
                painter = QPainter(pm)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                alpha = int(abs(b - 50) / 50.0 * 255)
                col = QColor(0,0,0,alpha) if b < 50 else QColor(255,255,255,alpha)
                painter.fillRect(pm.rect(), col)
                painter.end()

            self.bg_pixmap = pm
        else:
            self.bg_pixmap = None

        if self.bg_pixmap is None:
            self.scene.setBackgroundBrush(QBrush())
            self.view.viewport().update()
            return

        # タイル背景の設定
        brush = QBrush(self.bg_pixmap)
        tl = self.view.mapToScene(self.view.viewport().rect().topLeft())
        dx = int(tl.x()) % self.bg_pixmap.width()
        dy = int(tl.y()) % self.bg_pixmap.height()
        brush.setTransform(QTransform().translate(dx, dy))
        self.scene.setBackgroundBrush(brush)

    # --- Web URLからLauncherItem生成 ---
    def _make_web_launcher(self, weburl: str, sp: QPointF, icon_path: str = "", is_url_file: bool = False):
        if not isinstance(weburl, str) or not weburl.strip():
            warn(f"[drop] 無効なURL: {weburl!r}")
            return None, None

        domain = urlparse(weburl).netloc or weburl
        d = {
            "type": "launcher",
            "caption": domain,
            "path": weburl,
            "icon": icon_path if is_url_file else "",
            "icon_index": 0,
            "x": sp.x(), "y": sp.y()
        }

        if is_url_file:
            d["icon"] = icon_path
        else:
            icon_b64 = fetch_favicon_base64(domain)
            if icon_b64:
                d["icon_embed"] = icon_b64

        it = LauncherItem(d, self.text_color)
        return it, d

    # --- MainWindowドラッグ＆ドロップ対応 ---
    def handle_drop(self, e):
        """
        URL / ファイルドロップ共通ハンドラ
        * http(s) URL           → favicon 付き LauncherItem   ←★ NEW: 最優先
        * ネットワークドライブ   → 専用 LauncherItem
        * CanvasItem レジストリ → 自動判定で生成
        ドロップ後は全体を編集モードへ強制切替！
        """
        added_any = False
        added_items = []
        for url in e.mimeData().urls():
            sp = self.view.mapToScene(e.position().toPoint())

            # ① まずは “http/https” を最優先で処理  -----------------
            weburl = url.toString().strip()
            if weburl.startswith(("http://", "https://")):
                it, d = self._make_web_launcher(weburl, sp)
                if it:
                    self.scene.addItem(it); self.data["items"].append(d)
                    added_any = True
                    added_items.append(it)
                continue          # ★ GenericFileItem へフォールバックさせない

            # ② ローカルパス判定 ------------------------------------
            raw_path = url.toLocalFile().strip()
            if not raw_path:
                warn(f"[drop] パスも URL も解釈できない: {url}")
                continue
            path = normalize_unc_path(raw_path)

            # ④ レジストリ経由 (CanvasItem.ITEM_CLASSES) ------------
            it, d = self._create_item_from_path(path, sp)
            if it:
                self.scene.addItem(it); self.data["items"].append(d)
                added_any = True
                added_items.append(it)
                continue
                
            # ③ ネットワークドライブ -------------------------------
            if is_network_drive(path):
                dll = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                   "System32", "imageres.dll")
                d = {
                    "type": "launcher",
                    "caption": os.path.basename(path.rstrip('\\/')),
                    "path": path,
                    "workdir": path,
                    "icon": dll,
                    "icon_index": 28,
                    "x": sp.x(), "y": sp.y()
                }
                it = LauncherItem(d, self.text_color)
                self.scene.addItem(it); self.data["items"].append(d)
                added_any = True
                added_items.append(it)
                continue



            # ⑤ ここまで来ても未判定なら警告 -----------------------
            warn(f"[drop] unsupported: {url}")

        
        # 追加アイテムだけ run_mode=False にして編集モードにする
        # 別の仕組みにより、編集ウィンドウで編集後 OK または CANCEL後、全体の実行/編集モードに同期します
        for item in added_items:
            item.set_run_mode(False)
        
        # もしくは、ドロップ完了後に全体を編集モードへ。　好きなほうをどうぞ。
        #if added_any:
        #    self._set_mode(edit=True)


    # --- スナップヘルパー ---
    def snap_position(self, item, new_pos: QPointF) -> QPointF:
        # 他アイテムに吸着する座標補正
        SNAP_THRESHOLD = 10
        best_dx = None
        best_dy = None
        best_x = new_pos.x()
        best_y = new_pos.y()
        r1 = item.boundingRect().translated(new_pos)

        for other in self.scene.items():
            if other is item or not my_has_attr(other, "boundingRect"):
            #if isinstance(other, QGraphicsItem) and other is not item:
                continue

            r2 = other.boundingRect().translated(other.pos())

            # X方向スナップ
            for ox, tx in [(r2.left(), r1.left()), (r2.right(), r1.right())]:
                dx = abs(tx - ox)
                if dx < SNAP_THRESHOLD and (best_dx is None or dx < best_dx):
                    best_dx = dx
                    best_x = new_pos.x() + (ox - tx)

            # Y方向スナップ
            for oy, ty in [(r2.top(), r1.top()), (r2.bottom(), r1.bottom())]:
                dy = abs(ty - oy)
                if dy < SNAP_THRESHOLD and (best_dy is None or dy < best_dy):
                    best_dy = dy
                    best_y = new_pos.y() + (oy - ty)

        return QPointF(best_x, best_y)
        
    def snap_size(self, target_item, new_w, new_h):
        SNAP_THRESHOLD = 10
        best_dw, best_dh = None, None
        best_w, best_h = new_w, new_h
        # 現在の位置
        r1 = target_item.mapToScene(target_item.boundingRect()).boundingRect()
        x0, y0 = r1.left(), r1.top()

        for other in self.scene.items():
            if other is target_item or not my_has_attr(other, "boundingRect"):
                continue
            r2 = other.mapToScene(other.boundingRect()).boundingRect()
            # 横（幅）端スナップ
            for ox in [r2.left(), r2.right()]:
                dw = abs(x0 + new_w - ox)
                if dw < SNAP_THRESHOLD and (best_dw is None or dw < best_dw):
                    best_dw = dw
                    best_w = ox - x0
            # 縦（高さ）端スナップ
            for oy in [r2.top(), r2.bottom()]:
                dh = abs(y0 + new_h - oy)
                if dh < SNAP_THRESHOLD and (best_dh is None or dh < best_dh):
                    best_dh = dh
                    best_h = oy - y0

        return best_w, best_h

    # --- ノート追加 ---
    def _add_note(self):
        sp = self.view.mapToScene(self.view.viewport().rect().center())
        d = {"type": "note", "x": sp.x(), "y": sp.y(),
             "width": 200, "height": 120, "note": b64e("New note"),
             "isLabel": False, "color": "#000000", "fontsize": 14,
             "noteType": "text"}
        it = NoteItem(d, self.text_color)
        self.scene.addItem(it)
        self.data.setdefault("items", []).append(d)
        #self._set_mode(edit=True)
        it.set_run_mode(False)

    # --- マーカー追加 ---
    def _add_marker(self):
        """
        シーンの中央付近に、新規 MarkerItem を追加する。
        - 既存のマーカーIDを調べ、最大ID + 100 を新規IDとする
        - デフォルトで幅・高さ 32×32、キャプション「MARKER-<ID>」、ジャンプ先なし、開始地点 False、align="左上"
        """
        # 画面中心位置を取得
        sp = self.view.mapToScene(self.view.viewport().rect().center())

        # 既存マーカーの ID をすべて収集
        existing_ids = []
        for it in self.scene.items():
            if isinstance(it, MarkerItem):
                try:
                    existing_ids.append(int(it.d.get("id", 0)))
                except (TypeError, ValueError):
                    continue
        if existing_ids:
            new_id = max(existing_ids) + 100
        else:
            new_id = 10000

        # デフォルトの辞書を構築
        d = {
            "type": "marker",
            "id": new_id,
            "caption": f"MARKER-{new_id}",
            "jump_id": None,
            "is_start": False,
            "align": "左上",
            "x": sp.x(),
            "y": sp.y(),
            "width": 32,
            "height": 32,
            # z は後で必要なら指定。ここでは 0 にしておく
            "z": 0,
        }

        # MarkerItem インスタンスを生成してシーンに追加
        item = MarkerItem(d, text_color=self.text_color)
        self.scene.addItem(item)
        item.setZValue(d["z"])
        self.data.setdefault("items", []).append(d)

        # 追加直後は編集モードでプロパティを設定できるようにする
        item.set_run_mode(False)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        item.setFlag(item.GraphicsItemFlag.ItemIsMovable, True)

    # --- 履歴管理 ---
    def _push_history(self, p: Path):
        # 履歴を現在位置で切り詰めて追加
        if self.hidx < len(self.history) - 1:
            self.history = self.history[:self.hidx+1]
        self.history.append(p)
        self.hidx = len(self.history)-1
        self._update_nav()

    def _update_nav(self):
        # ナビゲーションボタンの有効・無効切替
        self.a_prev.setEnabled(self.hidx > 0)
        self.a_next.setEnabled(self.hidx < len(self.history)-1)

    def _go_home(self):
        # 履歴の先頭へ移動
        if self.history:
            self._load_path(self.history[0], ignore_geom=True)

    def _go_prev(self):
        """
        履歴を1つ戻る
        """
        if self.hidx > 0:
            self._load_path(
                self.history[self.hidx - 1],
                ignore_geom=True,
                from_history=True
            )
    def _go_next(self):
        """
        履歴を1つ進める
        """
        if self.hidx < len(self.history) - 1:
            self._load_path(
                self.history[self.hidx + 1],
                ignore_geom=True,
                from_history=True
            )


    def _load_path(self, p: Path, *, ignore_geom=False, from_history=False):
        """
        ファイルを読み込む。
        - from_history=False の場合 → 新規読み込みなので履歴に追加し、hidx を末尾にセット
        - from_history=True の場合 → 履歴移動なので履歴には追加せず、hidx を history.index(p) にセット
        """
        # ウィンドウジオメトリを保持するかどうか
        self._ignore_window_geom = ignore_geom
        # 読み込む JSON ファイルのパスをセット
        self.json_path = p

        if from_history:
            # 履歴移動：渡されたパスの index を hidx にセット（履歴は変更しない）
            self.hidx = self.history.index(p)
        else:
            # 新規読み込み：履歴に追加し、hidx を履歴末尾に設定
            self._push_history(p)

        # 実際の JSON 読み込み処理を実行
        self._load()
        # ジオメトリ保持フラグをリセット
        self._ignore_window_geom = ignore_geom
        # 読み込み後は必ず編集モードを解除
        self._set_mode(edit=False)
        # PREV/NEXT ボタンの有効・無効状態を更新
        self._update_nav()


    # --- モード切替（編集⇔実行） ---
    def _set_mode(self, *, edit: bool):
        """
        全CanvasItemの編集可否切替。
        edit=True: 移動・リサイズ可、False: 固定
        """

        #-----------------------
        # 呼び出し元のスタックトレースを取得
        #trace_this("edit")

        #-----------------------
        
        self.a_edit.blockSignals(True)
        self.a_run.blockSignals(True)
        self.a_edit.setChecked(edit)
        self.a_run.setChecked(not edit)
        self.a_edit.blockSignals(False)
        self.a_run.blockSignals(False)

        movable_flag    = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        selectable_flag = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        focusable_flag  = QGraphicsItem.GraphicsItemFlag.ItemIsFocusable

        for it in self.scene.items():
            # 保存対象（.d, set_run_mode を持つ）以外はスキップ
            if not isinstance(it, (CanvasItem, VideoItem)):
                continue

            # 実行モード切替
            it.set_run_mode(not edit)

            it.setFlag(movable_flag, edit)
            it.setFlag(selectable_flag, edit)
            it.setFlag(focusable_flag, edit)

            # リサイズグリップ表示切替
            if isinstance(it, CanvasItem):
                it.grip.setVisible(edit)
            elif isinstance(it, VideoItem):
                it.video_resize_dots.setVisible(edit)

        self.view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag if not edit
            else QGraphicsView.DragMode.RubberBandDrag
        )

    # --- データ読み込み ---
    # ---------- 
    def _load(self, on_finished=None):
        self._show_loading(True)
        self._on_load_finished = on_finished  # ← 後で呼ぶ
        QTimer.singleShot(50, self._do_load_actual)


    def _show_loading(self, show: bool):
        self.loading_label.setGeometry(self.rect())
        self.loading_label.setVisible(show)
        self.loading_label.raise_()

    def _do_load_actual(self):
        # 既存アイテムを全削除
        for it in list(self.scene.items()):
            self._remove_item(it)

        self.scene.clear()
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception as e:
            warn(f"LOAD failed: {e}")
            QMessageBox.critical(self, "Error", str(e))
            return
        # アイテム復元
        for d in self.data.get("items", []):
            cls = self._get_item_class_by_type(d.get("type", ""))
            if not cls:
                warn(f"[LOAD] Unknown item type: {d.get('type')}")
                continue

            # ---- コンストラクタの引数を動的に組み立てる ----
            kwargs = {}
            sig = inspect.signature(cls.__init__).parameters
            if "win" in sig:
                kwargs["win"] = self
            if "text_color" in sig:
                kwargs["text_color"] = self.text_color

            try:
                # it = cls(d, **kwargs)  # ← これで GifItem も OK！
                # MarkerItem は win を受け取らないため、text_color のみ指定する
                if cls is MarkerItem:
                    it = cls(d, text_color=self.text_color)
                else:
                    it = cls(d, **kwargs)                
            except Exception as e:
                warn(f"[LOAD] {cls.__name__} create failed: {e}")
                continue

            # ---- 共通後処理 ----
            it.setZValue(d.get("z", 0))
            self.scene.addItem(it)
            it.setPos(d.get("x", 0), d.get("y", 0))
            
            # MarkerItem は初期配置時にグリップをシーンに追加する必要があるため
            if isinstance(it, MarkerItem) and it.grip.scene() is None:
                self.scene.addItem(it.grip)            

            # VideoItem はリサイズグリップをシーンに載せる
            from DPyL_video import VideoItem
            if isinstance(it, VideoItem) and it.video_resize_dots.scene() is None:
                self.scene.addItem(it.video_resize_dots)

        # ウィンドウジオメトリ復元
        if not self._ignore_window_geom and (geo := self.data.get("window_geom")):
            try:
                self.restoreGeometry(base64.b64decode(geo))
            except Exception as e:
                warn(f"Geometry restore failed: {e}")

        self._apply_background()
        # _set_modeは呼び出し元で維持

        # --- アイテム群を左上へシフト ---
        #items = [it for it in self.scene.items() if my_has_attr(it, "d")]
        items = [it for it in self.scene.items() if isinstance(it, (CanvasItem, VideoItem))]
        if items:
            min_x = min((it.x() for it in items), default=0)
            min_y = min((it.y() for it in items), default=0)
            dx = 50 - min_x
            dy = 50 - min_y
            for it in items:
                it.setPos(it.x() + dx, it.y() + dy)
        self._apply_scene_padding()
        
        #  開始地点へスクロール
        self._scroll_to_start_marker()        


        # --- ローディング完了後、ラベル非表示 ---
        self._show_loading(False)

        # --- 完了後の処理呼び出し ---
        if callable(getattr(self, "_on_load_finished", None)):
            self._on_load_finished()
            self._on_load_finished = None

       
    def _apply_scene_padding(self, margin: int = 64):
        """シーン全体のバウンディングボックスを計算し中央寄せ"""
        #items = [i for i in self.scene.items() if my_has_attr(i, "d")]
        items = [i for i in self.scene.items() if isinstance(i, (CanvasItem, VideoItem))]
        if not items:
            return

        bounds = items[0].sceneBoundingRect()
        for it in items[1:]:
            bounds = bounds.united(it.sceneBoundingRect())

        bounds.adjust(-margin, -margin, margin, margin)
        self.scene.setSceneRect(bounds)


    # --- JSONプロジェクト切替用 ---
    def _load_json(self, path: Path):
        self._ignore_window_geom = True
        self.json_path = Path(path).expanduser().resolve()
        self.setWindowTitle(f"desktopPyLauncher - {self.json_path.name}")
        self._push_history(self.json_path)

        # 明示的にモードを一時保存し、ロード後に復元
        def after_load():
            self._ignore_window_geom = False
        self._load(on_finished=after_load)


    # --- セーブ処理 ---
    def _save(self, *, auto=False):
        # 位置・サイズ・Z値等をdに反映
        for it in self.scene.items():
            if not isinstance(it, (CanvasItem, VideoItem)):
                continue
            
            pos = it.pos()
            it.d["x"], it.d["y"] = pos.x(), pos.y()

            #r = it.rect() #謎い。d[] は最新のはず
            #it.d["width"], it.d["height"] = r.width(), r.height()

            it.d["z"] = it.zValue()

            if isinstance(it, VideoItem):
                try:
                    if not my_has_attr(it, "audio"):
                        pass
                    it.d["muted"] = it.audio.isMuted()
                except Exception as e:
                    warn(f"[WARN] muted状態の取得に失敗: {e}")

        # ウィンドウ位置を保存
        self.data["window_geom"] = base64.b64encode(self.saveGeometry()).decode("ascii")
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            if not auto:
                QMessageBox.information(self, "SAVE", "保存しました！")
        except Exception as e:
            QMessageBox.critical(self, "SAVE", str(e))
# ==============================================================
#  private helpers
# ==============================================================
    def _scroll_to_start_marker(self):
        """
        is_start==True の Marker があれば align に従ってビューをジャンプ
        """
        try:
            start_markers = sorted(
                (it for it in self.scene.items()
                 if isinstance(it, MarkerItem) and it.d.get("is_start")),
                key=lambda m: int(m.d.get("id", 0))
            )
            if not start_markers:
                return

            m   = start_markers[0]
            sp  = m.scenePos()
            w   = int(m.d.get("width",  32))
            h   = int(m.d.get("height", 32))
            aln = m.d.get("align", "左上")

            if aln == "中央":
                # ── ビューポート中央寄せ ───────────────────
                self.view.centerOn(sp.x() + w/2, sp.y() + h/2)
            else:
                # ── 左上寄せ ─────────────────────────────
                # ビューポート寸法をシーン座標へ変換（ズーム倍率対応）
                vp_w = self.view.viewport().width()  / self.view.transform().m11()
                vp_h = self.view.viewport().height() / self.view.transform().m22()
                # 対象点を (vp_w/2 , vp_h/2) だけ手前にずらして centerOn
                self.view.centerOn(sp.x() + vp_w/2, sp.y() + vp_h/2)
        except Exception as e:
            warn(f"[SCROLL] start-marker failed: {e}")

# ==============================================================
#  App helper - 補助関数
# ==============================================================
def apply_theme(app: QApplication):
    # ダークテーマ自動設定
    if app.palette().color(QPalette.ColorRole.WindowText).lightness() <= 128:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        txt = QColor(255, 255, 255)
        for r in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                  QPalette.ColorRole.ButtonText):
            pal.setColor(r, txt)
        pal.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        pal.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        app.setPalette(pal)

# ==============================================================
#  main - アプリ起動エントリポイント
# ==============================================================
class SafeApp(QApplication):
    """例外をログに残しても、イベント自体は処理済みにする"""
    def notify(self, obj, ev):
        try:
            return super().notify(obj, ev)
        except Exception as e:
            warn(f"[SafeApp] {type(e).__name__}: {e}")
            # 例外を握りつぶした後、もう一度デフォルトハンドラに委譲
            try:
                return super().notify(obj, ev)
            except Exception:
                return True

def _global_excepthook(exc_type, exc, tb):
    warn(f"[Uncaught] {exc_type.__name__}: {exc}")
    traceback.print_exception(exc_type, exc, tb)
    

sys.excepthook = _global_excepthook    # 最後の盾
r"""
# VideoItemが一度でも再生されると停止していても画面遷移でハングアップするので、以下通常のmainに戻します
# SafeApp版
def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "-create":
        tmpl = {"fileinfo": {"name": __file__, "info": "project data file", "version": "1.0"},
                "items": []}
        tgt = Path(sys.argv[2]).expanduser().resolve()
        if tgt.exists():
            print("Already exists!"); sys.exit(1)
        tgt.write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Created {tgt}"); sys.exit(0)

    # ② 通常起動
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("default.json")

    app = SafeApp(sys.argv)
    apply_theme(app)
    MainWindow(json_path).show()
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    finally:
        dump_missing_attrs()
"""
        
# ==============================================================
#  main - アプリ起動エントリポイント
# ==============================================================
# 通常
def main():
    # コマンドライン引数 -create で空jsonテンプレ生成
    if len(sys.argv) >= 3 and sys.argv[1] == "-create":
        tmpl = {"fileinfo": {"name": Path(__file__).name,
                             "info": "project data file", "version": "1.0"},
                "items": []}
        tgt = Path(sys.argv[2]).expanduser().resolve()
        if tgt.exists():
            print("Already exists!"); sys.exit(1)
        with open(tgt, "w", encoding="utf-8") as f:
            json.dump(tmpl, f, ensure_ascii=False, indent=2)
        print(f"Created {tgt}"); sys.exit(0)

    # デフォルトjson or 引数受け取り
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("default.json")
    app = QApplication(sys.argv)
    apply_theme(app)
    MainWindow(json_path).show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
