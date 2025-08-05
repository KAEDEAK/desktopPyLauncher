# NoteItem トラブルシューティングガイド

## 概要
NoteItemのキャンバス編集モードでの問題と解決策についてまとめています。

## クラス階層構造

### アプリケーション全体の3層構造

#### 問題発生時の状態
```
MainWindow (QMainWindow) ← 最上位：イベント拾えない❌
└── CanvasView (QGraphicsView) ← 中間層：一部イベント処理
    └── QGraphicsScene ← シーンレイヤー
        └── NoteItem ← EDITモード時にイベント競合
            └── txt_item (QGraphicsTextItem) ← テキスト編集でイベント独占
```

#### 修正後の理想的な構造
```
MainWindow (QMainWindow) ← 最上位：eventFilter()で全イベント監視✅
├── installEventFilter(self) ← アプリ全体のイベントキャッチ
└── CanvasView (QGraphicsView) ← 中間層：ビュー処理継続
    └── QGraphicsScene ← シーンレイヤー
        └── NoteItem (CanvasItem) ← アイテムレイヤー：MainWindowと連携
            ├── clip_item (QGraphicsRectItem) ← クリッピング用
            └── txt_item (QGraphicsTextItem) ← テキスト表示：適切なカーソル
```

#### 詳細な親子関係
```
MainWindow (QMainWindow)
├── _current_edit_item: NoteItem | None ← EDITモード追跡
├── eventFilter(obj, event) ← 全イベント監視
├── register_edit_item(item) ← EDITモード登録
├── unregister_edit_item(item) ← EDITモード解除
└── CanvasView (QGraphicsView)
    ├── scene: QGraphicsScene
    ├── mousePressEvent() ← Water Effect等
    ├── mouseReleaseEvent() ← 5ボタンマウス対応
    └── QGraphicsScene
        └── NoteItem (CanvasItem) ← parent=scene
            ├── _mode: int ← WALK/SCROLL/EDIT
            ├── _notify_edit_mode_start() ← MainWindowに通知
            ├── _notify_edit_mode_end() ← MainWindowに通知
            ├── _exit_to_walk_mode() ← 統一復帰処理
            ├── clip_item (QGraphicsRectItem) ← parent=self
            │   └── ItemClipsChildrenToShape=True
            └── txt_item (QGraphicsTextItem) ← parent=clip_item
                ├── TextInteractionFlags制御
                ├── setCursorWidth(2)
                └── setAcceptedMouseButtons制御
```

### 初期化コード位置
- **MainWindow**: `desktopPyLauncher.py:1299` - `class MainWindow(QMainWindow)`
- **CanvasView**: `desktopPyLauncher.py:666` - `class CanvasView(QGraphicsView)`
- **NoteItem**: `module/DPyL_note.py:93` - `class NoteItem(CanvasItem)`

### 階層間の接続
```python
# desktopPyLauncher.py:1332-1334
self.scene = QGraphicsScene(self)
self.view = CanvasView(self.scene, self)
self.setCentralWidget(self.view)
```

## 問題1: "|" 文字による仮キャレット

### 問題内容
EDITモード時に適切なテキストカーソル（キャレット）が表示されないため、"|" 文字を挿入して代替していた。

### 原因
```python
# 問題のあったコード（削除済み）
cursor.insertText("|")  # 仮キャレット挿入
self._temp_caret_added = True  # フラグ管理
```

### 解決策
1. **仮キャレット関連コードを全削除**
2. **適切なQt テキストカーソル設定**
```python
# 新しい実装
self.txt_item.setCursorWidth(2)  # カーソル幅設定
self.txt_item.ensureCursorVisible()  # 表示強制
self.txt_item.update()  # 描画更新
```

## 問題2: フォーカス外れ時の復帰問題

### 問題内容
フォーカスが外れてもEDITモードから元のドラッグモード（WALKモード）に戻らない。

### 原因
```python
# 問題のあった設定
self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # 親無効❌
```

### 解決策
```python
# 修正後の設定
self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)  # 親も有効✅

# 統一処理メソッド
def _exit_to_walk_mode(self):
    """EDITモードからWALKモードに戻る統一処理"""
    if self._mode == NOTE_MODE_EDIT:
        self._exit_edit_mode()
    self._mode = NOTE_MODE_WALK
    self._update_mode_label()
    self._update_selection_frame()
    self._restore_parent_event_handling()
```

