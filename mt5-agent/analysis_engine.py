"""Transparent multi-strategy analysis engine for MetaTrader 5 price bars.
This module creates signals; it does not promise or guarantee trading profits.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import math

@dataclass
class Signal:
    direction: str
    confidence: float
    entry: float
    stop_loss: float
    take_profit: float
    bar_time: str
    votes: list[dict[str, str]]
    atr: float

def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period: return []
    alpha=2.0/(period+1.0)
    out=[sum(values[:period])/period]
    for value in values[period:]: out.append(value*alpha+out[-1]*(1-alpha))
    return out

def rsi(values: list[float], period: int=14) -> float | None:
    if len(values) < period+1: return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=[max(x,0.0) for x in changes[-period:]]
    losses=[max(-x,0.0) for x in changes[-period:]]
    avg_gain=sum(gains)/period; avg_loss=sum(losses)/period
    if avg_loss == 0: return 100.0
    rs=avg_gain/avg_loss
    return 100.0-(100.0/(1.0+rs))

def atr(rates: Any, period: int=14) -> float | None:
    if len(rates) < period+1: return None
    trs=[]
    for i in range(1,len(rates)):
        high=float(rates[i]['high']); low=float(rates[i]['low']); prev=float(rates[i-1]['close'])
        trs.append(max(high-low,abs(high-prev),abs(low-prev)))
    return sum(trs[-period:])/period

def analyse_rates(rates: Any, fast_period: int=20, slow_period: int=50,
                  min_consensus: int=2, atr_stop_mult: float=1.8,
                  atr_target_mult: float=2.7) -> Signal | None:
    """Use the last completed candle, not the currently forming candle."""
    if rates is None or len(rates) < max(slow_period+12, 90): return None
    completed=list(rates[:-1])
    closes=[float(x['close']) for x in completed]
    efast=ema(closes,fast_period); eslow=ema(closes,slow_period)
    macd_fast=ema(closes,12); macd_slow=ema(closes,26)
    if not efast or not eslow or not macd_fast or not macd_slow: return None
    macd_line=[a-b for a,b in zip(macd_fast[-len(macd_slow):],macd_slow)]
    macd_signal=ema(macd_line,9)
    r=rsi(closes,14); a=atr(completed,14)
    if r is None or a is None or a <= 0 or not macd_signal: return None
    last=closes[-1]; trend='BUY' if efast[-1]>eslow[-1] and efast[-1]>=efast[-2] else ('SELL' if efast[-1]<eslow[-1] and efast[-1]<=efast[-2] else 'WAIT')
    momentum='BUY' if 52<=r<=70 else ('SELL' if 30<=r<=48 else 'WAIT')
    macd='BUY' if macd_line[-1]>macd_signal[-1] and macd_line[-1]>0 else ('SELL' if macd_line[-1]<macd_signal[-1] and macd_line[-1]<0 else 'WAIT')
    votes=[{'agent':'Trend Analyst','signal':trend,'detail':f'EMA{fast_period}/EMA{slow_period}'},
           {'agent':'Momentum Analyst','signal':momentum,'detail':f'RSI={r:.1f}'},
           {'agent':'MACD Analyst','signal':macd,'detail':'MACD histogram direction'}]
    buys=sum(v['signal']=='BUY' for v in votes); sells=sum(v['signal']=='SELL' for v in votes)
    if buys>=min_consensus: direction='BUY'; count=buys
    elif sells>=min_consensus: direction='SELL'; count=sells
    else: return None
    # Volatility Analyst adjusts the stop distance; it does not vote direction.
    distance=a*atr_stop_mult; target=a*atr_target_mult
    if direction=='BUY': sl=last-distance; tp=last+target
    else: sl=last+distance; tp=last-target
    bar=completed[-1]
    return Signal(direction=direction,confidence=count/len(votes),entry=last,stop_loss=sl,take_profit=tp,
                  bar_time=str(int(bar['time'])),votes=votes,atr=a)
