import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  TrendingUp,
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
  Wallet,
  PiggyBank,
  Plus,
  ChevronRight,
  Activity,
  BarChart3,
  Sparkles,
  Newspaper,
  Sun,
  Moon,
} from 'lucide-react'
import { fetchAPI, useLocalStorage } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Onboarding } from '@/components/onboarding'
import { SuggestionBadge, type SuggestionInfo, type KlineSummary } from '@/components/suggestion-badge'
import { KlineSummaryDialog } from '@/components/kline-summary-dialog'

interface MarketIndex {
  symbol: string
  name: string
  market: string
  current_price: number | null
  change_pct: number | null
  change_amount: number | null
  prev_close: number | null
}

interface MarketStatus {
  code: string
  name: string
  status: string
  status_text: string
  is_trading: boolean
  sessions: string[]
  local_time: string
}

interface PortfolioSummary {
  accounts: AccountSummary[]
  total: {
    total_market_value: number
    total_cost: number
    total_pnl: number
    total_pnl_pct: number
    available_funds: number
    total_assets: number
  }
  exchange_rates?: {
    HKD_CNY: number
    USD_CNY?: number
  }
}

interface AccountSummary {
  id: number
  name: string
  available_funds: number
  total_cost: number
  total_market_value: number
  total_pnl: number
  total_pnl_pct: number
  total_assets: number
  positions: Position[]
}

interface Position {
  id: number
  stock_id: number
  symbol: string
  name: string
  market: string
  cost_price: number
  quantity: number
  invested_amount: number | null
  trading_style: string
  current_price: number | null
  change_pct: number | null
}

interface MonitorStock {
  symbol: string
  name: string
  market: string
  current_price: number
  change_pct: number
  open_price: number | null
  high_price: number | null
  low_price: number | null
  volume: number | null
  turnover: number | null
  alert_type: string | null
  has_position: boolean
  cost_price: number | null
  pnl_pct: number | null
  trading_style: string | null
  kline: KlineSummary | null
  suggestion: SuggestionInfo | null
}

interface Stock {
  id: number
  symbol: string
  name: string
  market: string
  enabled: boolean
}

interface QuoteRequestItem {
  symbol: string
  market: string
}

interface QuoteResponse {
  symbol: string
  market: string
  current_price: number | null
  change_pct: number | null
  open_price?: number | null
  high_price?: number | null
  low_price?: number | null
  volume?: number | null
  turnover?: number | null
}

type QuoteMap = Record<string, { current_price: number | null; change_pct: number | null }>

interface AnalysisRecord {
  id: number
  agent_name: string
  stock_symbol: string
  analysis_date: string
  title: string
  content: string
  created_at: string
}

const round2 = (value: number) => Math.round(value * 100) / 100

const mergePortfolioQuotes = (
  portfolio: PortfolioSummary | null,
  quotes: QuoteMap
): PortfolioSummary | null => {
  if (!portfolio) return null

  const hkdRate = portfolio.exchange_rates?.HKD_CNY ?? 0.92
  const usdRate = portfolio.exchange_rates?.USD_CNY ?? 7.25

  let grandMarketValue = 0
  let grandCost = 0
  let grandAvailable = 0

  const accounts = portfolio.accounts.map(account => {
    let accMarketValue = 0
    let accCost = 0

    for (const pos of account.positions) {
      const quote = quotes[`${pos.market}:${pos.symbol}`]
      const current_price = quote?.current_price ?? pos.current_price ?? null
      const rate = pos.market === 'HK' ? hkdRate : pos.market === 'US' ? usdRate : 1
      const cost = pos.cost_price * pos.quantity * rate
      accCost += cost

      if (current_price != null) {
        accMarketValue += current_price * pos.quantity * rate
      }
    }

    const accPnl = accMarketValue - accCost
    const accPnlPct = accCost > 0 ? (accPnl / accCost * 100) : 0
    const accTotalAssets = accMarketValue + account.available_funds

    grandMarketValue += accMarketValue
    grandCost += accCost
    grandAvailable += account.available_funds

    return {
      ...account,
      total_market_value: round2(accMarketValue),
      total_cost: round2(accCost),
      total_pnl: round2(accPnl),
      total_pnl_pct: round2(accPnlPct),
      total_assets: round2(accTotalAssets),
    }
  })

  const grandPnl = grandMarketValue - grandCost
  const grandPnlPct = grandCost > 0 ? (grandPnl / grandCost * 100) : 0
  const grandTotalAssets = grandMarketValue + grandAvailable

  return {
    ...portfolio,
    accounts,
    total: {
      total_market_value: round2(grandMarketValue),
      total_cost: round2(grandCost),
      total_pnl: round2(grandPnl),
      total_pnl_pct: round2(grandPnlPct),
      available_funds: round2(grandAvailable),
      total_assets: round2(grandTotalAssets),
    },
  }
}

