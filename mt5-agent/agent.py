from __future__ import annotations
import os, json, time, argparse, logging
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from analysis_engine import analyse_rates

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'), format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('stb-mt5-agent')
BASE=Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE/'.env')
except ImportError:
    pass
TOKEN_FILE=BASE/'.bridge_token'
STATE_FILE=BASE/'sent_positions.json'
SIGNALS_FILE=BASE/'processed_signals.json'

def env_bool(name: str, default: bool=False) -> bool:
    return os.getenv(name,str(default)).lower() in ('1','true','yes','on')
def env_float(name: str, default: float) -> float:
    try: return float(os.getenv(name,str(default)))
    except ValueError: return default
def env_int(name: str, default: int) -> int:
    try: return int(os.getenv(name,str(default)))
    except ValueError: return default

def api_client(base: str, token: str=''):
    headers={'X-Bridge-Token':token} if token else {}
    return httpx.Client(base_url=base.rstrip('/'),headers=headers,timeout=15.0)

def claim_bridge(base: str, link_code: str, login: str, server: str) -> str:
    with api_client(base) as c:
        r=c.post('/api/mt5/claim',json={'link_code':link_code,'account_login':login,'server_name':server})
        r.raise_for_status(); data=r.json()
    token=data['bridge_token']
    TOKEN_FILE.write_text(token,encoding='utf-8')
    try: TOKEN_FILE.chmod(0o600)
    except OSError: pass
    log.info('MT5 bridge enrolled successfully. Bridge token stored locally.')
    return token

def timeframe_value(name: str):
    mapping={'M1':mt5.TIMEFRAME_M1,'M5':mt5.TIMEFRAME_M5,'M15':mt5.TIMEFRAME_M15,'M30':mt5.TIMEFRAME_M30,
             'H1':mt5.TIMEFRAME_H1,'H4':mt5.TIMEFRAME_H4,'D1':mt5.TIMEFRAME_D1}
    if name not in mapping: raise ValueError(f'Unsupported timeframe: {name}')
    return mapping[name]

def daily_net(mt5mod: Any) -> float | None:
    start=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
    deals=mt5mod.history_deals_get(start,datetime.now())
    positions=mt5mod.positions_get()
    # Unknown daily P/L must not be interpreted as zero risk.
    if deals is None or positions is None:
        return None
    magic=env_int('MAGIC_NUMBER',881611)
    realized=sum(float(getattr(d,'profit',0))+float(getattr(d,'swap',0))+float(getattr(d,'commission',0))+float(getattr(d,'fee',0))
                 for d in deals if int(getattr(d,'magic',0))==magic)
    floating=sum(float(getattr(p,'profit',0))+float(getattr(p,'swap',0))
                 for p in positions if int(getattr(p,'magic',-1))==magic)
    return realized+floating


def aggregate_open_risk(mt5mod: Any, magic: int) -> float:
    # Return cash risk to current SL for all our open positions. An unprotected
    # position or unavailable position snapshot is treated as unbounded risk.
    total=0.0
    positions=mt5mod.positions_get()
    if positions is None:
        return float('inf')
    for position in positions:
        if int(getattr(position,'magic',-1)) != magic:
            continue
        sl=float(getattr(position,'sl',0) or 0)
        if sl <= 0:
            return float('inf')
        order_type=int(getattr(position,'type',-1))
        result=mt5mod.order_calc_profit(order_type,position.symbol,float(position.volume),
                                        float(position.price_open),sl)
        if result is None:
            return float('inf')
        total += abs(float(result))
    return total


def load_processed_signals() -> dict[str, str]:
    if not SIGNALS_FILE.exists():
        return {}
    try:
        data=json.loads(SIGNALS_FILE.read_text(encoding='utf-8'))
        return {str(k):str(v) for k,v in data.items()} if isinstance(data,dict) else {}
    except Exception:
        log.warning('Processed signal state file could not be read; starting with an empty signal cache.')
        return {}


