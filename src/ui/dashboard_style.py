"""Compact dark theme for the existing Streamlit dashboard."""
CSS = '''
<style>
:root { color-scheme: dark; }
.stApp { background: #0f172a; color: #e2e8f0; }
[data-testid="stHeader"] { background: rgba(15,23,42,.96); }
[data-testid="stSidebar"] { background: #111827; border-right: 1px solid #293548; }
.block-container { max-width: 1600px; padding: 1.1rem 1.5rem 1.5rem; }
h1 { letter-spacing: -.035em; font-weight: 750; margin-bottom: .25rem; }
h2,h3 { letter-spacing: -.02em; }
[data-testid="stVerticalBlock"] { gap: .65rem; }
[data-testid="stHorizontalBlock"] { gap: .8rem; }
[data-testid="stMetric"] { background: #1e293b; border: 1px solid #334155;
 border-radius: 12px; padding: .7rem .85rem; min-height: 82px; }
[data-testid="stMetricLabel"] { color: #aebbd0; font-size: .82rem; }
[data-testid="stMetricValue"] { color: #f1f5f9; font-variant-numeric: tabular-nums; }
[data-testid="stExpander"] { border: 1px solid #334155; border-radius: 10px; background: #172235; }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] { border-radius: 10px; border: 1px solid #293548; }
[data-testid="stAlert"] { border-radius: 8px; padding: .45rem .7rem; }
.stButton button[kind="primary"] { background: #7c3aed; border-color: #8b5cf6; }
.stButton button[kind="primary"]:hover { background: #6d28d9; border-color: #a78bfa; }
hr { border-color: #293548; margin: .6rem 0; }
@media (max-width: 720px) {
 .block-container { padding: .7rem .65rem 1rem; }
 [data-testid="stMetric"] { padding: .55rem .65rem; min-height: 72px; }
 [data-testid="stHorizontalBlock"] { gap: .45rem; }
}
</style>
'''
