"""
app.py —— 网站入口（路由层）

职责：接收浏览器请求 -> 调用 fund_api 拿数据 -> 渲染 HTML 模板返回。
不直接写数据抓取逻辑，那些都在 fund_api.py 里。
"""
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
    return render_template("fund.html", info=info,
                           history=history, recent=recent)


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