def save_processed_signals(state: dict[str, str]) -> None:
    temporary=SIGNALS_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    temporary.replace(SIGNALS_FILE)
    try: SIGNALS_FILE.chmod(0o600)
    except OSError: pass

def calc_volume(mt5mod: Any, symbol: str, direction: str, entry: float, sl: float, risk_pct: float) -> float:
    info=mt5mod.symbol_info(symbol); account=mt5mod.account_info()
    if info is None or account is None: return 0.0
    order_type=mt5mod.ORDER_TYPE_BUY if direction=='BUY' else mt5mod.ORDER_TYPE_SELL
    loss=mt5mod.order_calc_profit(order_type,symbol,1.0,entry,sl)
    if loss is None or abs(loss)<=0: return 0.0
    if not (0 < risk_pct <= 2.0): return 0.0
    risk_cash=float(account.equity)*risk_pct/100.0
    raw=risk_cash/abs(float(loss)); step=Decimal(str(info.volume_step or 0.01))
    # Never round up to the broker's minimum lot if that would exceed the customer's risk budget.
    if raw < float(info.volume_min): return 0.0
    steps=(Decimal(str(raw))/step).to_integral_value(rounding=ROUND_DOWN)
    volume=min(float(info.volume_max),float(steps*step))
    digits=max(0,-step.normalize().as_tuple().exponent)
    return round(volume,digits)

def select_filling_mode(mt5mod: Any, symbol_info: Any):
    # SYMBOL_FILLING_FOK / IOC are bit flags; ORDER_FILLING_* are enum values.
    flags=int(getattr(symbol_info,'filling_mode',0) or 0)
    if flags & 1:
        return mt5mod.ORDER_FILLING_FOK
    if flags & 2:
        return mt5mod.ORDER_FILLING_IOC
    market_execution=int(getattr(mt5mod,'SYMBOL_TRADE_EXECUTION_MARKET',2))
    execution=int(getattr(symbol_info,'trade_exemode',-1))
    if execution == market_execution:
        return None
    return mt5mod.ORDER_FILLING_RETURN


