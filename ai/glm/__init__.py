"""AI 模块 · 子模块：智谱 GLM。

接口（OpenAI 兼容格式）
    POST {BASE_URL}/chat/completions
    Header: Authorization: Bearer {GLM_API_KEY}

参数完全对齐官方 OpenAPI（/paas/v4/chat/completions · ChatCompletionTextRequest），
下表里"官方默认"是该字段不传时服务端的行为，本模块对未传的参数一律不下发。

┌────────────────────┬──────────┬──────────────┬────────────────────────────────────┐
│ 参数               │ 类型     │ 官方默认     │ 说明                               │
├────────────────────┼──────────┼──────────────┼────────────────────────────────────┤
│ model              │ string   │ glm-5.3      │ 模型代码，见 MODELS                │
│ messages           │ array    │ 必填         │ 消息列表（system/user/assistant/tool）│
│ stream             │ boolean  │ false        │ 流式输出（SSE），本模块已实现        │
│ thinking           │ object   │ 不传         │ 思维链开关 {type, clear_thinking}   │
│ reasoning_effort   │ string   │ max          │ 推理程度 max/xhigh/high/medium/low/minimal/none │
│ do_sample          │ boolean  │ true         │ 是否采样（false = 每次取概率最高）   │
│ temperature        │ number   │ 1.0          │ 采样温度 [0.0, 1.0]，两位小数       │
│ top_p              │ number   │ 0.95         │ 核采样 [0.01, 1.0]                  │
│ max_tokens         │ integer  │ 不传         │ 最大输出 token（GLM-4.7 系列 128K）  │
│ tool_stream        │ boolean  │ false        │ 是否流式返回 Function Calls         │
│ tools              │ array    │ 不传         │ 可调用的工具列表（最多 128 个）      │
│ tool_choice        │ string/obj│ auto        │ 工具选择策略 auto/none/指定函数     │
│ stop               │ array    │ 不传         │ 停止词列表 ["stop_word"]            │
│ response_format    │ object   │ text         │ 输出格式 {type: text/json_object}   │
│ request_id         │ string   │ 自动生成     │ 请求唯一标识（6~64 字符）           │
│ user_id            │ string   │ 不传         │ 终端用户标识（6~128 字符）          │
└────────────────────┴──────────┴──────────────┴────────────────────────────────────┘
另有本模块自有的便利参数（不发给接口）：system、timeout、proxy、on_chunk

thinking 的写法（实测 + 官方定义）
    False（本模块默认）      → {"type": "disabled"}：只要结果、不要推理过程
                             实测同一道题 2.2s / 181 tokens → 0.4s / 2 tokens
    None / True            → {"type": "enabled"}：会返回 reasoning_content 思维链
    'disabled'             → {"type": "disabled"}
    {'type': 'enabled', 'clear_thinking': False}   → 原样透传
    注意：接口只接受对象形式，传布尔值会 JSON parse error，本模块已自动转换；
         clear_thinking 官方默认 True，即忽略历史轮次里的 reasoning_content

默认值与定位
    本模块只提供基础调用能力（chat / ask），不包含任何业务语义（如"解题"、"生成答案"），
    那些应在上层模块基于本模块再封装。
    默认 thinking=False 是因为日常用法（把内容丢进来直接要结果）不需要推理过程；
    传 thinking=True 即可拿回思维链。其余参数一律不传，交给服务端默认值。

错误分类与重试（失败时 data 里会带 error_type / retryable，方便上层判断）
    error_type='quota'      余额/额度/配额不足 → **不重试**（等多久都不会恢复），
                            用 r['data']['error_type'] == 'quota' 就能认出，提示充值或换 key
    error_type='rate_limit' 限流（429、“速率限制”/“访问量过大”）→ 3 次 × 2 秒快速重试后返回
    error_type='network'    网络异常/超时 → 重试（连接超时固定 5 秒，快速失败进重试）
    error_type='server'     5xx → 重试
    error_type='auth'       401/403 或 key 无效 → 不重试
    整次调用的时间上限由 total_timeout 控制（默认 30 秒），超了就不再重试，不会一直卡着

    用法：
        r = ask('...')
        if r['status'] != 'success':
            kind = (r['data'] or {}).get('error_type')
            if kind == 'quota':
                print('额度用完，需充值或换 key')
            elif kind == 'rate_limit':
                print('被限流，稍后重试')

    免费模型（glm-4.7-flash 等 free 系列）一般没有“余额”概念，常见的是 RPM/并发限流（rate_limit）；
    接入付费模型后若余额不足，就会返回 quota。

其它实测经验
    1. 开思维链时 max_tokens 不能太小：实测一次 completion 929 里有 911 是思维链，
       只给 10 个 token 会导致 content 为空、finish_reason=length
    2. 即使要求"不要 Markdown 标记"，仍可能返回 ```python 代码块围栏，需自行剥离

引用来源
    requests   发请求（普通 / stream=True 流式）
    json       解析流式响应的每个 data: 块
    ..keys     getKey('GLM_API_KEY') 从项目根目录 config.json 取密钥
    ...common  ok / fail 统一返回格式
"""
from .._compat import logCall
import json
import re
import threading
import time
from contextlib import contextmanager

