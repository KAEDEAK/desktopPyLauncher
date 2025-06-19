# -*- coding: utf-8 -*-

from __future__ import annotations

import warnings
import traceback
from collections import defaultdict

def trace_this(s):
    stack = traceback.extract_stack()
    caller = stack[-2]  # 呼び出し元（直前のフレーム）
    print(f"{s}, called from {caller.filename}:{caller.lineno} in {caller.name}()")


def simple_my_has_attr(obj, attr):
    if not hasattr(obj,attr):
        warnings.warn(f"[warn] {attr} が未定義: {type(obj).__name__} には {attr} が存在しません")        
        return False
    return True
    

# 記録用：クラス名ごとに欠損属性名を記録
_missing_attrs: dict[str, set[str]] = defaultdict(set)

def my_has_attr(obj: object, attr: str) -> bool:
    if not hasattr(obj, attr):
        cls_name = type(obj).__name__
        _missing_attrs[cls_name].add(attr)
        warnings.warn(f"[warn] {attr} が未定義: {cls_name} には {attr} が存在しません", stacklevel=2)
        return False
    return True

def dump_missing_attrs():
    print("\n🔍 属性が見つからなかったクラス一覧:")
    for cls, attrs in _missing_attrs.items():
        print(f"  📦 {cls}:")
        for attr in sorted(attrs):
            print(f"    - {attr}")

def my_has_attr(obj: object, attr: str) -> bool: return hasattr(obj, attr)
def dump_missing_attrs(): pass

__all__ = ["my_has_attr", "dump_missing_attrs", "trace_this"]
