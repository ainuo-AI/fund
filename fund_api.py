"""
fund_api.py —— 基金数据层

职责：封装所有对第三方接口的请求，对外提供 3 个干净的函数。
网页代码（app.py）不需要知道数据从哪来、怎么解析，只管调用。

数据来源（均为公开免费接口）：
  - 天天基金移动端 API（fundmobapi.eastmoney.com）：最新净值、历史净值
  - 天天基金搜索建议（fundsuggest.eastmoney.com）：按名称/代码搜索基金
  - 新浪财经（stock.finance.sina.com.cn）：基金概况（类型、规模、公司等）
"""

from datetime import date, datetime, timedelta

import requests

# 所有请求共用的请求头：User-Agent 模拟浏览器，避免被当成爬虫拒绝
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _get_json(url, params):
    """GET 请求并解析 JSON。外网接口偶尔 SSL 抖动导致 EOF，失败时重试一次"""
    for attempt in range(2):
        try:
            return requests.get(url, params=params, headers=HEADERS, timeout=10).json()
        except requests.RequestException:
            if attempt == 1:
                raise

# 天天基金移动端 API 需要的固定参数（相当于一个公共的"客户端标识"）
EM_COMMON_PARAMS = {
    "plat": "Android",
    "appType": "ttjj",
    "product": "EFund",
    "Version": "1",
    "deviceid": "jijin-demo",
}


def search_funds(keyword):
    """按关键词搜索基金，返回 [{'code': '161725', 'name': '招商中证白酒...'}, ...]"""
    url = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    data = _get_json(url, {"m": 1, "key": keyword})
    results = []
    for item in data.get("Datas") or []:
        results.append({"code": item["CODE"], "name": item["NAME"]})
    return results


def get_fund_info(code):
    """
    获取基金的基本信息 + 最新净值。
    返回一个字典，例如：
    {
        'code': '161725', 'name': '招商中证白酒指数(LOF)A',
        'nav': '0.5438', 'acc_nav': '2.2599', 'change_pct': '0.80',
        'nav_date': '2026-07-27',
        'fund_type': '股票型', 'scale': '209.24亿',
        'company': '招商基金管理有限公司', 'manager': '侯昊',
        'start_date': '2021-01-01',
    }
    """
    # 第一部分：最新净值（东财移动端接口，支持一次查多只，这里只查一只）
    nav_url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    nav_params = {"pageIndex": 1, "pageSize": 1, "Fcodes": code, **EM_COMMON_PARAMS}
    nav_rows = _get_json(nav_url, nav_params).get("Datas") or []
    if not nav_rows:
        return None  # 基金代码不存在
    row = nav_rows[0]

    info = {
        "code": code,
        "name": row.get("SHORTNAME") or code,
        "nav": row.get("NAV") or "--",           # 单位净值
        "acc_nav": row.get("ACCNAV") or "--",    # 累计净值
        "change_pct": row.get("NAVCHGRT") or "--",  # 日涨跌幅 %
        "nav_date": row.get("PDATE") or "--",    # 净值日期
    }

    # 第二部分：基金概况（新浪接口），失败不影响主体，用默认值兜底
    try:
        sina_url = ("https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/"
                    "FundPageInfoService.tabjjgk")
        sina_resp = _get_json(sina_url, {"symbol": code, "format": "json"})
        d = sina_resp["result"]["data"]
        info.update({
            "fund_type": d.get("Type2Name") or "--",        # 基金类型（股票型/混合型...）
            "scale": f"{d.get('jjgm')}亿" if d.get("jjgm") else "--",  # 规模
            "company": d.get("glr") or "--",                # 管理公司
            "manager": _strip_html(d.get("ManagerName")) or "--",  # 基金经理
            "start_date": (d.get("clrq") or "--").split(" ")[0],     # 成立日期
        })
    except Exception:
        info.update({"fund_type": "--", "scale": "--", "company": "--",
                     "manager": "--", "start_date": "--"})
    return info


# 排行榜可选的排序依据（推荐维度）：天天基金排行接口的 sc 参数 -> 中文名
RANK_SORTS = {
    "rzdf": "日涨幅",
    "zzf": "近1周",
    "1yzf": "近1月",
    "3yzf": "近3月",
    "6yzf": "近6月",
    "1nzf": "近1年",
    "jnzf": "今年来",
}

# 排行榜可选的基金类型：接口的 ft 参数 -> 中文名
RANK_TYPES = {
    "all": "全部",
    "gp": "股票型",
    "hh": "混合型",
    "zs": "指数型",
    "zq": "债券型",
    "qdii": "QDII",
    "fof": "FOF",
}


