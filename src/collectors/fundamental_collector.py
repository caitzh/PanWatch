"""基本面数据采集器

数据来源（按优先级）：
  1. SQLite 持久化缓存（7天有效，重启不丢失）
  2. AKShare stock_financial_abstract（快速概要，季报级别）
  3. 降级：返回 {"error": "..."}

缓存策略：
- 基本面为季报数据，7天内不变，直接复用缓存
- 进程内二级缓存（5分钟），避免同一次批量刷新重复查库
"""
import logging
import time
from datetime import datetime, timedelta
from typing import ClassVar

logger = logging.getLogger(__name__)

# 报告期月份 -> 季度标签
_QUARTER_MAP = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}

# 缓存有效期
_DB_TTL_DAYS = 7         # SQLite 缓存 7 天（季报数据不会频繁变化）
_MEM_TTL_SEC = 300       # 进程内二级缓存 5 分钟（同一批次复用）


def _date_to_period_label(date_str: str) -> str:
    """将 20250930 格式转换为 2025Q3"""
    if len(date_str) != 8:
        return date_str
    year = date_str[:4]
    month = date_str[4:6]
    quarter = _QUARTER_MAP.get(month, f"M{month}")
    return f"{year}{quarter}"


def _safe_float(value) -> float | None:
    """安全转换为 float，失败返回 None"""
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return v
    except (TypeError, ValueError):
        return None


def _yoy_growth(latest, prev_year) -> float | None:
    """计算同比增速（%）"""
    a = _safe_float(latest)
    b = _safe_float(prev_year)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100


def _get_db_session():
    """获取数据库 Session（延迟导入，避免循环依赖）"""
    from src.web.database import SessionLocal
    return SessionLocal()


def _read_db_cache(symbol: str) -> dict | None:
    """从 SQLite 读取未过期的基本面缓存"""
    try:
        from src.web.models import MarketDataCache
        db = _get_db_session()
        try:
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "fundamental",
                    MarketDataCache.expires_at > datetime.utcnow(),
                )
                .first()
            )
            if row:
                return row.data
        finally:
            db.close()
    except Exception as e:
        logger.debug("基本面缓存读取失败: %s", e)
    return None


def _write_db_cache(symbol: str, data: dict) -> None:
    """将基本面数据写入 SQLite 缓存"""
    try:
        from src.web.models import MarketDataCache
        db = _get_db_session()
        try:
            now = datetime.utcnow()
            expires = now + timedelta(days=_DB_TTL_DAYS)
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "fundamental",
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
                    data_type="fundamental",
                    data=data,
                    fetched_at=now,
                    expires_at=expires,
                )
                db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug("基本面缓存写入失败: %s", e)


