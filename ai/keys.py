"""AI 模块 · 密钥读取。

各 AI 平台的密钥统一记在项目根目录的 config.json 里（和头歌账号密码同一个文件）：

    {
      "GLM_API_KEY": "xxxx",
      "OPENAI_API_KEY": "xxxx"
    }

只放密钥，接口地址、模型名等非敏感内容写在对应厂商子模块的代码里。
（头歌账号密码不在这里：浏览器登录一次即可，账号会记进用户库 users.db）
本文件复用 common.config 的读取逻辑（带 mtime 缓存，改完不用重启）。

仓库里只有模板 config.example.json，config.json 自己建、不会提交。
"""
from ._compat import getSecret, loadSecrets, secretsPath


def configPath():
    """返回凭据文件（config.json）的绝对路径。"""
    return secretsPath()


def loadKeys(force=False):
    """读取 config.json 里的全部凭据，返回 dict。"""
    return loadSecrets(force)


def getKey(name, default=''):
    """取某个密钥（单个）；取不到返回 default。"""
    return getSecret(name, default)


def getKeys(name='GLM_API_KEY'):
    """取某个平台的全部密钥，返回列表（多 key 轮流用，能明显减少限流）。

    支持两种写法，合并且去重：
        {
          "GLM_API_KEY": "key1",
          "GLM_API_KEYS": ["key2", "key3"]
        }
    返回 ['key1', 'key2', 'key3']；什么都没配就返回 []。
    """
    data = loadKeys()
    keys = []

    single = data.get(name)
    if isinstance(single, str) and single.strip():
        keys.append(single.strip())

    many = data.get(f'{name}S') or data.get(f'{name}_LIST') or []
    if isinstance(many, str):
        many = [many]
    for item in many or []:
        if isinstance(item, str) and item.strip() and item.strip() not in keys:
            keys.append(item.strip())
    return keys
