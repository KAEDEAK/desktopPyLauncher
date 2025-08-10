# アニメーション関連コンポーネント

## 概要

desktopPyLauncherにおけるアニメーション機能（GIF、APNG）の実装について説明します。

## アーキテクチャ

### GifMixin

**ファイル**: `module/DPyL_classes.py`

GIFアニメーション機能を提供するミックスインクラス。

#### 主要機能
- QMovieを使用したGIFアニメーション再生
- 再生/一時停止の制御
- フレーム変更時の自動サイズ調整
- シグナル/スロット接続の安全な管理

#### 重要メソッド
```python
def _init_gif_movie(self, path_or_data)
def _play_gif(self)
def _pause_gif(self)
def _toggle_gif_playback(self)
def _on_movie_frame_changed(self, frame_number)
```

#### 使用パターン
```python
# QMovieの初期化
self._movie = QMovie()
self._movie.frameChanged.connect(self._on_movie_frame_changed)

# 再生制御
if self._movie.state() == QMovie.Running:
    self._pause_gif()
else:
    self._play_gif()
```

### GifItem

**ファイル**: `module/DPyL_classes.py`

GIFファイル専用のCanvasItemクラス。GifMixinとImageItemを継承。

#### クラス定義
```python
class GifItem(GifMixin, ImageItem):
    TYPE_NAME = "gif"
```

#### 特徴
- `.gif`拡張子のファイルを自動検出
- マウスクリックでアニメーション切り替え
- GifMixinの全機能を継承
- ImageItemの基本機能（リサイズ、移動等）を継承

#### ファイル判定
```python
@classmethod
def supports_path(cls, path: str) -> bool:
    return Path(path).suffix.lower() == '.gif'
```

### APNGItem

**ファイル**: `module/DPyL_classes.py`

Animated PNG（APNG）ファイル専用のCanvasItemクラス。

#### 特徴
- APNG形式の自動検出（acTLチャンクの検出）
- pyAPNGライブラリを使用したフレーム抽出
- QTimer + QPixmapによる独自アニメーション実装
- GifItemと同様のマウスクリック切り替え機能

#### 主要プロパティ
```python
self.frames = []           # フレームデータのリスト
self.current_frame = 0     # 現在のフレーム番号
self.timer = QTimer()      # アニメーション制御用タイマー
self._is_playing = False   # 再生状態
```

#### アニメーション実装
```python
def _next_frame(self):
    """次のフレームに移動"""
    if not self.frames or not self._is_playing:
        return
    
    self.current_frame = (self.current_frame + 1) % len(self.frames)
    frame_data, delay = self.frames[self.current_frame]
    
    # フレーム表示
    self._display_frame(frame_data)
    
    # 次のフレームをスケジュール
    self.timer.start(delay)
```

#### APNG検出
**ファイル**: `module/DPyL_utils.py`
```python
def detect_apng(data: bytes) -> bool:
    """PNGデータからAPNG（アニメーションPNG）かどうかを判定"""
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    
    offset = 8
    while offset < len(data) - 8:
        chunk_type = data[offset+4:offset+8]
        if chunk_type == b'acTL':
            return True
        if chunk_type == b'IDAT':
            return False
        # 次のチャンクへ
```

## ファイル形式対応

### 対応形式と優先順位

1. **APNG** (APNGItem) - `*.png`でacTLチャンクを含む
2. **GIF** (GifItem) - `*.gif`
3. **静的画像** (ImageItem) - その他の画像形式

### 判定フロー

1. ファイル拡張子が`.png`の場合
   - バイナリデータを読み込み
   - `detect_apng()`でAPNGかチェック
   - APNGならAPNGItem、そうでなければImageItem

2. ファイル拡張子が`.gif`の場合
   - GifItemで処理

3. その他の画像拡張子
   - ImageItemで処理

## 使用例

### GIF再生
```python
# GIFファイルの読み込み（自動でGifItemが選択される）
gif_item = create_canvas_item_from_path("animation.gif", position, window)

# マウスクリックで再生/停止切り替え
# gif_item.mousePressEvent() が自動的に _toggle_gif_playback() を呼び出し
```

### APNG再生
```python
# APNGファイルの読み込み（自動でAPNGItemが選択される）
apng_item = create_canvas_item_from_path("animation.png", position, window)

# マウスクリックで再生/停止切り替え
# apng_item.mousePressEvent() が自動的に _toggle_playback() を呼び出し
```

## 技術的詳細

### QMovieの制限
- Qt6のQMovieはAPNG形式をサポートしていない
- そのためAPNGは独自実装（pyAPNG + QTimer + QPixmap）を使用

### メモリ管理
- APNGItem: 全フレームをメモリに保持（高速再生）
- GifItem: QMovieがフレームを動的に管理（メモリ効率）

### タイマー管理
- APNGItem: QTimerをsingleShotモードで使用
- 各フレームの表示後、次のフレームのタイマーをスケジュール
- 親オブジェクト指定なし（CanvasItemはQObjectではない）

## 依存関係

### 必須ライブラリ
- **PySide6**: Qt6ベースのGUI
- **pyAPNG**: APNG処理用（`pip install apng>=0.3.4`）

### インポート
```python
# DPyL_classes.py
from PySide6.QtCore import QTimer
from PySide6.QtGui import QMovie, QPixmap
from apng import APNG  # APNG処理用

# DPyL_utils.py  
def detect_apng(data: bytes) -> bool  # APNG判定関数
```

## トラブルシューティング

### よくある問題

1. **APNGが再生されない**
   - pyAPNGライブラリがインストールされているか確認
   - `detect_apng()`が正しくAPNGを検出しているか確認

2. **GIFの再生/停止が効かない**
   - `mousePressEvent`の実装確認
   - QMovieの状態確認

3. **メモリリーク**
   - QTimerの適切な停止確認
   - QMovieのリソース解放確認

### デバッグ用設定
```python
# DPyL_utils.py
DEBUG_MODE = True  # デバッグメッセージの有効化
```