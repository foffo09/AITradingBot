"""Single visual theme for the existing Streamlit dashboard."""
CSS = '''
<style>
:root { color-scheme: dark; }
.stApp { background: #0b1220; color: #e5edf8; }
[data-testid="stHeader"] { background: rgba(11,18,32,.94); }
[data-testid="stSidebar"] { background: #101b2c; border-right: 1px solid #24334b; }
.block-container { max-width: 1560px; padding-top: 2rem; padding-bottom: 3rem; }
h1 { letter-spacing: -.035em; font-weight: 750; }
h2,h3 { letter-spacing: -.02em; }
[data-testid="stMetric"] { background: #111e32; border: 1px solid #293b56;
 border-radius: 14px; padding: 1rem 1.15rem; min-height: 105px; }
[data-testid="stMetricLabel"] { color: #b7c8df; }
[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
[data-testid="stExpander"] { border: 1px solid #293b56; border-radius: 12px; background: #0f1a2a; }
[data-testid="stDataFrame"], [data-testid="stPlotlyChart"] { border-radius: 12px; border: 1px solid #24334b; }
[data-testid="stAlert"] { border-radius: 10px; }
.stButton button[kind="primary"] { background: #2563eb; border-color: #3b82f6; }
hr { border-color: #24334b; }
@media (max-width: 720px) { .block-container { padding: 1rem .7rem; }
 [data-testid="stMetric"] { padding: .7rem; min-height: 92px; } }
</style>
'''