## 問題3: テキスト領域サイズ問題

### 問題内容
テキスト領域が親領域より小さい場合、テキスト領域からマウスが出ても親領域内にいるため`hoverLeaveEvent`が発火しない。

### 初期アプローチ（複雑すぎて却下）
```python
# 試行錯誤したカスタムクラス（削除済み）
class NoteTextItem(QGraphicsTextItem):
    def hoverLeaveEvent(self, event):
        # 複雑なhover event処理
```

### 最終解決策
既存の`mousePressEvent`でテキスト領域外クリック検知を活用
```python
def mousePressEvent(self, ev):
    if self._mode == NOTE_MODE_EDIT:
        local_pos = self.mapFromScene(ev.scenePos())
        text_rect = self.txt_item.boundingRect()
        text_rect.translate(self.txt_item.pos())
        
        if not text_rect.contains(local_pos):
            # テキストエリア外のクリック → 編集終了
            self._exit_to_walk_mode()
```

## 問題4: 3層構造でのイベント伝搬問題

### 問題内容
最上位のMainWindowがマウスイベントを拾えない。中間層のCanvasViewでイベントが止まってしまう。

### 解決策: MainWindowレベルでのイベント監視

#### 1. イベントフィルター実装
```python
# MainWindow初期化時
self._current_edit_item = None  # EDITモード追跡
self.installEventFilter(self)   # 全体監視

def eventFilter(self, obj, event):
    """アプリケーション全体のイベントフィルター"""
    if event.type() == QEvent.Type.MouseButtonPress:
        if self._current_edit_item is not None:
            # 座標変換
            global_pos = obj.mapToGlobal(event.pos())
            view_pos = self.view.mapFromGlobal(global_pos)
            scene_pos = self.view.mapToScene(view_pos)
            
            # 領域チェック
            item_rect = self._current_edit_item.boundingRect()
            item_pos = self._current_edit_item.pos()
            item_scene_rect = QRectF(
                item_pos.x() + item_rect.x(),
                item_pos.y() + item_rect.y(),
                item_rect.width(),
                item_rect.height()
            )
            
            # 領域外クリック時に自動終了
            if not item_scene_rect.contains(scene_pos):
                self._current_edit_item._exit_to_walk_mode()
                self._current_edit_item = None
    
    return super().eventFilter(obj, event)
```

#### 2. EDITモード管理システム
```python
def register_edit_item(self, item):
    """NoteItemがEDITモードに入った時の登録"""
    self._current_edit_item = item

def unregister_edit_item(self, item):
    """NoteItemがEDITモードから抜けた時の登録解除"""
    if self._current_edit_item == item:
        self._current_edit_item = None
```

#### 3. NoteItemからの通知
```python
def _notify_edit_mode_start(self):
    """MainWindowにEDITモード開始を通知"""
    try:
        scene = self.scene()
        if scene and scene.views():
            win = scene.views()[0].window()
            if hasattr(win, 'register_edit_item'):
                win.register_edit_item(self)
    except Exception as e:
        warn(f"[NoteItem] _notify_edit_mode_start error: {e}")

def _notify_edit_mode_end(self):
    """MainWindowにEDITモード終了を通知"""
    try:
        scene = self.scene()
        if scene and scene.views():
            win = scene.views()[0].window()
            if hasattr(win, 'unregister_edit_item'):
                win.unregister_edit_item(self)
    except Exception as e:
        warn(f"[NoteItem] _notify_edit_mode_end error: {e}")
```

## イベント処理の優先順位

### 最終的な処理順序
```
1. MainWindow.eventFilter() ← 最高優先度：アプリ全体監視
   ├── EDITモード中のアイテム領域外クリック検知
   └── 自動的にWALKモードに復帰

2. CanvasView.mousePressEvent() ← 中間優先度：ビューレベル処理
   ├── Water Effect
   └── 通常のビュー操作

3. NoteItem.mousePressEvent() ← アイテム優先度
   ├── テキスト領域内外の判定
   └── EDITモード管理

4. txt_item (QGraphicsTextItem) ← 最低優先度：テキスト編集
```

## 動作確認ポイント