def maybe_execute_order(mt5mod: Any, symbol: str, signal, timeframe: str, policy: dict):
    account=mt5mod.account_info(); info=mt5mod.symbol_info(symbol)
    terminal=mt5mod.terminal_info() if hasattr(mt5mod,'terminal_info') else None
    if account is None or info is None or terminal is None: return None
    # Fail closed when either the connected terminal or account disallows Expert Advisor trading.
    if not bool(getattr(terminal,'connected',False)) or not bool(getattr(terminal,'trade_allowed',False)):
        log.warning('MT5 terminal disconnected or automated trading disabled; execution blocked.')
        return None
    if not bool(getattr(account,'trade_allowed',False)) or not bool(getattr(account,'trade_expert',False)):
        log.warning('MT5 account permissions do not allow automated trading; execution blocked.')
        return None
    if int(getattr(info,'trade_mode',0)) == int(getattr(mt5mod,'SYMBOL_TRADE_MODE_DISABLED',0)):
        log.warning('Trading is disabled for symbol %s.',symbol)
        return None
    demo_mode=int(getattr(mt5mod,'ACCOUNT_TRADE_MODE_DEMO',0))
    real_mode=int(getattr(mt5mod,'ACCOUNT_TRADE_MODE_REAL',2))
    is_demo=int(account.trade_mode)==demo_mode
    is_real=int(account.trade_mode)==real_mode
    if is_demo:
        if not env_bool('ENABLE_DEMO_EXECUTION',False) or not bool(policy.get('demo_execution_allowed')): return None
    elif is_real:
        confirmation=os.getenv('LIVE_TRADING_CONFIRMATION','')
        live_gate=(env_bool('ENABLE_LIVE_EXECUTION',False) and
                   confirmation=='I_ACCEPT_REAL_MONEY_RISK' and
                   bool(policy.get('live_trading_allowed')))
        if not live_gate:
            log.warning('Real account detected; live order blocked because server, customer consent, and local confirmation gates are not all open.')
            return None
    else:
        log.warning('Contest/unknown account type; execution blocked.')
        return None
    if not info.visible and not mt5mod.symbol_select(symbol,True): return None
    tick=mt5mod.symbol_info_tick(symbol)
    if tick is None: return None
    direction=signal.direction
    price=float(tick.ask if direction=='BUY' else tick.bid)
    digits=int(info.digits)
    sl=round(signal.stop_loss,digits); tp=round(signal.take_profit,digits)
    if direction=='BUY' and not (sl < price < tp): return None
    if direction=='SELL' and not (tp < price < sl): return None
    stops_distance=float(getattr(info,'trade_stops_level',0))*float(info.point)
    if abs(price-sl)<stops_distance or abs(price-tp)<stops_distance: return None
    order_type=mt5mod.ORDER_TYPE_BUY if direction=='BUY' else mt5mod.ORDER_TYPE_SELL
    vol=calc_volume(mt5mod,symbol,direction,price,sl,env_float('RISK_PER_TRADE_PERCENT',0.25))
    if vol<=0: return None
    account=mt5mod.account_info()
    if account is None: return None
    new_loss=mt5mod.order_calc_profit(order_type,symbol,vol,price,sl)
    if new_loss is None: return None
    max_total_risk=env_float('MAX_TOTAL_OPEN_RISK_PERCENT',1.0)
    if not (0 < max_total_risk <= 10.0):
        log.error('MAX_TOTAL_OPEN_RISK_PERCENT must be greater than 0 and no more than 10.'); return None
    open_risk=aggregate_open_risk(mt5mod,env_int('MAGIC_NUMBER',881611))
    projected_risk=open_risk+abs(float(new_loss))
    if projected_risk > float(account.equity)*max_total_risk/100.0:
        log.info('Aggregate open-position risk cap reached: %.2f exceeds %.2f%% of equity.',
                 projected_risk,max_total_risk)
        return None
    daily=daily_net(mt5mod); max_daily=abs(float(account.balance))*env_float('MAX_DAILY_LOSS_PERCENT',1.0)/100
    if daily is None or max_daily <= 0:
        log.warning('Daily P/L or daily loss limit is unavailable; execution blocked.'); return None
    if daily <= -max_daily:
        log.warning('Daily loss limit reached; automatic execution paused.'); return None
    max_positions=env_int('MAX_OPEN_POSITIONS',3)
    positions=mt5mod.positions_get()
    magic=env_int('MAGIC_NUMBER',881611)
    own=[p for p in (positions or []) if int(getattr(p,'magic',-1))==magic]
    if max_positions>0 and len(own)>=max_positions: return None
    per_symbol=env_int('MAX_OPEN_POSITIONS_PER_SYMBOL',1)
    if per_symbol>0 and sum(1 for p in own if p.symbol==symbol)>=per_symbol: return None
    margin=mt5mod.order_calc_margin(order_type,symbol,vol,price)
    if margin is None or float(margin)>float(account.margin_free)*0.5:
        log.warning('Insufficient free margin buffer; trade skipped.'); return None
    filling=select_filling_mode(mt5mod,info)
    if filling is None:
        log.warning('No supported market-order filling mode for %s; execution blocked.',symbol)
        return None
    request={'action':mt5mod.TRADE_ACTION_DEAL,'symbol':symbol,'volume':vol,'type':order_type,'price':price,
             'sl':sl,'tp':tp,'deviation':env_int('DEVIATION_POINTS',20),'magic':magic,
             'comment':f'STB {timeframe} multi-agent','type_time':mt5mod.ORDER_TIME_GTC,
             'type_filling':filling}
    # Ask the broker/terminal to validate the request before sending any order.
    check=mt5mod.order_check(request)
    if check is None or int(getattr(check,'retcode',-1)) != 0:
        log.warning('MT5 order pre-check rejected: %s',getattr(check,'comment','No check result'))
        return None
    result=mt5mod.order_send(request)
    if result is None or result.retcode not in (mt5mod.TRADE_RETCODE_DONE,mt5mod.TRADE_RETCODE_PLACED):
        log.error('MT5 order rejected: %s', getattr(result,'comment','No result'))
        return None
    log.info('%s order placed: %s %s volume=%s ticket=%s','DEMO' if is_demo else 'REAL',direction,symbol,vol,result.order)
    return result