def get_fund_rank(sort="1yzf", fund_type="all", top=20):
    """
    天天基金排行榜：按某个区间涨幅排序，取前 top 只，返回：
    [{'code': '161725', 'name': '招商中证白酒...', 'nav': 0.5438,
      'day': 0.8, 'week': 2.58, 'month': 28.53, 'month3': -9.37,
      'month6': -15.2, 'year': -6.93, 'this_year': -9.2, ...}, ...]

    sort 取 RANK_SORTS 的键，fund_type 取 RANK_TYPES 的键。
    接口返回的是 JS 片段（var rankData = {...}），不是纯 JSON，用正则取 datas 数组。
    """
    import json
    import re

    end = date.today()
    start = _minus_months(end, 12)  # 排行区间取近一年，近1周的榜也用这个区间
    url = "https://fund.eastmoney.com/data/rankhandler.aspx"
    params = {
        "op": "ph", "dt": "kf", "ft": fund_type, "rs": "", "gs": "0",
        "sc": sort, "st": "desc",
        "sd": start.isoformat(), "ed": end.isoformat(),
        "qdii": "", "tabSubtype": ",,,,,",
        "pi": 1, "pn": top, "dx": 1, "v": 0.5,
    }
    headers = {**HEADERS, "Referer": "https://fund.eastmoney.com/data/fundranking.html"}
    text = None
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            text = r.content.decode("utf-8", errors="replace")
            break
        except requests.RequestException:
            if attempt == 1:
                raise
    match = re.search(r"datas\s*:\s*(\[.*?\])\s*,\s*allRecords", text, re.S)
    if not match:
        return []
    datas = json.loads(match.group(1))  # datas 是合法的 JSON 字符串数组
    ranks = []
    for item in datas:
        f = item.split(",")
        # 字段顺序：0代码 1名称 2拼音 3日期 4单位净值 5累计净值 6日涨幅
        #           7近1周 8近1月 9近3月 10近6月 11近1年 ... 14今年来 15成立来 16成立日期
        if len(f) < 17:
            continue
        ranks.append({
            "code": f[0],
            "name": f[1],
            "nav": _to_float(f[4]),
            "day": _to_float(f[6]),
            "week": _to_float(f[7]),
            "month": _to_float(f[8]),
            "month3": _to_float(f[9]),
            "month6": _to_float(f[10]),
            "year": _to_float(f[11]),
            "this_year": _to_float(f[14]),
        })
    return ranks


def get_nav_history(code, pages=2, page_size=250):
    """
    获取历史净值，返回按日期升序的列表：
    [{'date': '2026-07-27', 'nav': 0.5438, 'acc_nav': 2.2599, 'change_pct': 0.8}, ...]

    接口每页最多约 250 条（约 1 年），pages=2 即取最近约 2 年的数据。
    """
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList"
    history = []
    for page in range(1, pages + 1):
        params = {"FCODE": code, "pageIndex": page, "pageSize": page_size,
                  **EM_COMMON_PARAMS}
        rows = _get_json(url, params).get("Datas") or []
        if not rows:
            break  # 没有更多数据了
        for r in rows:
            history.append({
                "date": r.get("FSRQ"),
                "nav": _to_float(r.get("DWJZ")),
                "acc_nav": _to_float(r.get("LJJZ")),
                "change_pct": _to_float(r.get("JZZZL")),
            })
    # 接口返回是"最新在前"，画图和展示都需要"最早在前"，所以翻转
    history.reverse()
    return history


def calc_interval_returns(history):
    """
    根据历史净值（日期升序）计算区间涨跌幅，返回：
    [('近1月', 2.35), ('近3月', None), ...]，None 表示历史数据不够算不出来。
    算法：以最新净值为终点，找目标日期当天或之前最近的一个净值做起点。
    """
    points = [(datetime.strptime(h["date"], "%Y-%m-%d").date(), h["nav"])
              for h in history if h["date"] and h["nav"]]
    if len(points) < 2:
        return []
    end_date, end_nav = points[-1]
    results = []
    for label, months in [("近1月", 1), ("近3月", 3), ("近6月", 6), ("近1年", 12)]:
        target = _minus_months(end_date, months)
        # 目标日期当天或之前最近的一个交易日净值
        base = None
        for d, nav in points:
            if d <= target:
                base = nav
            else:
                break
        pct = round((end_nav / base - 1) * 100, 2) if base else None
        results.append((label, pct))
    return results


