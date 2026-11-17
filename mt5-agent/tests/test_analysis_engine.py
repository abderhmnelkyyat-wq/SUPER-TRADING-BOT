from analysis_engine import ema, rsi, analyse_rates

def test_ema_returns_expected_length_and_slope():
    values=[float(x) for x in range(1,101)]
    result=ema(values,10)
    assert len(result)==91
    assert result[-1]>result[-2]

def test_rsi_detects_monotonic_gains():
    assert rsi([float(x) for x in range(30)],14)==100.0

def test_insufficient_rates_do_not_emit_signal():
    assert analyse_rates([],20,50,2) is None


def test_open_positions_without_stop_loss_are_unbounded_risk():
    from types import SimpleNamespace
    from agent import aggregate_open_risk
    class FakeMT5:
        def positions_get(self):
            return [SimpleNamespace(magic=881611, sl=0, symbol='EURUSD', volume=0.1, price_open=1.1, type=0)]
    assert aggregate_open_risk(FakeMT5(),881611)==float('inf')


def test_open_position_risk_is_aggregated_in_account_currency():
    from types import SimpleNamespace
    from agent import aggregate_open_risk
    class FakeMT5:
        def positions_get(self):
            return [SimpleNamespace(magic=881611, sl=1.09, symbol='EURUSD', volume=0.1, price_open=1.1, type=0),
                    SimpleNamespace(magic=881611, sl=1.08, symbol='GBPUSD', volume=0.2, price_open=1.1, type=0),
                    SimpleNamespace(magic=999, sl=1.0, symbol='USDJPY', volume=1, price_open=1.1, type=0)]
        def order_calc_profit(self, order_type, symbol, volume, entry, stop):
            return -abs(entry-stop)*volume*10000
    result=aggregate_open_risk(FakeMT5(),881611)
    assert round(result,2)==50.0


def test_processed_signal_cache_survives_restart(tmp_path,monkeypatch):
    import agent
    monkeypatch.setattr(agent,'SIGNALS_FILE',tmp_path/'processed_signals.json')
    data={'EURUSD:M15':'1794823200','XAUUSD:H1':'1794820000'}
    agent.save_processed_signals(data)
    assert agent.load_processed_signals()==data


def test_closed_position_feed_excludes_manual_trades(monkeypatch):
    from types import SimpleNamespace
    import time
    import agent
    monkeypatch.setenv('MAGIC_NUMBER','881611')
    class FakeMT5:
        DEAL_TYPE_BUY=0
        def positions_get(self): return []
        def account_info(self): return SimpleNamespace(currency='USD')
        def history_deals_get(self,start,end):
            now=int(time.time())
            return [
                SimpleNamespace(position_id=101,magic=881611,entry=0,volume=.1,profit=0,swap=0,commission=-1,fee=0,type=0,symbol='EURUSD',time=now),
                SimpleNamespace(position_id=101,magic=0,entry=1,volume=.1,profit=100,swap=0,commission=-2,fee=0,type=0,symbol='EURUSD',time=now+1),
                SimpleNamespace(position_id=202,magic=0,entry=0,volume=.1,profit=0,swap=0,commission=-1,fee=0,type=0,symbol='GBPUSD',time=now),
                SimpleNamespace(position_id=202,magic=0,entry=1,volume=.1,profit=90,swap=0,commission=-2,fee=0,type=0,symbol='GBPUSD',time=now+1),
            ]
    rows=agent.closed_positions(FakeMT5())
    assert [x['external_position_id'] for x in rows]==['101']
    assert rows[0]['gross_profit']==100


