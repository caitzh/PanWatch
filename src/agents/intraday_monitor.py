"""盘中监测 Agent - 实时监控持仓，AI 判断是否需要提醒"""

import json
import logging
import re
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

from src.agents.base import BaseAgent, AgentContext, AnalysisResult
from src.collectors.akshare_collector import AkshareCollector
from src.collectors.kline_collector import KlineCollector
from src.core.analysis_history import get_latest_analysis, get_analysis
from src.core.context_builder import ContextBuilder
from src.core.context_store import (
    save_agent_context_run,
    save_agent_prediction_outcome,
)
from src.core.suggestion_pool import save_suggestion
from src.core.signals import SignalPackBuilder
from src.core.signals.structured_output import try_parse_action_json
from src.models.market import MarketCode, StockData, MARKETS

logger = logging.getLogger(__name__)


def is_market_trading(market: MarketCode) -> bool:
    """按市场判断是否在交易时段。"""
    market_def = MARKETS.get(market)
    if not market_def:
        return False
    return market_def.is_trading_time()


def market_label(market: MarketCode) -> str:
    if market == MarketCode.CN:
        return "A股"
    if market == MarketCode.HK:
        return "港股"
    if market == MarketCode.US:
        return "美股"
    return market.value


# 标准化操作建议
SUGGESTION_TYPES = {
    "建仓": "buy",  # 新开仓位
    "加仓": "add",  # 增加现有仓位
    "减仓": "reduce",  # 减少仓位
    "清仓": "sell",  # 全部卖出
    "持有": "hold",  # 维持现状
    "观望": "watch",  # 暂不操作
}

PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "intraday_monitor.txt"


