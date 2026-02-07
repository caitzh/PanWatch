# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

# PanWatch 盯盘侠 - CodeBuddy 开发知识库

本文档记录了 PanWatch 项目的核心架构、常见问题及解决方案，供 AI 助手快速理解项目上下文。

## 项目概述

PanWatch 是一个智能股票监控系统，集成了实时行情采集、AI 分析、技术指标计算和推送通知功能。

### 技术栈

**后端**:
- Python 3.11+ (FastAPI, SQLAlchemy)
- SQLite 数据库
- 异步任务调度 (APScheduler)

**前端**:
- React + TypeScript
- shadcn/ui 组件库
- Vite 构建工具

**部署**:
- Docker/Podman 容器化
- Nginx 反向代理

## 常用命令

### 开发环境

```bash
# 后端开发（需先激活虚拟环境）
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py              # 启动后端服务，带热重载

# 前端开发
cd frontend
pnpm install
pnpm dev                      # 开发服务器 http://localhost:5173

# 前端构建
cd frontend
pnpm install --frozen-lockfile
pnpm build                    # 输出到 frontend/dist/
```

### 测试

```bash
# 运行后端测试
pytest                        # 运行所有测试
pytest tests/test_<module>.py # 运行单个测试文件
pytest -k <test_name>         # 运行特定测试
```

### 构建与部署

```bash
# 完整构建（前端 + Docker 镜像）
./build.sh <version>          # 例如: ./build.sh latest

# 手动构建 Docker 镜像
cd frontend && pnpm install --frozen-lockfile && pnpm build
cd .. && docker build --platform linux/amd64 -t localhost/panwatch:latest .

# 运行容器
docker run -d -p 8000:8000 -v panwatch_data:/app/data sunxiao0721/panwatch:latest

# 查看日志
docker logs -f panwatch                    # 实时日志
docker logs --tail 100 panwatch            # 最近 100 行
docker logs panwatch | grep ERROR          # 错误日志
```

### 代码规范

```bash
# Python 格式化（Black）
black src/ tests/

# TypeScript 格式化（Prettier）
cd frontend && pnpm exec prettier --write "src/**/*.{ts,tsx}"
```

## 项目结构

```
/root/PanWatch/
├── src/                      # 后端源码
│   ├── agents/               # AI Agent（日报、盘中监控等）
│   │   ├── base.py           # Agent 抽象基类
│   │   ├── daily_report.py   # 盘后日报 Agent
│   │   ├── intraday_monitor.py # 盘中监测 Agent
│   │   ├── premarket_outlook.py # 盘前分析 Agent
│   │   ├── news_digest.py    # 新闻速递 Agent
│   │   └── chart_analyst.py  # 技术分析 Agent
│   ├── collectors/           # 数据采集器（K线、资金流、新闻等）
│   │   ├── kline_collector.py      # K线数据（腾讯 API）
│   │   ├── capital_flow_collector.py # 资金流向（东方财富）
│   │   ├── screenshot_collector.py   # K线截图
│   │   ├── news_collector.py         # 新闻采集
│   │   └── akshare_collector.py      # AKShare 数据
│   ├── core/                 # 核心模块
│   │   ├── ai_client.py      # AI 客户端封装
│   │   ├── notifier.py       # 通知管理器
│   │   ├── scheduler.py      # Agent 调度器
│   │   ├── suggestion_pool.py # 建议池管理
│   │   └── agent_runs.py     # Agent 执行记录
│   ├── web/                  # Web API
│   │   ├── app.py            # FastAPI 应用
│   │   ├── database.py       # 数据库连接
│   │   ├── models.py         # SQLAlchemy 模型
│   │   └── api/              # API 路由
│   │       ├── auth.py       # 认证接口
│   │       ├── stocks.py     # 股票接口
│   │       ├── suggestions.py # 建议池接口
│   │       └── ...
│   ├── models/               # 领域模型
│   │   └── market.py         # 市场代码枚举
│   └── config.py             # 配置管理
├── frontend/                 # 前端源码
│   ├── src/
│   │   ├── pages/            # 页面组件
│   │   │   ├── Dashboard.tsx # 仪表盘
│   │   │   ├── Stocks.tsx    # 持仓页面
│   │   │   └── Settings.tsx  # 设置页面
│   │   ├── components/       # 通用组件
│   │   └── lib/              # 工具函数
│   └── dist/                 # 构建产物
├── prompts/                  # AI Prompt 模板
│   ├── daily_report.txt      # 日报 Prompt
│   ├── premarket_outlook.txt # 盘前展望 Prompt
│   └── news_digest.txt       # 新闻摘要 Prompt
├── tests/                    # 测试文件
├── server.py                 # 后端入口点
├── build.sh                  # 构建脚本
└── scripts/                  # 部署脚本
    ├── restart.sh            # 重启服务
    └── deploy.sh             # 部署脚本
```

