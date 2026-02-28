import type { KlineSummaryData } from '@panwatch/biz-ui/components/kline-summary-dialog'

export type Action = 'buy' | 'add' | 'reduce' | 'sell' | 'hold' | 'watch' | 'avoid'

export interface KlineEvidenceItem {
  text: string
  details?: string
  delta: number
  tag?: string
}

export interface KlineScoreSuggestion {
  action: Action
  action_label: string
  signal: string
  score: number
  evidence: KlineEvidenceItem[]
  tags: string[]
  /** 反向信号警告（多空矛盾或特殊提示） */
  warnings?: string[]
}

export function buildKlineSuggestion(s: KlineSummaryData, holding?: boolean): KlineScoreSuggestion {
  let score = 0
  const items: KlineEvidenceItem[] = []
  const tags: string[] = []
  const warnings: string[] = []

  const fmt = (n?: number | null, digits: number = 2): string => {
    if (n == null || Number.isNaN(n)) return '--'
    return Number(n).toFixed(digits)
  }

  const tf = s.timeframe || '1d'
  const asof = s.asof ? `截至${s.asof}` : ''

  const addItem = (text: string, delta: number = 0, tag?: string, details?: string) => {
    items.push({ text, delta, tag, details })
    score += delta
    if (tag) tags.push(tag)
  }

  // ── 1. 均线趋势：加入强度系数 ─────────────────────────────────────────
  // 在多头/空头基础上，根据 MA5 偏离 MA10 的百分比判断强度
  if (s.trend?.includes('多头')) {
    let delta = 2
    let strengthLabel = ''
    if (s.ma5 != null && s.ma10 != null && s.ma10 > 0) {
      const gap = (s.ma5 - s.ma10) / s.ma10 * 100
      if (gap >= 2) {
        delta = 3         // 极强多头：MA5 高于 MA10 超过 2%
        strengthLabel = '（强势）'
        tags.push('强势多头')
      } else if (gap < 0.3) {
        delta = 1         // 弱多头：MA5 仅略高于 MA10
        strengthLabel = '（弱势）'
      }
    }
    addItem(
      `均线多头排列${strengthLabel}，趋势偏强`,
      delta,
      delta >= 3 ? '强势多头' : '多头',
      `周期${tf} ${asof} · MA5/10/20: ${fmt(s.ma5)}/${fmt(s.ma10)}/${fmt(s.ma20)}`
    )
  } else if (s.trend?.includes('空头')) {
    let delta = -2
    let strengthLabel = ''
    if (s.ma5 != null && s.ma10 != null && s.ma10 > 0) {
      const gap = (s.ma10 - s.ma5) / s.ma10 * 100
      if (gap >= 2) {
        delta = -3        // 极强空头
        strengthLabel = '（强势）'
        tags.push('强势空头')
      } else if (gap < 0.3) {
        delta = -1        // 弱空头
        strengthLabel = '（弱势）'
      }
    }
    addItem(
      `均线空头排列${strengthLabel}，趋势偏弱`,
      delta,
      delta <= -3 ? '强势空头' : '空头',
      `周期${tf} ${asof} · MA5/10/20: ${fmt(s.ma5)}/${fmt(s.ma10)}/${fmt(s.ma20)}`
    )
  } else if (s.trend?.includes('交织')) {
    addItem('均线交织，趋势不明', 0, undefined, `周期${tf} ${asof} · MA5/10/20: ${fmt(s.ma5)}/${fmt(s.ma10)}/${fmt(s.ma20)}`)
  }

  // ── 2. MACD ───────────────────────────────────────────────────────────
  if (s.macd_status?.includes('金叉')) {
    addItem('MACD 金叉，短线动能偏强', 2, 'MACD金叉', `周期${tf} ${asof} · hist: ${fmt(s.macd_hist, 3)}`)
  }
  if (s.macd_status?.includes('死叉')) {
    addItem('MACD 死叉，短线动能转弱', -2, 'MACD死叉', `周期${tf} ${asof} · hist: ${fmt(s.macd_hist, 3)}`)
  }
  if (s.macd_hist != null) {
    if (s.macd_hist > 0.0) {
      addItem('MACD 柱体为正（动能偏多）', 1, undefined, `周期${tf} ${asof} · hist: ${fmt(s.macd_hist, 3)}`)
    } else if (s.macd_hist < 0.0) {
      addItem('MACD 柱体为负（动能偏空）', -1, undefined, `周期${tf} ${asof} · hist: ${fmt(s.macd_hist, 3)}`)
    }
  }

  // ── 3. RSI ────────────────────────────────────────────────────────────
  if (s.rsi_status?.includes('超卖')) {
    addItem('RSI 超卖，可能存在反弹', 1, 'RSI超卖', `周期${tf} ${asof} · RSI6: ${fmt(s.rsi6, 1)}（阈值<20）`)
  } else if (s.rsi_status?.includes('偏强')) {
    addItem('RSI 偏强，买盘占优', 1, 'RSI偏强', `周期${tf} ${asof} · RSI6: ${fmt(s.rsi6, 1)}（阈值70-80）`)
  } else if (s.rsi_status?.includes('超买')) {
    addItem('RSI 超买，注意回调风险', -1, 'RSI超买', `周期${tf} ${asof} · RSI6: ${fmt(s.rsi6, 1)}（阈值>80）`)
  } else if (s.rsi_status?.includes('偏弱')) {
    addItem('RSI 偏弱，短线承压', -1, 'RSI偏弱', `周期${tf} ${asof} · RSI6: ${fmt(s.rsi6, 1)}（阈值<30）`)
  } else if (s.rsi_status?.includes('中性')) {
    addItem('RSI 中性', 0, undefined, `周期${tf} ${asof} · RSI6: ${fmt(s.rsi6, 1)}`)
  }

  // ── 4. KDJ ────────────────────────────────────────────────────────────
  if (s.kdj_status?.includes('金叉')) {
    // KDJ 低位金叉（K < 30）信号更可靠，加额外权重
    const isLowCross = s.kdj_k != null && s.kdj_k < 30
    addItem(
      isLowCross ? 'KDJ 低位金叉，超卖区反转信号' : 'KDJ 金叉，短线转强',
      isLowCross ? 2 : 1,
      'KDJ金叉',
      `周期${tf} ${asof} · K/D/J: ${fmt(s.kdj_k, 1)}/${fmt(s.kdj_d, 1)}/${fmt(s.kdj_j, 1)}`
    )
  }
  if (s.kdj_status?.includes('死叉')) {
    // KDJ 高位死叉（K > 70）信号更可靠
    const isHighCross = s.kdj_k != null && s.kdj_k > 70
    addItem(
      isHighCross ? 'KDJ 高位死叉，超买区转弱信号' : 'KDJ 死叉，短线转弱',
      isHighCross ? -2 : -1,
      'KDJ死叉',
      `周期${tf} ${asof} · K/D/J: ${fmt(s.kdj_k, 1)}/${fmt(s.kdj_d, 1)}/${fmt(s.kdj_j, 1)}`
    )
  }

  // ── 5. 布林带：区分突破方向 + 收口/放大 ─────────────────────────────
  if (s.boll_status?.includes('突破上轨')) {
    addItem('突破布林上轨，趋势强势', 1, '突破上轨', `周期${tf} ${asof} · close: ${fmt(s.last_close)} · 上轨: ${fmt(s.boll_upper)}`)
  } else if (s.boll_status?.includes('跌破下轨')) {
    addItem('跌破布林下轨，走势偏弱', -1, '跌破下轨', `周期${tf} ${asof} · close: ${fmt(s.last_close)} · 下轨: ${fmt(s.boll_lower)}`)
  }
  // 布林带收口：波动收敛，蓄力中，不加减分，但加提示 tag
  if (s.boll_width != null) {
    if (s.boll_width < 5) {
      addItem('布林带收口，波动收敛蓄力', 0, '布林收口', `带宽: ${fmt(s.boll_width, 1)}%（阈值<5%）`)
    } else if (s.boll_width > 20) {
      addItem('布林带大幅开口，波动剧烈', 0, '波动扩张', `带宽: ${fmt(s.boll_width, 1)}%（阈值>20%）`)
    }
  }

  // ── 6. 量能：结合涨跌方向判断 ──────────────────────────────────────
  // recent_5_up 是近5日上涨天数（0-5），<=2 视为近期偏弱（下跌趋势）
  const recentUpDays = s.recent_5_up ?? null
  if (s.volume_trend?.includes('放量')) {
    addItem('放量配合，资金参与度提升', 1, '放量', `周期${tf} ${asof} · 量比: ${fmt(s.volume_ratio, 1)}x`)
  } else if (s.volume_trend?.includes('缩量')) {
    // 下跌缩量不算弱信号（抛压减弱），上涨缩量才是弱信号
    if (recentUpDays !== null && recentUpDays <= 2) {
      addItem('下跌缩量，抛压减弱', 0, undefined, `量比: ${fmt(s.volume_ratio, 1)}x · 近期偏弱但缩量`)
    } else {
      addItem('缩量，动能不足', -1, '缩量', `周期${tf} ${asof} · 量比: ${fmt(s.volume_ratio, 1)}x`)
    }
  }

  // ── 7. 支撑/压力：动态阈值（基于振幅） ──────────────────────────────
  // 高波动股阈值放宽，低波动股阈值收紧
  const avgAmp = s.amplitude_avg5 ?? s.amplitude ?? 2
  const proxThreshold = Math.min(4, Math.max(1, avgAmp * 0.6)) / 100  // 0.6x 振幅，限制在1%-4%

  if (s.last_close != null && s.support != null && s.support > 0) {
    if (s.last_close <= s.support * (1 + proxThreshold)) {
      const dist = (s.last_close - s.support) / s.support * 100
      addItem(
        '价格接近支撑位，止跌反弹概率提升',
        1,
        '靠近支撑',
        `周期${tf} ${asof} · close: ${fmt(s.last_close)} · 支撑: ${fmt(s.support)} · 距离: ${dist >= 0 ? '+' : ''}${dist.toFixed(1)}%（动态阈值: ${(proxThreshold * 100).toFixed(1)}%）`
      )
    }
  }
  if (s.last_close != null && s.resistance != null && s.resistance > 0) {
    if (s.last_close >= s.resistance * (1 - proxThreshold)) {
      const dist = (s.last_close - s.resistance) / s.resistance * 100
      addItem(
        '价格接近压力位，上行空间受限',
        -1,
        '靠近压力',
        `周期${tf} ${asof} · close: ${fmt(s.last_close)} · 压力: ${fmt(s.resistance)} · 距离: ${dist >= 0 ? '+' : ''}${dist.toFixed(1)}%（动态阈值: ${(proxThreshold * 100).toFixed(1)}%）`
      )
    }
  }

  // ── 8. K线形态权重 ────────────────────────────────────────────────────
  if (s.kline_pattern) {
    const pattern = s.kline_pattern
    const isBullishTrend = s.trend?.includes('多头')
    const isBearishTrend = s.trend?.includes('空头')

    // 看涨形态
    if (pattern.includes('锤子线') || pattern.includes('倒锤头')) {
      // 空头趋势末端锤子线：强反转信号
      const delta = isBearishTrend ? 2 : 1
      addItem(
        isBearishTrend ? `${pattern}（空头末端，反转信号强）` : `${pattern}（潜在支撑信号）`,
        delta, 'K线形态',
        `周期${tf} ${asof} · 形态: ${pattern}`
      )
    } else if (pattern.includes('早晨之星') || pattern.includes('看涨吞没') || pattern.includes('启明星')) {
      addItem(`${pattern}（看涨反转形态）`, 2, 'K线形态', `周期${tf} ${asof} · 形态: ${pattern}`)
    } else if (pattern.includes('红三兵') || pattern.includes('三白兵')) {
      addItem(`${pattern}（持续上涨形态）`, 1, 'K线形态', `周期${tf} ${asof} · 形态: ${pattern}`)
    }
    // 看跌形态
    else if (pattern.includes('射击之星') || pattern.includes('上吊线')) {
      const delta = isBullishTrend ? -2 : -1
      addItem(
        isBullishTrend ? `${pattern}（多头顶部，反转信号强）` : `${pattern}（潜在压力信号）`,
        delta, 'K线形态',
        `周期${tf} ${asof} · 形态: ${pattern}`
      )
    } else if (pattern.includes('黄昏之星') || pattern.includes('看跌吞没') || pattern.includes('傍晚之星')) {
      addItem(`${pattern}（看跌反转形态）`, -2, 'K线形态', `周期${tf} ${asof} · 形态: ${pattern}`)
    } else if (pattern.includes('三黑鸦') || pattern.includes('三只乌鸦')) {
      addItem(`${pattern}（持续下跌形态）`, -1, 'K线形态', `周期${tf} ${asof} · 形态: ${pattern}`)
    }
    // 中性形态
    else if (pattern.includes('十字星') || pattern.includes('纺锤')) {
      addItem(`${pattern}（多空博弈，方向待定）`, 0, 'K线形态', `周期${tf} ${asof} · 形态: ${pattern}`)
    }
  }

  // ── 9. 反向信号检测（矛盾信号警告） ──────────────────────────────────
  const hasBullish = tags.some(t => ['多头', '强势多头', 'MACD金叉', 'KDJ金叉', 'RSI偏强'].includes(t))
  const hasBearish = tags.some(t => ['空头', '强势空头', 'MACD死叉', 'KDJ死叉', 'RSI偏弱'].includes(t))
  const isOverbought = s.rsi_status?.includes('超买')
  const isOversold = s.rsi_status?.includes('超卖')
  const isBullTrend = s.trend?.includes('多头')
  const isBearTrend = s.trend?.includes('空头')
  const isVolumeShrink = s.volume_trend?.includes('缩量')

  // 多头趋势 + 超买 + 缩量 → 高位滞涨风险
  if (isBullTrend && isOverbought && isVolumeShrink) {
    warnings.push('多头+超买+缩量：高位滞涨信号，注意回调风险')
    score -= 1  // 轻度惩罚置信度
    items.push({ text: '⚠️ 高位滞涨信号（多头+超买+缩量）', delta: -1, tag: '矛盾信号' })
  }
  // 空头趋势 + 超卖 + 放量 → 下跌加速风险
  else if (isBearTrend && isOversold && !isVolumeShrink && s.volume_trend?.includes('放量')) {
    warnings.push('空头+超卖+放量：可能恐慌性下跌，非超卖买入信号')
    score -= 1
    items.push({ text: '⚠️ 恐慌性下跌信号（空头+超卖+放量）', delta: -1, tag: '矛盾信号' })
  }
  // 多空信号均强：震荡市特征
  else if (hasBullish && hasBearish) {
    warnings.push('多空信号均存在，当前处于分歧震荡区间')
  }
  // 布林收口 + MACD金叉/死叉：方向选择临近
  if (s.boll_width != null && s.boll_width < 5) {
    if (tags.includes('MACD金叉')) {
      warnings.push('布林收口+MACD金叉：蓄力向上突破概率较大')
    } else if (tags.includes('MACD死叉')) {
      warnings.push('布林收口+MACD死叉：蓄力向下突破概率较大')
    }
  }

  // ── 10. 最终建议 ──────────────────────────────────────────────────────
  const holdingFlag = holding === true
  let action: Action
  if (holdingFlag) {
    if (score >= 4) action = 'add'
    else if (score >= 1) action = 'hold'
    else if (score <= -4) action = 'sell'
    else if (score <= -1) action = 'reduce'
    else action = 'watch'
  } else {
    if (score >= 4) action = 'buy'
    else if (score <= -3) action = 'avoid'
    else action = 'watch'
  }

  const uniqTags = Array.from(new Set(tags.filter(t => t !== '矛盾信号')))
  const signal = uniqTags.length > 0 ? uniqTags.join(' / ') : '技术面中性'

  const actionLabel = (a: Action): string => {
    switch (a) {
      case 'buy': return '买入'
      case 'add': return '加仓'
      case 'reduce': return '减仓'
      case 'sell': return '卖出'
      case 'hold': return '持有'
      case 'watch': return '观望'
      case 'avoid': return '回避'
      default: return '观望'
    }
  }

  return {
    action,
    action_label: actionLabel(action),
    signal,
    score,
    evidence: items,
    tags: uniqTags,
    warnings: warnings.length > 0 ? warnings : undefined,
  }
}
