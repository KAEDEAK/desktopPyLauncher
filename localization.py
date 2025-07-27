import json
import locale
import os
from pathlib import Path

class Localizer:
    def __init__(self, language=None):
        self.translations = {}
        self.current_language = language if language else self._detect_system_language()
        self._load_translations()
    
    def _detect_system_language(self):
        """OSの言語設定を検出してデフォルト言語を決定"""
        try:
            # Windows環境での言語検出を改善
            import platform
            if platform.system() == 'Windows':
                import ctypes
                windll = ctypes.windll.kernel32
                language_id = windll.GetUserDefaultUILanguage()
                if language_id == 1041:  # Japanese
                    return 'ja'
                else:
                    return 'en'
            else:
                # その他のOS
                system_locale = locale.getlocale()[0]
                if system_locale and system_locale.startswith('ja'):
                    return 'ja'
        except:
            pass
        return 'en'  # デフォルトは英語
    
    def _load_translations(self):
        """localize.jsonから翻訳データを読み込み"""
        try:
            localize_path = Path(__file__).parent / "localize.json"
            with open(localize_path, 'r', encoding='utf-8') as f:
                self.translations = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load localize.json: {e}")
            self.translations = {}
    
    def get_text(self, key: str) -> str:
        """指定されたキーの翻訳テキストを取得"""
        if self.current_language in self.translations:
            return self.translations[self.current_language].get(key, key)
        return key  # キーが見つからない場合はキー自体を返す
    
    def set_language(self, language: str):
        """言語を手動で設定"""
        if language in self.translations:
            self.current_language = language
    
    def get_current_language(self):
        """現在の言語を取得"""
        return self.current_language

# グローバルなローカライザーインスタンス
_localizer = None

def initialize_localizer(language=None):
    """ローカライザーを初期化"""
    global _localizer
    _localizer = Localizer(language)

def _(key: str) -> str:
    """翻訳テキストを取得するための短縮関数"""
    if _localizer is None:
        initialize_localizer()
    return _localizer.get_text(key)

def get_localizer():
    """ローカライザーインスタンスを取得"""
    if _localizer is None:
        initialize_localizer()
    return _localizer