"""CSS block ל-Streamlit. מותאם מ-app_gpt_dashboard.py של billing_system.

צבעי מותג של חברת בנייה: כתום-אדמה (#D97706) במקום ירוק.
"""
from __future__ import annotations

# ── Loading veil (מסך טעינה ראשוני) ────────────────────────────
LOADING_VEIL = """
<style>
@keyframes _ca_boot_spin { to { transform: rotate(360deg); } }
@keyframes _ca_boot_pulse { 0%,100%{opacity:.4;} 50%{opacity:1;} }
@keyframes _ca_boot_force_fade {
   0%, 80% { opacity:1; pointer-events:auto; }
   100%    { opacity:0; pointer-events:none; }
}
#ca-boot-veil {
    position:fixed;inset:0;z-index:99998;
    background:linear-gradient(180deg,#F1F5F9 0%,#E2E8F0 100%);
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    font-family:'Inter','Segoe UI',Arial,sans-serif;direction:rtl;
    transition:opacity .35s ease;
    animation:_ca_boot_force_fade 5s ease forwards;
}
html:has(.top-bar) #ca-boot-veil,
html:has(.filter-marker) #ca-boot-veil,
html:has(.kpi-group-head) #ca-boot-veil,
html:has(.empty-state) #ca-boot-veil,
html:has(.exec-summary) #ca-boot-veil,
body:has(.top-bar) #ca-boot-veil,
body:has(.filter-marker) #ca-boot-veil,
body:has(.kpi-group-head) #ca-boot-veil,
body:has(.empty-state) #ca-boot-veil,
body:has(.exec-summary) #ca-boot-veil {
    opacity:0 !important;
    pointer-events:none !important;
    animation:none !important;
}
#ca-boot-veil .boot-spinner {
    width:54px;height:54px;border:5px solid #FED7AA;
    border-top-color:#D97706;border-radius:50%;
    animation:_ca_boot_spin .8s linear infinite;margin-bottom:22px;
}
#ca-boot-veil .boot-title {
    font-size:16px;font-weight:800;color:#7C2D12;letter-spacing:.2px;
    margin-bottom:4px;
}
#ca-boot-veil .boot-sub {
    font-size:12.5px;color:#64748B;
    animation:_ca_boot_pulse 1.4s ease-in-out infinite;
}
</style>
<div id="ca-boot-veil">
  <div class="boot-spinner"></div>
  <div class="boot-title">טוען נתוני ביקורת…</div>
  <div class="boot-sub">מ. אילון אביב נכסים בע"מ · מערכת ביקורת פרויקטים</div>
</div>
"""


# ── CSS ראשי ──────────────────────────────────────────────────
MAIN_CSS = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

/* ═══ Brand palette - construction (orange/earth) ═══ */
:root {
  --brand-primary:      #D97706;
  --brand-primary-dark: #7C2D12;
  --brand-primary-soft: #FFF7ED;
  --brand-primary-mid:  #FED7AA;
  --status-good:        #059669;
  --status-good-soft:   #F0FDF4;
  --status-good-border: #BBF7D0;
  --status-warn:        #D97706;
  --status-warn-soft:   #FFFBEB;
  --status-warn-border: #FDE68A;
  --status-bad:         #DC2626;
  --status-bad-soft:    #FEF2F2;
  --status-bad-border:  #FECACA;
  --status-info:        #2563EB;
  --status-info-soft:   #EFF6FF;
  --status-info-border: #BFDBFE;
  --ink-strong:         #0F172A;
  --ink-mid:            #475569;
  --ink-soft:           #64748B;
  --ink-faint:          #94A3B8;
  --line:               #E2E8F0;
  --line-faint:         #F1F5F9;
  --bg-card:            #FFFFFF;
  --bg-page:            #F8FAFC;
}

html,body,.stApp{direction:rtl;font-family:'Inter','Segoe UI',Arial,sans-serif;
  background:#F0F4F8;overflow-x:hidden!important;}

/* Hide Streamlit chrome - we own the header */
#MainMenu, footer, header[data-testid="stHeader"]{visibility:hidden!important;height:0!important;}
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], .stDeployButton,
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"]{display:none!important;}
section[data-testid="stSidebar"],[data-testid="collapsedControl"]{display:none!important;}
footer{display:none!important;}
*,*::before,*::after{box-sizing:border-box;}
.block-container{padding:0 1.5rem 4rem!important;max-width:100%!important;overflow-x:hidden!important;}

