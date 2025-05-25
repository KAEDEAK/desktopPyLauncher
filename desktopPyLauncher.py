# -*- coding: utf-8 -*-
"""
desktopPyLauncher.py ― エントリポイント
◎ Qt6 / PyQt6 専用
"""

from __future__ import annotations

# --- 標準・サードパーティライブラリ ---
import sys, json, base64, os
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsItemGroup, QGraphicsPixmapItem,
    QGraphicsTextItem, QGraphicsRectItem, QToolBar, QMessageBox,
    QFileDialog, QFileIconProvider, QStyleFactory, QDialog,
    QLabel, QLineEdit, QTextEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QMenu, QComboBox, QSpinBox, QCheckBox, QSizePolicy,
    QWidget, QSlider, QGraphicsProxyWidget
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget, QGraphicsVideoItem
from PyQt6.QtGui import (
    QPixmap, QPainter, QBrush, QColor, QPalette, QAction,
    QIcon, QImage, QPen, QTransform, QFont
)
from PyQt6.QtCore import (
    Qt, QSizeF, QPointF, QFileInfo, QProcess,
    QBuffer, QIODevice, QTimer, 
    QUrl
)

# --- プロジェクト内モジュール ---
from DPyL_utils   import (
    warn, b64e, fetch_favicon_base64,
    compose_url_icon, b64encode_pixmap, normalize_unc_path, is_network_drive
)
from DPyL_classes import (
    LauncherItem, JSONItem, ImageItem,
    CanvasItem, CanvasResizeGrip,
    BackgroundDialog
)
from DPyL_note    import NoteItem
from DPyL_video   import VideoItem
from configparser import ConfigParser
from urllib.parse import urlparse

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

    def dragEnterEvent(self, e): 
        # ファイルやURLドロップの受付
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)
    def dragMoveEvent(self, e):  
        e.acceptProposedAction()
    def dropEvent(self, e):      
        self.win.handle_drop(e)
    def mousePressEvent(self, ev):
        # 右クリック時、空白エリアならペーストメニュー表示
        if ev.button() == Qt.MouseButton.RightButton:
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
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

                if not can_paste and cb.mimeData().hasImage():
                    can_paste = True

                act_paste.setEnabled(can_paste)

                sel = menu.exec(ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos())
                if sel == act_paste:
                    self.win._paste_image_if_available(scene_pos)
                    pasted_items = self.win._paste_items_at(scene_pos)
                    if pasted_items:
                        for item in pasted_items:
                            if hasattr(item, "set_editable"):
                                item.set_editable(True)
                            if hasattr(item, "set_run_mode"):
                                item.set_run_mode(False)
                ev.accept()
                return
        super().mousePressEvent(ev)


