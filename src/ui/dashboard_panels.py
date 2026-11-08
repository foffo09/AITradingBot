"""Display-only cards; account data is supplied by the owning workspace."""
import streamlit as st

from src.ui.dashboard_metrics import market_summary
from src.ui.presentation import money


def account_extras(values, label):
    cards = st.columns(4)
    cards[0].metric(f'Capitale iniziale {label}', money(values['capital']))
    cards[1].metric(f'Saldo disponibile {label}', money(values['cash']))
    cards[2].metric(f'P/L cumulativo {label}', money(values['cumulative_pnl']))
    cards[3].metric(f'Drawdown massimo {label}', 'N/D' if values['drawdown'] is None else f"{values['drawdown']:.2f}%")
    st.caption('Fonte: snapshot broker. Capitale iniziale, P/L cumulativo e drawdown N/D senza storico contabile verificato.'
               if label == 'Paper' else
               'Fonte: ledger del contesto selezionato, USD. Le stime di uscita del ledger sono incluse; drawdown dalla curva registrata.')


def risk_summary(values, label, *, trade_limit, exposure_limit, daily_loss_limit, order_limit,
                 offline, coordinator_available=False):
    st.markdown('**Rischio e controlli**')
    cards = st.columns(4)
    cards[0].metric(f'Esposizione {label} (USD)', money(values['exposure_value']))
    cards[1].metric(f'Esposizione {label} (%)', 'N/D' if values['exposure_pct'] is None else f"{values['exposure_pct']:.2f}%")
    cards[2].metric('Limite per trade', f'{trade_limit:.0%}')
    cards[3].metric('Limite perdita giornaliera', f'{daily_loss_limit:.0%}')
    st.caption(f'Esposizione massima: {exposure_limit:.0%} · Limite ordini Paper/giorno: {order_limit}. '
               'Il motore riverifica i controlli: questo riepilogo non autorizza ordini.')
    if offline:
        st.caption('Controlli broker: DISABILITATI — contesto offline. Le operazioni locali applicano i limiti del ledger.')
    else:
        st.caption('Permessi Paper: esecutore configurato.' if coordinator_available else
                   'Permessi Paper: BLOCCATI — esecutore esclusivo non configurato.')


def market_cards(quote, data, quality, symbol):
    view = market_summary(quote, data, quality)
    st.markdown(f'**{symbol} · mercato e provenienza**')
    cards = st.columns(5)
    cards[0].metric('Prezzo quotato' if view['state'] == 'fresh' else 'Ultimo close storico', money(view['price']))
    cards[1].metric('Bid', money(view['bid']))
    cards[2].metric('Ask', money(view['ask']))
    cards[3].metric('Spread (USD)', money(view['spread']), help='Ask meno bid; N/D senza quote corrente verificata.')
    cards[4].metric('Variazione ultime 2 chiusure', 'N/D' if view['change_pct'] is None else f"{view['change_pct']:+.2f}%",
                    help='Confronto storico fra barre, non variazione giornaliera del conto.')
    st.caption(f"Fonte: {view['source'] or 'N/D'} · Timestamp UTC: {view['timestamp'] or 'N/D'} · Stato: {view['state']}. Prezzi in USD.")
    if view['state'] != 'fresh':
        st.caption('Quotazione corrente N/D. Il close storico è un dato di analisi, non un prezzo eseguibile o un fallback realtime.')
