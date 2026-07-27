# 基金信息站

一个用 Python + Flask 写的基金信息查询网站：搜索基金、查看基本信息、净值走势图和历史净值。

## 项目结构

```
jijin/
├── app.py            # 网站入口：定义路由（网址 -> 页面）
├── fund_api.py       # 数据层：封装第三方接口，获取基金数据
├── templates/        # HTML 模板（Jinja2）
│   ├── base.html     #   公共骨架：导航栏 + 页脚
│   ├── index.html    #   首页：搜索框 + 热门基金卡片
│   ├── search.html   #   搜索结果页
│   ├── fund.html     #   基金详情页：信息 + 走势图 + 历史净值表
│   └── 404.html
├── static/
│   ├── style.css     # 全站样式
│   └── echarts.min.js# 图表库（已下载到本地，无需联网加载）
└── venv/             # Python 虚拟环境（依赖都装在这里）
```

## 如何启动

```bash
cd ~/Desktop/jijin
venv/Scripts/python app.py
```

然后浏览器打开 http://127.0.0.1:5000

停止服务：在运行窗口按 `Ctrl + C`。

## 页面与路由

| 网址 | 页面 | 对应函数 |
|---|---|---|
| `/` | 首页（热门基金） | `index()` |
| `/search?q=关键词` | 搜索结果 | `search()` |
| `/fund/161725` | 基金详情 | `fund_detail()` |

## 数据来源

均为公开免费接口，仅用于学习：

- 天天基金移动端 API：最新净值、历史净值
- 天天基金搜索建议：按名称/代码搜索
- 新浪财经：基金概况（类型、规模、公司、经理）

## 可以练手的改进方向

1. 首页热门基金换成你自己关注的代码（改 `app.py` 里的 `HOT_FUND_CODES`）
2. 给详情页加"近1月/近1年"区间涨跌幅统计
3. 加"自选基金"功能，用浏览器 localStorage 保存
4. 用 `fund_api.get_nav_history` 做定投收益模拟计算