def _minus_months(d, months):
    """日期往前推 N 个月（不引入第三方库，手工换算年月）"""
    month = d.month - months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def calc_sip(history, amount=1000, freq="month", years=2, start=None):
    """
    定投收益模拟：从 start 日期（缺省按 years 年从最新净值日往回推）开始，
    按固定频率每次投入 amount 元，返回：
    {
        'invested': 累计投入, 'value': 当前市值, 'profit': 收益, 'pct': 收益率%,
        'count': 定投次数, 'start': 首次买入日期, 'end': 结束日期,
        'postponed': [{deduct: 扣款日, buy: 实际买入日}, ...],  # 休市顺延记录
        'series': [[日期, 累计投入, 当时市值], ...]  # 画图用
    }
    买入规则：到扣款日后，按之后第一个交易日的净值买入（同一交易日只买一次，
    多期顺延到不同交易日）；早于首个净值日的扣款日跳过；数据不足返回 None。
    """
    points = [(datetime.strptime(h["date"], "%Y-%m-%d").date(), h["nav"])
              for h in history if h["date"] and h["nav"]]
    if len(points) < 2:
        return None
    end_date, end_nav = points[-1]
    if start is None:
        start = _minus_months(end_date, years * 12)

    # 生成扣款日序列：每周/每两周按天数推，每月按月份推
    step_days = {"week": 7, "biweek": 14}.get(freq)
    schedule = []
    if step_days is None:
        # 每月：以开始日为锚点推算，避免 2 月天数少导致扣款日越推越靠前
        k = 0
        while True:
            d = _plus_months(start, k)
            if d > end_date:
                break
            schedule.append(d)
            k += 1
    else:
        d = start
        while d <= end_date:
            schedule.append(d)
            d += timedelta(days=step_days)

    invested, shares, count = 0.0, 0.0, 0
    series = []
    postponed = []  # 扣款日遇到休市/非交易日被顺延的记录，给图表标注用
    i = 0  # 净值游标：points 按日期升序，扣款日也升序，只需往前走不回退
    first_date = points[0][0]
    for d in schedule:
        if d < first_date:
            continue  # 基金还没成立/没有净值数据，跳过，否则会重复按第一天净值买入
        while i < len(points) and points[i][0] < d:
            i += 1
        if i >= len(points):
            break  # 扣款日之后没有净值数据了
        buy_date, nav = points[i]
        i += 1  # 本期已占用这个交易日，下期顺延到之后的交易日，避免两期买在同一天
        if buy_date != d:
            postponed.append({"deduct": d.isoformat(), "buy": buy_date.isoformat()})
        invested += amount
        shares += amount / nav
        count += 1
        series.append([buy_date.isoformat(), round(invested, 2), round(shares * nav, 2)])
    if not count:
        return None
    value = shares * end_nav
    return {
        "invested": round(invested, 2),
        "value": round(value, 2),
        "profit": round(value - invested, 2),
        "pct": round((value / invested - 1) * 100, 2),
        "count": count,
        "start": series[0][0],
        "end": end_date.isoformat(),
        "postponed": postponed,
        "series": series,
    }


def _plus_months(d, months):
    """日期往后推 N 个月，复用 _minus_months 的月底天数处理"""
    return _minus_months(d, -months)


def get_hot_funds(codes):
    """首页用：一次查询多只基金的最新净值，返回列表"""
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    params = {"pageIndex": 1, "pageSize": len(codes),
              "Fcodes": ",".join(codes), **EM_COMMON_PARAMS}
    result = []
    for row in _get_json(url, params).get("Datas") or []:
        result.append({
            "code": row.get("FCODE"),
            "name": row.get("SHORTNAME"),
            "nav": row.get("NAV") or "--",
            "change_pct": _to_float(row.get("NAVCHGRT")),
            "nav_date": row.get("PDATE"),
        })
    return result


# ===== 实时估值（根据重仓股自己估算） =====
# 2026 年起监管要求各平台下架官方"盘中估值"，公开估值接口已全部失效。
# 这里按同样的原理自算：最新披露的前十大重仓股 × 股票实时涨跌幅，加权估算当日净值涨跌。
# 持仓是季度披露数据，和实盘有偏差，结果仅供参考。

_holdings_cache = {}  # {基金代码: 持仓数据}，持仓一个季度才更新一次，缓存避免重复抓取


