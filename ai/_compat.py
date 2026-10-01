# -*- coding: utf-8 -*-
"""AI 模块兼容层：替代源项目（头歌闯关王）的 logger / common 依赖。

- logCall：no-op 装饰器（原 logger.decorator.logCall）
- ok / fail：统一返回结构（原 common.response）
- secretsPath / loadSecrets / getSecret：config.json 密钥读取（原 common.config）
"""
import functools
import json
import os


def logCall(func=None, *, show_args=True, show_result=True, level=None):
    """no-op 装饰器（替代源项目 logger，仅保证可导入与可装饰）。"""
    if func is None:
        return lambda f: f
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# ---------------- 统一返回格式（原 common.response） ----------------
def ok(message='操作成功', data=None):
    return {'status': 'success', 'message': message,
            'data': data if data is not None else {}}


def fail(message='操作失败', data=None):
    return {'status': 'error', 'message': message,
            'data': data if data is not None else {}}


# ---------------- 密钥读取（原 common.config，config.json 在项目根） ----------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ai/ → 项目根
SECRETS_PATH = os.path.join(_ROOT, 'config.json')

_secrets_cache = None
_secrets_mtime = None


def secretsPath():
    return SECRETS_PATH


def loadSecrets(force=False):
    global _secrets_cache, _secrets_mtime
    try:
        mtime = os.path.getmtime(SECRETS_PATH)
    except OSError:
        _secrets_cache, _secrets_mtime = {}, None
        return {}
    if force or mtime != _secrets_mtime:
        try:
            with open(SECRETS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _secrets_cache = {k: v for k, v in data.items()
                              if not k.startswith('_')}
        except (OSError, ValueError):
            _secrets_cache = {}
        _secrets_mtime = mtime
    return dict(_secrets_cache)


def getSecret(name, default=''):
    value = loadSecrets().get(name, default)
    return value if value is not None else default