### テスト項目
1. **EDITモード開始**: ダブルクリック → 赤枠表示 → カーソル点滅
2. **テキスト領域外クリック**: EDITモード → 領域外クリック → WALKモード復帰
3. **フォーカス喪失**: EDITモード → 他ウィンドウクリック → WALKモード復帰
4. **カーソル離脱**: EDITモード → ノートエリア外移動 → WALKモード復帰
5. **ドラッグ操作**: WALKモード → 画面ドラッグ → スクロール動作

### デバッグ出力
```python
warn("[MainWindow] Click outside edit item, exit EDIT mode")
warn("[NoteItem] Entering EDIT mode")
warn("[NoteItem] Exiting EDIT mode")
warn("[NoteItem] Restored parent event handling for WALK mode")
```

## 修正されたファイル

### 主要変更
- `desktopPyLauncher.py`: MainWindowにイベントフィルターとEDITモード管理を追加
- `module/DPyL_note.py`: 仮キャレット削除、適切なカーソル表示、MainWindow連携

### コード位置
- MainWindow.eventFilter: `desktopPyLauncher.py:4407-4441`
- MainWindow.register_edit_item: `desktopPyLauncher.py:4443-4446`
- MainWindow.unregister_edit_item: `desktopPyLauncher.py:4448-4452`
- NoteItem._notify_edit_mode_start: `module/DPyL_note.py:768-777`
- NoteItem._notify_edit_mode_end: `module/DPyL_note.py:779-788`

## 今後の改善点

### 考慮事項
1. **複数NoteItemの同時EDIT対応**（現在は1個まで）
2. **パフォーマンス最適化**（イベントフィルターの負荷軽減）
3. **他のCanvasItemへの適用**（VideoItem、TerminalItem等）

### 拡張可能性
```python
# 将来的な複数アイテム対応例
self._edit_items = set()  # 複数アイテム管理

def register_edit_item(self, item):
    self._edit_items.add(item)

def check_all_edit_items(self, scene_pos):
    for item in list(self._edit_items):
        if not item.contains_point(scene_pos):
            item._exit_to_walk_mode()
```

## 問題5: QGraphicsTextItemカーソル点滅問題 **【保留】**

### 問題内容
EDITモード時にテキストカーソル（キャレット）が適切に表示・点滅しない問題。

#### 症状
- EDITモード開始時にカーソルが表示されない（見えない）
- カーソルの点滅アニメーションが動作しない
- カーソルキーで移動した後にのみ静止したカーソルが表示される
- フォーカス設定やテキスト入力は正常に動作

### 根本原因の特定

#### 1. Qtの既知バグ（QTBUG-16627）
- **バグ詳細**: `QTextControlPrivate`のカーソル点滅タイマーが適切に再起動されない
- **影響範囲**: Qt 4.7.1以降、現在まで**未解決**の長期バグ
- **技術的詳細**:
  ```
  カーソル点滅は QTextControlPrivate 内のタイマーで制御される
  - タイマーが "cursorOn" boolean を切り替えてカーソル表示/非表示
  - カーソル移動時に cursorOn は true に設定される
  - しかし、タイマーの再起動が行われない
  - 結果: 点滅の同期が崩れ、カーソルが見えない状態が続く
  ```

#### 2. 親子関係による影響（調査結果）
```
NoteItem (CanvasItem)
├── clip_item (QGraphicsRectItem) ← ItemClipsChildrenToShape=True
│   └── txt_item (CustomQGraphicsTextItem) ← parent=clip_item
```
- **仮説**: `ItemClipsChildrenToShape=True`がカーソル描画をクリップ
- **検証結果**: マージン追加とクリップ領域拡張を実施したが**効果なし**
- **結論**: 根本原因ではない（点滅自体が動作していない）

### 実施した対策と結果

#### 1. focusInEventオーバーライド ❌
```python
class CustomQGraphicsTextItem(QGraphicsTextItem):
    def focusInEvent(self, event):
        super().focusInEvent(event)  # 重要: 最後に呼び出し
        # カーソル位置再設定で表示トリガー
        cursor = self.textCursor()
        cursor.setPosition(cursor.position())
        self.setTextCursor(cursor)
```
**結果**: カーソル表示されず、点滅もしない

#### 2. フォーカス制御の強化 ❌
```python
self.txt_item.setFocus(Qt.FocusReason.MouseFocusReason)
if self.scene():
    self.scene().setFocusItem(self.txt_item)
```
**結果**: フォーカスは正常だが、カーソル表示問題は未解決