## 代码规范与命名约定

- **Python**: PEP 8, 4 空格缩进，新代码需要类型提示
  - 文件: `snake_case.py`
  - 类: `PascalCase`
  - 函数/变量: `snake_case`
- **TypeScript**: 
  - 组件: `PascalCase.tsx`
  - Hooks: `use-` 前缀
  - 工具函数: `camelCase.ts`
- **Agent 开发**: 
  - 实现放在 `src/agents/*.py`
  - 在 `server.py` 的 `AGENT_REGISTRY` 中注册
  - 在 `seed_agents()` 中初始化配置
- **Collector 开发**:
  - 放在 `src/collectors/`
  - 保持无状态，返回类型化的 dataclass
- **Prompt**: 每个 Agent 一个文件在 `prompts/` 目录

## 提交规范

- 格式: `<type>: <subject>`，type ∈ {feat, fix, docs, refactor, style, test}
- 示例: `feat: add intraday monitor agent`
- 使用中文描述，详细说明修改内容

## 核心概念

### 1. 市场代码 (Market Code)

A 股市场有三个交易所，股票代码前缀决定了交易所归属：

| 交易所 | 代码前缀 | 示例 |
|--------|----------|------|
| 上交所 (SH) | 6, 9 | 600519 (贵州茅台), 900001 (B股) |
| 深交所 (SZ) | 0, 1, 2, 3 | 000001 (平安银行), 002594 (比亚迪), 300750 (宁德时代) |
| 北交所 (BJ) | 43, 83, 87, 88, 92 | 430047, 830809 |

**重要**: 不同数据源的符号格式不同：

| 数据源 | 上交所格式 | 深交所格式 | 示例代码位置 |
|--------|-----------|-----------|-------------|
| 腾讯 API | sh600519 | sz000001 | `src/collectors/kline_collector.py:_tencent_symbol()` |
| 东方财富 | 1.600519 | 0.000001 | `src/collectors/capital_flow_collector.py:_get_eastmoney_secid()` |
| 新浪财经 URL | sh600519 | sz000001 | `src/collectors/screenshot_collector.py:_get_sina_url()` |
| 雪球 URL | SH600519 | SZ000001 | `src/collectors/screenshot_collector.py:_get_xueqiu_url()` |

**常见错误**: 将 "000" 开头的深交所股票误判为上交所，导致价格显示错误（相差1000倍）。

### 2. AI 建议系统

#### 建议类型分类

系统根据持仓状态提供不同的建议类型：

**已持仓股票**:
- 继续持有 (hold)
- 考虑加仓 (add)
- 考虑减仓 (reduce)
- 考虑止损 (sell)

**未持仓股票**:
- 明日关注 / 准备建仓 (buy)
- 观望 / 设置预警 (watch)
- 暂时回避 (avoid)

**关键点**: 
- Prompt 中必须明确标注股票的持仓状态（"持仓：X股" 或 "持仓：未持仓"）
- AI 容易对未持仓股票使用"继续持有"等错误建议，需在 Prompt 中强调
- 参见: `prompts/daily_report.txt`, `prompts/premarket_outlook.txt`

#### 建议池 (Suggestion Pool)

所有 AI 建议保存在数据库的 `suggestions` 表中，供前端展示。

**保存逻辑** (`src/agents/intraday_monitor.py:analyze()`):
```python
# 特殊情况：AI 明确返回 [无需提醒] 时，不保存建议
if "[无需提醒]" in content:
    logger.info(f"AI 判断无需提醒，跳过保存建议: {stock.symbol}")
else:
    # 其他所有情况都保存到建议池
    save_suggestion(...)
```