class FundamentalCollector:
    """基本面数据采集器（双层缓存：进程内5分钟 + SQLite 7天）"""

    # 进程内二级缓存：symbol -> (timestamp, data_dict)
    _mem_cache: ClassVar[dict[str, tuple[float, dict]]] = {}

    def get_fundamental_summary(self, symbol: str) -> dict:
        """
        获取最新季报关键指标。

        缓存查找顺序：
          1. 进程内缓存（5分钟）
          2. SQLite 持久化缓存（7天）
          3. 实时采集（AKShare）

        返回格式：
        {
            "report_date": "20250930",
            "period_label": "2025Q3",
            "revenue": 5.12e9,
            "revenue_yoy": -45.7,
            "net_profit": -1.55e8,
            "net_profit_yoy": -33.2,
            "roe": -2.93,
            "gross_margin": 11.1,
            "debt_ratio": 69.7,
            "eps": -0.097,
            "cached": True,         # 是否来自缓存
        }

        失败时返回 {"error": "..."} 。
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

        # 3. 实时采集
        result = self._fetch_from_akshare(symbol)
        if not result.get("error"):
            # 采集成功，写入两层缓存
            self._mem_cache[symbol] = (now, result)
            _write_db_cache(symbol, result)
        else:
            # 采集失败，若有过期的旧缓存也将就用（比没有好）
            stale = _read_db_cache_stale(symbol)
            if stale and not stale.get("error"):
                stale["cached"] = True
                stale["stale"] = True
                logger.debug("基本面实时采集失败，使用过期缓存: %s", symbol)
                return stale

        return result

    @staticmethod
    def _fetch_from_akshare(symbol: str) -> dict:
        """从 AKShare 采集基本面数据"""
        try:
            import akshare as ak
            df = ak.stock_financial_abstract(symbol=symbol)
            return FundamentalCollector._parse_df(df)
        except Exception as e:
            # ETF/指数没有财报数据属正常情况，降为 DEBUG 级别
            logger.debug("FundamentalCollector %s 获取失败: %s", symbol, e)
            return {"error": str(e)}

    @staticmethod
    def _parse_df(df) -> dict:
        """从 DataFrame 中提取关键指标"""
        if df is None or not hasattr(df, "columns") or df.empty:
            return {"error": "无财务数据（可能是 ETF/指数）"}

        # 指标名称 -> 行索引的映射
        indicator_to_idx: dict[str, int] = {}
        for i, row in df.iterrows():
            name = str(row.get("指标", "")).strip()
            if name:
                indicator_to_idx[name] = i

        # 日期列：从第 3 列开始（索引 2），去掉前两列（选项/指标）
        date_cols = [c for c in df.columns if c not in ("选项", "指标")]
        if len(date_cols) < 5:
            return {"error": "数据列不足"}

        latest_col = date_cols[0]    # 最新季
        prev_year_col = date_cols[4] if len(date_cols) > 4 else None  # 去年同季

        def get_val(indicator: str, col: str) -> float | None:
            idx = indicator_to_idx.get(indicator)
            if idx is None:
                return None
            return _safe_float(df.at[idx, col])

        # 最新季数据
        revenue = get_val("营业总收入", latest_col)
        net_profit = get_val("归母净利润", latest_col)
        roe = get_val("净资产收益率(ROE)", latest_col)
        gross_margin = get_val("毛利率", latest_col)
        debt_ratio = get_val("资产负债率", latest_col)
        eps = get_val("基本每股收益", latest_col)

        # 同比增速
        revenue_yoy = None
        net_profit_yoy = None
        if prev_year_col:
            revenue_yoy = _yoy_growth(revenue, get_val("营业总收入", prev_year_col))
            net_profit_yoy = _yoy_growth(net_profit, get_val("归母净利润", prev_year_col))

        result: dict = {
            "report_date": latest_col,
            "period_label": _date_to_period_label(latest_col),
            "cached": False,
        }

        if revenue is not None:
            result["revenue"] = revenue
        if revenue_yoy is not None:
            result["revenue_yoy"] = round(revenue_yoy, 1)
        if net_profit is not None:
            result["net_profit"] = net_profit
        if net_profit_yoy is not None:
            result["net_profit_yoy"] = round(net_profit_yoy, 1)
        if roe is not None:
            result["roe"] = round(roe, 2)
        if gross_margin is not None:
            result["gross_margin"] = round(gross_margin, 1)
        if debt_ratio is not None:
            result["debt_ratio"] = round(debt_ratio, 1)
        if eps is not None:
            result["eps"] = eps

        return result


def _read_db_cache_stale(symbol: str) -> dict | None:
    """读取过期的缓存（作为最后兜底）"""
    try:
        from src.web.models import MarketDataCache
        db = _get_db_session()
        try:
            row = (
                db.query(MarketDataCache)
                .filter(
                    MarketDataCache.symbol == symbol,
                    MarketDataCache.data_type == "fundamental",
                )
                .order_by(MarketDataCache.fetched_at.desc())
                .first()
            )
            if row:
                return row.data
        finally:
            db.close()
    except Exception as e:
        logger.debug("基本面过期缓存读取失败: %s", e)
    return None