/* ═══ Top bar (sticky) ═══ */
.top-bar{background:linear-gradient(135deg,#7C2D12 0%,#9A3412 55%,#D97706 100%);
  color:#fff;height:62px;width:100%;display:flex;align-items:center;
  justify-content:space-between;padding:0 1.5rem;margin-bottom:18px;
  box-shadow:0 2px 12px rgba(124,45,18,.35);
  border-radius:0 0 14px 14px;position:sticky;top:0;z-index:100;}
.top-bar-brand{display:flex;align-items:center;gap:12px;}
.top-bar-logo{height:42px;width:42px;border-radius:50%;background:#fff;
  display:inline-flex;align-items:center;justify-content:center;font-size:22px;
  box-shadow:0 1px 4px rgba(0,0,0,.2),0 0 0 1.5px rgba(217,119,6,0.5);}
.top-bar-title{font-size:16px;font-weight:800;letter-spacing:-.2px;
  display:flex;align-items:center;}
.top-bar-title .ltd{font-weight:600;opacity:.85;}
.top-bar-title .sep{opacity:.5;margin:0 8px;}
.top-bar-title .sys{font-weight:600;opacity:.9;font-size:13.5px;}
.top-bar-actions{display:flex;align-items:center;gap:10px;}

.sys-pill{display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);
  color:#fff;font-size:11px;font-weight:700;padding:5px 11px;border-radius:99px;
  backdrop-filter:blur(4px);}
