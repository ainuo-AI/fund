"""
app.py —— 网站入口（路由层）

职责：接收浏览器请求 -> 调用 fund_api 拿数据 -> 渲染 HTML 模板返回。
不直接写数据抓取逻辑，那些都在 fund_api.py 里。
"""
from datetime import date, datetime

from flask import Flask, render_template, request

import fund_api

app = Flask(__name__)

# 首页展示的基金（换成你感兴趣的代码即可）
HOT_FUND_CODES = ["161725", "005827", "110022", "260108", "000478", "519736"]


@app.route("/")
def index():
    """首页：搜索框 + 几只基金的最新净值速览"""
    funds = fund_api.get_hot_funds(HOT_FUND_CODES)
    return render_template("index.html", funds=funds)


@app.route("/search")
def search():
    """搜索页：/search?q=关键词"""
    keyword = request.args.get("q", "").strip()
    results = fund_api.search_funds(keyword) if keyword else []
    return render_template("search.html", keyword=keyword, results=results)


@app.route("/fund/<code>")
def fund_detail(code):
    """基金详情页：基本信息 + 净值走势图 + 历史净值表"""
    info = fund_api.get_fund_info(code)
    if info is None:
        return render_template("404.html", code=code), 404
    history = fund_api.get_nav_history(code)
    recent = history[-30:][::-1]  # 表格只显示最近 30 条，最新在前
    intervals = fund_api.calc_interval_returns(history)
    return render_template("fund.html", info=info,
                           history=history, recent=recent, intervals=intervals)


@app.route("/sip/<code>")
def sip(code):
    """定投模拟页：/sip/161725?amount=1000&freq=month&start=2024-01-01（也可用 years=2）"""
    info = fund_api.get_fund_info(code)
    if info is None:
        return render_template("404.html", code=code), 404
    amount = request.args.get("amount", 1000, type=int) or 1000
    amount = max(1, min(amount, 1000000))  # 每期金额限制在 1~100 万
    freq = request.args.get("freq", "month")
    if freq not in ("week", "biweek", "month"):
        freq = "month"
    # 开始日期：优先 URL 里的 start（YYYY-MM-DD）；没给就按 years 年兼容旧链接
    start = None
    start_str = request.args.get("start", "").strip()
    if start_str:
        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
        except ValueError:
            start = None  # 格式不对当作没给
    years = max(1, min(request.args.get("years", 2, type=int) or 2, 5))  # 1~5 年
    # 接口每页约 1 年数据，按定投跨度估算要取几页（最多 6 页 ≈ 5 年）
    span_days = (date.today() - start).days if start else years * 365
    pages = max(1, min(span_days // 365 + 2, 6))
    history = fund_api.get_nav_history(code, pages=pages)
    # 可选的最早开始日期：基金成立日和"近 5 年"（接口最多取 6 页 ≈ 5 年）取较晚者
    min_start = fund_api._minus_months(date.today(), 60)
    try:
        inception = datetime.strptime(info["start_date"], "%Y-%m-%d").date()
        min_start = max(min_start, inception)
    except (TypeError, ValueError):
        pass  # 成立日期拿不到就只按近 5 年限制
    if start is None and history:
        end = datetime.strptime(history[-1]["date"], "%Y-%m-%d").date()
        start = fund_api._minus_months(end, years * 12)
    # 开始日期不能早于基金首个净值日，早于则钳制到 min_start
    if start is not None and start < min_start:
        start = min_start
    # 开始日期也不能晚于今天，晚于则钳制到今天
    max_start = date.today()
    if start is not None and start > max_start:
        start = max_start
    result = fund_api.calc_sip(history, amount=amount, freq=freq, start=start)
    return render_template("sip.html", info=info, amount=amount, freq=freq,
                           start=start.isoformat() if start else "",
                           min_start=min_start.isoformat(),
                           max_start=max_start.isoformat(),
                           result=result)


@app.route("/hot")
def hot():
    """热门推荐榜：/hot?sort=1yzf&type=gp 按区间涨幅排序取前 20 只"""
    sort = request.args.get("sort", "1yzf")
    if sort not in fund_api.RANK_SORTS:
        sort = "1yzf"
    fund_type = request.args.get("type", "all")
    if fund_type not in fund_api.RANK_TYPES:
        fund_type = "all"
    ranks = fund_api.get_fund_rank(sort=sort, fund_type=fund_type)
    return render_template("hot.html", ranks=ranks, sort=sort, fund_type=fund_type,
                           sorts=fund_api.RANK_SORTS, types=fund_api.RANK_TYPES)


@app.route("/api/funds")
def api_funds():
    """给首页"我的自选"用的小接口：/api/funds?codes=161725,005827 返回 JSON"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    return {"funds": fund_api.get_hot_funds(codes) if codes else []}


@app.route("/compare")
def compare():
    """基金对比页：把多只基金近一年的涨跌幅画在同一张图上"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    codes = list(dict.fromkeys(codes))[:5]  # 去重、最多 5 只
    # 批量查一次名称（顺便验证代码是否存在），再逐个取历史净值
    names = {f["code"]: f["name"] for f in fund_api.get_hot_funds(codes)} if codes else {}
    funds = []
    for code in codes:
        if code not in names:
            continue  # 代码不存在，跳过
        history = fund_api.get_nav_history(code, pages=1)  # 最近约 1 年
        # 归一化：以第一天为基准换算成累计涨跌幅 %，
        # 不然 1 块钱的基金和 3 块钱的基金净值差太远，没法在一张图上比
        base = history[0]["nav"] if history and history[0]["nav"] else None
        series = ([[h["date"], round((h["nav"] / base - 1) * 100, 2)]
                   for h in history if h["nav"]] if base else [])
        funds.append({"code": code, "name": names[code], "series": series})
    return render_template("compare.html", funds=funds, codes=codes)


@app.route("/api/search")
def api_search():
    """给对比页"按名称搜索添加"用的 JSON 接口：/api/search?q=白酒"""
    keyword = request.args.get("q", "").strip()
    return {"results": fund_api.search_funds(keyword)[:10] if keyword else []}


@app.errorhandler(404)
def not_found(e):
    """所有未匹配的路径统一走这里"""
    return render_template("404.html", code=""), 404


if __name__ == "__main__":
    app.run(debug=True)