**should_alert 语义**:
- `should_alert=True`: 发送推送通知（明确操作或重要信号）
- `should_alert=False`: 不推送通知（仅在前端显示）
- **关键**: should_alert 只控制通知，不影响建议池保存

#### AI 响应解析

建议解析代码: `src/agents/intraday_monitor.py:_parse_suggestion()`

**关键改进**:
1. **只在建议字段中搜索**: 避免从全文中误匹配关键词
2. **只在第一个逗号前搜索**: 避免"暂不建仓"被识别为"建仓"
3. **优先级**: 先提取结构化字段，再搜索关键词

```python
# 错误示例：从全文搜索
for label in SUGGESTION_TYPES:
    if label in content:  # "暂不建仓" 包含 "建仓"
        action = SUGGESTION_TYPES[label]

# 正确示例：只在建议字段的第一个逗号前搜索
if suggestion_text:
    for label, action in SUGGESTION_TYPES.items():
        if label in suggestion_text.split("，")[0].split(",")[0]:
            result["action"] = action
            break
```

### 3. 技术指标系统

**K 线数据采集**: `src/collectors/kline_collector.py`
- 数据源: 腾讯 API
- 计算指标: MA5/10/20, MACD, RSI, KDJ, 布林带, 成交量

**前端打分逻辑**: `frontend/src/lib/kline-scorer.ts:buildKlineSuggestion()`
- 根据持仓状态给出不同建议
- 已持仓: 重点关注止损/减仓信号
- 未持仓: 重点关注买入信号

### 4. 持仓状态同步

**问题**: Dashboard 页面初始渲染时，portfolioRaw 异步加载导致 positionMap 为空。

**解决方案** (`frontend/src/pages/Dashboard.tsx`):
```typescript
// 添加 portfolioRaw 到 useEffect 依赖
useEffect(() => {
  if (stocks.length > 0 && !initialScanDone.current) {
    initialScanDone.current = true
    loadMonitorFromPool()
  } else if (stocks.length > 0 && initialScanDone.current) {
    loadMonitorFromPool()  // portfolioRaw 变化时重新加载
  }
}, [stocks, portfolioRaw])  // 添加 portfolioRaw 依赖
```

## 常见问题及解决方案

### 问题 1: 股票价格显示 1000 倍错误

**症状**: 000158 显示 1520.16，实际应该是 ~20

**原因**: 市场代码前缀判断错误，将深交所股票发送到上交所接口

**解决**: 修正所有符号转换函数
```python
# 错误
prefix = "sh" if symbol.startswith("6") or symbol.startswith("000") else "sz"

# 正确
prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
```

**影响文件**:
- `src/collectors/kline_collector.py`
- `src/collectors/capital_flow_collector.py`
- `src/collectors/screenshot_collector.py`
- `src/agents/daily_report.py`
- `src/agents/news_digest.py`
- `src/agents/premarket_outlook.py`

### 问题 2: Dashboard 技术建议与持仓页面不一致

**症状**: Dashboard 显示"观望"，持仓页面显示"考虑加仓"

**原因**: portfolioRaw 异步加载完成前，positionMap 为空对象

**解决**: 添加 portfolioRaw 到 useEffect 依赖数组

### 问题 3: 未持仓股票显示"持有"建议

**症状**: AI 响应是 [无需提醒]，但前端显示"持有"

**原因**: 解析逻辑默认返回 "hold" action

**解决**: 
1. AI 返回 [无需提醒] 时跳过保存
2. 在 Prompt 中强调持仓状态判断

### 问题 4: AI 建议与响应内容不符

**症状**: 利欧股份显示"买入"，但 AI 说"观望，暂不建仓"

**原因**: 关键词搜索在全文中进行，"暂不建仓"包含"建仓"

**解决**: 
1. 先提取建议字段
2. 只在第一个逗号前搜索
3. 使用完整词匹配

### 问题 5: "观望"建议未保存到建议池

**症状**: 日志显示"跳过保存建议"，但 AI 给出了有效建议

**原因**: should_alert=False 时跳过保存

**解决**: 分离保存逻辑和通知逻辑
- 除 [无需提醒] 外都保存
- should_alert 只控制是否推送通知

## Agent 架构详解

### Agent 生命周期

Agent 通过 `server.py` 中的调度器管理：