import requests

from .._compat import fail, ok
from ..keys import getKey, getKeys

# 接口地址与默认参数（非敏感，写在这里；密钥见 config.json）
PROVIDER = 'glm'          # 厂商名，modules.ai.chat(provider='glm') 用它分发
LABEL = '智谱 GLM'         # 展示用名称
BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'
DEFAULT_MODEL = 'glm-4.7-flash'
# 额外可用的免费模型（默认不用它们，需要时显式指定 model= 或 models=[...]）
#   glm-4-flash-250414  最快（实测 0.4s）
#   glm-z1-flash        推理模型，思维链写在 content 里的 <think>…</think>（模块会自动拆出来）
# 注意：限流是账户级的，换模型没用；该换的是 key（见 config.json 的 GLM_API_KEYS）
EXTRA_MODELS = ['glm-4-flash-250414', 'glm-z1-flash']
TIMEOUT = 20

# 该模型的请求并发数是 1：同一时刻只允许一个请求在飞，
# 这里用进程内全局锁把调用串行化（重试过程也持锁），避免并发把自己撞成限流。
_LOCK = threading.Lock()
_lastRequestAt = 0.0


@contextmanager
def _serialized(min_interval=0.5):
    """串行化入口：同一时刻只有一个请求；可选保证两次请求之间的最小间隔。"""
    global _lastRequestAt
    with _LOCK:
        gap = time.time() - _lastRequestAt
        if min_interval and gap < float(min_interval):
            time.sleep(float(min_interval) - gap)
        _lastRequestAt = time.time()
        yield


# 官方支持的模型代码（取自 OpenAPI enum）
MODELS = [
    'glm-5.3', 'glm-5.2', 'glm-5.1', 'glm-5-turbo', 'glm-5',
    'glm-4.7', 'glm-4.7-flash', 'glm-4.7-flashx', 'glm-4.6',
    'glm-4.5-air', 'glm-4.5-airx', 'glm-4.5-flash',
    'glm-4-flash-250414', 'glm-4-flashx-250414',
    'glm-z1-flash',
]

# 官方默认值（未传参时服务端的行为，仅作参考，本模块不会主动下发）
OFFICIAL_DEFAULTS = {
    'temperature': 1.0,
    'top_p': 0.95,
    'do_sample': True,
    'reasoning_effort': 'max',
    'thinking': {'type': 'enabled', 'clear_thinking': True},
    'stream': False,
    'tool_stream': False,
    'response_format': {'type': 'text'},
}

ALLOWED_REASONING_EFFORT = ['max', 'xhigh', 'high', 'medium', 'low', 'minimal', 'none']
ALLOWED_THINKING_TYPE = ['enabled', 'disabled']
ALLOWED_RESPONSE_FORMAT = ['text', 'json_object']


_THINK_RE = re.compile(r'<think[^>]*>(.*?)</think>', re.S | re.I)


def splitThinking(content):
    """把推理模型（如 glm-z1-flash）写在 content 里的思维链拆出来。

    glm-z1-flash 返回形如 '<think>思考…</think>正式回答'，这里拆成 (正文, 思维链)。
    没有 <think> 标签时原样返回。
    注意：如果输出被 max_tokens 截断（有 <think> 没有 </think>），正文按空处理，
    这样上层会当成“没生成出代码”而重试，不会把半截思维链当代码提交。
    """
    text = content or ''
    matched = _THINK_RE.search(text)
    if matched:
        reasoning = matched.group(1).strip()
        answer = _THINK_RE.sub('', text).strip()
        return answer, reasoning

    opened = re.search(r'<think[^>]*>', text, re.I)
    if opened:
        return '', text[opened.end():].strip()
    return text, ''