def get_stock_holdings(code):
    """
    获取基金最新披露的前十大重仓股（天天基金 F10 持仓页，返回 JS 包裹的 HTML，正则解析），返回：
    {'date': '2026-06-30', 'stocks': [
        {'secid': '1.600519', 'code': '600519', 'name': '贵州茅台', 'weight': 17.28}, ...]}
    secid 是东财行情接口用的"市场.代码"格式（直接取自持仓页的链接，A股/港股通用）。
    纯债基等没有股票持仓的基金 stocks 为空列表。
    """
    if code in _holdings_cache:
        return _holdings_cache[code]
    import re
    url = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    headers = {**HEADERS, "Referer": f"https://fundf10.eastmoney.com/jjcc_{code}.html"}
    text = requests.get(url, params={"type": "jjcc", "code": code, "topline": 10},
                        headers=headers, timeout=10).text
    date_match = re.search(r"截止至：<font class='px12'>([\d-]+)</font>", text)
    # 接口会返回多个季度的表格（最新在前），只取最近一个季度，避免重复计算
    blocks = text.split("季度股票投资明细")
    section = blocks[1] if len(blocks) > 1 else text
    stocks = []
    for row in section.split("<tr>"):  # 表头里没有持仓链接，逐行扫描即可
        m = re.search(r"unify/r/([\d.]+)'>(\w+)</a></td>"
                      r"<td class='tol'><a href='[^']*'>([^<]+)</a>", row)
        w = re.search(r"<td class='tor'>([\d.]+)%</td>", row)  # 占净值比例列
        if m and w:
            stocks.append({"secid": m.group(1), "code": m.group(2),
                           "name": m.group(3), "weight": _to_float(w.group(1))})
    result = {"date": date_match.group(1) if date_match else "--", "stocks": stocks}
    _holdings_cache[code] = result
    return result


def get_realtime_quotes(secids):
    """
    东财实时行情：批量查股票涨跌幅，返回 {股票代码: 涨跌幅%}。
    接口的 f3 字段是涨跌幅×100 的整数；停牌/缺数据时按 0 处理。
    """
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    data = _get_json(url, {"secids": ",".join(secids), "fields": "f12,f3"})
    quotes = {}
    for row in ((data.get("data") or {}).get("diff") or []):
        f3 = row.get("f3")
        quotes[row.get("f12")] = f3 / 100 if isinstance(f3, (int, float)) else 0.0
    return quotes


def get_fund_estimate(code):
    """
    估算基金当日净值，返回：
    {'est_nav': 0.55, 'est_pct': 1.23, 'nav': '0.5438', 'nav_date': '2026-07-30',
     'holdings_date': '2026-06-30', 'time': '14:35:02'}

    算法：估算涨幅 = Σ(重仓股涨跌幅 × 占净值比例) / 100
          估算净值 = 最新净值 × (1 + 估算涨幅/100)
    只算了前十大重仓股，其余持仓按不涨不跌处理；没有股票持仓或拿不到净值时返回 None。
    """
    nav_url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    nav_params = {"pageIndex": 1, "pageSize": 1, "Fcodes": code, **EM_COMMON_PARAMS}
    nav_rows = _get_json(nav_url, nav_params).get("Datas") or []
    if not nav_rows:
        return None
    row = nav_rows[0]
    nav = _to_float(row.get("NAV"))
    holdings = get_stock_holdings(code)
    stocks = holdings["stocks"]
    if not nav or not stocks:
        return None  # 纯债基/货币基金等没有股票持仓，不支持估算
    try:
        # 持仓日期太旧（如债基挂着十年前的零星持仓）说明不是股票类基金，估算没意义
        h_date = datetime.strptime(holdings["date"], "%Y-%m-%d").date()
        if (date.today() - h_date).days > 366:
            return None
    except ValueError:
        return None  # 持仓日期解析失败，同样不支持
    quotes = get_realtime_quotes([s["secid"] for s in stocks])
    est_pct = sum(s["weight"] * quotes.get(s["code"], 0.0) for s in stocks) / 100
    return {
        "est_nav": round(nav * (1 + est_pct / 100), 4),
        "est_pct": round(est_pct, 2),
        "nav": row.get("NAV") or "--",
        "nav_date": row.get("PDATE") or "--",
        "holdings_date": holdings["date"],
        "time": datetime.now().strftime("%H:%M:%S"),
    }


def _to_float(value):
    """把接口返回的字符串安全地转成浮点数，转不了就返回 None"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strip_html(text):
    """新浪接口的基金经理字段带 <a> 标签，去掉标签只留名字"""
    if not text:
        return ""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


if __name__ == "__main__":
    # 直接运行本文件时做个小测试：python fund_api.py
    print("搜索'白酒':", search_funds("白酒")[:3])
    print()
    print("161725 基本信息:", get_fund_info("161725"))
    print()
    hist = get_nav_history("161725")
    print(f"161725 历史净值共 {len(hist)} 条，最早 {hist[0]['date']}，最新 {hist[-1]['date']}")