1. **注册**: 在 `AGENT_REGISTRY` 中注册 Agent 类
2. **配置**: 在 `seed_agents()` 中定义默认配置（调度计划、执行模式等）
3. **调度**: `AgentScheduler` 根据 cron 表达式触发执行
4. **执行**: 根据 `execution_mode` 选择执行方式

### 执行模式

- **batch** (批量模式): 多只股票一起分析，适合日报、盘前分析
- **single** (单只模式): 逐只股票分析，适合盘中监测（可针对单只股票决策是否通知）

### Agent 基类

所有 Agent 继承自 `src/agents/base.py:BaseAgent`：

```python
class BaseAgent(ABC):
    name: str = ""              # 唯一标识
    display_name: str = ""      # 显示名称
    description: str = ""       # 描述

    @abstractmethod
    async def collect(self, context: AgentContext) -> dict:
        """采集数据"""

    @abstractmethod
    def build_prompt(self, data: dict, context: AgentContext) -> tuple[str, str]:
        """构建 prompt，返回 (system_prompt, user_content)"""

    async def analyze(self, context: AgentContext, data: dict) -> AnalysisResult:
        """调用 AI 分析（通常不需要重写）"""

    async def should_notify(self, result: AnalysisResult) -> bool:
        """是否需要通知，子类可重写"""

    async def run(self, context: AgentContext) -> AnalysisResult:
        """标准执行流程（通常不需要重写）"""
```

### AgentContext

Agent 运行时的上下文，包含：

- `ai_client`: AI 客户端
- `notifier`: 通知管理器
- `config`: 应用配置（含自选股列表）
- `portfolio`: 持仓信息（多账户汇总）
- `model_label`: AI 模型标识

### 添加新 Agent

1. 在 `src/agents/` 创建新文件，继承 `BaseAgent`
2. 实现 `collect()` 和 `build_prompt()` 方法
3. 在 `server.py:AGENT_REGISTRY` 中注册
4. 在 `seed_agents()` 中添加默认配置

## 开发工作流

### 前端开发

```bash
cd /root/PanWatch/frontend
pnpm dev             # 开发服务器 http://localhost:5173
pnpm build           # 构建生产版本
```

### 后端开发

```bash
cd /root/PanWatch
python server.py     # 启动后端服务（带热重载）
```

### 完整部署

```bash
# 使用构建脚本
./build.sh <version>

# 或手动构建
cd /root/PanWatch/frontend && pnpm install --frozen-lockfile && pnpm build
cd /root/PanWatch && docker build --platform linux/amd64 -t localhost/panwatch:latest .
cd /root/PanWatch/scripts && ./restart.sh
```

### 查看日志

```bash
docker logs -f panwatch                    # 实时日志
docker logs --tail 100 panwatch            # 最近 100 行
docker logs panwatch | grep ERROR          # 错误日志
```

## API 接口

### 认证

- `POST /api/auth/login` - 登录
- `POST /api/auth/change-password` - 修改密码

### 股票

- `GET /api/stocks` - 获取自选股列表
- `POST /api/stocks` - 添加自选股
- `DELETE /api/stocks/{symbol}` - 删除自选股
- `GET /api/stocks/{symbol}/kline` - 获取 K 线数据

### 持仓

- `GET /api/portfolio` - 获取持仓数据
- `GET /api/portfolio/raw` - 获取原始持仓数据（含账户信息）

### 建议池

- `GET /api/suggestions` - 获取建议列表
- `DELETE /api/suggestions/{id}` - 删除建议

## 数据库表结构

### suggestions 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| stock_symbol | VARCHAR(20) | 股票代码 |
| stock_name | VARCHAR(100) | 股票名称 |
| action | VARCHAR(20) | 操作类型 (buy/sell/hold/add/reduce/watch) |
| action_label | VARCHAR(50) | 操作标签（中文） |
| signal | TEXT | 信号描述 |
| reason | TEXT | 建议理由 |
| agent_name | VARCHAR(100) | Agent 名称 |
| agent_label | VARCHAR(100) | Agent 显示名称 |
| should_alert | BOOLEAN | 是否推送通知 |
| is_expired | BOOLEAN | 是否过期 |
| prompt_context | TEXT | Prompt 上下文 |
| ai_response | TEXT | AI 原始响应 |
| created_at | DATETIME | 创建时间 |
| expires_at | DATETIME | 过期时间 |