def _normalize_messages(messages, system=None):
    """统一成接口需要的 messages 列表。"""
    if isinstance(messages, str):
        messages = [{'role': 'user', 'content': messages}]
    elif isinstance(messages, dict):
        messages = [messages]
    else:
        messages = list(messages or [])

    if system:
        messages = [{'role': 'system', 'content': system}] + messages
    return messages


def _normalize_thinking(thinking):
    """把 thinking 简写转成接口要求的对象形式；None 表示不下发该字段。"""
    if thinking is None:
        return None
    if isinstance(thinking, bool):
        return {'type': 'enabled' if thinking else 'disabled'}
    if isinstance(thinking, str):
        return {'type': thinking}
    return dict(thinking)


def _normalize_response_format(value):
    """response_format 支持 'text' / 'json_object' 简写，或直接传 dict。"""
    if value is None:
        return None
    if isinstance(value, str):
        return {'type': value}
    return dict(value)


def _validate(request_id, user_id, message):
    """按官方文档的约束做一次轻量校验，提前给出友好错误。"""
    if request_id and not (6 <= len(request_id) <= 64):
        return fail('request_id 长度需为 6~64 个字符', {'message': message})
    if user_id and not (6 <= len(user_id) <= 128):
        return fail('user_id 长度需为 6~128 个字符', {'message': message})
    return None


def _build_body(messages, model, stream, thinking, reasoning_effort, do_sample, temperature, top_p,
                max_tokens, stop, tools, tool_choice, response_format, tool_stream, request_id,
                user_id, system, extra):
    """按官方参数拼请求体：值为 None 的参数一律不下发，交给服务端默认。"""
    body = {'model': model, 'messages': _normalize_messages(messages, system)}
    if stream:
        body['stream'] = True

    optional = {
        'thinking': _normalize_thinking(thinking),
        'reasoning_effort': reasoning_effort,
        'do_sample': do_sample,
        'temperature': temperature,
        'top_p': top_p,
        'max_tokens': max_tokens,
        'stop': stop,
        'tools': tools,
        'tool_choice': tool_choice,
        'response_format': _normalize_response_format(response_format),
        'tool_stream': tool_stream,
        'request_id': request_id,
        'user_id': user_id,
    }
    body.update({k: v for k, v in optional.items() if v is not None})
    body.update(extra)  # 以后接口新增字段可直接透传
    return body


def _post(body, api_key, timeout, proxy, stream=False):
    """发请求，返回 (response, error, status)。stream=True 时用流式读取，on_chunk 才能实时回调。

    timeout 传数值时拆成（连接超时 5 秒, 读取超时 timeout）：
    连不上时快速失败进重试，不会卡在一个地方很久。
    """
    if isinstance(timeout, (int, float)):
        timeout = (5, timeout)
    try:
        resp = requests.post(
            f'{BASE_URL}/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=body,
            timeout=timeout,
            stream=stream,
            proxies={'http': proxy, 'https': proxy} if proxy else None,
        )
    except Exception as e:
        return None, fail(f'请求 GLM 失败：{e}'), None

    if resp.status_code != 200:
        try:
            detail = resp.json()
        except ValueError:
            detail = {'text': resp.text[:500]}
        message = (detail.get('error') or {}).get('message') if isinstance(detail, dict) else ''
        return None, fail(message or f'GLM 接口返回状态码 {resp.status_code}', detail), resp.status_code
    return resp, None, resp.status_code


# 值得重试的错误：限流、服务端 5xx、网络异常，或错误信息里带这些关键词
_RETRY_HINTS = ('访问量', '速率限制', '请求频率', '稍后再试', '稍后重试', '请稍后', 'rate limit',
                'too many', 'busy', 'overload', 'timeout', 'timed out')

# 额度/余额/配额 类错误：重试没有意义（等多久都不会恢复），要单独识别并明确提示
_QUOTA_HINTS = ('余额', '额度', '配额', '欠费', '已用完', 'quota', 'insufficient', 'balance',
                'exhausted', 'not enough')


