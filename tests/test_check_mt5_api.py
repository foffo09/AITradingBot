from scripts.check_mt5_api import steps


def connected_report(**market):
    return {'connection': {'status': 'connected'}, 'account_fields_present': ['currency', 'server', 'equity'],
            'diagnostics': {'phase': 'connected', 'worker': {'pid': 4321}}, 'service_exit_code': 0,
            'market': {'quote_timestamp': '2026-11-25T10:00:00+00:00', 'quote_age_s': 1.5, 'bars': 200,
                       'last_bar_age_s': 900, 'price_digits': 5, 'reason': None, **market}}


def test_all_steps_pass_only_with_fresh_quote_and_bars():
    assert all(ok for _, ok, _ in steps(connected_report()))


def test_server_time_rejection_fails_timestamp_step_and_shows_the_reason():
    reason = 'Terminal quote is stale or in the future (+7200 s vs UTC; MT5 server time may not be UTC).'
    result = {name: (ok, detail) for name, ok, detail in steps(connected_report(quote_timestamp=None, quote_age_s=None, bars=0, last_bar_age_s=None, reason=reason))}
    assert result['4 connection'][0] and not result['6 quote'][0] and not result['8 timestamps'][0]
    assert '+7200 s vs UTC' in result['6 quote'][1]


def test_no_terminal_reports_phase_and_skips_market_steps():
    report = {'connection': {'status': 'unavailable', 'reason': 'MetaTrader 5 is unsupported on this platform.'},
              'diagnostics': {'phase': 'platform', 'worker': None}, 'service_exit_code': 0}
    result = {name: (ok, detail) for name, ok, detail in steps(report)}
    assert [name for name, (ok, _) in result.items() if ok] == ['9 shutdown']
    assert result['7 bars'][1] == 'not read: no verified connection'
