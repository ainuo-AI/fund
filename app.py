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


@app.errorhandler(404)
def not_found(e):
    """所有未匹配的路径统一走这里"""
    return render_template("404.html", code=""), 404


if __name__ == "__main__":
    app.run(debug=True)