def closed_positions(mt5mod: Any):
    lookback=env_int('HISTORY_LOOKBACK_DAYS',90)
    start=datetime.now()-timedelta(days=lookback)
    deals=mt5mod.history_deals_get(start,datetime.now())
    if deals is None: return []
    active={int(p.identifier) for p in (mt5mod.positions_get() or [])}
    grouped={}
    for d in deals:
        pid=int(getattr(d,'position_id',0) or 0)
        if pid<=0: continue
        grouped.setdefault(pid,[]).append(d)
    output=[]
    magic=env_int('MAGIC_NUMBER',881611)
    for pid,items in grouped.items():
        # Only charge and synchronize positions touched by this bot's own magic number.
        # Manual trades and unrelated EAs in the customer's account are excluded.
        if not any(int(getattr(d,'magic',0))==magic for d in items): continue
        if pid in active: continue
        exits=[d for d in items if int(getattr(d,'entry',-1)) in (1,2,3)]
        entries=[d for d in items if int(getattr(d,'entry',-1))==0]
        if not exits or not entries: continue
        # Send a full position only after all its volume has closed. Aggregate entry and exit costs.
        gross=sum(float(getattr(d,'profit',0)) for d in items)
        swap=sum(float(getattr(d,'swap',0)) for d in items)
        commission=sum(float(getattr(d,'commission',0))+float(getattr(d,'fee',0)) for d in items)
        first=entries[0]
        side='BUY' if int(getattr(first,'type',0))==int(mt5mod.DEAL_TYPE_BUY) else 'SELL'
        closed=max(int(getattr(d,'time',0)) for d in exits)
        volume=sum(float(getattr(d,'volume',0)) for d in entries)
        output.append({'external_position_id':str(pid),'symbol':str(getattr(first,'symbol','UNKNOWN')),'side':side,
          'volume':volume,'gross_profit':gross,'swap':swap,'commission':commission,
          'currency':str(getattr(mt5mod.account_info(),'currency','USD') or 'USD'),
          'closed_at':datetime.fromtimestamp(closed,tz=timezone.utc).isoformat()})
    return output

def send_closed_positions(client, mt5mod):
    sent=set()
    if STATE_FILE.exists():
        try: sent=set(json.loads(STATE_FILE.read_text(encoding='utf-8')))
        except Exception: sent=set()
    changed=False
    for trade in closed_positions(mt5mod):
        pid=trade['external_position_id']
        if pid in sent: continue
        r=client.post('/api/mt5/deals',json=trade)
        r.raise_for_status()
        sent.add(pid); changed=True
        log.info('Closed position synchronized: %s %s net=%s fee=%s',pid,trade['symbol'],r.json().get('net_profit'),r.json().get('performance_fee'))
    if changed:
        STATE_FILE.write_text(json.dumps(sorted(sent),ensure_ascii=False),encoding='utf-8')
        try: STATE_FILE.chmod(0o600)
        except OSError: pass

