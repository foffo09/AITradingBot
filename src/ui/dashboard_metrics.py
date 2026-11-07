"""Pure dashboard summaries; amounts are USD and percentages use 0–100 units."""
import pandas as pd

from src.ui.presentation import finite_number, paper_metrics


def _utc(value):
    try:
        timestamp = pd.Timestamp(value)
        return timestamp.tz_convert('UTC') if not pd.isna(timestamp) and timestamp.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def dashboard_summary(scope, *, account=None, overview=None, positions=None, history=None, now=None):
    """Keep broker Paper separate from local ledger; None means unavailable."""
    if scope not in {'demo', 'simulation', 'paper'}:
        raise ValueError('Unknown dashboard scope')
    result = dict.fromkeys(('capital', 'equity', 'cash', 'daily_pnl', 'cumulative_pnl',
                            'drawdown', 'exposure_value', 'exposure_pct', 'fees'))
    result['source'] = scope
    account, overview = account or {}, overview or {}
    if scope == 'paper':
        metrics = paper_metrics(account, positions)
        result.update(equity=metrics['equity'], cash=metrics['cash'],
                      daily_pnl=metrics['daily_change'], exposure_value=metrics['market_value'])
    else:
        initial, rate = finite_number(account.get('initial_eur')), finite_number(account.get('eur_usd_rate'))
        if initial is not None and rate is not None and initial > 0 and rate > 0:
            result['capital'] = finite_number(initial * rate)
        for target, key in [('equity', 'current_capital'), ('cash', 'cash'),
                            ('cumulative_pnl', 'total_pnl'), ('exposure_value', 'market_value'), ('fees', 'fees')]:
            result[target] = finite_number(overview.get(key))
        curve = overview.get('equity_curve')
        if curve and all(finite_number(point.get('equity')) is not None for point in curve):
            result['drawdown'] = finite_number(overview.get('max_drawdown_pct'))
        if result['exposure_value'] is None and positions is not None:
            values = []
            for position in positions:
                value = finite_number(position.get('market_value'))
                if value is None:
                    quantity = finite_number(position.get('quantity'))
                    price = finite_number(position.get('market_price'))
                    value = finite_number(quantity * price) if quantity is not None and price is not None and price > 0 else None
                values.append(value)
            if all(value is not None for value in values):
                result['exposure_value'] = finite_number(sum(abs(value) for value in values))
        current = _utc(now) if now is not None else pd.Timestamp.now(tz='UTC')
        if history is not None and current is not None:
            daily = 0.0
            for row in history:
                if row.get('closed_at') is None:
                    continue
                closed = _utc(row['closed_at'])
                if closed is None or closed > current:
                    daily = None
                    break
                if closed.date() == current.date():
                    pnl = finite_number(row.get('net_pnl'))
                    if pnl is None:
                        daily = None
                        break
                    daily += pnl
            result['daily_pnl'] = finite_number(daily)
    equity, exposure = result['equity'], result['exposure_value']
    if equity is not None and equity > 0 and exposure is not None:
        result['exposure_pct'] = finite_number(exposure / equity * 100)
    return result


def market_summary(quote=None, data=None, quality=None, now=None):
    """Quote freshness is separate from historical last-close change_pct."""
    result = dict.fromkeys(('bid', 'ask', 'price', 'spread', 'spread_bps', 'change_pct',
                            'timestamp', 'source', 'age_seconds'))
    result['state'] = 'unavailable'
    current = _utc(now) if now is not None else pd.Timestamp.now(tz='UTC')
    quote = quote or {}
    if quote and quality == 'real':
        bid, ask = finite_number(quote.get('bid')), finite_number(quote.get('ask'))
        timestamp = _utc(quote.get('timestamp'))
        source = quote.get('source')
        real_source = source in {'Alpaca IEX latest quote', 'Alpaca Crypto latest quote'}
        age = (current - timestamp).total_seconds() if current is not None and timestamp is not None else None
        result['state'] = 'invalid'
        if age is not None:
            result['state'] = 'future' if age < 0 else 'stale' if age > 120 else 'invalid'
        if real_source and bid is not None and ask is not None and 0 < bid <= ask and age is not None and 0 <= age <= 120:
            midpoint = bid + (ask - bid) / 2
            result.update(bid=bid, ask=ask, price=midpoint, spread=ask - bid,
                          spread_bps=finite_number((ask - bid) / midpoint * 10000),
                          timestamp=timestamp.isoformat(), source=source, state='fresh', age_seconds=age)
    if data is not None and not data.empty and 'close' in data:
        attrs = data.attrs
        synthetic = (quality == 'synthetic' or attrs.get('quality') == 'synthetic'
                     or ('is_synthetic' in data and not data['is_synthetic'].eq(False).all())
                     or any(word in str(attrs.get('source', '')).lower() for word in ('demo', 'synthe', 'sinteti')))
        history_quality = 'synthetic' if synthetic else attrs.get('quality', quality)
        close = finite_number(data.iloc[-1]['close'])
        timestamp = _utc(data.iloc[-1].get('timestamp'))
        valid_history = (history_quality in {'real', 'synthetic'} and close is not None and close > 0
                         and timestamp is not None and current is not None and timestamp <= current)
        if valid_history:
            if len(data) >= 2:
                previous = finite_number(data.iloc[-2]['close'])
                previous_time = _utc(data.iloc[-2].get('timestamp'))
                if previous is not None and previous > 0 and previous_time is not None and previous_time < timestamp:
                    result['change_pct'] = finite_number((close / previous - 1) * 100)
            if result['state'] != 'fresh':
                result.update(price=close, timestamp=timestamp.isoformat(), source=attrs.get('source'),
                              state='synthetic' if synthetic else 'historical',
                              age_seconds=(current - timestamp).total_seconds())
    return result