#### 3. クリップ領域とマージン調整 ❌
```python
# txt_itemにマージン追加
self.txt_item.setPos(2, 2)

# clip_item拡張
expanded_rect = rect.adjusted(-1, -1, 1, 1)
self.clip_item.setRect(expanded_rect)
```
**結果**: レイアウトは改善されたが、カーソル点滅問題は継続

#### 4. 遅延処理によるカーソル確保 ❌
```python
QTimer.singleShot(50, self._ensure_cursor_blinking)

def _ensure_cursor_blinking(self):
    cursor = self.txt_item.textCursor()
    cursor.setPosition(cursor.position())
    self.txt_item.setTextCursor(cursor)
```
**結果**: カーソル位置設定は動作するが、視覚的表示は改善されず

### 調査で判明した技術的詳細

#### QTextControlPrivateの点滅メカニズム
1. **正常動作時**:
   ```
   Timer → cursorOn切替 → 500ms間隔で点滅 → 視覚的フィードバック
   ```

2. **バグ発生時**:
   ```
   カーソル移動 → cursorOn=true → タイマー再起動せず → 点滅停止
   → ユーザー操作490ms後 → タイマー発火 → カーソル消える
   → 短時間表示後すぐに非表示 → 視覚的に見えない
   ```

#### 関連するQtバグレポート
- **QTBUG-16627**: メインのカーソル点滅バグ
- **QTBUG-70627**: マウスでのカーソル位置変更で表示されない問題  
- **QTBUG-30120**: カーソル点滅関連の追加問題
- **QTBUG-83029**: TextSelectableByKeyboardでカーソル点滅しない

### 将来の解決策候補

#### アプローチ1: カスタム点滅タイマー実装
```python
class CursorBlinkManager(QObject):
    def __init__(self, text_item):
        super().__init__()
        self.text_item = text_item
        self.timer = QTimer()
        self.cursor_visible = True
        
        # システムのカーソル点滅間隔を取得
        app = QApplication.instance()
        flash_time = app.styleHints().cursorFlashTime()
        self.timer.timeout.connect(self._toggle_cursor)
        self.timer.start(flash_time // 2)  # 半分の間隔で切り替え
```

#### アプローチ2: paint()オーバーライドによる手動制御
```python
class CustomQGraphicsTextItem(QGraphicsTextItem):
    def paint(self, painter, option, widget):
        super().paint(painter, option, widget)
        # Qt内部のカーソル描画を無効化
        # 独自の縦線カーソルを描画
        if self.hasFocus() and self.cursor_visible:
            self._draw_custom_cursor(painter)
```

#### アプローチ3: 固定カーソル表示（シンプル解決策）
```python
# 点滅を諦めて、常時表示の縦線を描画
def _draw_fixed_cursor(self, painter):
    cursor_pos = self._get_cursor_position()
    painter.setPen(QPen(QColor(255, 255, 255), 1))
    painter.drawLine(cursor_pos.x(), cursor_pos.y(), 
                    cursor_pos.x(), cursor_pos.y() + line_height)
```

### 保留理由と推奨事項

#### 保留理由
1. **Qt内部バグのため根本解決困難**: カーソル点滅はQt内部の複雑なタイマーシステムに依存
2. **工数対効果**: カスタム実装の複雑性に対して得られる改善効果が限定的
3. **回避策の存在**: カーソルキー移動で表示される現状でも基本的な編集作業は可能
4. **将来のQt更新期待**: バグ修正される可能性を考慮

#### 推奨事項
1. **現状受容**: カーソルキー移動後に表示される動作で運用継続
2. **UI設計変更検討**: 
   - EDITモード時の視覚的フィードバック強化（枠色変更等）
   - ステータス表示でEDITモード状態を明示
3. **Qt更新監視**: 将来のQtバージョンでのバグ修正状況を追跡
4. **必要時の段階的実装**: ユーザーフィードバックに応じてカスタム実装を検討

### 参考情報
- **Qt Bug Tracker**: QTBUG-16627, QTBUG-70627, QTBUG-30120
- **検証環境**: PySide6, Windows 10/11
- **関連ファイル**: `module/DPyL_note.py`, `CustomQGraphicsTextItem`クラス