class IntradayMonitorAgent(BaseAgent):
    """
    盘中监测 Agent

    特点：
    - 单只模式 (single): 逐只股票分析，每只单独发送通知
    - AI 智能判断: 把股票数据发给 AI，由 AI 决定是否值得提醒
    - 通知节流: 同一股票短时间内不重复通知
    - 技术分析: 包含 K 线和技术指标
    """

    name = "intraday_monitor"
    display_name = "盘中监测"
    description = "交易时段实时监控持仓，AI 判断是否有值得关注的信号"

    def __init__(
        self,
        throttle_minutes: int = 30,
        bypass_throttle: bool = False,
        bypass_market_hours: bool = False,
        event_only: bool = True,
        price_alert_threshold: float = 3.0,
        volume_alert_ratio: float = 2.0,
        stop_loss_warning: float = -5.0,
        take_profit_warning: float = 10.0,
        enable_chart_screenshot: bool = False,
        screenshot_period: str = "daily",
    ):
        """
        Args:
            throttle_minutes: 同一股票通知间隔（分钟）
            bypass_throttle: 是否跳过节流（测试用）
            bypass_market_hours: 是否跳过交易时段门禁（仅手动分析场景）
            price_alert_threshold: 涨跌幅超过阈值视为价格异动（%）
            volume_alert_ratio: 量比超过阈值视为放量异动
            stop_loss_warning: 浮亏超过阈值触发止损预警（%）
            take_profit_warning: 浮盈超过阈值触发止盈提醒（%）
            enable_chart_screenshot: 是否启用 K 线截图多模态分析（需要 Vision 模型）
            screenshot_period: 截图 K 线周期 daily/weekly/monthly
        """
        self.throttle_minutes = throttle_minutes
        self.bypass_throttle = bypass_throttle
        self.bypass_market_hours = bypass_market_hours
        self.event_only = event_only
        self.price_alert_threshold = price_alert_threshold
        self.volume_alert_ratio = volume_alert_ratio
        self.stop_loss_warning = stop_loss_warning
        self.take_profit_warning = take_profit_warning
        self.enable_chart_screenshot = enable_chart_screenshot
        self.screenshot_period = screenshot_period

    async def collect(self, context: AgentContext) -> dict:
        """采集实时行情 + K线 + 历史分析"""
        if not context.watchlist:
            logger.warning("自选股列表为空，跳过盘中监测")
            return {"stocks": [], "stock_data": None}

        # SignalPack: 统一结构化输入（quote/technical/position）
        stock_config = context.watchlist[0] if context.watchlist else None
        market = stock_config.market if stock_config else MarketCode.CN
        symbol = stock_config.symbol if stock_config else ""
        name = stock_config.name if stock_config else symbol

        # 按股票所属市场做交易时段门禁（而非全局任一市场开盘）
        if not self.bypass_market_hours and not is_market_trading(market):
            msg = f"当前{market_label(market)}非交易时段，已跳过执行"
            logger.info(f"{msg}: {symbol}")
            return {
                "stocks": [],
                "stock_data": None,
                "skip_reason": msg,
            }

        builder = SignalPackBuilder()
        packs = await builder.build_for_symbols(
            symbols=[(symbol, market, name)],
            include_news=True,
            news_hours=24,
            portfolio=context.portfolio,
            include_technical=True,
            include_capital_flow=True,
            include_fundamental=True,
            include_events=True,
            events_days=3,
        )
        pack = packs.get(symbol)

        context_builder = ContextBuilder()
        context_pack = await context_builder.build_symbol_contexts(
            agent_name=self.name,
            context=context,
            packs=packs,
            realtime_hours=6,
            extended_hours=24,
            history_days=7,
            kline_days=60,
            persist_snapshot=True,
        )
        symbol_context = (context_pack.get("symbols", {}) or {}).get(symbol, {})
        quality_overview = context_pack.get("quality_overview", {}) or {}

        stock_data = pack.quote if pack and pack.quote else None

        kline_summary = pack.technical if pack else None

        # 采集大盘指数（仅 A 股）
        market_indices = []
        if market == MarketCode.CN:
            try:
                market_indices = await AkshareCollector(MarketCode.CN).get_index_data()
            except Exception as e:
                logger.warning(f"大盘指数采集失败: {e}")

        # 获取历史分析（为 AI 提供更多上下文）
        daily_analysis = get_latest_analysis(
            agent_name="daily_report",
            stock_symbol="*",
            before_date=date.today(),
        )
        premarket_analysis = get_analysis(
            agent_name="premarket_outlook",
            stock_symbol="*",
            analysis_date=date.today(),
        )

        # 可选：K 线截图（多模态分析）
        screenshot = None
        if self.enable_chart_screenshot:
            try:
                from src.collectors.screenshot_collector import ScreenshotCollector

                collector = ScreenshotCollector()
                try:
                    screenshot = await collector.capture(
                        symbol=symbol,
                        name=name,
                        market=market.value,
                        period=self.screenshot_period,
                        provider="xueqiu",
                    )
                finally:
                    await collector.close()
                if screenshot and screenshot.exists:
                    logger.info(f"K 线截图成功: {symbol} -> {screenshot.filepath}")
                else:
                    logger.warning(f"K 线截图失败或文件不存在，将继续纯文本分析: {symbol}")
                    screenshot = None
            except Exception as e:
                logger.warning(f"K 线截图异常，继续纯文本分析: {e}")
                screenshot = None

        return {
            "stocks": [stock_data] if stock_data else [],
            "stock_data": stock_data,
            "kline_summary": kline_summary,
            "signal_pack": pack,
            "daily_analysis": daily_analysis.content if daily_analysis else None,
            "premarket_analysis": premarket_analysis.content
            if premarket_analysis
            else None,
            "symbol_context": symbol_context,
            "quality_overview": quality_overview,
            "market_indices": market_indices,
            "screenshot": screenshot,
            "timestamp": datetime.now().isoformat(),
        }

    def build_prompt(self, data: dict, context: AgentContext) -> tuple[str, str]:
        """构建盘中分析 Prompt"""
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

        # 辅助函数
        def safe_num(value, default=0):
            return value if value is not None else default

        def format_num(value, precision=2):
            if value is None:
                return "N/A"
            return f"{value:.{precision}f}"

        def format_money(value):
            """格式化金额，自动选择万/亿单位"""
            if value is None:
                return "N/A"
            if abs(value) >= 1e8:
                return f"{value/1e8:.2f}亿"
            return f"{value/1e4:.0f}万"

        def classify_news_sentiment(title: str) -> str:
            """简单关键词情感分类"""
            bullish = ["上涨", "盈利", "增长", "利好", "突破", "涨停", "回购", "增持", "超预期", "重组", "获批", "合同", "中标", "签约"]
            bearish = ["下跌", "亏损", "违规", "处罚", "调查", "减持", "利空", "暴跌", "跌停", "负面", "被罚", "立案", "退市"]
            for w in bullish:
                if w in title:
                    return "[利好]"
            for w in bearish:
                if w in title:
                    return "[利空]"
            return "[中性]"

        stock: StockData | None = data.get("stock_data")
        if not stock:
            return system_prompt, "无股票数据"

        positions = context.portfolio.get_positions_for_stock(stock.symbol)

        lines = []

        # 0. 市场环境（大盘）
        market_indices = data.get("market_indices") or []
        if market_indices:
            lines.append("【市场环境】")
            for idx in market_indices:
                arrow = "↑" if idx.change_pct > 0 else ("↓" if idx.change_pct < 0 else "→")
                lines.append(f"{idx.name}：{idx.current_price:.2f}  {arrow}{idx.change_pct:+.2f}%")
            avg_chg = sum(i.change_pct for i in market_indices) / len(market_indices)
            if avg_chg >= 1.0:
                market_sentiment = "偏强（指数普涨）"
            elif avg_chg <= -1.0:
                market_sentiment = "偏弱（指数普跌）"
            else:
                market_sentiment = "中性震荡"
            lines.append(f"市场情绪：{market_sentiment}")

        current_price = safe_num(stock.current_price)
        change_pct = safe_num(stock.change_pct)
        open_price = safe_num(stock.open_price)
        high_price = safe_num(stock.high_price)
        low_price = safe_num(stock.low_price)
        prev_close = safe_num(stock.prev_close)

        # 1. 基本信息（精简）
        lines.append("【基本信息】")
        lines.append(f"股票：{stock.name}（{stock.symbol}）")
        lines.append(f"现价：{current_price:.2f}  涨跌：{change_pct:+.2f}%")
        lines.append(f"今开/最高/最低：{open_price:.2f} / {high_price:.2f} / {low_price:.2f}")
        lines.append(f"昨收：{prev_close:.2f}")
        
        # 计算日内位置（当前价在日内高低点中的位置）
        day_range = high_price - low_price if high_price != low_price else 1
        day_position = (current_price - low_price) / day_range * 100
        lines.append(f"日内位置：{day_position:.0f}%（0%=最低点，100%=最高点）")

        # 2. 技术分析（核心指标）
        kline = data.get("kline_summary")
        if kline and not kline.get("error"):
            lines.append("\n【技术分析】")
            
            # 趋势判断
            trend = kline.get("trend", "N/A")
            ma5 = kline.get("ma5")
            ma10 = kline.get("ma10")
            ma20 = kline.get("ma20")
            
            lines.append(f"趋势：{trend}")
            
            # 均线关系（关键：判断多空）
            if ma5 and ma10 and ma20:
                ma_status = ""
                if ma5 > ma10 > ma20:
                    ma_status = "多头排列（看涨）"
                elif ma5 < ma10 < ma20:
                    ma_status = "空头排列（看跌）"
                else:
                    ma_status = "均线交织（震荡）"
                
                # 当前价相对均线位置
                price_vs_ma = ""
                if current_price > ma5:
                    price_vs_ma = "站上MA5"
                elif current_price > ma10:
                    price_vs_ma = "MA5下方、MA10上方"
                elif current_price > ma20:
                    price_vs_ma = "MA10下方、MA20上方"
                else:
                    price_vs_ma = "跌破MA20"
                    
                lines.append(f"均线：{ma_status}，{price_vs_ma}")
                lines.append(f"MA5/10/20：{format_num(ma5)} / {format_num(ma10)} / {format_num(ma20)}")
            
            # MACD
            macd_status = kline.get("macd_status", "N/A")
            macd_cross = kline.get("macd_cross_days")
            macd_info = f"MACD：{macd_status}"
            if macd_cross:
                macd_info += f"（{macd_cross}日前{'金叉' if '金叉' in macd_status else '死叉'}）"
            lines.append(f"- {macd_info}")
            
            # RSI
            rsi6 = kline.get("rsi6")
            rsi_status = kline.get("rsi_status")
            if rsi6 is not None:
                rsi_hint = "中性"
                if rsi6 > 80:
                    rsi_hint = "严重超买"
                elif rsi6 > 70:
                    rsi_hint = "超买"
                elif rsi6 < 20:
                    rsi_hint = "严重超卖"
                elif rsi6 < 30:
                    rsi_hint = "超卖"
                lines.append(f"RSI(6)：{rsi6:.1f}（{rsi_hint}）")
            
            # KDJ
            kdj_k = kline.get("kdj_k")
            kdj_d = kline.get("kdj_d")
            kdj_j = kline.get("kdj_j")
            kdj_status = kline.get("kdj_status")
            if kdj_k is not None:
                kdj_hint = ""
                if kdj_j is not None:
                    if kdj_j > 100:
                        kdj_hint = "，超买注意风险"
                    elif kdj_j < 0:
                        kdj_hint = "，超卖关注反弹"
                lines.append(f"KDJ：K={kdj_k:.1f} D={kdj_d:.1f} J={kdj_j:.1f}（{kdj_status}{kdj_hint}）")
            
            # 量能
            volume_ratio = kline.get("volume_ratio")
            volume_trend = kline.get("volume_trend")
            if volume_ratio:
                vol_hint = "放量" if volume_ratio > 1.5 else ("缩量" if volume_ratio < 0.7 else "正常")
                lines.append(f"量比：{volume_ratio:.2f}（{vol_hint}）")
            if volume_trend:
                lines.append(f"量能趋势：{volume_trend}")
            
            # 换手率（A 股专用）
            pack_for_tr = data.get("signal_pack")
            if pack_for_tr and pack_for_tr.quote:
                tr = getattr(pack_for_tr.quote, "turnover_rate", None)
                if tr is not None:
                    if tr > 10:
                        tr_hint = "（异常高换手，活跃）"
                    elif tr > 5:
                        tr_hint = "（高换手）"
                    elif tr < 1:
                        tr_hint = "（低换手）"
                    else:
                        tr_hint = ""
                    lines.append(f"换手率：{tr:.2f}%{tr_hint}")
            
            # 支撑压力位
            support_s = kline.get("support_s")
            resistance_s = kline.get("resistance_s")
            if support_s and resistance_s:
                # 计算距离
                dist_support = (current_price - support_s) / current_price * 100
                dist_resist = (resistance_s - current_price) / current_price * 100
                lines.append(f"支撑：{format_num(support_s)}（-{dist_support:.1f}%）| 压力：{format_num(resistance_s)}（+{dist_resist:.1f}%）")
            
            # 近期涨跌
            change_5d = kline.get("change_5d")
            if change_5d is not None:
                lines.append(f"近5日涨跌：{change_5d:+.1f}%")

        # 3. 资金流向
        pack = data.get("signal_pack")
        flow = getattr(pack, "capital_flow", None) if pack else None
        if isinstance(flow, dict) and flow and not flow.get("error") and flow.get("status"):
            lines.append("\n【资金流向】")
            
            main_inflow = flow.get("main_net_inflow", 0)
            main_pct = flow.get("main_net_inflow_pct", 0)
            super_inflow = flow.get("super_net_inflow", 0)
            big_inflow = flow.get("big_net_inflow", 0)
            
            lines.append(f"主力净流入：{format_money(main_inflow)}（{main_pct:+.1f}%）")
            lines.append(f"超大单：{format_money(super_inflow)}  大单：{format_money(big_inflow)}")
            
            trend_5d = flow.get("trend_5d")
            if trend_5d and trend_5d != "无数据":
                lines.append(f"5日资金：{trend_5d}")

        # 4. 基本面（季报数据）
        fund = getattr(pack, "fundamental", None) if pack else None
        if isinstance(fund, dict) and fund and not fund.get("error"):
            period = fund.get("period_label", "")
            lines.append(f"\n【基本面】（{period}）")

            revenue = fund.get("revenue")
            rev_yoy = fund.get("revenue_yoy")
            if revenue is not None:
                rev_str = format_money(revenue)
                yoy_str = f"（同比{rev_yoy:+.1f}%）" if rev_yoy is not None else ""
                lines.append(f"营收：{rev_str}{yoy_str}")

            net_profit = fund.get("net_profit")
            np_yoy = fund.get("net_profit_yoy")
            if net_profit is not None:
                np_str = format_money(net_profit)
                yoy_str = f"（同比{np_yoy:+.1f}%）" if np_yoy is not None else ""
                lines.append(f"净利润：{np_str}{yoy_str}")

            metrics = []
            roe = fund.get("roe")
            gross = fund.get("gross_margin")
            debt = fund.get("debt_ratio")
            if roe is not None:
                metrics.append(f"ROE {roe:.1f}%")
            if gross is not None:
                metrics.append(f"毛利率 {gross:.1f}%")
            if debt is not None:
                metrics.append(f"负债率 {debt:.1f}%")
            if metrics:
                lines.append("  ".join(metrics))

            eps = fund.get("eps")
            if eps is not None:
                lines.append(f"EPS：{eps:.3f}元")

        # 5. 新闻（情感标记，按重要性排序）
        symbol_ctx = data.get("symbol_context") or {}
        layered_news = symbol_ctx.get("news") or {}
        realtime_news = layered_news.get("realtime") or []
        extended_news = layered_news.get("extended") or []
        all_news = realtime_news + extended_news
        if all_news:
            all_news_sorted = sorted(all_news, key=lambda x: x.get("importance", 0), reverse=True)
            lines.append("\n【相关新闻】")
            for item in all_news_sorted[:3]:
                sentiment = classify_news_sentiment(item.get("title", ""))
                lines.append(f"- {sentiment} {item.get('title')}")

        # 6. 持仓情况
        if positions:
            lines.append("\n【持仓情况】")
            total_qty = 0
            for i, pos in enumerate(positions, 1):
                cost_price = safe_num(pos.cost_price)
                pnl_pct = ((current_price - cost_price) / cost_price * 100) if cost_price > 0 else 0
                qty = safe_num(pos.quantity)
                total_qty += qty

                lines.append(f"账户{i}：{qty}股，成本{cost_price:.2f}，盈亏{pnl_pct:+.1f}%")

                # 止损止盈提示
                if pnl_pct <= self.stop_loss_warning:
                    lines.append(f"  ⚠️ 已触发止损预警（{self.stop_loss_warning}%）")
                elif pnl_pct >= self.take_profit_warning:
                    lines.append(f"  ✅ 已触发止盈提醒（{self.take_profit_warning}%）")
            lines.append(f"合计：{total_qty}股")
        else:
            lines.append("\n【持仓情况】未持仓")
            lines.append(f"可用资金：{context.portfolio.total_available_funds:.0f}元")

        # 7. 历史分析参考（精简）
        daily_analysis = data.get("daily_analysis")
        premarket_analysis = data.get("premarket_analysis")
        if daily_analysis or premarket_analysis:
            lines.append("\n【历史参考】")
            if premarket_analysis:
                # 提取关键信息，限制长度
                brief = premarket_analysis[:150].replace("\n", " ")
                lines.append(f"盘前观点：{brief}...")
            elif daily_analysis:
                brief = daily_analysis[:150].replace("\n", " ")
                lines.append(f"昨日分析：{brief}...")

        user_content = "\n".join(lines)
        return system_prompt, user_content

    def _parse_suggestion(self, content: str) -> dict:
        """
        从 AI 响应中解析操作建议

        Returns:
            {
                "action": "hold",  # buy/add/reduce/sell/hold/watch
                "action_label": "持有",
                "signal": "...",
                "reason": "...",
                "should_alert": True
            }
        """
        result = {
            "action": "watch",
            "action_label": "观望",
            "signal": "",
            "reason": "",
            "should_alert": True,  # 所有建议都发送提醒
        }

        # 1) Prefer JSON output (structured mode)
        obj = try_parse_action_json(content) or self._try_parse_loose_json(content)
        if obj:
            action = (obj.get("action") or "watch").strip()
            result["action"] = action
            result["action_label"] = (
                obj.get("action_label") or result["action_label"]
            ).strip()[:20]
            result["signal"] = (obj.get("signal") or "").strip()[:60]
            result["reason"] = (obj.get("reason") or "").strip()[:160]
            result["should_alert"] = True  # 所有建议都发送提醒
            result["triggers"] = (
                obj.get("triggers") if isinstance(obj.get("triggers"), list) else []
            )
            result["invalidations"] = (
                obj.get("invalidations")
                if isinstance(obj.get("invalidations"), list)
                else []
            )
            result["risks"] = (
                obj.get("risks") if isinstance(obj.get("risks"), list) else []
            )
            return result

        # 所有建议都发送提醒，不再区分

        # 提取建议类型（从全文搜索）
        for label, action in SUGGESTION_TYPES.items():
            if label in content:
                result["action"] = action
                result["action_label"] = label
                break

        # 提取信号（支持多种格式）
        signal_patterns = [
            r"「信号」\s*[:：]?\s*(.+?)(?=「|$|\n\n)",
            r"\*\*信号\*\*\s*[:：]?\s*(.+?)(?=\*\*|$|\n\n)",
            r"信号\s*[:：]\s*(.+?)(?=\n|$)",
        ]
        for pattern in signal_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                result["signal"] = match.group(1).strip()[:50]
                break

        # 提取建议内容（支持多种格式）
        suggest_patterns = [
            r"「建议」\s*[:：]?\s*(.+?)(?=「|$|\n\n)",
            r"\*\*建议\*\*\s*[:：]?\s*(.+?)(?=\*\*|$|\n\n)",
            r"建议\s*[:：]\s*(.+?)(?=\n|$)",
        ]
        for pattern in suggest_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                suggest_text = match.group(1).strip()
                # 从建议中提取操作类型
                for label, action in SUGGESTION_TYPES.items():
                    if label in suggest_text:
                        result["action"] = action
                        result["action_label"] = label
                        break
                # 如果信号为空，使用建议内容作为信号
                if not result["signal"]:
                    result["signal"] = suggest_text[:50]
                break

        # 提取理由（支持多种格式）
        reason_patterns = [
            r"「理由」\s*[:：]?\s*(.+?)(?=「|$|\n\n)",
            r"\*\*理由\*\*\s*[:：]?\s*(.+?)(?=\*\*|$|\n\n)",
            r"理由\s*[:：]\s*(.+?)(?=\n|$)",
        ]
        for pattern in reason_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                result["reason"] = match.group(1).strip()[:100]
                break

        # 如果没有提取到信号和理由，尝试使用整段内容的前部分
        if not result["signal"] and not result["reason"]:
            # 清理 markdown 格式后取前 100 字符
            clean_content = re.sub(r"\*\*|##|#", "", content).strip()
            # 跳过无需提醒的情况
            if not clean_content.startswith("[无需提醒]"):
                result["reason"] = clean_content[:100]

        # 所有建议都发送提醒
        result["should_alert"] = True
        return result

    def _try_parse_loose_json(self, text: str) -> dict | None:
        """宽松解析 JSON 输出，兜底兼容模型异常格式。"""
        raw = (text or "").strip()
        if not raw:
            return None

        # 兼容首行 "json"
        lines = raw.splitlines()
        if lines and lines[0].strip().lower() == "json":
            raw = "\n".join(lines[1:]).strip()

        # 去掉 fenced code block
        if raw.startswith("```"):
            block_lines = raw.splitlines()
            if len(block_lines) >= 3 and block_lines[-1].strip().startswith("```"):
                raw = "\n".join(block_lines[1:-1]).strip()
                if raw.lower().startswith("json\n"):
                    raw = raw[5:].strip()

        # 优先直接解析，失败则提取首个 JSON 对象片段
        try:
            obj = json.loads(raw)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except Exception:
                return None

        if not isinstance(obj, dict):
            return None

        # 必须有 action 或 action_label 字段
        if "action" not in obj and "action_label" not in obj:
            return None
        return obj

    def _format_human_readable_content(
        self, stock: StockData, suggestion: dict, raw_content: str
    ) -> str:
        """生成可读通知内容。"""
        action_label = suggestion.get("action_label") or "观望"
        reason = suggestion.get("reason") or ""
        
        price = (
            f"{stock.current_price:.2f}" if getattr(stock, "current_price", None) else "N/A"
        )
        chg = f"{(stock.change_pct or 0):+.2f}%"
        lines = [
            f"{stock.name}（{stock.symbol}）",
            f"现价：{price}  涨跌：{chg}",
            f"建议：{action_label}",
        ]

        # 理由：优先使用解析出的值，否则从原文提取
        if reason:
            lines.append(f"理由：{reason}")
        else:
            # 从原文提取关键信息
            brief = re.sub(r"\s+", " ", (raw_content or "").strip())[:200]
            if brief:
                brief = re.sub(r'^```json\s*|```\s*$|^\s*```\s*$', '', brief)
                lines.append(f"分析：{brief}")

        return "\n".join(lines)

    async def analyze(self, context: AgentContext, data: dict) -> AnalysisResult:
        """AI 分析并判断是否需要提醒"""
        # 非交易时段跳过
        if data.get("skip_reason"):
            return AnalysisResult(
                agent_name=self.name,
                title=f"【{self.display_name}】跳过",
                content=data.get("skip_reason", "跳过执行"),
                raw_data={"skipped": True, **data},
            )

        stock: StockData | None = data.get("stock_data")

        if not stock:
            return AnalysisResult(
                agent_name=self.name,
                title=f"【{self.display_name}】无数据",
                content="未获取到股票数据",
                raw_data=data,
            )

        system_prompt, user_content = self.build_prompt(data, context)

        # 打印完整 prompt 用于调试
        logger.info(f"=== Prompt for {stock.symbol} ===\n{user_content}")

        # 可选：附加 K 线截图进行多模态分析
        screenshot = data.get("screenshot")
        image_paths: list[str] = []
        if screenshot and screenshot.exists:
            image_paths = [screenshot.filepath]
            logger.info(f"多模态分析：附加 K 线截图 {screenshot.filepath}")

        raw_content = await context.ai_client.chat(
            system_prompt,
            user_content,
            images=image_paths if image_paths else None,
        )

        # 打印 AI 返回结果
        logger.info(f"=== AI Response for {stock.symbol} ===\n{raw_content}")

        # 解析操作建议
        suggestion = self._parse_suggestion(raw_content)
        analysis_date = (data.get("timestamp") or "")[:10] or datetime.now().strftime(
            "%Y-%m-%d"
        )
        quality_score = (
            (data.get("symbol_context") or {}).get("data_quality", {}).get("score")
        )
        # 始终使用格式化的可读文本，避免推送原始 JSON
        content = self._format_human_readable_content(stock, suggestion, raw_content)

        # 保存到建议池（包含 prompt 上下文）
        save_suggestion(
            stock_symbol=stock.symbol,
            stock_name=stock.name,
            action=suggestion["action"],
            action_label=suggestion["action_label"],
            signal=suggestion.get("signal", ""),
            reason=suggestion.get("reason", ""),
            agent_name=self.name,
            agent_label=self.display_name,
            expires_hours=6,  # 盘中建议 6 小时有效
            prompt_context=user_content,  # 保存 prompt 上下文
            ai_response=raw_content,  # 保存 AI 原始响应
            stock_market=stock.market.value,
            meta={
                "quote": {
                    "current_price": stock.current_price,
                    "change_pct": stock.change_pct,
                },
                "kline_meta": {
                    "computed_at": (data.get("kline_summary") or {}).get("computed_at"),
                    "asof": (data.get("kline_summary") or {}).get("asof"),
                },
                "event_gate": data.get("event_gate"),
                "analysis_date": analysis_date,
                "context_quality_score": quality_score,
                "plan": {
                    "triggers": suggestion.get("triggers")
                    if isinstance(suggestion, dict)
                    else [],
                    "invalidations": suggestion.get("invalidations")
                    if isinstance(suggestion, dict)
                    else [],
                    "risks": suggestion.get("risks")
                    if isinstance(suggestion, dict)
                    else [],
                },
            },
        )
        for horizon in (1, 5):
            save_agent_prediction_outcome(
                agent_name=self.name,
                stock_symbol=stock.symbol,
                stock_market=stock.market.value,
                prediction_date=analysis_date,
                horizon_days=horizon,
                action=suggestion.get("action") or "watch",
                action_label=suggestion.get("action_label") or "观望",
                confidence=(float(quality_score) / 100.0)
                if quality_score is not None
                else None,
                trigger_price=getattr(stock, "current_price", None),
                meta={
                    "source": "intraday_monitor",
                    "reason": suggestion.get("reason", ""),
                    "signal": suggestion.get("signal", ""),
                },
            )

        save_agent_context_run(
            agent_name=self.name,
            stock_symbol=stock.symbol,
            analysis_date=analysis_date,
            context_payload={
                "symbol_context": data.get("symbol_context") or {},
                "quality_overview": data.get("quality_overview") or {},
            },
            quality={"score": quality_score or 0},
        )

        # 构建标题
        title = f"【{self.display_name}】{stock.name} {stock.change_pct:+.2f}%"

        # 附 AI 模型信息
        if context.model_label:
            content = content.rstrip() + f"\n\n---\nAI: {context.model_label}"

        return AnalysisResult(
            agent_name=self.name,
            title=title,
            content=content,
            raw_data={
                "stock": {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "current_price": stock.current_price,
                    "change_pct": stock.change_pct,
                },
                "suggestion": suggestion,
                "should_alert": suggestion["should_alert"],
                "kline_summary": data.get("kline_summary"),
                "symbol_context": data.get("symbol_context") or {},
                "quality_overview": data.get("quality_overview") or {},
                **data,
            },
        )

    async def should_notify(self, result: AnalysisResult) -> bool:
        """检查是否需要通知"""
        # 跳过的结果不通知
        if result.raw_data.get("skipped"):
            return False

        # AI 判断不需要提醒
        if not result.raw_data.get("should_alert", True):
            logger.info(
                f"AI 判断无需提醒: {result.raw_data.get('stock', {}).get('symbol')}"
            )
            return False

        stock_data = result.raw_data.get("stock")
        if not stock_data:
            return False

        symbol = stock_data.get("symbol")
        if not symbol:
            return False

        # 检查节流（测试模式可跳过）
        if not self.bypass_throttle:
            if not self._check_throttle(symbol):
                logger.info(
                    f"通知节流: {symbol} 在 {self.throttle_minutes} 分钟内已通知"
                )
                return False
        else:
            logger.info(f"跳过节流检查（测试模式）: {symbol}")

        return True

    def _check_throttle(self, symbol: str) -> bool:
        """检查是否可以发送通知（未被节流）"""
        from src.web.database import SessionLocal
        from src.web.models import NotifyThrottle

        db = SessionLocal()
        try:
            record = (
                db.query(NotifyThrottle)
                .filter(
                    NotifyThrottle.agent_name == self.name,
                    NotifyThrottle.stock_symbol == symbol,
                )
                .first()
            )

            if not record:
                return True

            # 以 UTC 进行比较，避免容器/部署时区变化导致异常
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            threshold = now - timedelta(minutes=self.throttle_minutes)
            last = record.last_notify_at
            if last and last.tzinfo is not None:
                last = last.astimezone(timezone.utc).replace(tzinfo=None)
            return (last or datetime.fromtimestamp(0)) < threshold
        finally:
            db.close()

    def _update_throttle(self, symbol: str):
        """更新节流记录"""
        from src.web.database import SessionLocal
        from src.web.models import NotifyThrottle

        db = SessionLocal()
        try:
            record = (
                db.query(NotifyThrottle)
                .filter(
                    NotifyThrottle.agent_name == self.name,
                    NotifyThrottle.stock_symbol == symbol,
                )
                .first()
            )

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if record:
                # 检查是否是新的一天
                if record.last_notify_at.date() < now.date():
                    record.notify_count = 1
                else:
                    record.notify_count += 1
                record.last_notify_at = now
            else:
                db.add(
                    NotifyThrottle(
                        agent_name=self.name,
                        stock_symbol=symbol,
                        last_notify_at=now,
                        notify_count=1,
                    )
                )

            db.commit()
        finally:
            db.close()

    async def run_single(
        self, context: AgentContext, stock_symbol: str
    ) -> AnalysisResult | None:
        """
        单只模式执行：只分析指定的一只股票

        用于实时监控场景，每只股票独立分析和通知
        """
        # 过滤只保留指定股票
        original_watchlist = context.config.watchlist
        context.config.watchlist = [
            s for s in original_watchlist if s.symbol == stock_symbol
        ]

        if not context.config.watchlist:
            return None

        try:
            data = await self.collect(context)
            if not data.get("stock_data"):
                return None

            # 事件门禁仅作为上下文信号，不阻断 AI 分析。
            # 产品策略：建议持续刷新，通知再由 should_alert + throttle 控制降噪。
            if self.event_only:
                try:
                    from src.core.intraday_event_gate import check_and_update

                    stock = data.get("stock_data")
                    kline_summary = data.get("kline_summary")
                    decision = check_and_update(
                        symbol=stock_symbol,
                        change_pct=getattr(stock, "change_pct", None),
                        volume_ratio=(kline_summary or {}).get("volume_ratio"),
                        kline_summary=kline_summary,
                        price_threshold=self.price_alert_threshold,
                        volume_threshold=self.volume_alert_ratio,
                    )
                    data["event_gate"] = {
                        "reasons": decision.reasons,
                        "should_analyze": bool(decision.should_analyze),
                    }
                except Exception as e:
                    logger.debug(f"事件门禁异常，继续分析: {e}")

            result = await self.analyze(context, data)

            if getattr(context, "suppress_notify", False):
                result.raw_data["notified"] = False
                result.raw_data["notify_skipped"] = "suppressed"
                return result

            if await self.should_notify(result):
                notify_result = await context.notifier.notify_with_result(
                    result.title,
                    result.content,
                    result.images,
                )
                notified = bool(notify_result.get("success"))
                result.raw_data["notified"] = notified
                if notified:
                    logger.info(
                        f"Agent [{self.display_name}] 通知已发送: {stock_symbol}"
                    )
                    if not self.bypass_throttle:
                        self._update_throttle(stock_symbol)
                else:
                    notify_error = notify_result.get("error") or "未知错误"
                    result.raw_data["notify_error"] = notify_error
                    logger.error(
                        f"Agent [{self.display_name}] 通知发送失败: {stock_symbol} - {notify_error}"
                    )
            else:
                result.raw_data["notified"] = False

            return result
        finally:
            context.config.watchlist = original_watchlist