def test_real_account_is_blocked_without_complete_server_customer_and_local_gates(monkeypatch):
    from types import SimpleNamespace
    import agent
    monkeypatch.setenv('ENABLE_LIVE_EXECUTION','true')
    monkeypatch.setenv('LIVE_TRADING_CONFIRMATION','I_ACCEPT_REAL_MONEY_RISK')
    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO=0
        ACCOUNT_TRADE_MODE_REAL=2
        SYMBOL_TRADE_MODE_DISABLED=0
        def account_info(self):
            return SimpleNamespace(trade_mode=2,trade_allowed=True,trade_expert=True)
        def symbol_info(self,symbol):
            return SimpleNamespace(trade_mode=4)
        def terminal_info(self):
            return SimpleNamespace(connected=True,trade_allowed=True)
    signal=SimpleNamespace()
    # The customer has not consented on the server, so no MT5 order APIs are reached.
    assert agent.maybe_execute_order(FakeMT5(),'EURUSD',signal,'M15',{'live_trading_allowed':False}) is None


def test_real_account_is_blocked_when_local_live_switch_is_off(monkeypatch):
    from types import SimpleNamespace
    import agent
    monkeypatch.setenv('ENABLE_LIVE_EXECUTION','false')
    monkeypatch.setenv('LIVE_TRADING_CONFIRMATION','I_ACCEPT_REAL_MONEY_RISK')
    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO=0
        ACCOUNT_TRADE_MODE_REAL=2
        SYMBOL_TRADE_MODE_DISABLED=0
        def account_info(self):
            return SimpleNamespace(trade_mode=2,trade_allowed=True,trade_expert=True)
        def symbol_info(self,symbol):
            return SimpleNamespace(trade_mode=4)
        def terminal_info(self):
            return SimpleNamespace(connected=True,trade_allowed=True)
    assert agent.maybe_execute_order(FakeMT5(),'EURUSD',SimpleNamespace(),'M15',{'live_trading_allowed':True}) is None


def test_filling_mode_uses_symbol_supported_execution():
    from types import SimpleNamespace
    import agent
    class FakeMT5:
        ORDER_FILLING_FOK=0
        ORDER_FILLING_IOC=1
        ORDER_FILLING_RETURN=2
        SYMBOL_TRADE_EXECUTION_MARKET=2
    assert agent.select_filling_mode(FakeMT5(),SimpleNamespace(filling_mode=2,trade_exemode=2))==1
    assert agent.select_filling_mode(FakeMT5(),SimpleNamespace(filling_mode=0,trade_exemode=2)) is None


def test_real_execution_reaches_order_send_only_after_all_gates_and_broker_check(monkeypatch):
    from types import SimpleNamespace
    import agent
    monkeypatch.setenv('ENABLE_LIVE_EXECUTION', 'true')
    monkeypatch.setenv('LIVE_TRADING_CONFIRMATION', 'I_ACCEPT_REAL_MONEY_RISK')
    monkeypatch.setenv('RISK_PER_TRADE_PERCENT', '0.25')
    monkeypatch.setenv('MAX_TOTAL_OPEN_RISK_PERCENT', '1.0')
    monkeypatch.setenv('MAX_DAILY_LOSS_PERCENT', '1.0')
    monkeypatch.setenv('MAX_OPEN_POSITIONS', '3')
    monkeypatch.setenv('MAX_OPEN_POSITIONS_PER_SYMBOL', '1')

    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0
        ACCOUNT_TRADE_MODE_REAL = 2
        SYMBOL_TRADE_MODE_DISABLED = 0
        SYMBOL_TRADE_EXECUTION_MARKET = 2
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        TRADE_ACTION_DEAL = 1
        ORDER_TIME_GTC = 0
        ORDER_FILLING_FOK = 0
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_RETURN = 2
        TRADE_RETCODE_DONE = 10009
        TRADE_RETCODE_PLACED = 10008

        def __init__(self):
            self.checked = False
            self.sent = []

        def account_info(self):
            return SimpleNamespace(trade_mode=2, trade_allowed=True, trade_expert=True,
                                   equity=10000.0, balance=10000.0, margin_free=10000.0)

        def symbol_info(self, symbol):
            return SimpleNamespace(visible=True, trade_mode=4, digits=5, point=0.00001,
                                   trade_stops_level=0, volume_min=0.01, volume_max=100,
                                   volume_step=0.01, filling_mode=1, trade_exemode=2)

        def terminal_info(self):
            return SimpleNamespace(connected=True, trade_allowed=True)

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(ask=1.1002, bid=1.1000)

        def positions_get(self):
            return []

        def history_deals_get(self, start, end):
            return []

        def order_calc_profit(self, order_type, symbol, volume, entry, stop):
            return -abs(entry - stop) * 100000 * volume

        def order_calc_margin(self, order_type, symbol, volume, price):
            return volume * 100.0

        def order_check(self, request):
            self.checked = True
            return SimpleNamespace(retcode=0, comment='check passed')

        def order_send(self, request):
            assert self.checked, 'order_send must never run before order_check'
            self.sent.append(request)
            return SimpleNamespace(retcode=10009, order=987654)

    fake = FakeMT5()
    signal = SimpleNamespace(direction='BUY', stop_loss=1.0990, take_profit=1.1020)
    result = agent.maybe_execute_order(fake, 'EURUSD', signal, 'M15', {'live_trading_allowed': True})
    assert result is not None and result.order == 987654
    assert len(fake.sent) == 1
    assert fake.sent[0]['sl'] == 1.0990 and fake.sent[0]['tp'] == 1.1020


