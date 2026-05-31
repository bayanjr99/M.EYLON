"""CSS block ל-Streamlit. מותאם מ-app_gpt_dashboard.py של billing_system.

צבעי מותג: ירוק (#16A34A) לפי הלוגו של "מ. אילון אביב נכסים בע"מ" -
חברת עבודות עפר וניפוץ עם זהות סביבתית.
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
    width:54px;height:54px;border:5px solid #BBF7D0;
    border-top-color:#16A34A;border-radius:50%;
    animation:_ca_boot_spin .8s linear infinite;margin-bottom:22px;
}
#ca-boot-veil .boot-title {
    font-size:16px;font-weight:800;color:#0E5A2E;letter-spacing:.2px;
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

/* ═══ Brand palette - environmental green per company logo ═══ */
:root {
  --brand-primary:      #16A34A;
  --brand-primary-dark: #0E5A2E;
  --brand-primary-soft: #F0FDF4;
  --brand-primary-mid:  #BBF7D0;
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
/* Hide Streamlit Community Cloud "Manage app" viewer badge + host chrome */
[data-testid="stStatusWidgetContainer"],
.viewerBadge_container__1QSob, .viewerBadge_link__qRIco,
div[class*="viewerBadge"], .stActionButton,
a[href*="streamlit.io/cloud"], a[href*="share.streamlit.io"]{display:none!important;}
*,*::before,*::after{box-sizing:border-box;}
.block-container{padding:0 1.5rem 4rem!important;max-width:100%!important;overflow-x:hidden!important;}

/* ═══ Top bar (sticky) ═══ */
.top-bar{background:linear-gradient(135deg,#052E16 0%,#0E5A2E 55%,#16A34A 100%);
  color:#fff;height:62px;width:100%;display:flex;align-items:center;
  justify-content:space-between;padding:0 1.5rem;margin-bottom:18px;
  box-shadow:0 2px 12px rgba(5,46,22,.35);
  border-radius:0 0 14px 14px;position:sticky;top:0;z-index:100;}
.top-bar-brand{display:flex;align-items:center;gap:12px;}
.top-bar-logo{height:42px;width:42px;border-radius:50%;background:#fff;
  display:inline-flex;align-items:center;justify-content:center;font-size:22px;
  box-shadow:0 1px 4px rgba(0,0,0,.2),0 0 0 1.5px rgba(22,163,74,0.5);}
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
  color:#F0FDF4;font-size:11px;font-weight:500;padding:5px 11px;border-radius:99px;}
.meta-pill i.ti{font-size:13px;color:#BBF7D0;}

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
  background:linear-gradient(90deg,#0E5A2E 0%,#16A34A 50%,#22C55E 100%);}
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

/* ═══ Responsive: מסכים קטנים / מובייל (פריט 19) ═══ */
/* רוחב ביניים — מקטינים מעט את ערך ה-KPI כדי שלא ייחתך */
@media (max-width:1200px){
  .kpi-val{font-size:20px;letter-spacing:-.4px;}
}
/* טאבלט — עוטפים את ה-strip ל-3 עמודות במקום N קבוע */
@media (max-width:992px){
  .kpi-strip{grid-template-columns:repeat(3,minmax(0,1fr))!important;}
  .kpi-val{font-size:19px;}
}
/* מובייל — 2 עמודות, ערך קצת קטן יותר, וכותרת יכולה להישבר */
@media (max-width:640px){
  .kpi-strip{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
  .kpi-val{font-size:18px;}
  .kpi-lbl{white-space:normal;}
  .block-container{padding-left:.75rem!important;padding-right:.75rem!important;}
  .exec-sum-q-value{font-size:17px;}
}

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
[data-testid="stDataFrame"] tr:hover td{background:#F0FDF4!important;cursor:default;}

/* ═══ Buttons ═══ */
button[kind="primary"]{transition:all .2s;}
button[kind="primary"]:hover{transform:translateY(-1px);
  box-shadow:0 4px 12px rgba(22,163,74,.35);}
[data-testid="stFormSubmitButton"]>button{
  background:linear-gradient(135deg,#16A34A 0%,#0E5A2E 100%)!important;
  border-color:#16A34A!important;color:#fff!important;font-weight:700!important;}
[data-testid="stFormSubmitButton"]>button:hover{
  background:linear-gradient(135deg,#0E5A2E 0%,#052E16 100%)!important;
  box-shadow:0 4px 14px rgba(22,163,74,.4)!important;transform:translateY(-1px);}

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
.status-pill.info{background:#EFF6FF;color:#1D4ED8;border:1px solid #BFDBFE;}
.status-pill.neutral{background:#F1F5F9;color:#475569;border:1px solid #CBD5E1;}

/* ═══════════════════════════════════════════════════════════════════
   POLISH LAYER - מעובד מ-app_gpt_dashboard.py של billing_system.
   שכבת עידונים אדיטיבית; לא לגעת בכללים מעל. כל המחלקות החדשות
   זמינות לשימוש ב-app.py דרך st.markdown(..., unsafe_allow_html=True).
   ══════════════════════════════════════════════════════════════════ */

/* --- Tabs as polished pill navigation -------------------------- */
[data-baseweb="tab-list"]{
  background:#FFFFFF!important;border:1px solid var(--line)!important;
  border-radius:14px!important;padding:6px!important;gap:4px!important;
  box-shadow:0 1px 4px rgba(15,23,42,.04);margin-bottom:14px!important;
  overflow:visible!important;}
[data-baseweb="tab-list"] button[data-baseweb="tab"]{
  background:transparent!important;border-radius:10px!important;
  font-weight:700!important;font-size:13px!important;
  color:var(--ink-mid)!important;
  padding:9px 16px!important;height:auto!important;
  transition:background .15s,color .15s,box-shadow .15s!important;
  border:none!important;}
[data-baseweb="tab-list"] button[data-baseweb="tab"]:hover{
  background:var(--brand-primary-soft)!important;color:var(--brand-primary-dark)!important;}
[data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"]{
  background:linear-gradient(135deg,#0E5A2E 0%,#16A34A 100%)!important;
  color:#FFFFFF!important;
  box-shadow:0 3px 10px rgba(22,163,74,.32)!important;}
[data-baseweb="tab-list"] [data-baseweb="tab-highlight"],
[data-baseweb="tab-list"] [data-baseweb="tab-border"]{display:none!important;}

/* nested tabs (sub-tabs) — slightly smaller pills */
[data-baseweb="tab-panel"] [data-baseweb="tab-list"]{
  padding:5px!important;background:#FAFBFD!important;}
[data-baseweb="tab-panel"] [data-baseweb="tab-list"] button[data-baseweb="tab"]{
  font-size:12px!important;padding:7px 14px!important;}

/* --- Tables: sticky header + frozen first column + better hover ----- */
[data-testid="stDataFrame"] [data-testid="StyledDataFrameDataCell"]{
  font-variant-numeric:tabular-nums;}
[data-testid="stDataFrame"]{max-height:60vh!important;}
[data-testid="stDataFrame"] thead th{
  position:sticky!important;top:0!important;z-index:5!important;
  background:#F1F5F9!important;
  box-shadow:inset 0 -2px 0 #CBD5E1;}
[data-testid="stDataFrame"] tbody td:first-child,
[data-testid="stDataFrame"] thead th:first-child{
  position:sticky!important;right:0!important;z-index:4!important;
  background:#F8FAFC!important;
  box-shadow:-2px 0 0 #E2E8F0;}
[data-testid="stDataFrame"] thead th:first-child{z-index:6!important;}
[data-testid="stDataFrame"] tr:hover td:last-child{
  box-shadow:inset -3px 0 0 var(--brand-primary);}

/* --- CSV download buttons under tables: clearer affordance --------- */
.stDownloadButton button{
  border:1px solid var(--brand-primary)!important;
  color:var(--brand-primary-dark)!important;background:#fff!important;
  font-weight:700!important;}
.stDownloadButton button:hover{
  background:var(--brand-primary-soft)!important;
  box-shadow:0 3px 10px rgba(22,163,74,.18)!important;}

/* --- Section card: clean wrapper for in-tab content blocks --------- */
.section-card{background:#FFFFFF;border:1px solid var(--line);
  border-radius:14px;padding:18px 20px;margin-bottom:14px;
  box-shadow:0 1px 4px rgba(15,23,42,.04);}
.section-card-title{font-size:13px;font-weight:800;color:var(--ink-strong);
  margin-bottom:12px;display:flex;align-items:center;gap:8px;
  padding-bottom:10px;border-bottom:1px solid var(--line-faint);}
.section-card-title i.ti{font-size:18px;color:var(--brand-primary);}
.section-card-title .badge{margin-right:auto;font-size:11px;font-weight:700;
  background:var(--brand-primary-soft);color:var(--brand-primary-dark);
  border:1px solid var(--brand-primary-mid);padding:2px 9px;border-radius:99px;}

/* --- Focus alert: prominent strip for critical signals ------------- */
.focus{padding:13px 18px;border-radius:10px;font-size:13.5px;font-weight:700;
  margin-bottom:16px;border:1px solid;border-right-width:4px;
  box-shadow:0 1px 4px rgba(0,0,0,.06);}
.focus.red{background:var(--status-bad-soft);border-color:var(--status-bad-border);
  border-right-color:var(--status-bad);color:#7F1D1D;}
.focus.amber{background:var(--status-warn-soft);border-color:var(--status-warn-border);
  border-right-color:var(--status-warn);color:#78350F;}
.focus.green{background:var(--status-good-soft);border-color:var(--status-good-border);
  border-right-color:var(--status-good);color:#14532D;}
.focus.blue{background:var(--status-info-soft);border-color:var(--status-info-border);
  border-right-color:var(--status-info);color:#1E3A8A;}

/* --- Executive insight card: problem · impact · who · action · priority */
.exec-insight{background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;margin-bottom:10px;display:grid;
  grid-template-columns:auto 1fr auto;gap:10px 16px;align-items:start;
  box-shadow:0 1px 3px rgba(15,23,42,.04);
  border-right:4px solid var(--ink-faint);transition:box-shadow .15s,transform .15s;}
.exec-insight:hover{box-shadow:0 6px 16px rgba(15,23,42,.10);transform:translateY(-1px);}
.exec-insight[data-priority="high"]{border-right-color:var(--status-bad);}
.exec-insight[data-priority="med"]{border-right-color:var(--status-warn);}
.exec-insight[data-priority="low"]{border-right-color:var(--status-good);}
.exec-insight-icon{font-size:22px;line-height:1;padding-top:2px;}
.exec-insight-body{display:flex;flex-direction:column;gap:6px;min-width:0;}
.exec-insight-problem{font-size:13.5px;font-weight:800;color:var(--ink-strong);
  line-height:1.4;}
.exec-insight-meta{display:flex;flex-wrap:wrap;gap:6px 10px;font-size:11px;
  color:var(--ink-mid);align-items:center;}
.exec-insight-tag{display:inline-flex;align-items:center;gap:4px;
  padding:3px 9px;border-radius:99px;background:#F8FAFC;
  border:1px solid var(--line);font-weight:600;font-size:11px;color:var(--ink-mid);}
.exec-insight-tag.impact{background:var(--status-bad);
  border-color:var(--status-bad);color:#fff;font-variant-numeric:tabular-nums;}
.exec-insight-tag.impact.positive{background:var(--status-good);
  border-color:var(--status-good);color:#fff;}
.exec-insight-tag.who{background:var(--brand-primary-soft);
  border-color:var(--brand-primary-mid);color:var(--brand-primary-dark);}
.exec-insight-action{font-size:12px;color:var(--ink-mid);
  background:var(--bg-page);border-radius:8px;padding:7px 10px;
  border-right:2px solid var(--brand-primary);line-height:1.5;}
.exec-insight-action b{color:var(--brand-primary-dark);}
.exec-priority-pill{display:inline-flex;align-items:center;gap:5px;
  padding:5px 11px;border-radius:99px;font-size:10.5px;font-weight:800;
  text-transform:uppercase;letter-spacing:.8px;white-space:nowrap;
  align-self:start;margin-top:2px;}
.exec-priority-pill[data-priority="high"]{background:var(--status-bad-soft);
  color:var(--status-bad);border:1px solid var(--status-bad-border);}
.exec-priority-pill[data-priority="med"]{background:var(--status-warn-soft);
  color:var(--status-warn);border:1px solid var(--status-warn-border);}
.exec-priority-pill[data-priority="low"]{background:var(--status-good-soft);
  color:var(--status-good);border:1px solid var(--status-good-border);}

/* --- Executive banner (for conclusions / summary tabs) ------------- */
.exec-banner{background:linear-gradient(135deg,#0E5A2E 0%,#16A34A 50%,#22C55E 100%);
  color:#fff;border-radius:14px;padding:18px 22px;margin-bottom:16px;
  box-shadow:0 8px 24px rgba(22,163,74,.22);display:flex;
  align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
.exec-banner-title{font-size:15px;font-weight:800;letter-spacing:.2px;
  display:flex;align-items:center;gap:9px;}
.exec-banner-title i.ti{font-size:22px;opacity:.95;}
.exec-banner-sub{font-size:11px;opacity:.85;font-weight:500;
  margin-top:3px;letter-spacing:.3px;}
.exec-banner-stats{display:flex;gap:18px;align-items:center;}
.exec-stat{text-align:right;}
.exec-stat-val{font-size:18px;font-weight:800;line-height:1.1;
  font-variant-numeric:tabular-nums;}
.exec-stat-lbl{font-size:10px;opacity:.8;letter-spacing:.6px;
  text-transform:uppercase;margin-top:2px;}

/* --- Period header (top of any tab: date range + scope counts) ----- */
.period-header{background:linear-gradient(135deg,#F8FAFC,#F1F5F9);
  border:1px solid #E2E8F0;border-radius:10px;padding:10px 16px;
  margin:0 0 14px;display:flex;justify-content:space-between;
  align-items:center;font-size:13px;color:#475569;}
.period-header b{color:#0F172A;}
.period-header .sep{opacity:.5;margin:0 6px;}
.period-header .tag{font-size:11px;opacity:.6;letter-spacing:.05em;}

/* --- Non-primary buttons: subtle base hover with brand tint -------- */
.stButton > button{transition:all .15s;border-radius:10px!important;
  font-weight:700!important;}
.stButton > button:hover{box-shadow:0 3px 10px rgba(22,163,74,.18);
  border-color:var(--brand-primary)!important;}

/* --- Caption: tighter, gentler ------------------------------------- */
.stCaption{font-size:11.5px!important;color:var(--ink-soft)!important;}

/* --- Selectbox / multiselect: brand focus ring -------------------- */
[data-baseweb="select"]:focus-within > div{
  border-color:var(--brand-primary)!important;
  box-shadow:0 0 0 2px rgba(22,163,74,.18)!important;}

/* --- KPI cells: hover chip-row reveal (drill on hover) ------------- */
.kpi-cell .kpi-chip-row + .kpi-chip-row{
  max-height:0;opacity:0;overflow:hidden;margin-top:0;padding:0;
  transition:max-height .25s ease,opacity .2s ease,margin-top .25s,padding .25s;}
.kpi-cell:hover .kpi-chip-row + .kpi-chip-row{
  max-height:60px;opacity:1;margin-top:4px;}
.kpi-cell:has(.kpi-chip-row + .kpi-chip-row) .kpi-chip-row:first-of-type::after{
  content:"…";color:#94A3B8;font-weight:700;font-size:11px;
  margin-right:auto;padding:0 4px;align-self:center;}

/* --- Section breathing room: gentler gaps between vertical blocks --- */
.block-container > div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"]{
  gap:14px;}

/* --- Plotly chart inner-padding ------------------------------- */
[data-testid="stPlotlyChart"] + .stCaption,
[data-testid="stPlotlyChart"] + div .stCaption{
  font-size:11px!important;color:var(--ink-soft)!important;
  font-style:italic;margin-top:-2px!important;margin-bottom:10px!important;
  padding:0 4px;line-height:1.5;}

/* --- Expander dataframe: drop inner border to avoid double-border --- */
[data-testid="stExpander"] [data-testid="stDataFrame"]{
  border:none!important;border-radius:8px!important;}
</style>
"""
