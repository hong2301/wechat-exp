"""AI 模块（ai）：统一的大模型调用入口，厂商以插件形式接入。

一个 AI 厂商 = modules/ai 下的一个子模块文件夹，模块会被自动发现并注册，
所以新增厂商不用改本文件的任何代码。

已接入
    glm/    智谱 GLM（默认模型 glm-4.7-flash，带 reasoning_content 思维链）

────────────────────────────────────────────────────────────────────────
新增一个厂商的步骤（以 openai 为例）
────────────────────────────────────────────────────────────────────────
1. 复制 modules/ai/glm/ 为 modules/ai/openai/
2. 在 openai/__init__.py 里改这几处：
       PROVIDER = 'openai'                 # 厂商名，调用时 provider='openai'
       LABEL = 'OpenAI'                    # 展示用名称
       BASE_URL = 'https://api.openai.com/v1'
       DEFAULT_MODEL = 'gpt-4o-mini'
       api_key = getKey('OPENAI_API_KEY')  # 密钥名
   并保证提供 chat(messages, ...) 与 ask(prompt, ...) 两个函数（返回 ok/fail 统一格式）
3. 在项目根目录 config.json 里加一行：{"OPENAI_API_KEY": "xxxx"}
   完成，providers() 会自动多出 'openai'

────────────────────────────────────────────────────────────────────────
本文件引用的内容说明
────────────────────────────────────────────────────────────────────────
【.keys】密钥读取
    getKey('GLM_API_KEY')  从项目根目录 config.json 取密钥
    loadKeys()             读取全部密钥
    configPath()           密钥文件路径
【..common】ok / fail 统一返回格式
【importlib / pkgutil】扫描本包下的子模块文件夹，自动注册厂商；
    厂商名取子模块里的 PROVIDER，没有则用文件夹名
【.glm 等子模块】必须提供 chat(messages, ...) / ask(prompt, ...)，
    可选提供 PROVIDER / LABEL / DEFAULT_MODEL，用于 providers() 与 info() 展示

对外函数
    providers()                          已接入厂商名列表，如 ['glm']
    info()                               各厂商信息 [{provider, label, default_model}]
    chat(messages, provider='glm', ...)  统一对话入口，按 provider 分发
    ask(prompt, provider='glm', ...)     统一单轮提问入口
    统一返回 {'status', 'message', 'data'}，data 含 content / reasoning_content / usage / raw

本模块定位
    只做「基础能力」：发现厂商、转发调用、统一返回格式。
    不包含任何业务语义（如"解题"、"生成答案"、"闯关"），这类能力应当基于本模块
    在更高层封装（例如另建一个业务模块，内部调 ai.ask / ai.chat）。
    厂商子模块只负责自家接口的参数与响应适配。

默认行为
    GLM 子模块的 chat / ask 默认 thinking=False（只要结果，不返回推理过程）：
        ask('给点内容')['data']['content']        # 直接拿结果
        ask('给点内容', thinking=True)            # 需要思维链时显式打开
"""
from ._compat import logCall
import importlib
import pkgutil

from ._compat import fail
from . import glm  # noqa: F401  先导入默认厂商，保证离线时也有可用实现
from .keys import configPath, getKey, loadKeys

_providerCache = None


def _discover():
    """扫描本包下所有子模块文件夹，返回 {厂商名: 子模块}。"""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        name = info.name
        if not info.ispkg or name.startswith('_'):
            continue  # 只认"一个厂商一个文件夹"
        try:
            module = importlib.import_module(f'{__name__}.{name}')
        except Exception:
            continue  # 子模块导入失败（如缺少依赖）不影响其它厂商
        if callable(getattr(module, 'chat', None)):
            found[getattr(module, 'PROVIDER', None) or name] = module
    return found


def _providers():
    """带缓存的厂商表。"""
    global _providerCache
    if _providerCache is None:
        _providerCache = _discover()
    return _providerCache


def reloadProviders():
    """重新扫描厂商（新增子模块后想立即生效时调用，通常不需要）。"""
    global _providerCache
    _providerCache = None
    return providers()


@logCall
def providers():
    """已接入的 AI 厂商名列表。"""
    return sorted(_providers())


@logCall
def info():
    """各厂商信息，便于上层展示：厂商名 / 名称 / 默认模型。"""
    return [{
        'provider': name,
        'label': getattr(module, 'LABEL', name),
        'default_model': getattr(module, 'DEFAULT_MODEL', ''),
    } for name, module in sorted(_providers().items())]


def _pick(provider):
    """按厂商名取子模块，返回 (module, error)。"""
    module = _providers().get(provider)
    if module is None:
        return None, fail(f'未接入的 AI 厂商：{provider}（当前可用：{"、".join(providers())}）')
    return module, None


@logCall
def chat(messages, provider='glm', **kwargs):
    """统一对话入口：按 provider 分发到对应厂商子模块。

    messages 传字符串或 [{'role', 'content'}, ...]，其余参数原样传给厂商的 chat。
    返回: {status, message, data}。
    """
    module, error = _pick(provider)
    if error:
        return error
    return module.chat(messages, **kwargs)


@logCall
def ask(prompt, provider='glm', **kwargs):
    """统一单轮提问入口：ask('你好')。"""
    module, error = _pick(provider)
    if error:
        return error
    return module.ask(prompt, **kwargs)


__all__ = [
    'chat', 'ask', 'providers', 'info', 'reloadProviders',
    'glm',
    'getKey', 'loadKeys', 'configPath',
]