def main():
    parser=argparse.ArgumentParser(description='SUPER TRADING BOT MT5 Windows Agent')
    parser.add_argument('--claim-code',help='One-time code from the client app')
    args=parser.parse_args()
    if mt5 is None: raise SystemExit('MetaTrader5 Python package is missing. Run this agent on Windows with the MT5 terminal installed.')
    api_base=os.getenv('API_BASE_URL','http://127.0.0.1:8000')
    expected_login=os.getenv('MT5_ACCOUNT_LOGIN','').strip(); expected_server=os.getenv('MT5_SERVER','').strip()
    if not expected_login or not expected_server: raise SystemExit('Set MT5_ACCOUNT_LOGIN and MT5_SERVER in .env first.')
    if not mt5.initialize(): raise SystemExit(f'MT5 initialize failed: {mt5.last_error()}. Open MT5 and log in first.')
    account=mt5.account_info()
    if account is None: mt5.shutdown(); raise SystemExit('No logged-in MT5 account detected.')
    if str(account.login)!=expected_login or str(account.server)!=expected_server:
        mt5.shutdown(); raise SystemExit('The logged-in MT5 account/server does not match the approved link information.')
    if args.claim_code:
        token=claim_bridge(api_base,args.claim_code,str(account.login),str(account.server))
    elif TOKEN_FILE.exists(): token=TOKEN_FILE.read_text(encoding='utf-8').strip()
    else:
        mt5.shutdown(); raise SystemExit('No bridge token. Use --claim-code <one-time-code> once to enroll this terminal.')
    if not token: mt5.shutdown(); raise SystemExit('Bridge token file is empty.')
    timeframes=[s.strip().upper() for s in os.getenv('TIMEFRAMES',os.getenv('TIMEFRAME','M15')).split(',') if s.strip()]
    timeframe_map={tf:timeframe_value(tf) for tf in timeframes}
    symbols=[s.strip() for s in os.getenv('SYMBOLS','EURUSD,GBPUSD,XAUUSD').split(',') if s.strip()]
    poll=max(10,env_int('POLL_SECONDS',30)); fast=env_int('EMA_FAST',20); slow=env_int('EMA_SLOW',50)
    min_votes=env_int('MIN_CONSENSUS',2); last_bar=load_processed_signals()
    with api_client(api_base,token) as client:
        log.info('Agent started for MT5 %s on %s. Symbols=%s, timeframes=%s',account.login,account.server,','.join(symbols),','.join(timeframes))
        while True:
            try:
                heartbeat=client.post('/api/mt5/heartbeat'); heartbeat.raise_for_status(); policy=heartbeat.json()
                for symbol in symbols:
                    if not mt5.symbol_select(symbol,True):
                        log.warning('Symbol unavailable in Market Watch: %s',symbol); continue
                    for timeframe in timeframes:
                        rates=mt5.copy_rates_from_pos(symbol,timeframe_map[timeframe],0,260)
                        signal=analyse_rates(rates,fast,slow,min_votes)
                        if not signal: continue
                        key=f'{symbol}:{timeframe}'
                        if last_bar.get(key)==signal.bar_time: continue
                        info=mt5.symbol_info_tick(symbol)
                        if not info: continue
                        entry=float(info.ask if signal.direction=='BUY' else info.bid)
                        payload={'symbol':symbol,'timeframe':timeframe,'direction':signal.direction,'confidence':signal.confidence,
                            'entry_price':entry,'stop_loss':signal.stop_loss,'take_profit':signal.take_profit,
                            'bar_time':datetime.fromtimestamp(int(signal.bar_time),tz=timezone.utc).isoformat(),
                            'strategy_votes':signal.votes}
                        try:
                            client.post('/api/mt5/signals',json=payload).raise_for_status()
                        except Exception as ex:
                            log.warning('Signal sync failed for %s %s; order execution skipped for safety: %s',symbol,timeframe,ex)
                            continue
                        # Persist before any order_send call so a restart cannot replay this signal.
                        last_bar[key]=signal.bar_time
                        save_processed_signals(last_bar)
                        log.info('CONSENSUS %s %s %s confidence=%d%% votes=%s',symbol,timeframe,signal.direction,int(signal.confidence*100),
                                 ','.join(v['agent']+':'+v['signal'] for v in signal.votes))
                        try: maybe_execute_order(mt5,symbol,signal,timeframe,policy)
                        except Exception as ex: log.error('Execution safeguard for %s %s: %s',symbol,timeframe,ex)
                try: send_closed_positions(client,mt5)
                except Exception as ex: log.warning('Closed-position sync failed: %s',ex)
            except KeyboardInterrupt: break
            except Exception as ex: log.exception('Agent cycle failed: %s',ex)
            time.sleep(poll)
    mt5.shutdown()

if __name__=='__main__': main()