def _isQuotaError(message):
    return any(hint in (message or '').lower() for hint in _QUOTA_HINTS)


def _isRetryable(status, message):
    if _isQuotaError(message):
        return False            # 额度用完，重试无用
    if status is None or status == 429 or 500 <= status < 600:
        return True
    return any(hint.lower() in (message or '').lower() for hint in _RETRY_HINTS)


def _errorType(status, message):
    """把失败原因分类，方便上层判断：quota / rate_limit / network / server / auth / other。"""
    message = message or ''
    if _isQuotaError(message):
        return 'quota'
    if status == 429 or '频率' in message or '访问量' in message:
        return 'rate_limit'
    if status in (401, 403) or '认证' in message or 'api key' in message.lower():
        return 'auth'
    if status is None:
        return 'network'
    if status and status >= 500:
        return 'server'
    return 'other'


def _request(body, api_keys, timeout, proxy, stream, retries, retry_interval, total_timeout=30,
             min_interval=0.5):
    """带自动重试的请求，并带总时间预算（整体串行，见 _serialized）。

    api_keys 是密钥列表：每次尝试轮换着用（多 key 能明显减少限流）。

    · 限流（429、“访问量过大”/“速率限制”）→ 固定间隔快速重试，默认 3 次 × 2 秒；
      限流响应本身只要 0.1 秒，没必要干等，3 次都不行就直接返回失败
    · 额度/余额不足 → 不重试（等多久都不会恢复），直接返回并标记 error_type=quota
    · total_timeout 是整次调用（含重试）的时间上限，超了就不再重试，避免卡太久
    返回 (response, error, retries_used)。
    """
    last_error, used = None, 0
    started = time.time()
    with _serialized(min_interval):     # 并发数 1：串行执行，重试期间也不放别的请求进来
        for attempt in range(max(0, int(retries)) + 1):
            if attempt and time.time() - started > float(total_timeout):
                break                     # 超出总预算，不再重试
            key = api_keys[attempt % len(api_keys)] if api_keys else ''
            resp, error, status = _post(body, key, timeout, proxy, stream=stream)
            if error is None:
                return resp, None, used
            last_error = error
            kind = _errorType(status, error.get('message', ''))
            error['data'] = {**(error.get('data') or {}), 'error_type': kind,
                             'retryable': kind in ('rate_limit', 'network', 'server')}
            if attempt < int(retries) and _isRetryable(status, error.get('message', '')):
                used += 1
                time.sleep(float(retry_interval))  # 固定短间隔，限流响应很快，快速再试
                continue
            break
    return None, last_error, used


def _read_stream(resp, on_chunk=None):
    """逐块读取 SSE 流，返回 (content, reasoning_content, finish_reason, usage, chunks)。"""
    content, reasoning, finish_reason, usage, count = '', '', None, {}, 0
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            break
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue
        count += 1
        choices = chunk.get('choices') or []
        if choices:
            delta = choices[0].get('delta') or {}
            content += delta.get('content') or ''
            reasoning += delta.get('reasoning_content') or ''
            finish_reason = choices[0].get('finish_reason') or finish_reason
        if chunk.get('usage'):
            usage = chunk['usage']
        if on_chunk:
            on_chunk(chunk)
    return content, reasoning, finish_reason, usage, count


