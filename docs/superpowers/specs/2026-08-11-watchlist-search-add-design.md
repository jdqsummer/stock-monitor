# 自选股搜索添加功能 — 设计文档

日期：2026-08-11

## 1. 背景与目标

### 现状
- 前端「添加自选股」弹窗为**两个手动输入框**（股票代码 + 股票名称），提交调 `watchlistApi.add()`
- 后端 `/api/watchlist` CRUD API **完全不存在**（前端现有调用会 404）
- `westock_client.search_stock(keyword)` 已存在，返回 `list[StockQuote]`，但 **mock 模式返回空列表**

### 目标
将「添加自选股」从手动输入改为：**输入股票代码或名称 → 联想搜索 → 展示行情数据 → 确认后加入自选**。

### 已确认决策
| 决策点 | 结论 |
|:--|:---|
| 交互形态 | 输入即联想下拉（AutoComplete），选中后展示详情确认添加 |
| 数据展示 | 仅行情数据：现价 / 涨跌幅 / 总市值 / 动态PE / 总股本（StockQuote） |
| 实现范围 | 后端 + 前端全做（补齐 /api/watchlist CRUD + search，前端重做添加弹窗） |
| 开发降级 | `search_stock` 未配置 westock-mcp 时降级为**内置 mock 股票库** |

## 2. 架构（方案 A：独立 watchlist 模块）

```
backend/api/watchlist.py          # 新路由：CRUD + search
backend/services/watchlist_svc.py # 新服务层：db 操作 + 智能分类
backend/data/westock_client.py    # 增强：search_stock mock 库降级
frontend/src/components/Stock/StockSearchSelect.tsx  # 新联想下拉组件
frontend/src/pages/Watchlist.tsx  # 添加弹窗改用新组件
```

遵循现有 `auth.py` / `config.py` 分层模式：路由薄、服务层收 `db: AsyncSession`、统一 `ApiResponse` 包装。

## 3. 后端 API 契约

新增路由 `backend/api/watchlist.py`（prefix `/api/watchlist`，全部需 JWT 认证）：

| 方法 | 端点 | 说明 | 认证 |
|:--|:--|:---|:--|
| `GET` | `/api/watchlist` | 当前用户自选股列表（含行业分类） | ✅ |
| `POST` | `/api/watchlist` | 添加自选股（body: `stock_code`, `stock_name`, `industry?`） | ✅ |
| `DELETE` | `/api/watchlist/{id}` | 删除自选 | ✅ |
| `PATCH` | `/api/watchlist/{id}` | 更新行业分类（body: `industry`） | ✅ |
| `POST` | `/api/watchlist/auto-classify` | 智能一键分类（内置行业映射批量赋值） | ✅ |
| `GET` | `/api/watchlist/search?keyword=` | 搜索股票（westock-mcp，未配置降级 mock 库） | ✅ |

所有响应用统一 `ApiResponse` 包装。schemas 新增 `WatchlistItemOut`（id / stock_code / stock_name / industry / added_at）。

## 4. 服务层 `backend/services/watchlist_svc.py`

```
class WatchlistService:
    list_items(db, user_id) -> list[WatchlistItem]
    add_item(db, user_id, code, name, industry=None) -> WatchlistItem   # 重复 code 报 409
    remove_item(db, user_id, id) -> bool
    update_industry(db, user_id, id, industry) -> WatchlistItem | None
    auto_classify(db, user_id) -> int   # 返回已更新数量
```

- 遵循 `auth_svc.py` 模式：所有方法收 `db: AsyncSession`
- **添加去重**：同用户 + 同 `stock_code` 已存在 → 409「该股票已在自选股中」
- 删除/更新前校验 `user_id` 归属，非本人记录返回 404

### 智能分类数据源
StockQuote 无行业字段，auto-classify 用**内置代码→行业映射**（覆盖 mock 库股票 + 常见白马），未命中置空。当前阶段不做 LLM 分类。

## 5. Mock 搜索库（westock_client.py 增强）

`search_stock` 未配置 `base_url` 时，不再返回 `[]`，改为查内置 mock 股票库：

```python
_MOCK_STOCK_DB = [
    # (code, name, price, change_pct, market_cap亿, pe, shares亿)
    ("600519", "贵州茅台", 1560.0, 1.2, 19500.0, 25.3, 12.6),
    ("600036", "招商银行",  32.5, -0.3, 8200.0,  5.8, 252.2),
    ("601318", "中国平安",  45.8,  0.8, 8350.0,  9.1, 182.1),
    ("000858", "五粮液",   142.0,  1.0, 5510.0, 18.4, 38.8),
    # ... 约 12 只常见 A 股
]
```

- 关键字匹配：代码精确 / 名称模糊（子串），均可命中
- 返回 `list[StockQuote]`，按相关性排序（代码精确匹配优先）
- 生产路径（`base_url` 已配置）逻辑不变，仍调 westock-mcp

## 6. 前端交互

### 新组件 `frontend/src/components/Stock/StockSearchSelect.tsx`

```
输入框（AutoComplete 可搜索）
  └─ 输入变化 → debounce 300ms → GET /api/watchlist/search?keyword=
  └─ 下拉展示：代码 + 名称 + 现价 + 涨跌幅（涨红跌绿）
选中某股票 → 面板展示行情详情（现价/涨跌幅/总市值/动态PE/总股本）
          → 「确认添加」→ POST /api/watchlist
```

- 输入超短（<1 字符）不触发搜索
- 下拉「暂无匹配」空态

### `Watchlist.tsx` 添加弹窗改造
- 删除原两个手动输入框（stock_code / stock_name）
- 改为 `StockSearchSelect`：搜索 → 选中 → 展示详情卡片 → 确认添加
- 选中后详情卡片含「确认添加」按钮；添加已存在（409）提示「该股票已在自选股中」

## 7. 错误处理与边界

| 场景 | 处理 |
|:--|:---|
| 搜索无匹配 | 下拉显示「暂无匹配」 |
| 添加已存在股票 | 后端 409 → 前端 message.error「该股票已在自选股中」 |
| 搜索时 westock 异常 | 后端捕获返回空列表 + 日志，前端正常显示「暂无匹配」 |
| 未选中就点添加 | 按钮禁用，需先选股票 |
| 输入超短（<1 字符） | 不触发搜索 |

## 8. 测试策略（TDD）

**后端**（`tests/test_api/test_watchlist.py` + `tests/test_data/`）：
1. search 正常返回：代码精确 / 名称模糊 / 无匹配 / mock 库匹配优先级
2. watchlist CRUD：添加 / 列表 / 去重 409 / 删除 / 非本人 404 / 分类更新
3. auto-classify 批量赋值

**前端**：TypeScript 编译检查 + 手动浏览器验收（`npm run dev`）

## 9. 不做的事（YAGNI）
- 不做持仓 / 看板模块（本次范围仅自选股）
- 不做 LLM 行业分类
- 不做搜索结果分页（A 股代码/名称搜索量级无需分页）
