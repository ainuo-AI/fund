"""
ai_api.py —— AI 新闻分析层

职责：把 fund_api.get_market_news() 抓到的新闻，批量发给大模型（OpenAI 兼容接口），
让模型判断每条新闻影响哪些行业、是利好还是利空（对应看涨/看跌）。

注意：AI 不生成新闻，只阅读已有的真实新闻并点评；判断结果只是文本解读的推测，
不构成投资建议（页面上也有同样的免责声明）。

配置（项目根目录 .env 文件，不会被 git 提交）：
    AI_API_KEY=sk-xxx                          # 必填，不填则 AI 分析关闭
    AI_BASE_URL=https://api.deepseek.com       # 可选，默认 DeepSeek；Kimi 填 https://api.moonshot.cn/v1
    AI_MODEL=deepseek-chat                     # 可选；Kimi 填 moonshot-v1-8k，OpenAI 填 gpt-4o-mini
"""

import json
import os

import requests

# 请求大模型共用的请求头 UA（复用 fund_api 的风格，避免被误判为异常流量）
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 内存缓存：{新闻id: 分析结果}，快讯 id 唯一且内容不变，刷新页面不重复扣费
_analysis_cache = {}


def _load_env():
    """手写解析 .env（KEY=VALUE，# 开头为注释），不引入 python-dotenv 依赖"""
    config = {}
    if not os.path.exists(_ENV_PATH):
        return config
    with open(_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def get_config():
    """AI 配置：api_key 为空表示未配置；base_url 默认 DeepSeek（OpenAI 兼容）。
    temperature 为 None 表示不传给接口（有的模型如 kimi-k2 只允许默认值）。"""
    env = _load_env()
    return {
        "api_key": env.get("AI_API_KEY") or os.environ.get("AI_API_KEY") or "",
        "base_url": (env.get("AI_BASE_URL") or "https://api.deepseek.com").rstrip("/"),
        "model": env.get("AI_MODEL") or "deepseek-chat",
        "temperature": _to_float_or_none(env.get("AI_TEMPERATURE")),
    }


def _to_float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_configured():
    """是否已配置 API Key（没配 key 时前端显示提示，不调用接口）"""
    return bool(get_config()["api_key"])


def analyze_news(news_list):
    """
    批量分析新闻，返回 {新闻id: {'industries': '白酒、食品饮料', 'impact': '利好',
    'reason': '…'}}；impact 只会是 利好/利空/中性。
    未配置 key 或调用/解析失败时返回 None（前端显示提示，页面照常可用）。
    """
    config = get_config()
    if not config["api_key"] or not news_list:
        return None

    # 先查缓存，只把没分析过的新闻发给模型，省钱
    todo = [n for n in news_list if n["id"] not in _analysis_cache]
    if todo:
        results = _call_llm(todo, config)
        if results is None:
            return None
        _analysis_cache.update(results)
    # 按传入列表的 id 组装返回；缓存里也没有的（理论上不会）就不出现在结果里
    return {n["id"]: _analysis_cache[n["id"]] for n in news_list if n["id"] in _analysis_cache}


def _call_llm(news_list, config):
    """
    把整页新闻一次性发给模型（30 条一次调用），要求只输出 JSON。
    返回 {新闻id: 分析结果}；任何失败返回 None。
    """
    # 给新闻编号，让模型按编号返回，回来后按编号对齐，防止顺序错乱
    lines = [f"{i}. {n['text']}" for i, n in enumerate(news_list)]
    prompt = (
        "你是财经分析师。下面是编号的新闻快讯，请对每一条判断：它会影响哪些行业板块"
        "（A股行业名称，多个用、分隔；无明确行业指向就填「宏观」）；对该行业股市是"
        "利好（看涨）、利空（看跌）还是中性；以及一句话理由（不超过30字）。\n"
        "只输出 JSON，格式：{\"items\": [{\"i\": 编号, \"industries\": \"行业\", "
        "\"impact\": \"利好|利空|中性\", \"reason\": \"理由\"}]}，不要输出其他内容。\n\n"
        + "\n".join(lines)
    )
    try:
        payload = {
            "model": config["model"],
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        # 只在显式配置时传 temperature：kimi-k2 等模型只允许默认值，传了会 400
        if config["temperature"] is not None:
            payload["temperature"] = config["temperature"]
        resp = requests.post(
            f"{config['base_url']}/chat/completions",
            headers={**HEADERS, "Authorization": f"Bearer {config['api_key']}"},
            json=payload,
            timeout=120,  # 思考型模型分析 30 条新闻可能要 1 分多钟
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        items = json.loads(content).get("items") or []
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None

    results = {}
    for item in items:
        try:
            idx = int(item.get("i"))
        except (TypeError, ValueError):
            continue  # 模型返回了无法对齐的条目，跳过
        if not (0 <= idx < len(news_list)):
            continue  # 编号越界（模型幻觉），跳过
        impact = item.get("impact") if item.get("impact") in ("利好", "利空", "中性") else "中性"
        results[news_list[idx]["id"]] = {
            "industries": str(item.get("industries") or "宏观"),
            "impact": impact,
            "reason": str(item.get("reason") or ""),
        }
    return results
