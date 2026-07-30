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