def test_real_execution_fails_closed_when_broker_order_check_rejects(monkeypatch):
    from types import SimpleNamespace
    import agent
    monkeypatch.setenv('ENABLE_LIVE_EXECUTION', 'true')
    monkeypatch.setenv('LIVE_TRADING_CONFIRMATION', 'I_ACCEPT_REAL_MONEY_RISK')
    monkeypatch.setenv('RISK_PER_TRADE_PERCENT', '0.25')
    monkeypatch.setenv('MAX_TOTAL_OPEN_RISK_PERCENT', '1.0')
    monkeypatch.setenv('MAX_DAILY_LOSS_PERCENT', '1.0')

    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0
        ACCOUNT_TRADE_MODE_REAL = 2
        SYMBOL_TRADE_MODE_DISABLED = 0
        SYMBOL_TRADE_EXECUTION_MARKET = 2
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        TRADE_ACTION_DEAL = 1
        ORDER_TIME_GTC = 0
        ORDER_FILLING_FOK = 0
        ORDER_FILLING_IOC = 1
        ORDER_FILLING_RETURN = 2
        TRADE_RETCODE_DONE = 10009
        TRADE_RETCODE_PLACED = 10008

        def __init__(self): self.sent = 0
        def account_info(self):
            return SimpleNamespace(trade_mode=2, trade_allowed=True, trade_expert=True,
                                   equity=10000.0, balance=10000.0, margin_free=10000.0)
        def symbol_info(self, symbol):
            return SimpleNamespace(visible=True, trade_mode=4, digits=5, point=0.00001,
                                   trade_stops_level=0, volume_min=0.01, volume_max=100,
                                   volume_step=0.01, filling_mode=1, trade_exemode=2)
        def terminal_info(self): return SimpleNamespace(connected=True, trade_allowed=True)
        def symbol_info_tick(self, symbol): return SimpleNamespace(ask=1.1002, bid=1.1000)
        def positions_get(self): return []
        def history_deals_get(self, start, end): return []
        def order_calc_profit(self, order_type, symbol, volume, entry, stop):
            return -abs(entry - stop) * 100000 * volume
        def order_calc_margin(self, order_type, symbol, volume, price): return volume * 100.0
        def order_check(self, request): return SimpleNamespace(retcode=10018, comment='market closed')
        def order_send(self, request):
            self.sent += 1
            return SimpleNamespace(retcode=10009, order=987654)

    fake = FakeMT5()
    signal = SimpleNamespace(direction='BUY', stop_loss=1.0990, take_profit=1.1020)
    assert agent.maybe_execute_order(fake, 'EURUSD', signal, 'M15', {'live_trading_allowed': True}) is None
    assert fake.sent == 0