.sys-pill .dot{width:7px;height:7px;border-radius:50%;background:#22C55E;
  box-shadow:0 0 8px #22C55E;display:inline-block;}
.sys-pill.warn{background:rgba(217,119,6,.3);border-color:rgba(253,230,138,.5);}
.sys-pill.warn .dot{background:#FBBF24;box-shadow:0 0 6px #FBBF24;}
.sys-pill.bad{background:rgba(220,38,38,.3);border-color:rgba(254,202,202,.5);}
.sys-pill.bad .dot{background:#F87171;box-shadow:0 0 6px #F87171;}
.meta-pill{display:inline-flex;align-items:center;gap:6px;
  background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);
  color:#FFF7ED;font-size:11px;font-weight:500;padding:5px 11px;border-radius:99px;}
.meta-pill i.ti{font-size:13px;color:#FED7AA;}

/* Tabs strip sticky just under top bar */
[data-baseweb="tab-list"]{position:sticky!important;top:62px!important;
  z-index:90!important;background:#F0F4F8;padding-top:4px;}

/* ═══ Filter card ═══ */
[data-testid="stVerticalBlock"]:has(.filter-marker){
  background:#FFFFFF;border:1px solid var(--line);border-radius:14px;
  padding:14px 16px 6px;margin-bottom:16px;
  box-shadow:0 1px 4px rgba(15,23,42,.04);position:relative;}
[data-testid="stVerticalBlock"]:has(.filter-marker)::before{
  content:"";display:block;position:absolute;top:-1px;right:-1px;left:-1px;
  height:3px;border-radius:14px 14px 0 0;
  background:linear-gradient(90deg,#7C2D12 0%,#D97706 50%,#FBBF24 100%);}
.filter-marker{font-size:11px;font-weight:800;color:#475569;
  text-transform:uppercase;letter-spacing:1.2px;margin-bottom:8px;
  display:flex;align-items:center;gap:6px;}
.filter-marker::before{content:"\\f1c1";font-family:"tabler-icons";
  color:var(--brand-primary);font-size:16px;font-weight:normal;letter-spacing:0;}
[data-testid="stVerticalBlock"]:has(.filter-marker) [data-testid="stWidgetLabel"],
[data-testid="stVerticalBlock"]:has(.filter-marker) label{
  font-size:11px!important;font-weight:600!important;color:var(--ink-soft)!important;}

/* ═══ KPI groups ═══ */
.kpi-group{margin-bottom:14px;}
.kpi-group-head{font-size:11px;font-weight:800;color:#475569;
  text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px;
  display:flex;align-items:center;gap:8px;padding:0 2px;}
.kpi-group-head i.ti{font-size:16px;color:var(--brand-primary);}
.kpi-group-head .kpi-group-count{margin-right:auto;font-size:10px;
  font-weight:600;color:#94A3B8;letter-spacing:.3px;text-transform:none;}

.kpi-strip{display:grid;gap:10px;margin-bottom:8px;align-items:stretch;}
.kpi-cell{background:#fff;border:0.5px solid #E8EAED;border-radius:12px;
  border-top:3px solid transparent;padding:14px 14px 10px;
  position:relative;direction:rtl;display:flex;flex-direction:column;
  min-width:0;overflow:hidden;
  box-shadow:0 1px 3px rgba(0,0,0,.04),0 0 0 0.5px rgba(0,0,0,.015);
  transition:box-shadow .15s,transform .15s;}
.kpi-cell:hover{box-shadow:0 6px 18px rgba(15,23,42,.10);transform:translateY(-2px);}
.kpi-cell[data-accent="orange"]{border-top-color:#D97706;}
.kpi-cell[data-accent="green"]{border-top-color:#16A34A;}
.kpi-cell[data-accent="red"]{border-top-color:#DC2626;}
.kpi-cell[data-accent="amber"]{border-top-color:#F59E0B;}
.kpi-cell[data-accent="blue"]{border-top-color:#2563EB;}
.kpi-cell[data-accent="slate"]{border-top-color:#64748B;}
.kpi-lbl{font-size:11px;font-weight:600;color:#64748B;margin-bottom:6px;
  display:flex;align-items:center;gap:5px;line-height:1.2;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kpi-lbl i.ti{font-size:14px;color:var(--brand-primary);}
.kpi-val{font-size:24px;font-weight:700;color:#0F172A;line-height:1.15;
  letter-spacing:-.5px;direction:ltr;text-align:right;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.kpi-delta{font-size:10.5px;font-weight:600;margin-top:auto;padding-top:6px;
  color:#64748B;min-height:0;line-height:1.5;direction:rtl;text-align:right;
  word-break:break-word;}
.kpi-delta:not(:empty){padding-top:8px;border-top:1px dashed #E5E7EB;}
.kpi-chip-row{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px;direction:rtl;}
.kpi-delta:empty + .kpi-chip-row{margin-top:9px;padding-top:8px;
  border-top:1px dashed #E5E7EB;}
.kpi-chip{display:inline-flex;align-items:center;background:#F8FAFC;color:#64748B;
  padding:3px 7px;border-radius:6px;font-size:10px;font-weight:600;line-height:1.35;
  border:1px solid #E2E8F0;white-space:nowrap;font-variant-numeric:tabular-nums;}
.kpi-chip:hover{background:var(--brand-primary-soft);
  border-color:var(--brand-primary-mid);color:var(--brand-primary-dark);}
.up-bad{color:var(--status-bad);}
.dn-good{color:var(--status-good);}
.neutral{color:var(--ink-faint);}

/* ═══ Section heading ═══ */
.sec{font-size:13px;font-weight:800;color:var(--ink-strong);
  letter-spacing:.2px;padding:18px 0 10px;border-bottom:2px solid var(--brand-primary);
  margin:8px 0 16px;display:flex;align-items:center;gap:8px;}
.sec::before{content:"";display:inline-block;width:3px;height:18px;
  background:var(--brand-primary);border-radius:2px;}
.sec .sec-meta{margin-right:auto;font-size:11px;font-weight:600;color:var(--ink-soft);
  letter-spacing:0;text-transform:none;}

/* ═══ Block card ═══ */
.blk{background:var(--bg-card);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin-bottom:12px;box-shadow:0 1px 4px rgba(0,0,0,.05);}
.blk-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.8px;
  color:var(--ink-faint);margin-bottom:10px;}
.blk-body{font-size:13px;color:var(--ink-strong);line-height:1.75;}
.blk.warm{background:var(--brand-primary-soft);border-color:var(--brand-primary-mid);}
.blk.dark{background:var(--ink-strong);border-color:var(--ink-strong);
  box-shadow:0 3px 14px rgba(15,23,42,.35);}
.blk.dark .blk-lbl{color:var(--ink-mid);font-size:10px;}
.blk.dark .blk-body{color:#F1F5F9;font-weight:800;font-size:16px;line-height:1.4;}

/* ═══ Insight cards (colored borders) ═══ */
.ins{border-radius:10px;padding:13px 16px;margin-bottom:9px;
  display:flex;gap:12px;align-items:flex-start;border:1px solid;
  box-shadow:0 1px 3px rgba(0,0,0,.04);}
.ins.red{background:var(--status-bad-soft);border-color:var(--status-bad-border);
  border-right:3px solid var(--status-bad);}
.ins.amber{background:var(--status-warn-soft);border-color:var(--status-warn-border);
  border-right:3px solid var(--status-warn);}
.ins.green{background:var(--status-good-soft);border-color:var(--status-good-border);
  border-right:3px solid var(--status-good);}
.ins.blue{background:var(--status-info-soft);border-color:var(--status-info-border);
  border-right:3px solid var(--status-info);}
.ins-icon{font-size:18px;flex-shrink:0;margin-top:1px;}
.ins-title{font-size:12px;font-weight:700;color:var(--ink-strong);margin-bottom:3px;}
.ins-body{font-size:11px;color:#4B5563;line-height:1.55;}

/* ═══ Executive summary card ═══ */
.exec-summary{background:#FFFFFF;border:1px solid var(--line);border-radius:16px;
  padding:0;margin:0 0 18px;box-shadow:0 4px 14px rgba(15,23,42,.06);overflow:hidden;}
.exec-summary-head{padding:14px 20px;display:flex;align-items:center;
  justify-content:space-between;flex-wrap:wrap;gap:12px;
  background:linear-gradient(90deg,#F8FAFC 0%,#FFFFFF 100%);
  border-bottom:1px solid var(--line);}
.exec-summary-title{font-size:15px;font-weight:800;color:#0F172A;
  letter-spacing:-.1px;display:flex;align-items:center;gap:9px;}
.exec-summary-title i.ti{font-size:22px;color:var(--brand-primary);}
.exec-summary-status{display:inline-flex;align-items:center;gap:6px;
  padding:6px 14px;border-radius:99px;font-size:12px;font-weight:800;
  letter-spacing:.4px;white-space:nowrap;}
.exec-summary-status.good{background:var(--status-good-soft);
  color:var(--status-good);border:1px solid var(--status-good-border);}
.exec-summary-status.warn{background:var(--status-warn-soft);
  color:var(--status-warn);border:1px solid var(--status-warn-border);}
.exec-summary-status.bad{background:var(--status-bad-soft);
  color:var(--status-bad);border:1px solid var(--status-bad-border);}
.exec-summary-status::before{content:"";width:8px;height:8px;
  border-radius:50%;background:currentColor;}
.exec-summary-body{display:grid;grid-template-columns:repeat(3,1fr);
  padding:18px 20px;gap:18px;}
.exec-sum-q{display:flex;flex-direction:column;gap:5px;min-width:0;}
.exec-sum-q-label{font-size:10.5px;font-weight:800;color:#94A3B8;
  text-transform:uppercase;letter-spacing:1.2px;}
.exec-sum-q-value{font-size:20px;font-weight:800;color:#0F172A;
  letter-spacing:-.4px;display:flex;align-items:center;gap:8px;
  line-height:1.25;word-break:break-word;}
.exec-sum-q-sub{font-size:11.5px;color:#64748B;line-height:1.4;}
@media (max-width:900px){.exec-summary-body{grid-template-columns:1fr;}}

/* ═══ Empty state ═══ */
.empty-state{background:#FFFFFF;border:1px solid var(--line);border-radius:14px;
  padding:36px 28px;margin:16px 0;text-align:center;
  box-shadow:0 1px 4px rgba(15,23,42,.04);max-width:620px;
  margin-left:auto;margin-right:auto;}
.empty-state-icon{font-size:48px;color:var(--brand-primary-mid);line-height:1;margin-bottom:10px;}
.empty-state-icon i.ti{font-size:48px;}
.empty-state-title{font-size:16px;font-weight:800;color:#0F172A;margin-bottom:8px;}
.empty-state-body{font-size:12.5px;color:#475569;line-height:1.6;}
.empty-state-body ul{list-style:disc;padding-right:20px!important;
  list-style-position:inside;text-align:right;}
.empty-state-body li{margin-bottom:3px;}
.empty-state-body code{background:#F1F5F9;padding:2px 6px;border-radius:4px;
  font-size:11px;color:var(--brand-primary-dark);font-family:'Courier New',monospace;}
.empty-state-action{font-size:13px;color:var(--brand-primary-dark);
  background:var(--brand-primary-soft);border:1px solid var(--brand-primary-mid);
  border-radius:10px;padding:10px 14px;margin-top:14px;font-weight:600;
  display:inline-block;}

/* ═══ Plotly chart frames ═══ */
[data-testid="stPlotlyChart"]{
  background:var(--bg-card);border:1px solid var(--line);border-radius:10px;
  padding:8px 6px 4px;margin-bottom:6px;
  box-shadow:0 1px 3px rgba(0,0,0,.03);overflow:hidden;}
[data-testid="stPlotlyChart"] .js-plotly-plot{max-width:100%;}
[data-testid="stPlotlyChart"] .modebar{display:none!important;}
[data-testid="stPlotlyChart"] .js-plotly-plot .main-svg{background:transparent!important;}

/* ═══ DataFrame styling ═══ */
[data-testid="stDataFrame"]{border-radius:10px!important;overflow:hidden;
  border:1px solid #E2E8F0!important;}
[data-testid="stDataFrame"] th{font-size:10px!important;font-weight:700!important;
  background:#F8FAFC!important;color:#475569!important;padding:10px 14px!important;
  text-transform:uppercase;letter-spacing:.4px;border-bottom:2px solid #E2E8F0!important;}
[data-testid="stDataFrame"] td{font-size:12px!important;padding:11px 14px!important;
  border-bottom:1px solid #F1F5F9!important;color:#0F172A!important;}
[data-testid="stDataFrame"] tr:nth-child(even) td{background:#FAFBFD!important;}
[data-testid="stDataFrame"] tr:hover td{background:#FFF7ED!important;cursor:default;}

/* ═══ Buttons ═══ */
button[kind="primary"]{transition:all .2s;}
button[kind="primary"]:hover{transform:translateY(-1px);
  box-shadow:0 4px 12px rgba(217,119,6,.35);}
[data-testid="stFormSubmitButton"]>button{
  background:linear-gradient(135deg,#D97706 0%,#B45309 100%)!important;
  border-color:#D97706!important;color:#fff!important;font-weight:700!important;}
[data-testid="stFormSubmitButton"]>button:hover{
  background:linear-gradient(135deg,#B45309 0%,#92400E 100%)!important;
  box-shadow:0 4px 14px rgba(217,119,6,.4)!important;transform:translateY(-1px);}

/* ═══ Expanders ═══ */
[data-testid="stExpander"] details summary{
  font-weight:700!important;color:var(--ink-strong)!important;
  background:#FAFBFD!important;border-radius:10px!important;padding:10px 14px!important;}
[data-testid="stExpander"] details[open] summary{
  background:var(--brand-primary-soft)!important;
  border-bottom:1px solid var(--brand-primary-mid)!important;
  border-radius:10px 10px 0 0!important;}
[data-testid="stExpander"]{border:1px solid var(--line)!important;
  border-radius:10px!important;margin-bottom:14px!important;
  box-shadow:0 1px 3px rgba(0,0,0,.03);}

/* ═══ Metric components ═══ */
[data-testid="stMetric"]{background:var(--bg-card);border:1px solid var(--line);
  border-radius:10px;padding:12px 14px;}
[data-testid="stMetricLabel"]{font-size:11px!important;color:var(--ink-soft)!important;
  font-weight:600!important;letter-spacing:.2px!important;}
[data-testid="stMetricValue"]{font-size:20px!important;font-weight:700!important;
  color:var(--ink-strong)!important;letter-spacing:-.3px!important;}
[data-testid="stMetricDelta"]{font-size:11px!important;font-weight:600!important;}

/* ═══ Sliders RTL fix ═══ */
[data-testid="stSlider"]{direction:ltr!important;}
[data-testid="stSlider"] label{direction:rtl!important;text-align:right!important;display:block!important;}
[data-testid="stSlider"] [data-baseweb="slider"]{direction:ltr!important;}

/* ═══ HR softer ═══ */
hr{border:none!important;border-top:1px dashed var(--line)!important;
  margin:18px 0!important;opacity:.85;}

/* ═══ Markdown headers ═══ */
.stMarkdown h5, .stMarkdown h4{
  font-size:14px!important;font-weight:800!important;color:#0F172A!important;
  margin:14px 0 6px!important;letter-spacing:-.1px;}

/* ═══ Status pill for tables ═══ */
.status-pill{display:inline-block;padding:3px 9px;border-radius:99px;
  font-size:11px;font-weight:700;letter-spacing:.2px;}
.status-pill.ok{background:var(--status-good-soft);color:var(--status-good);
  border:1px solid var(--status-good-border);}
.status-pill.warn{background:var(--status-warn-soft);color:var(--status-warn);
  border:1px solid var(--status-warn-border);}
.status-pill.crit{background:var(--status-bad-soft);color:var(--status-bad);
  border:1px solid var(--status-bad-border);}
</style>
"""