## Prompt 编写规范

### 基本结构

```
你是一位专业的{角色}，负责{任务描述}。

## 输入数据
{数据说明}

## 输出要求

### 1. {板块名称}
{内容要求}

### 2. 个股建议
格式：「股票代码 股票名称」建议类型：一句话理由

**重要**：首先查看该股票的持仓状态

**已持仓股票使用**：
- 继续持有 / 考虑加仓 / 考虑减仓 / 考虑止损

**未持仓股票使用**：
- 明日关注 / 设置预警 / 观望 / 暂时回避

**注意：未持仓的股票不要使用"继续持有""考虑加仓"等针对持仓的建议！**

## 风格要求
{风格说明}
```

### 持仓状态标注

在 Prompt 中构造股票列表时，必须标注持仓状态：

```python
if position:
    lines.append(f"- 持仓：{position['total_quantity']}股 成本{avg_cost:.2f}")
else:
    lines.append(f"- 持仓：未持仓")
```

## 前端组件

### SuggestionBadge

建议徽章组件，显示 AI 建议和技术指标。

**位置**: `frontend/src/components/suggestion-badge.tsx`

**Props**:
- `suggestion`: AI 建议数据
- `kline`: K 线数据（可选）
- `hasPosition`: 是否持仓

**显示逻辑**:
- AI 建议 + 技术指标并排显示
- 点击查看详情对话框
- 显示来源和时间

### KlineSummaryDialog

K 线指标详情对话框。

**位置**: `frontend/src/components/kline-summary-dialog.tsx`

**功能**:
- 展示所有技术指标
- 趋势判断和信号分析
- 根据持仓状态给出建议

## 环境变量

```bash
# 数据库
DATABASE_URL=sqlite:///data/panwatch.db

# API Keys
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1

# 推送服务（可选）
PUSHPLUS_TOKEN=xxx
SERVERCHAN_KEY=xxx
BARK_KEY=xxx

# 服务配置
PORT=8000
HOST=0.0.0.0
```

## 注意事项

### 1. Git 管理

- 主分支: `main`
- 自定义分支: `deploy-custom`
- 远程仓库: `git@github.com:caitzh/PanWatch.git`

### 2. Docker 镜像

- 镜像名: `localhost/panwatch:latest`
- 平台: `linux/amd64`
- 容器名: `panwatch`

### 3. 数据持久化

重要数据目录（需挂载）：
- `/data/panwatch.db` - 数据库文件
- `/logs/` - 日志文件

### 4. 代码规范

- Python: 使用 Black 格式化
- TypeScript: 使用 Prettier 格式化
- 提交信息: 使用中文，详细描述修改内容

## 测试指南

- 测试文件放在 `tests/test_<module>.py`
- 优先编写快速、隔离的单元测试
- 使用工厂函数创建 DB 模型 fixture
- 模拟 Collector 和 AI 客户端，避免网络调用
- 包含正常路径和错误 case

## 安全与配置

- 不要提交 API Key，使用环境变量或 UI 配置
- 支持的配置项: `AUTH_USERNAME`, `AUTH_PASSWORD`, `JWT_SECRET`, `DATA_DIR`
- 企业代理: 支持通过 `data/ca-bundle.pem` 添加自定义 CA
- Playwright: Docker 环境下自动安装到 `DATA_DIR/playwright`

## 相关资源

- 腾讯股票 API: `https://qt.gtimg.cn/`
- 东方财富 API: `https://push2.eastmoney.com/`
- 新浪财经: `https://finance.sina.com.cn/`
- 雪球: `https://xueqiu.com/`

## 最近更新

### 2024-02 (deploy-custom 分支)

1. **修复市场代码前缀错误** - 000 开头股票价格显示正确
2. **优化 AI 建议系统** - 分离保存和通知逻辑，修复解析错误
3. **完善 Prompt** - 添加持仓状态判断说明
4. **新增密码修改功能** - Settings 页面支持修改登录密码
5. **UI 优化** - 建议显示布局改进，添加来源和时间显示

---

**维护者**: CodeBuddy AI Assistant  
**最后更新**: 2026-02-05