export default function DashboardPage() {
  const navigate = useNavigate()

  // Market indices
  const [indices, setIndices] = useState<MarketIndex[]>([])
  const [indicesLoading, setIndicesLoading] = useState(true)

  // Market status
  const [marketStatus, setMarketStatus] = useState<MarketStatus[]>([])

  // Portfolio
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [portfolioRaw, setPortfolioRaw] = useState<PortfolioSummary | null>(null)
  const [portfolioLoading, setPortfolioLoading] = useState(false)
  const hasPortfolio = portfolio && portfolio.accounts.length > 0

  // Watchlist
  const [stocks, setStocks] = useState<Stock[]>([])
  // Keyed by `${market}:${symbol}` to avoid cross-market collisions
  const [quotes, setQuotes] = useState<QuoteMap>({})
  const [quotesLoading, setQuotesLoading] = useState(false)
  const hasWatchlist = stocks.filter(s => s.enabled).length > 0

  // Kline Dialog
  const [klineDialogOpen, setKlineDialogOpen] = useState(false)
  const [klineDialogSymbol, setKlineDialogSymbol] = useState('')
  const [klineDialogMarket, setKlineDialogMarket] = useState('CN')
  const [klineDialogName, setKlineDialogName] = useState<string | undefined>(undefined)
  const [klineDialogHasPosition, setKlineDialogHasPosition] = useState(false)
  const [klineDialogInitialSummary, setKlineDialogInitialSummary] = useState<KlineSummary | null>(null)

  // Monitor stocks
  const [monitorStocks, setMonitorStocks] = useState<MonitorStock[]>([])
  const [availableFunds, setAvailableFunds] = useState<number>(0)
  const [scanning, setScanning] = useState(false)
  const [enableAIAnalysis, setEnableAIAnalysis] = useState(true)

  // Auto-refresh (持久化到 localStorage)
  const [autoRefresh, setAutoRefresh] = useLocalStorage('panwatch_dashboard_autoRefresh', false)
  const [refreshInterval, setRefreshInterval] = useLocalStorage('panwatch_dashboard_refreshInterval', 30)
  const [lastRefreshTime, setLastRefreshTime] = useState<Date | null>(null)
  const refreshTimerRef = useRef<ReturnType<typeof setInterval>>()

  // Onboarding
  const [showOnboarding, setShowOnboarding] = useState(false)

  // AI Insights
  const [dailyReport, setDailyReport] = useState<AnalysisRecord | null>(null)
  const [premarketOutlook, setPremarketOutlook] = useState<AnalysisRecord | null>(null)
  const [newsDigest, setNewsDigest] = useState<AnalysisRecord | null>(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null)

  // Initial load
  useEffect(() => {
    loadIndices()
    loadMarketStatus()
    loadPortfolio()
    loadWatchlist()
    loadAIInsights()

    // Check if onboarding should be shown
    const onboardingCompleted = localStorage.getItem('panwatch_onboarding_completed')
    if (!onboardingCompleted) {
      setShowOnboarding(true)
    }
  }, [])

  // 自选股加载后只从建议池读取已有分析结果，不自动调用AI分析
  const initialScanDone = useRef(false)
  useEffect(() => {
    if (stocks.length > 0 && !initialScanDone.current) {
      initialScanDone.current = true
      loadMonitorFromPool() // 只从建议池加载已有数据，不调用AI分析
    } else if (stocks.length > 0 && initialScanDone.current) {
      // 当持仓数据变化时，重新加载监控数据以更新持仓状态
      loadMonitorFromPool()
    }
  }, [stocks, portfolioRaw])

  const loadIndices = async () => {
    setIndicesLoading(true)
    try {
      const data = await fetchAPI<MarketIndex[]>('/market/indices')
      setIndices(data)
    } catch (e) {
      console.error('获取指数失败:', e)
    } finally {
      setIndicesLoading(false)
    }
  }

  const loadMarketStatus = async () => {
    try {
      const data = await fetchAPI<MarketStatus[]>('/stocks/markets/status')
      setMarketStatus(data)
    } catch (e) {
      console.error('获取市场状态失败:', e)
    }
  }

  const loadPortfolio = async () => {
    setPortfolioLoading(true)
    try {
      const data = await fetchAPI<PortfolioSummary>('/portfolio/summary?include_quotes=false')
      setPortfolioRaw(data)
      setPortfolio(mergePortfolioQuotes(data, quotes))
    } catch (e) {
      console.error('获取持仓失败:', e)
    } finally {
      setPortfolioLoading(false)
    }
  }

  const loadWatchlist = async () => {
    try {
      const stocksData = await fetchAPI<Stock[]>('/stocks')
      setStocks(stocksData)
    } catch (e) {
      console.error('获取自选股失败:', e)
    }
  }

  const buildQuoteItems = useCallback((): QuoteRequestItem[] => {
    const items: QuoteRequestItem[] = []
    const seen = new Set<string>()

    for (const stock of stocks) {
      if (!stock.enabled) continue
      const key = `${stock.market}:${stock.symbol}`
      if (seen.has(key)) continue
      seen.add(key)
      items.push({ symbol: stock.symbol, market: stock.market })
    }

    for (const account of portfolioRaw?.accounts || []) {
      for (const pos of account.positions) {
        const key = `${pos.market}:${pos.symbol}`
        if (seen.has(key)) continue
        seen.add(key)
        items.push({ symbol: pos.symbol, market: pos.market })
      }
    }

    return items
  }, [stocks, portfolioRaw])

  const refreshQuotes = useCallback(async () => {
    const items = buildQuoteItems()
    if (items.length === 0) return

    setQuotesLoading(true)
    try {
      const data = await fetchAPI<QuoteResponse[]>('/quotes/batch', {
        method: 'POST',
        body: JSON.stringify({ items }),
      })
      const map: QuoteMap = {}
      for (const item of data) {
        map[`${item.market}:${item.symbol}`] = {
          current_price: item.current_price ?? null,
          change_pct: item.change_pct ?? null,
        }
      }
      setQuotes(map)
      setLastRefreshTime(new Date())
    } catch (e) {
      console.warn('刷新行情失败:', e)
    } finally {
      setQuotesLoading(false)
    }
  }, [buildQuoteItems])

  const openKlineDialog = useCallback((symbol: string, market: string, name?: string, hasPosition?: boolean, initialSummary?: KlineSummary | null) => {
    setKlineDialogSymbol(symbol)
    setKlineDialogMarket(market || 'CN')
    setKlineDialogName(name)
    setKlineDialogHasPosition(!!hasPosition)
    setKlineDialogInitialSummary(initialSummary || null)
    setKlineDialogOpen(true)
  }, [])

  useEffect(() => {
    if (!portfolioRaw) return
    setPortfolio(mergePortfolioQuotes(portfolioRaw, quotes))
  }, [portfolioRaw, quotes])

  useEffect(() => {
    if (stocks.length === 0 && (!portfolioRaw || portfolioRaw.accounts.length === 0)) return
    refreshQuotes()
  }, [stocks, portfolioRaw, refreshQuotes])

  // Auto-refresh timer
  useEffect(() => {
    if (autoRefresh) {
      refreshQuotes()
      refreshTimerRef.current = setInterval(() => {
        refreshQuotes()
      }, refreshInterval * 1000)
    } else {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current)
        refreshTimerRef.current = undefined
      }
    }

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current)
      }
    }
  }, [autoRefresh, refreshInterval, refreshQuotes])

  const loadAIInsights = async () => {
    setInsightsLoading(true)
    try {
      const [dailyData, premarketData, newsData] = await Promise.all([
        fetchAPI<AnalysisRecord[]>('/history?agent_name=daily_report&limit=1'),
        fetchAPI<AnalysisRecord[]>('/history?agent_name=premarket_outlook&limit=1'),
        fetchAPI<AnalysisRecord[]>('/history?agent_name=news_digest&limit=1'),
      ])
      setDailyReport(dailyData.length > 0 ? dailyData[0] : null)
      setPremarketOutlook(premarketData.length > 0 ? premarketData[0] : null)
      setNewsDigest(newsData.length > 0 ? newsData[0] : null)
    } catch (e) {
      console.error('获取 AI 洞察失败:', e)
    } finally {
      setInsightsLoading(false)
    }
  }

  // 从建议池加载监控数据（快速显示）
  const loadMonitorFromPool = useCallback(async () => {
    const watchlistStocks = stocks.filter(s => s.enabled)
    if (watchlistStocks.length === 0) return

    setScanning(true)
    try {

      // 并发获取：建议、行情、K线数据
      const symbols = watchlistStocks.map(s => s.symbol).join(',')
      
      const [suggestionsDict, quotesRes, klineResults] = await Promise.all([
        // 获取所有最新建议（返回格式: {symbol: suggestion}）
        fetchAPI<Record<string, any>>(`/suggestions?symbols=${encodeURIComponent(symbols)}`),
        
        // 获取实时行情
        fetchAPI<QuoteResponse[]>('/quotes/batch', {
          method: 'POST',
          body: JSON.stringify({ items: watchlistStocks.map(s => ({ symbol: s.symbol, market: s.market })) }),
        }),
        
        // 并发获取K线数据
        Promise.allSettled(
          watchlistStocks.map(stock =>
            fetchAPI<{ symbol: string; market: string; summary: KlineSummary }>(
              `/klines/${encodeURIComponent(stock.symbol)}/summary?market=${encodeURIComponent(stock.market)}`
            ).catch(() => null)
          )
        )
      ])

      const quotesMap: Record<string, QuoteResponse> = {}
      for (const q of quotesRes || []) {
        quotesMap[`${q.market}:${q.symbol}`] = q
      }

      // 构建K线数据映射
      const klineMap: Record<string, KlineSummary> = {}
      klineResults.forEach((result, idx) => {
        if (result.status === 'fulfilled' && result.value) {
          const stock = watchlistStocks[idx]
          const key = `${stock.market}:${stock.symbol}`
          klineMap[key] = result.value.summary
        }
      })

      // 构建持仓映射
      const positionMap: Record<string, boolean> = {}
      for (const account of portfolioRaw?.accounts || []) {
        for (const pos of account.positions || []) {
          positionMap[pos.symbol] = true
        }
      }
      
      console.log('[Dashboard] positionMap:', positionMap)

      // suggestionsDict 是 {symbol: suggestion} 格式
      const stockSuggestions: Record<string, any> = suggestionsDict || {}

      const monitorData: MonitorStock[] = watchlistStocks.map(stock => {
        const quote = quotesMap[`${stock.market}:${stock.symbol}`]
        const sug = stockSuggestions[stock.symbol]
        const kline = klineMap[`${stock.market}:${stock.symbol}`] || null
        const change_pct = quote?.change_pct || 0
        const hasPosition = positionMap[stock.symbol] || false
        
        if (stock.symbol === '601127' || stock.symbol === '000158') {
          console.log(`[Dashboard] ${stock.symbol} hasPosition:`, hasPosition, 'kline:', !!kline)
        }

        return {
          symbol: stock.symbol,
          name: stock.name,
          market: stock.market,
          current_price: quote?.current_price || 0,
          change_pct: change_pct,
          open_price: quote?.open_price || null,
          high_price: quote?.high_price || null,
          low_price: quote?.low_price || null,
          volume: quote?.volume || null,
          turnover: quote?.turnover || null,
          alert_type: Math.abs(change_pct) >= 3 ? (change_pct > 0 ? '急涨' : '急跌') : null,
          has_position: hasPosition,
          cost_price: null,
          pnl_pct: null,
          trading_style: null,
          kline: kline,
          suggestion: sug ? {
            action: sug.action,
            action_label: sug.action_label,
            signal: sug.signal,
            reason: sug.reason,
            should_alert: sug.should_alert,
            agent_name: sug.agent_name,
            agent_label: sug.agent_label,
            created_at: sug.created_at,
            is_expired: sug.is_expired,
          } : null,
        }
      })

      setMonitorStocks(monitorData)
    } catch (e) {
      console.error('从建议池加载失败:', e)
    } finally {
      setScanning(false)
    }
  }, [stocks, portfolioRaw])

  const scanAlerts = useCallback(async () => {
    if (!hasWatchlist) return

    setScanning(true)
    try {
      const url = enableAIAnalysis ? '/agents/intraday/scan?analyze=true' : '/agents/intraday/scan'
      const result = await fetchAPI<{ stocks: MonitorStock[]; available_funds: number }>(url, { method: 'POST' })
      setMonitorStocks(result.stocks || [])
      setAvailableFunds(result.available_funds || 0)
      setLastRefreshTime(new Date())
    } catch (e) {
      console.error('扫描失败:', e)
    } finally {
      setScanning(false)
    }
  }, [hasWatchlist, enableAIAnalysis])

  const handleRefresh = useCallback(async () => {
    await refreshQuotes()
  }, [refreshQuotes])

  const formatMoney = (value: number) => {
    if (Math.abs(value) >= 10000) {
      return `${(value / 10000).toFixed(2)}万`
    }
    return value.toFixed(2)
  }

  const formatIndexPrice = (value: number | null) => {
    if (value === null) return '--'
    if (value >= 10000) {
      return value.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    }
    return value.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  }

  const marketBadge = (m: string) => {
    if (m === 'HK') return { style: 'bg-orange-500/10 text-orange-600', label: '港' }
    if (m === 'US') return { style: 'bg-green-500/10 text-green-600', label: '美' }
    return { style: 'bg-blue-500/10 text-blue-600', label: 'A' }
  }

  const handleOnboardingComplete = () => {
    localStorage.setItem('panwatch_onboarding_completed', 'true')
    setShowOnboarding(false)
    // Reload data in case sample stocks were added
    loadWatchlist()
  }

  const portfolioDayPnl = useMemo(() => {
    if (!portfolioRaw) return null
    const hkdRate = portfolioRaw.exchange_rates?.HKD_CNY ?? 0.92
    const usdRate = portfolioRaw.exchange_rates?.USD_CNY ?? 7.25

    let dayPnl = 0
    let prevMv = 0
    let posCount = 0

    for (const acc of portfolioRaw.accounts || []) {
      for (const p of acc.positions || []) {
        const q = quotes[`${p.market}:${p.symbol}`]
        if (!q || q.current_price == null || q.change_pct == null) continue
        const prev = q.change_pct === -100 ? null : (q.current_price / (1 + q.change_pct / 100))
        if (prev == null || !isFinite(prev)) continue
        const fx = p.market === 'HK' ? hkdRate : p.market === 'US' ? usdRate : 1
        const qty = p.quantity || 0
        posCount += 1
        dayPnl += (q.current_price - prev) * qty * fx
        prevMv += prev * qty * fx
      }
    }

    return {
      day_pnl: dayPnl,
      day_pnl_pct: prevMv > 0 ? (dayPnl / prevMv * 100) : 0,
      has_data: posCount > 0,
    }
  }, [portfolioRaw, quotes])

  const dayMovers = useMemo(() => {
    if (!portfolioRaw) return { worst: null as null | { market: string; symbol: string; name: string; day_pnl: number; day_pct: number }, best: null as null | { market: string; symbol: string; name: string; day_pnl: number; day_pct: number } }
    const hkdRate = portfolioRaw.exchange_rates?.HKD_CNY ?? 0.92
    const usdRate = portfolioRaw.exchange_rates?.USD_CNY ?? 7.25

    const rows: Array<{ market: string; symbol: string; name: string; day_pnl: number; day_pct: number }> = []
    for (const acc of portfolioRaw.accounts || []) {
      for (const p of acc.positions || []) {
        const q = quotes[`${p.market}:${p.symbol}`]
        if (!q || q.current_price == null || q.change_pct == null) continue
        const prev = q.change_pct === -100 ? null : (q.current_price / (1 + q.change_pct / 100))
        if (prev == null || !isFinite(prev)) continue
        const fx = p.market === 'HK' ? hkdRate : p.market === 'US' ? usdRate : 1
        const qty = p.quantity || 0
        const pnl = (q.current_price - prev) * qty * fx
        const prevMv = prev * qty * fx
        const pct = prevMv > 0 ? (pnl / prevMv * 100) : 0
        rows.push({ market: p.market, symbol: p.symbol, name: p.name, day_pnl: pnl, day_pct: pct })
      }
    }

    if (rows.length === 0) return { worst: null, best: null }
    const worst = rows.slice().sort((a, b) => a.day_pnl - b.day_pnl)[0]
    const best = rows.slice().sort((a, b) => b.day_pnl - a.day_pnl)[0]
    return { worst, best }
  }, [portfolioRaw, quotes])

  return (
    <div>
      {/* Onboarding */}
      <Onboarding
        open={showOnboarding}
        onComplete={handleOnboardingComplete}
        hasStocks={hasWatchlist}
      />

      <KlineSummaryDialog
        open={klineDialogOpen}
        onOpenChange={setKlineDialogOpen}
        symbol={klineDialogSymbol}
        market={klineDialogMarket}
        stockName={klineDialogName}
        hasPosition={klineDialogHasPosition}
        initialSummary={klineDialogInitialSummary as any}
      />

      {/* Risk dialog removed (was too noisy when empty) */}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-[20px] md:text-[22px] font-bold text-foreground tracking-tight">Dashboard</h1>
          <div className="flex items-center gap-2 md:gap-3 mt-1.5 flex-wrap">
            {marketStatus.map(m => {
              const statusColors: Record<string, string> = {
                trading: 'bg-emerald-500',
                pre_market: 'bg-amber-500',
                break: 'bg-amber-500',
                after_hours: 'bg-slate-400',
                closed: 'bg-slate-400',
              }
              return (
                <div
                  key={m.code}
                  className="flex items-center gap-1"
                  title={`${m.sessions.join(', ')} (${m.local_time})`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${statusColors[m.status] || 'bg-slate-400'}`} />
                  <span className="text-[11px] md:text-[12px] text-muted-foreground">{m.name}</span>
                  <span className={`text-[10px] md:text-[11px] ${m.is_trading ? 'text-emerald-600' : 'text-muted-foreground/60'}`}>
                    {m.status_text}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Auto Refresh & AI Analysis Controls */}
          <div className="flex items-center gap-2 md:gap-3 px-2 md:px-3 py-1.5 rounded-lg bg-accent/30">
            <div className="flex items-center gap-1 md:gap-1.5">
              <Switch
                checked={autoRefresh}
                onCheckedChange={setAutoRefresh}
                className="scale-90"
              />
              <span className="text-[11px] md:text-[12px] text-muted-foreground hidden sm:inline">自动刷新</span>
              {autoRefresh && (
                <Select value={refreshInterval.toString()} onValueChange={v => setRefreshInterval(parseInt(v))}>
                  <SelectTrigger className="h-6 w-14 md:w-16 text-[10px] md:text-[11px] px-1.5 md:px-2">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10s</SelectItem>
                    <SelectItem value="30">30s</SelectItem>
                    <SelectItem value="60">1分钟</SelectItem>
                    <SelectItem value="120">2分钟</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="w-px h-4 bg-border hidden sm:block" />
            <div className="flex items-center gap-1 md:gap-1.5">
              <Switch
                checked={enableAIAnalysis}
                onCheckedChange={setEnableAIAnalysis}
                className="scale-90"
              />
              <span className="text-[11px] md:text-[12px] text-muted-foreground hidden sm:inline">AI 建议</span>
            </div>
            {lastRefreshTime && (
              <span className="text-[9px] md:text-[10px] text-muted-foreground/60 hidden md:inline">
                {lastRefreshTime.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={handleRefresh} disabled={quotesLoading || portfolioLoading} className="h-8 md:h-9 px-2.5 md:px-3">
            <RefreshCw className={`w-4 h-4 ${quotesLoading || portfolioLoading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">刷新</span>
          </Button>
        </div>
      </div>

      {/* Portfolio Summary Cards */}
      {hasPortfolio && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
          <div className="card p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <PiggyBank className="w-4 h-4" />
              <span className="text-[12px]">总资产</span>
            </div>
            <div className="text-[20px] font-bold text-foreground font-mono">
              {formatMoney(portfolio!.total.total_assets)}
            </div>
          </div>

          <div className="card p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              {portfolio!.total.total_pnl >= 0 ? (
                <ArrowUpRight className="w-4 h-4 text-rose-500" />
              ) : (
                <ArrowDownRight className="w-4 h-4 text-emerald-500" />
              )}
              <span className="text-[12px]">总盈亏</span>
            </div>
            <div className={`text-[20px] font-bold font-mono ${portfolio!.total.total_pnl >= 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
              {portfolio!.total.total_pnl >= 0 ? '+' : ''}{formatMoney(portfolio!.total.total_pnl)}
              <span className="text-[13px] ml-1.5">
                ({portfolio!.total.total_pnl_pct >= 0 ? '+' : ''}{portfolio!.total.total_pnl_pct.toFixed(2)}%)
              </span>
            </div>
          </div>

          <div className="card p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <TrendingUp className="w-4 h-4" />
              <span className="text-[12px]">持仓市值</span>
            </div>
            <div className="text-[20px] font-bold text-foreground font-mono">
              {formatMoney(portfolio!.total.total_market_value)}
            </div>
          </div>

          <div className="card p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Wallet className="w-4 h-4" />
              <span className="text-[12px]">可用资金</span>
            </div>
            <div className="text-[20px] font-bold text-foreground font-mono">
              {formatMoney(portfolio!.total.available_funds)}
            </div>
          </div>

          <div className="card p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              {(portfolioDayPnl?.day_pnl ?? 0) >= 0 ? (
                <ArrowUpRight className="w-4 h-4 text-rose-500" />
              ) : (
                <ArrowDownRight className="w-4 h-4 text-emerald-500" />
              )}
              <span className="text-[12px]">今日盈亏</span>
            </div>
            <div className={`text-[20px] font-bold font-mono ${(portfolioDayPnl?.day_pnl ?? 0) >= 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
              {(portfolioDayPnl?.day_pnl ?? 0) >= 0 ? '+' : ''}{formatMoney(portfolioDayPnl?.day_pnl ?? 0)}
              <span className="text-[13px] ml-1.5">({(portfolioDayPnl?.day_pnl_pct ?? 0) >= 0 ? '+' : ''}{(portfolioDayPnl?.day_pnl_pct ?? 0).toFixed(2)}%)</span>
            </div>
            {!portfolioDayPnl?.has_data && (
              <div className="mt-1 text-[11px] text-muted-foreground">等待行情数据</div>
            )}
          </div>

          <button
            type="button"
            className="card p-4 text-left hover:bg-accent/10 transition-colors"
            onClick={() => {
              if (dayMovers.worst) navigate(`/stock/${encodeURIComponent(dayMovers.worst.market)}/${encodeURIComponent(dayMovers.worst.symbol)}`)
            }}
          >
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Activity className="w-4 h-4" />
              <span className="text-[12px]">今日最大拖累</span>
            </div>
            {dayMovers.worst ? (
              <>
                <div className="text-[14px] font-medium text-foreground truncate">{dayMovers.worst.name}</div>
                <div className={`mt-1 text-[16px] font-bold font-mono ${dayMovers.worst.day_pnl >= 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                  {dayMovers.worst.day_pnl >= 0 ? '+' : ''}{formatMoney(dayMovers.worst.day_pnl)}
                  <span className="text-[12px] ml-1.5">({dayMovers.worst.day_pct >= 0 ? '+' : ''}{dayMovers.worst.day_pct.toFixed(2)}%)</span>
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">点击查看详情</div>
              </>
            ) : (
              <div className="text-[12px] text-muted-foreground">等待行情数据</div>
            )}
          </button>
        </div>
      )}

      {/* Market Indices */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-semibold text-foreground flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-primary" />
            大盘指数
          </h2>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {indicesLoading ? (
            Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="card p-3 animate-pulse">
                <div className="h-4 bg-accent/50 rounded w-16 mb-2" />
                <div className="h-6 bg-accent/50 rounded w-20 mb-1" />
                <div className="h-3 bg-accent/30 rounded w-12" />
              </div>
            ))
          ) : (
            indices.map(idx => {
              const isUp = idx.change_pct !== null && idx.change_pct > 0
              const isDown = idx.change_pct !== null && idx.change_pct < 0
              const changeColor = isUp ? 'text-rose-500' : isDown ? 'text-emerald-500' : 'text-muted-foreground'
              const bgColor = isUp ? 'bg-rose-500/5' : isDown ? 'bg-emerald-500/5' : 'bg-accent/30'

              return (
                <div key={idx.symbol} className={`card p-3 ${bgColor} border-0`}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`text-[9px] px-1 py-0.5 rounded ${marketBadge(idx.market).style}`}>
                      {marketBadge(idx.market).label}
                    </span>
                    <span className="text-[12px] text-muted-foreground">{idx.name}</span>
                  </div>
                  <div className={`text-[18px] font-bold font-mono ${changeColor}`}>
                    {formatIndexPrice(idx.current_price)}
                  </div>
                  <div className={`text-[12px] font-mono ${changeColor}`}>
                    {idx.change_pct !== null ? (
                      <>
                        {isUp ? '+' : ''}{idx.change_pct.toFixed(2)}%
                        <span className="ml-1.5 opacity-60">
                          {isUp ? '+' : ''}{idx.change_amount?.toFixed(2)}
                        </span>
                      </>
                    ) : (
                      '--'
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Intraday Monitor */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-semibold text-foreground flex items-center gap-2">
            <Activity className="w-4 h-4 text-primary" />
            盘中监控
            {monitorStocks.length > 0 && (
              <Badge variant="secondary" className="text-[10px]">{monitorStocks.length} 只</Badge>
            )}
            {availableFunds > 0 && (
              <span className="text-[11px] text-muted-foreground ml-2">
                可用: ¥{formatMoney(availableFunds)}
              </span>
            )}
          </h2>
          {hasWatchlist && (
            <Button variant="ghost" size="sm" onClick={scanAlerts} disabled={scanning} className="h-7 text-[12px]">
              {scanning ? (
                <span className="w-3 h-3 border-2 border-current/30 border-t-current rounded-full animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              刷新
            </Button>
          )}
        </div>

        {!hasWatchlist ? (
          <div className="card p-6 text-center">
            <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-3">
              <Activity className="w-5 h-5 text-primary" />
            </div>
            <p className="text-[14px] font-medium text-foreground mb-1">启用盘中监控</p>
            <p className="text-[12px] text-muted-foreground mb-4">为股票启用「盘中监测」Agent 后可查看实时分析</p>
            <Button size="sm" onClick={() => navigate('/portfolio')}>
              <Plus className="w-4 h-4" /> 添加自选股
            </Button>
          </div>
        ) : monitorStocks.length === 0 ? (
          <div className="card p-6 text-center">
            <p className="text-[13px] text-muted-foreground">点击刷新获取监控数据</p>
          </div>
        ) : (
          <div className="space-y-3">
            {monitorStocks.map(stock => {
              const styleLabels: Record<string, string> = { short: '短线', swing: '波段', long: '长线' }
              const changeColor = stock.change_pct > 0 ? 'text-rose-500' : stock.change_pct < 0 ? 'text-emerald-500' : 'text-muted-foreground'
              const suggestion = stock.suggestion

              return (
                <div key={stock.symbol} className="card p-4">
                  {/* Header */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[13px] font-semibold text-foreground">{stock.symbol}</span>
                      <span className="text-[12px] text-muted-foreground">{stock.name}</span>
                      {!(suggestion || stock.kline) && (
                        <button
                          onClick={() => openKlineDialog(stock.symbol, stock.market, stock.name, stock.has_position)}
                          className="p-1 rounded hover:bg-accent/50 transition-colors"
                          title="K线指标"
                        >
                          <BarChart3 className="w-4 h-4 text-muted-foreground" />
                        </button>
                      )}
                      {stock.alert_type && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          stock.alert_type === '急涨' ? 'bg-rose-500/10 text-rose-500' : 'bg-emerald-500/10 text-emerald-500'
                        }`}>
                          {stock.alert_type}
                        </span>
                      )}
                      {stock.has_position && stock.trading_style && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                          {styleLabels[stock.trading_style] || '波段'}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <div className={`font-mono text-[14px] font-medium ${changeColor}`}>
                          {stock.current_price?.toFixed(2) || '--'}
                        </div>
                        <div className={`font-mono text-[11px] ${changeColor}`}>
                          {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct?.toFixed(2) || '0.00'}%
                        </div>
                      </div>
                      {stock.has_position && stock.pnl_pct != null && (
                        <div className="text-right min-w-[60px]">
                          <div className="text-[10px] text-muted-foreground">盈亏</div>
                          <div className={`font-mono text-[13px] font-medium ${stock.pnl_pct >= 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                            {stock.pnl_pct >= 0 ? '+' : ''}{stock.pnl_pct.toFixed(2)}%
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Technical Info */}
                  {stock.kline && (
                    <div className="flex flex-wrap gap-2 mb-3 text-[11px]">
                      <span className="px-2 py-0.5 rounded bg-accent/50 text-muted-foreground">
                        {stock.kline.trend}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-accent/50 text-muted-foreground">
                        {stock.kline.macd_status}
                      </span>
                      {stock.kline.support && (
                        <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600">
                          支撑 {stock.kline.support.toFixed(2)}
                        </span>
                      )}
                      {stock.kline.resistance && (
                        <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-600">
                          压力 {stock.kline.resistance.toFixed(2)}
                        </span>
                      )}
                    </div>
                  )}

                  {/* AI Suggestion */}
                  {suggestion ? (
                    <SuggestionBadge
                      suggestion={suggestion}
                      stockName={stock.name}
                      stockSymbol={stock.symbol}
                      kline={stock.kline}
                      showFullInline={true}
                      hasPosition={stock.has_position}
                    />
                  ) : enableAIAnalysis ? (
                    <div className="pt-3 border-t border-border/30">
                      <p className="text-[11px] text-muted-foreground/60">AI 分析中...</p>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* AI Insights */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-semibold text-foreground flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-primary" />
            AI 洞察
          </h2>
          {(dailyReport || premarketOutlook || newsDigest) && (
            <button
              onClick={() => navigate('/history')}
              className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-primary transition-colors"
            >
              查看更多 <ChevronRight className="w-4 h-4" />
            </button>
          )}
        </div>

        {insightsLoading ? (
          <div className="card p-4 animate-pulse">
            <div className="h-4 bg-accent/50 rounded w-32 mb-3" />
            <div className="h-3 bg-accent/30 rounded w-full mb-2" />
            <div className="h-3 bg-accent/30 rounded w-3/4" />
          </div>
        ) : !dailyReport && !premarketOutlook && !newsDigest ? (
          <div className="card p-6 text-center">
            <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-3">
              <Sparkles className="w-5 h-5 text-primary" />
            </div>
            <p className="text-[14px] font-medium text-foreground mb-1">暂无 AI 分析</p>
            <p className="text-[12px] text-muted-foreground mb-4">配置 AI 服务后，启用盘后日报或盘前分析 Agent</p>
            <Button variant="secondary" size="sm" onClick={() => navigate('/agents')}>
              配置 Agent
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 盘后日报 */}
            {dailyReport && (
              <div
                className="card p-4 cursor-pointer hover:bg-accent/30 transition-colors"
                onClick={() => setExpandedInsight(expandedInsight === 'daily' ? null : 'daily')}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-orange-500/10 flex items-center justify-center">
                    <Moon className="w-4 h-4 text-orange-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-foreground">盘后日报</span>
                      <span className="text-[11px] text-muted-foreground">{dailyReport.analysis_date}</span>
                    </div>
                    {dailyReport.title && (
                      <p className="text-[12px] text-muted-foreground truncate">{dailyReport.title}</p>
                    )}
                  </div>
                  <ChevronRight className={`w-4 h-4 text-muted-foreground transition-transform ${expandedInsight === 'daily' ? 'rotate-90' : ''}`} />
                </div>
                {expandedInsight === 'daily' && (
                  <div className="mt-3 pt-3 border-t border-border/30">
                    <div className="prose prose-sm dark:prose-invert max-w-none max-h-[300px] overflow-y-auto text-[12px]">
                      <ReactMarkdown>{dailyReport.content}</ReactMarkdown>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate('/history') }}
                      className="mt-3 text-[11px] text-primary hover:underline"
                    >
                      查看历史记录
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 盘前分析 */}
            {premarketOutlook && (
              <div
                className="card p-4 cursor-pointer hover:bg-accent/30 transition-colors"
                onClick={() => setExpandedInsight(expandedInsight === 'premarket' ? null : 'premarket')}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
                    <Sun className="w-4 h-4 text-amber-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-foreground">盘前分析</span>
                      <span className="text-[11px] text-muted-foreground">{premarketOutlook.analysis_date}</span>
                    </div>
                    {premarketOutlook.title && (
                      <p className="text-[12px] text-muted-foreground truncate">{premarketOutlook.title}</p>
                    )}
                  </div>
                  <ChevronRight className={`w-4 h-4 text-muted-foreground transition-transform ${expandedInsight === 'premarket' ? 'rotate-90' : ''}`} />
                </div>
                {expandedInsight === 'premarket' && (
                  <div className="mt-3 pt-3 border-t border-border/30">
                    <div className="prose prose-sm dark:prose-invert max-w-none max-h-[300px] overflow-y-auto text-[12px]">
                      <ReactMarkdown>{premarketOutlook.content}</ReactMarkdown>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate('/history') }}
                      className="mt-3 text-[11px] text-primary hover:underline"
                    >
                      查看历史记录
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 新闻速递 */}
            {newsDigest && (
              <div
                className="card p-4 cursor-pointer hover:bg-accent/30 transition-colors"
                onClick={() => setExpandedInsight(expandedInsight === 'news' ? null : 'news')}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <Newspaper className="w-4 h-4 text-blue-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-foreground">新闻速递</span>
                      <span className="text-[11px] text-muted-foreground">{newsDigest.analysis_date}</span>
                    </div>
                    {newsDigest.title && (
                      <p className="text-[12px] text-muted-foreground truncate">{newsDigest.title}</p>
                    )}
                  </div>
                  <ChevronRight className={`w-4 h-4 text-muted-foreground transition-transform ${expandedInsight === 'news' ? 'rotate-90' : ''}`} />
                </div>
                {expandedInsight === 'news' && (
                  <div className="mt-3 pt-3 border-t border-border/30">
                    <div className="prose prose-sm dark:prose-invert max-w-none max-h-[300px] overflow-y-auto text-[12px]">
                      <ReactMarkdown>{newsDigest.content}</ReactMarkdown>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate('/history') }}
                      className="mt-3 text-[11px] text-primary hover:underline"
                    >
                      查看历史记录
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Watchlist Quick View */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-semibold text-foreground flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-primary" />
            自选股快览
          </h2>
          {hasWatchlist && (
            <button
              onClick={() => navigate('/portfolio')}
              className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-primary transition-colors"
            >
              查看全部 <ChevronRight className="w-4 h-4" />
            </button>
          )}
        </div>

        {!hasWatchlist ? (
          <div className="card p-6 md:p-8 text-center">
            <div className="w-12 md:w-14 h-12 md:h-14 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-3 md:mb-4">
              <TrendingUp className="w-5 md:w-6 h-5 md:h-6 text-primary" />
            </div>
            <p className="text-[15px] font-medium text-foreground mb-1">还没有添加自选股</p>
            <p className="text-[13px] text-muted-foreground mb-4">添加股票后，这里会显示实时行情和异动提醒</p>
            <div className="flex items-center justify-center gap-3">
              <Button onClick={() => navigate('/portfolio')}>
                <Plus className="w-4 h-4" /> 添加第一只股票
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {stocks.filter(s => s.enabled).slice(0, 12).map(stock => {
              const quote = quotes[`${stock.market}:${stock.symbol}`]
              const isUp = quote?.change_pct != null && quote.change_pct > 0
              const isDown = quote?.change_pct != null && quote.change_pct < 0
              const changeColor = isUp ? 'text-rose-500' : isDown ? 'text-emerald-500' : 'text-muted-foreground'
              const bgColor = isUp ? 'bg-rose-500/5' : isDown ? 'bg-emerald-500/5' : 'bg-accent/30'

              return (
                <div
                  key={stock.id}
                  className={`card p-3 ${bgColor} border-0 cursor-pointer hover:opacity-80 transition-opacity`}
                  onClick={() => navigate('/portfolio')}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`text-[9px] px-1 py-0.5 rounded ${marketBadge(stock.market).style}`}>
                      {marketBadge(stock.market).label}
                    </span>
                    <span className="text-[11px] text-muted-foreground truncate">{stock.name}</span>
                  </div>
                  <div className={`text-[16px] font-bold font-mono ${changeColor}`}>
                    {quote?.current_price?.toFixed(2) || '--'}
                  </div>
                  <div className={`text-[11px] font-mono ${changeColor}`}>
                    {quote?.change_pct != null ? (
                      `${isUp ? '+' : ''}${quote.change_pct.toFixed(2)}%`
                    ) : (
                      '--'
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Empty Portfolio Hint */}
      {!hasPortfolio && hasWatchlist && (
        <div className="card p-6 text-center border-dashed">
          <div className="w-12 h-12 rounded-2xl bg-blue-500/10 flex items-center justify-center mx-auto mb-3">
            <Wallet className="w-5 h-5 text-blue-500" />
          </div>
          <p className="text-[14px] font-medium text-foreground mb-1">添加持仓查看盈亏</p>
          <p className="text-[12px] text-muted-foreground mb-4">记录你的持仓成本，系统会自动计算盈亏情况</p>
          <Button variant="secondary" size="sm" onClick={() => navigate('/portfolio')}>
            管理持仓
          </Button>
        </div>
      )}
    </div>
  )
}
