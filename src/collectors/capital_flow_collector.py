"""资金流向采集器

数据来源（按优先级）：
  1. SQLite 持久化缓存（当日有效，次日自动失效）
  2. AKShare stock_individual_fund_flow（东方财富，非交易时间也能返回历史数据）
  3. 降级：直接调东方财富 HTTP API（push2his，原有逻辑）
  4. 最终降级：返回 {"error": "..."}

缓存策略：
- 资金流向按交易日更新，缓存有效期到次日 05:00（UTC）
- 进程内二级缓存（5分钟），避免同一批次重复查库
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar

import httpx

from src.core.cn_symbol import is_cn_sh
from src.models.market import MarketCode

logger = logging.getLogger(__name__)

# 东方财富历史资金流向 API（直接 HTTP，备用）
EASTMONEY_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"

# 缓存有效期
_MEM_TTL_SEC = 300       # 进程内二级缓存 5 分钟


def _cache_expire_time() -> datetime:
    """计算缓存过期时间：下一个工作日 05:00 UTC（北京时间 13:00）

    周五采集的数据延期到周一，确保周末也能读到上一交易日的资金流数据。
    """
    now = datetime.utcnow()
    tomorrow = now.date() + timedelta(days=1)
    # 如果明天是周六(5)，跳到周一；如果明天是周日(6)，跳到周一
    weekday = tomorrow.weekday()  # 0=周一 ... 6=周日
    if weekday == 5:   # 周六 → 跳到周一（+2天）
        tomorrow += timedelta(days=2)
    elif weekday == 6:  # 周日 → 跳到周一（+1天）
        tomorrow += timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 5, 0, 0)


def _get_eastmoney_secid(symbol: str, market: MarketCode) -> str:
    """转换为东方财富的 secid 格式"""
    if market == MarketCode.HK:
        return f"116.{symbol}"
    if market == MarketCode.US:
        return f"105.{symbol}"
    prefix = "1" if is_cn_sh(symbol) else "0"
    return f"{prefix}.{symbol}"


def _get_db_session():
    """获取数据库 Session（延迟导入，避免循环依赖）"""
    from src.web.database import SessionLocal
    return SessionLocal()


def _read_db_cache(symbol: str) -> dict | None:
    """从 SQLite 读取资金流向缓存。

    查找顺序：
    1. 未过期的当前缓存
    2. 最近 5 天内的历史缓存（跨日降级，用于周末/非交易日）
    """
    try:
        from src.web.models import MarketDataCache
        db = _get_db_session()
        try:
            now = datetime.utcnow()
            # 1. 优先读未过期缓存
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "capital_flow",
                    MarketDataCache.expires_at > now,
                )
                .first()
            )
            if row:
                return row.data
            # 2. 降级：读最近 5 天内的历史缓存（非交易日/采集失败时使用上一交易日数据）
            cutoff = now - timedelta(days=5)
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "capital_flow",
                    MarketDataCache.fetched_at > cutoff,
                )
                .order_by(MarketDataCache.fetched_at.desc())
                .first()
            )
            if row:
                logger.debug("资金流向使用历史缓存 %s（采集于 %s）", symbol, row.fetched_at)
                data = dict(row.data) if isinstance(row.data, dict) else row.data
                if isinstance(data, dict):
                    data["stale"] = True   # 标记为过期数据，调用方可选择忽略
                return data
        finally:
            db.close()
    except Exception as e:
        logger.debug("资金流向缓存读取失败: %s", e)
    return None


def _write_db_cache(symbol: str, data: dict) -> None:
    """将资金流向数据写入 SQLite 缓存"""
    try:
        from src.web.models import MarketDataCache
        db = _get_db_session()
        try:
            now = datetime.utcnow()
            expires = _cache_expire_time()
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "capital_flow",
                )
                .first()
            )
            if row:
                row.data = data
                row.fetched_at = now
                row.expires_at = expires
            else:
                row = MarketDataCache(
                    symbol=symbol,
                    data_type="capital_flow",
                    data=data,
                    fetched_at=now,
                    expires_at=expires,
                )
                db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug("资金流向缓存写入失败: %s", e)


@dataclass
class CapitalFlow:
    """资金流向数据（内部使用）"""
    symbol: str
    name: str
    main_net_inflow: float
    main_net_inflow_pct: float
    super_net_inflow: float
    big_net_inflow: float
    mid_net_inflow: float
    small_net_inflow: float
    main_net_5d: float | None = None


class CapitalFlowCollector:
    """资金流向采集器（双层缓存：进程内5分钟 + SQLite 次日失效）"""

    # 进程内二级缓存：symbol -> (timestamp, summary_dict)
    _mem_cache: ClassVar[dict[str, tuple[float, dict]]] = {}

    def __init__(self, market: MarketCode):
        self.market = market

    def get_capital_flow_summary(self, symbol: str) -> dict:
        """
        获取资金流向摘要（带双层缓存）。

        缓存查找顺序：
          1. 进程内缓存（5分钟）
          2. SQLite 持久化缓存（当日有效）
          3. AKShare 实时采集
          4. 东方财富直接 HTTP 降级

        返回格式：
        {
            "status": "主力明显流入",
            "main_net_inflow": 1.2e8,
            "main_net_inflow_pct": 6.5,
            "super_net_inflow": 5.0e7,
            "big_net_inflow": 7.0e7,
            "mid_net_inflow": -3.0e7,
            "small_net_inflow": -2.0e7,
            "trend_5d": "5日净流入2.30亿",
            "cached": True,
        }
        """
        now = time.time()

        # 1. 进程内缓存
        if symbol in self._mem_cache:
            ts, data = self._mem_cache[symbol]
            if now - ts < _MEM_TTL_SEC:
                return data

        # 2. SQLite 持久化缓存
        cached = _read_db_cache(symbol)
        if cached and not cached.get("error"):
            cached["cached"] = True
            self._mem_cache[symbol] = (now, cached)
            return cached

        # 3. AKShare 采集（仅 A 股）
        if self.market == MarketCode.CN:
            result = self._fetch_from_akshare(symbol)
            if not result.get("error"):
                self._mem_cache[symbol] = (now, result)
                _write_db_cache(symbol, result)
                return result

        # 4. 东方财富直接 HTTP 降级（原有逻辑）
        result = self._fetch_from_eastmoney(symbol)
        if not result.get("error"):
            self._mem_cache[symbol] = (now, result)
            _write_db_cache(symbol, result)

        return result

    def _fetch_from_akshare(self, symbol: str) -> dict:
        """通过 AKShare stock_individual_fund_flow 采集，非交易时间也有历史数据"""
        try:
            import akshare as ak

            # 判断市场前缀（AKShare 需要 "sh"/"sz"/"bj"）
            if is_cn_sh(symbol):
                market_str = "sh"
            elif symbol.startswith(("43", "83", "87", "88", "92", "920")):
                market_str = "bj"
            else:
                market_str = "sz"

            df = ak.stock_individual_fund_flow(stock=symbol, market=market_str)
            if df is None or df.empty:
                return {"error": "AKShare 无资金流向数据"}

            # 取最新一行（按日期倒序或正序，取最后一行）
            latest = df.iloc[-1]

            # 字段名参考 AKShare 文档（列名可能含空格，strip 处理）
            col_map = {c.strip(): c for c in df.columns}

            def _get(name: str) -> float | None:
                col = col_map.get(name)
                if col is None:
                    return None
                return _safe_float(latest.get(col))

            main_net = _get("主力净流入-净额") or _get("主力净流入净额") or 0.0
            super_net = _get("超大单净流入-净额") or _get("超大单净流入净额") or 0.0
            big_net = _get("大单净流入-净额") or _get("大单净流入净额") or 0.0
            mid_net = _get("中单净流入-净额") or _get("中单净流入净额") or 0.0
            small_net = _get("小单净流入-净额") or _get("小单净流入净额") or 0.0

            # 主力净流入占比
            total_flow = abs(main_net) + abs(mid_net) + abs(small_net)
            main_pct = (main_net / total_flow * 100) if total_flow > 0 else 0.0

            # 近 5 日主力净流入合计
            n = min(5, len(df))
            main_5d_col = col_map.get("主力净流入-净额") or col_map.get("主力净流入净额")
            main_net_5d = float(df[main_5d_col].tail(n).sum()) if main_5d_col else None

            summary = _build_summary(
                main_net_inflow=main_net,
                main_net_inflow_pct=main_pct,
                super_net_inflow=super_net,
                big_net_inflow=big_net,
                mid_net_inflow=mid_net,
                small_net_inflow=small_net,
                main_net_5d=main_net_5d,
            )
            summary["cached"] = False
            return summary

        except Exception as e:
            logger.debug("AKShare 资金流向采集失败 %s: %s", symbol, e)
            return {"error": str(e)}

    def _fetch_from_eastmoney(self, symbol: str) -> dict:
        """直接调东方财富 HTTP API（原有逻辑，作为降级）"""
        secid = _get_eastmoney_secid(symbol, self.market)
        params = {
            "secid": secid,
            "klt": "101",
            "lmt": "5",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        try:
            with httpx.Client(follow_redirects=True, timeout=4) as client:
                resp = client.get(EASTMONEY_FLOW_URL, params=params, headers=headers)
                data = resp.json()

            if data.get("data") is None or not data["data"].get("klines"):
                return {"error": "东方财富无资金流向数据"}

            klines = data["data"]["klines"]
            today_parts = klines[-1].split(",")
            if len(today_parts) < 6:
                return {"error": "东方财富数据格式错误"}

            main_net = float(today_parts[1])
            small_net = float(today_parts[2])
            mid_net = float(today_parts[3])
            big_net = float(today_parts[4])
            super_net = float(today_parts[5])

            total_flow = abs(main_net) + abs(mid_net) + abs(small_net)
            main_pct = (main_net / total_flow * 100) if total_flow > 0 else 0.0
            main_5d = sum(float(k.split(",")[1]) for k in klines)

            summary = _build_summary(
                main_net_inflow=main_net,
                main_net_inflow_pct=main_pct,
                super_net_inflow=super_net,
                big_net_inflow=big_net,
                mid_net_inflow=mid_net,
                small_net_inflow=small_net,
                main_net_5d=main_5d,
            )
            summary["cached"] = False
            return summary

        except Exception as e:
            logger.error("东方财富资金流向采集失败 %s: %s", symbol, e)
            return {"error": str(e)}

    def batch_get(
        self,
        symbols: list[str],
        *,
        workers: int = 8,
        per_symbol_timeout: float = 6.0,
        total_timeout: float = 60.0,
    ) -> dict[str, dict]:
        """并发批量采集资金流向数据。

        策略：
        - 先批量读缓存，命中的直接返回，未命中的提交到线程池并发拉取
        - workers：并发线程数（默认 8，AKShare 是 IO 密集型，多线程有效）
        - per_symbol_timeout：单只股票最大等待时间（秒）
        - total_timeout：整批采集最大总时间（秒）

        返回：{symbol: summary_dict}，失败/超时的 symbol 不出现在结果中
        """
        import concurrent.futures
        import time as _time

        if not symbols:
            return {}

        result: dict[str, dict] = {}
        now = _time.time()

        # 第一步：批量读缓存，已缓存的直接放入结果
        pending: list[str] = []
        for sym in symbols:
            # 进程内缓存
            if sym in self._mem_cache:
                ts, data = self._mem_cache[sym]
                if now - ts < _MEM_TTL_SEC:
                    result[sym] = data
                    continue
            # SQLite 持久缓存
            cached = _read_db_cache(sym)
            if cached and not cached.get("error"):
                cached["cached"] = True
                self._mem_cache[sym] = (now, cached)
                result[sym] = cached
                continue
            pending.append(sym)

        if not pending:
            return result

        # 第二步：对未命中缓存的股票并发采集
        batch_start = _time.monotonic()

        def _fetch_one(sym: str) -> tuple[str, dict | None]:
            """单只采集，返回 (symbol, data_or_None)"""
            try:
                data = self.get_capital_flow_summary(sym)
                if data and not data.get("error"):
                    return sym, data
            except Exception:
                pass
            return sym, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_fetch_one, sym): sym for sym in pending}
            try:
                for future in concurrent.futures.as_completed(
                    future_map, timeout=min(per_symbol_timeout * len(pending), total_timeout)
                ):
                    sym, data = future.result(timeout=per_symbol_timeout)
                    if data is not None:
                        result[sym] = data
                    # 检查总超时
                    if _time.monotonic() - batch_start > total_timeout:
                        break
            except concurrent.futures.TimeoutError:
                pass  # 超时后直接返回已采集的结果，剩余的降级为 0
            finally:
                # 取消尚未开始的 future（已在运行的无法取消，但会被忽略）
                for f in future_map:
                    f.cancel()

        return result

    # 保留向后兼容的方法
    def get_capital_flow(self, symbol: str) -> CapitalFlow | None:
        """向后兼容接口，内部直接调 get_capital_flow_summary"""
        summary = self.get_capital_flow_summary(symbol)
        if summary.get("error"):
            return None
        return CapitalFlow(
            symbol=symbol,
            name="",
            main_net_inflow=summary.get("main_net_inflow", 0),
            main_net_inflow_pct=summary.get("main_net_inflow_pct", 0),
            super_net_inflow=summary.get("super_net_inflow", 0),
            big_net_inflow=summary.get("big_net_inflow", 0),
            mid_net_inflow=summary.get("mid_net_inflow", 0),
            small_net_inflow=summary.get("small_net_inflow", 0),
            main_net_5d=None,
        )


def _build_summary(
    *,
    main_net_inflow: float,
    main_net_inflow_pct: float,
    super_net_inflow: float,
    big_net_inflow: float,
    mid_net_inflow: float,
    small_net_inflow: float,
    main_net_5d: float | None,
) -> dict:
    """根据数值构建摘要 dict（复用逻辑）"""
    if main_net_inflow > 0:
        if main_net_inflow_pct > 10:
            status = "主力大幅流入"
        elif main_net_inflow_pct > 5:
            status = "主力明显流入"
        else:
            status = "主力小幅流入"
    elif main_net_inflow < 0:
        if main_net_inflow_pct < -10:
            status = "主力大幅流出"
        elif main_net_inflow_pct < -5:
            status = "主力明显流出"
        else:
            status = "主力小幅流出"
    else:
        status = "主力资金平衡"

    trend_5d = "无数据"
    if main_net_5d is not None:
        if main_net_5d > 0:
            trend_5d = f"5日净流入{main_net_5d / 1e8:.2f}亿"
        else:
            trend_5d = f"5日净流出{abs(main_net_5d) / 1e8:.2f}亿"

    return {
        "status": status,
        "main_net_inflow": main_net_inflow,
        "main_net_inflow_pct": main_net_inflow_pct,
        "super_net_inflow": super_net_inflow,
        "big_net_inflow": big_net_inflow,
        "mid_net_inflow": mid_net_inflow,
        "small_net_inflow": small_net_inflow,
        "trend_5d": trend_5d,
    }


def _safe_float(value) -> float | None:
    """安全转换为 float"""
    try:
        v = float(value)
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None