# ==============================================================
#  MainWindow - メインウィンドウ
# ==============================================================
class MainWindow(QMainWindow):
    def __init__(self, json_path: Path):
        super().__init__()
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

        # --- 履歴エントリ追加 ---
        self._push_history(self.json_path)

        # --- データ読み込み＆編集モード初期化 ---
        self._load()
        self._set_mode(edit=False)

    # --- CanvasItem レジストリ経由でアイテム生成 ----------
    def _create_item_from_path(self, path, sp):
        """
        ドロップされたファイルから対応するアイテムを生成する。
        VideoItem は CanvasItem に含まれないので、特別扱いする。
        """
        from DPyL_video import VideoItem
        from pathlib import Path
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
        from DPyL_classes import CanvasItem
        for i in range(len(CanvasItem.ITEM_CLASSES)):
            c = CanvasItem.ITEM_CLASSES[i]
            if getattr(c, "TYPE_NAME", None) == t:
                return c
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

    # --- ツールバー構築 ---
    def _toolbar(self):
        tb = QToolBar("Main", self); self.addToolBar(tb)
        def act(text, slot, *, chk=False):
            a = QAction(text, self, checkable=chk); a.triggered.connect(slot)
            tb.addAction(a); return a
        
        act("New", self._new_project)
        act("Load", lambda: (self._load(), self._set_mode(edit=False)))
        act("Save", self._save)
        tb.addSeparator()
        
        spacer1 = QWidget()
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer1.setFixedWidth(24)
        tb.addWidget(spacer1)
        
        self.a_home = act("Home",    self._go_home)
        self.a_prev = act("Prev",    self._go_prev)
        self.a_next = act("Next",    self._go_next)
        
        self.add_toolbar_spacer(tb, width=24)

        self.a_edit = act("編集モード", lambda c: self._set_mode(edit=c), chk=True)
        self.a_run  = act("実行モード", lambda c: self._set_mode(edit=not c), chk=True)
        
        self.add_toolbar_spacer(tb, width=24)

        act("NOTE追加", self._add_note)
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

        from DPyL_video import VideoItem as _Vid
        is_vid = isinstance(item, _Vid)
        is_pix = hasattr(item, "_src_pixmap") and item._src_pixmap

        menu = QMenu(self)
        
        act_copy = menu.addAction("コピー")
        act_cut  = menu.addAction("カット")
        
        r"""
        act_paste = menu.addAction("ペースト")
        
        # --- ペースト可否を判定して有効/無効を切り替え ---
        cb_text = QApplication.clipboard().text()
        try:
            js = json.loads(cb_text)
            if isinstance(js, dict):
                # base/items 構造 or 単一アイテムdict想定
                valid = "items" in js and isinstance(js["items"], list)
            elif isinstance(js, list):
                # リスト形式（旧バージョン複数アイテム）
                valid = all(isinstance(d, dict) for d in js)
            else:
                valid = False
            act_paste.setEnabled(valid)
        except Exception:
            act_paste.setEnabled(False)
        """
        
        menu.addSeparator()
        
        act_front = menu.addAction("最前面へ")
        act_back  = menu.addAction("最背面へ")
        menu.addSeparator()

        act_fit_orig = act_fit_inside = None
        if is_pix or is_vid:
            act_fit_orig   = menu.addAction("元のサイズに合わせる")
            label_in = "現在の{}サイズに合わせる（内側にフィット）"
            act_fit_inside = menu.addAction(label_in.format("画像" if is_pix else "動画"))
            menu.addSeparator()

        act_del = menu.addAction("Delete")
        sel = menu.exec(ev.screenPos())

        # --- コピー（複数選択対応） ---
        if sel == act_copy:
            items = self.scene.selectedItems()
            ds = [getattr(it, "d", None) for it in items if hasattr(it, "d")]
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
            ds = [getattr(it, "d", None) for it in items if hasattr(it, "d")]
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

        # --- ペースト ---
        r"""
        if sel == act_paste:
            txt = QApplication.clipboard().text()
            try:
                js = json.loads(txt)
                # 新形式（複数・相対座標付き）
                if isinstance(js, dict) and "base" in js and "items" in js:
                    base_x, base_y = js["base"]
                    for d in js["items"]:
                        t = d.get("type")
                        dx = d.get("x", 0) - base_x
                        dy = d.get("y", 0) - base_y
                        d_new = d.copy()
                        paste_x = d.get("x", 100) + 24
                        paste_y = d.get("y", 100) + 24
                        d_new["x"] = paste_x + dx
                        d_new["y"] = paste_y + dy
                        item_new = None
                        if t == "json":
                            item_new = JSONItem(d_new, self.text_color)
                        elif t == "image":
                            item_new = ImageItem(d_new, self.text_color)
                        elif t == "note":
                            item_new = NoteItem(d_new)
                        elif t == "video":
                            item_new = VideoItem(d_new, win=self)
                        elif t == "launcher":
                            item_new = LauncherItem(d_new, self.text_color)
                        if item_new:
                            self.scene.addItem(item_new)
                            self.data["items"].append(d_new)
                else:
                    # 旧形式（単一アイテム貼り付け）
                    items = js if isinstance(js, list) else [js]
                    for d in items:
                        t = d.get("type")
                        d_new = d.copy()
                        d_new["x"] = d.get("x", 100) + 24
                        d_new["y"] = d.get("y", 100) + 24
                        # ...同様に分岐
            except Exception as e:
                warn(f"ペースト失敗: {e}")
            ev.accept()
            return
        """
        
        # --- Zオーダー変更 ---
        if sel == act_front:
            item.setZValue(max((i.zValue() for i in self.scene.items()), default=0) + 1)
        elif sel == act_back:
            item.setZValue(min((i.zValue() for i in self.scene.items()), default=0) - 1)

        # --- 元のサイズに合わせる 
        elif sel == act_fit_orig:
            if is_pix:
                from DPyL_utils import ICON_SIZE, _icon_pixmap
                from base64 import b64decode
                from PyQt6.QtGui import QPixmap

                embed_data = item.d.get("icon_embed")
                if embed_data:
                    # Embed から復元
                    pix = QPixmap()
                    pix.loadFromData(b64decode(embed_data))
                else:
                    # 通常の icon パスから取得
                    src = item.d.get("icon") or item.d.get("path")
                    idx = item.d.get("icon_index", 0)
                    pix = _icon_pixmap(src, idx, ICON_SIZE)

                if pix.isNull():
                    warn("アイコン取得失敗")
                    return

                # 最小サイズ制限
                w = max(pix.width(),  ICON_SIZE)
                h = max(pix.height(), ICON_SIZE)

                item._src_pixmap = pix.copy()
                item.prepareGeometryChange()
                item._rect_item.setRect(0, 0, w, h)
                item.d["width"], item.d["height"] = w, h
                if hasattr(item, "resize_content"):
                    item.resize_content(w, h)
                if hasattr(item, "_update_grip_pos"):
                    item._update_grip_pos()
                if hasattr(item, "init_caption"):
                    item.init_caption()

            elif is_vid:
                ns = item.nativeSize()
                if not ns.isValid():
                    return
                w, h = int(ns.width()), int(ns.height())
                item.prepareGeometryChange()
                item.setSize(QSizeF(w, h))
                item.d["width"], item.d["height"] = w, h
                if hasattr(item, "resize_content"):
                    item.resize_content(w, h)
                if hasattr(item, "_update_grip_pos"):
                    item._update_grip_pos()
                if hasattr(item, "init_caption"):
                    item.init_caption()


        # --- 内側にフィット ---
        elif sel == act_fit_inside:
            cur_w = int(item.boundingRect().width())
            cur_h = int(item.boundingRect().height())

            if is_pix:
                pm = item._src_pixmap.scaled(
                    cur_w, cur_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                w, h = pm.width(), pm.height()
            else:
                ns = item.nativeSize()
                if not ns.isValid():
                    return
                scale = min(cur_w / ns.width(), cur_h / ns.height())
                w, h = int(ns.width() * scale), int(ns.height() * scale)

            item.prepareGeometryChange()
            if is_pix:
                item._rect_item.setRect(0, 0, w, h)
                item._pix_item.setPixmap(pm)
            else:
                item.setSize(QSizeF(w, h))
            item.d["width"], item.d["height"] = w, h
            if hasattr(item, "resize_content"):
                item.resize_content(w, h)
            if hasattr(item, "_update_grip_pos"):
                item._update_grip_pos()
            if hasattr(item, "init_caption"):
                item.init_caption()
            if hasattr(item, "update_layout"):
                item.update_layout()
        # --- 削除 ---
        elif sel == act_del:
            self._remove_item(item)

        ev.accept()

    # --- 選択アイテムのコピー／カット ---
    def copy_or_cut_selected_items(self, cut=False):
        items = self.scene.selectedItems()
        ds = [getattr(it, "d", None) for it in items if hasattr(it, "d")]
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
            from DPyL_utils import b64encode_pixmap
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
            if hasattr(item, "set_run_mode"):
                item.set_run_mode(False)
            if hasattr(item, "grip"):
                item.grip.setVisible(True)
            elif hasattr(item, "_grip"):
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
        if hasattr(item, "delete_self"):
            item.delete_self()
        # 関連Gripを削除
        for attr in ("grip", "_grip", "resize_grip"):
            grip = getattr(item, attr, None)
            if grip and grip.scene():
                grip.scene().removeItem(grip)
            setattr(item, attr, None)
        # シーンから本体除去
        if item.scene():
            item.scene().removeItem(item)
        # JSONから辞書データ削除
        if hasattr(item, "d") and item.d in self.data.get("items", []):
            self.data["items"].remove(item.d)
        # 追加Gripの掃除
        if hasattr(item, "resize_grip") and item.resize_grip:
            if item.resize_grip.scene():
                item.resize_grip.scene().removeItem(item.resize_grip)
            item.resize_grip = None

    # --- 動画一括操作 ---
    def _play_all_videos(self):
        for it in self.scene.items():
            if isinstance(it, VideoItem):
                it.player.play(); it.btn_play.setChecked(True); it.btn_play.setText("⏸")

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

    # --- ドラッグ＆ドロップ対応 ---
    def handle_drop(self, e):
        """
        URL / ファイルドロップ共通ハンドラ
        * ネットワークドライブ   → 専用 LauncherItem
        * CanvasItem レジストリ → 自動判定で生成
        * http(s) URL           → favicon 付き LauncherItem
        ドロップ後は全体を編集モードへ強制切替！
        """
        added_any = False  # ← 何か追加したかのフラグ

        for url in e.mimeData().urls():
            sp = self.view.mapToScene(e.position().toPoint())
            raw_path = url.toLocalFile()
            path = normalize_unc_path(raw_path)

            # ---------- ① ネットワークドライブ ----------
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
                self.scene.addItem(it)
                self.data["items"].append(d)
                added_any = True
                continue

            # ---------- ② レジストリ判定 ----------
            item, d = self._create_item_from_path(path, sp)
            if item:
                self.scene.addItem(item)
                self.data["items"].append(d)
                added_any = True
                continue

            # ---------- ③ Web URL (.url も統合) ----------
            weburl = url.toString() or path
            if weburl.startswith(("http://", "https://")):
                it, d = self._make_web_launcher(weburl, sp,
                                                icon_path=path if path.endswith(".url") else "",
                                                is_url_file=path.endswith(".url"))
                if it:
                    self.scene.addItem(it)
                    self.data["items"].append(d)
                    added_any = True
                continue

            warn(f"[drop] unsupported or missing: {url}")

        # ---------- ドロップ完了後に全体を編集モードへ ----------
        if added_any:
            self._set_mode(edit=True)

    def resizeEvent(self, event):
        """
        ウィンドウやビューのリサイズ時に背景を再適用
        """
        super().resizeEvent(event)
        self._resize_timer.start(100)

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
            if other is item or not hasattr(other, "boundingRect"):
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
            if other is target_item or not hasattr(other, "boundingRect"):
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
        self._set_mode(edit=True)

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
        # 履歴を1つ戻る
        if self.hidx > 0:
            self._load_path(self.history[self.hidx - 1], ignore_geom=True)

    def _go_next(self):
        # 履歴を1つ進める
        if self.hidx < len(self.history) - 1:
            self._load_path(self.history[self.hidx + 1], ignore_geom=True)

    def _load_path(self, p: Path, *, ignore_geom=False):
        # 指定パスを履歴にプッシュしつつロード
        self._ignore_window_geom = ignore_geom
        self.json_path = p
        self._push_history(p)
        self._load()
        self._ignore_window_geom = False
        self._set_mode(edit=False)

    # --- モード切替（編集⇔実行） ---
    def _set_mode(self, *, edit: bool):
        """
        全CanvasItemの編集可否切替。
        edit=True: 移動・リサイズ可、False: 固定
        """
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
            if not hasattr(it, "d"):
                continue

            # アイテム側にモード伝達
            if hasattr(it, "set_run_mode"):
                it.set_run_mode(not edit)

            it.setFlag(movable_flag, edit)
            it.setFlag(selectable_flag, edit)
            it.setFlag(focusable_flag, edit)

            # リサイズグリップ表示切替
            if hasattr(it, "grip"):
                it.grip.setVisible(edit)
            elif hasattr(it, "_grip"):
                it._grip.setVisible(edit)

        self.view.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag if not edit
            else QGraphicsView.DragMode.RubberBandDrag
        )

    # --- データ読み込み ---
    def _load(self):
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
        map_cls = {
            "launcher": LauncherItem, "json": JSONItem,
            "image": ImageItem, "video": VideoItem, "note": NoteItem
        }
        for d in self.data.get("items", []):
            cls = map_cls.get(d.get("type", "launcher"))
            if not cls: continue
            it = cls(d, win=self) if cls is VideoItem else cls(d, self.text_color)
            it.setZValue(d.get("z", 0)); self.scene.addItem(it)
            it.setPos(d.get("x", 0), d.get("y", 0))
            
            # VideoItemはリサイズグリップを追加
            if isinstance(it, VideoItem) and it.resize_grip.scene() is None:
                self.scene.addItem(it.resize_grip)

        # ウィンドウジオメトリ復元
        if not self._ignore_window_geom and (geo := self.data.get("window_geom")):
            try:
                self.restoreGeometry(base64.b64decode(geo))
            except Exception as e:
                warn(f"Geometry restore failed: {e}")

        self._apply_background()
        # _set_modeは呼び出し元で維持

        # --- アイテム群を左上へシフト ---
        items = [it for it in self.scene.items() if hasattr(it, "d")]
        if items:
            min_x = min((it.x() for it in items), default=0)
            min_y = min((it.y() for it in items), default=0)
            dx = 50 - min_x
            dy = 50 - min_y
            for it in items:
                it.setPos(it.x() + dx, it.y() + dy)
        self._apply_scene_padding()
       
    def _apply_scene_padding(self, margin: int = 64):
        """シーン全体のバウンディングボックスを計算し中央寄せ"""
        items = [i for i in self.scene.items() if hasattr(i, "d")]
        if not items:
            return

        bounds = items[0].sceneBoundingRect()
        for it in items[1:]:
            bounds = bounds.united(it.sceneBoundingRect())

        bounds.adjust(-margin, -margin, margin, margin)
        self.scene.setSceneRect(bounds)

    # --- JSONプロジェクト切替用 ---
    def _load_json(self, path: Path):
        """JSONItemから呼ばれるプロジェクト切替"""
        self._ignore_window_geom = True
        self.json_path = Path(path).expanduser().resolve()
        self.setWindowTitle(f"desktopPyLauncher - {self.json_path.name}")
        self._push_history(self.json_path)
        self._load()
        self._ignore_window_geom = False
        self._set_mode(edit=False)

    # --- セーブ処理 ---
    def _save(self, *, auto=False):
        # 位置・サイズ・Z値等をdに反映
        for it in self.scene.items():
            if not hasattr(it, "d"): continue
            pos = it.pos(); it.d["x"], it.d["y"] = pos.x(), pos.y()
            if hasattr(it, "rect"):
                r = it.rect(); it.d["width"], it.d["height"] = r.width(), r.height()
            elif hasattr(it, "size"):
                s = it.size(); it.d["width"], it.d["height"] = s.width(), s.height()
            it.d["z"] = it.zValue()
            if isinstance(it, VideoItem) and hasattr(it, "audio"):
                try:
                    it.d["muted"] = it.audio.isMuted()
                except Exception as e:
                    warn(f"[WARN] muted状態の取得に失敗: {e}")

        self.data["window_geom"] = base64.b64encode(self.saveGeometry()).decode("ascii")
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            if not auto:
                QMessageBox.information(self, "SAVE", "保存しました！")
        except Exception as e:
            QMessageBox.critical(self, "SAVE", str(e))

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