@logCall
def chat(messages, model=None, stream=False, thinking=False, reasoning_effort=None,
         do_sample=None, temperature=None, top_p=None, max_tokens=None, stop=None, tools=None,
         tool_choice=None, response_format=None, tool_stream=None, request_id=None, user_id=None,
         system=None, timeout=TIMEOUT, proxy=None, on_chunk=None, retries=3, retry_interval=2.0,
         total_timeout=45, min_interval=0.5, models=None, **extra):
    """调用 GLM 对话接口（参数与官方 OpenAPI 一一对应，未传的参数一律不下发）。

    messages 传字符串或 [{'role', 'content'}, ...]；system 会拼在消息列表最前面。
    model 指定单个模型；不传则用主模型 + 备用免费模型自动兜底（见 models）。
    models 显式指定多个模型的兜底顺序（默认只用 glm-4.7-flash，不自动换模型）。
        限流是账户级的，换模型没用；本模块的做法是重试时轮换 key（config.json 可配多个 key）。
    thinking 默认 False：只要结果，不返回推理过程；需要思维链传 thinking=True。
    stream=True 时开启 SSE 流式，可用 on_chunk(chunk_dict) 实时接收每个数据块。
    retries / retry_interval：限流（429、“访问量过大”/“速率限制”）、5xx、网络异常时自动重试的
        次数与间隔，默认 3 次 × 2 秒（限流响应只要 0.1 秒，快速重试即可，不等太久）。
    min_interval：两次请求之间的最小间隔，默认 0.5 秒（该模型并发数为 1，模块内部已用全局锁串行化）。
        免费模型 RPM 很低，建议按实际情况调大（如 8~12 秒）。
    total_timeout：整次调用（含模型链与重试）的时间上限，默认 45 秒，超了就不再重试。
        多个模型时每个模型只快速试一下（1 次重试）就换下一个，不把时间耗在单个模型上。
        想快速失败可以自己调小，例如 ask(..., retries=1, retry_interval=2, timeout=10, total_timeout=15)。
    额度类错误（余额/额度/配额不足）不会重试，会直接返回并在 data.error_type='quota' 里标明。
    返回: {status, message, data}，data 字段：
        content（回复正文）/ reasoning_content（思维链，gm-z1 系列的 <think> 也会拆到这里）
        model（实际用的模型）/ finish_reason / usage / retries（重试次数）/ stream / chunks / raw
    """
    if not getKeys('GLM_API_KEY'):
        return fail('未配置 GLM_API_KEY（请在项目根目录 config.json 里填写）')

    error = _validate(request_id, user_id, messages)
    if error:
        return error

    # 候选模型：显式传 model 就用它；否则主模型 + 备用模型依次兜底
    candidates = list(models) if models else ([model] if model else [DEFAULT_MODEL])
    body = _build_body(messages, candidates[0], stream, thinking, reasoning_effort, do_sample,
                       temperature, top_p, max_tokens, stop, tools, tool_choice, response_format,
                       tool_stream, request_id, user_id, system, extra)

    api_keys = getKeys('GLM_API_KEY')
    resp, last_error, retries_used, used_model = None, None, 0, candidates[0]
    deadline = time.time() + float(total_timeout)      # 整条模型链的总时间预算
    for candidate in candidates:
        remain = deadline - time.time()
        if remain <= 0:
            break
        body['model'] = candidate
        resp, error, retries_used = _request(body, api_keys, timeout, proxy, stream, retries,
                                             retry_interval, total_timeout=remain,
                                             min_interval=min_interval)
        used_model = candidate
        if error is None:
            break
        error['data'] = {**(error.get('data') or {}), 'retries': retries_used, 'model': candidate}
        last_error = error
        if (error.get('data') or {}).get('error_type') in ('quota', 'auth'):
            break                      # 账户级问题，换模型也没用
    if resp is None:
        return last_error

    if stream:
        content, reasoning, finish_reason, usage, chunks = _read_stream(resp, on_chunk)
        content, inline = splitThinking(content)
        return ok('调用成功', {
            'content': content,
            'reasoning_content': reasoning or inline,
            'model': used_model,
            'finish_reason': finish_reason,
            'usage': usage,
            'retries': retries_used,
            'stream': True,
            'chunks': chunks,
        })

    try:
        result = resp.json()
    except ValueError:
        return fail('GLM 返回内容不是合法 JSON', {'text': resp.text[:500]})

    choices = result.get('choices') or []
    message = (choices[0].get('message') or {}) if choices else {}
    content, inline = splitThinking(message.get('content', ''))
    return ok('调用成功', {
        'content': content,
        'reasoning_content': message.get('reasoning_content', '') or inline,
        'model': result.get('model', used_model),
        'finish_reason': choices[0].get('finish_reason') if choices else None,
        'usage': result.get('usage') or {},
        'retries': retries_used,
        'stream': False,
        'tool_calls': message.get('tool_calls') or [],
        'raw': result,
    })


@logCall
def ask(prompt, system=None, **kwargs):
    """单轮提问的简写（默认 thinking=False，只要结果）。

    ask('用一句话解释递归') 等价于 chat('用一句话解释递归')。
    返回: {status, message, data}，data 字段同 chat。
    """
    return chat(prompt, system=system, **kwargs)
