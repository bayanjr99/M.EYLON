"""רכיבי UI מולטי-שימוש לדשבורד הביקורת.

מותאם מ-app_gpt_dashboard.py של billing_system עם שינויי מותג
ל-מ. אילון אביב נכסים בע"מ.
"""
from __future__ import annotations

from typing import Iterable

import streamlit as st

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


# ── Plotly layout משותף ───────────────────────────────────────
PLOTLY_LAYOUT = dict(
    height=290,
    margin=dict(l=20, r=20, t=50, b=40),
    paper_bgcolor="white", plot_bgcolor="white",
    font=dict(family="Inter,Segoe UI,Arial", size=12, color="#0F172A"),
    hoverlabel=dict(bgcolor="#0F172A", font_color="#FFFFFF",
                    bordercolor="#0F172A", font_size=12,
                    font_family="Inter,Segoe UI"),
)


def polish(fig, title: str | None = None):
    """מוסיף עיצוב אחיד לציר/לתווית/לכותרת של Plotly figure."""
    if not HAS_PLOTLY:
        return fig
    try:
        u = dict(
            xaxis_tickfont=dict(size=11, color="#64748B"),
            yaxis_tickfont=dict(size=11, color="#64748B"),
            xaxis_title_font=dict(size=11, color="#475569"),
            yaxis_title_font=dict(size=11, color="#475569"),
            xaxis_zeroline=False, yaxis_zeroline=False,
            legend_font=dict(size=11, color="#475569"),
            xaxis_automargin=True, yaxis_automargin=True,
        )
        # tick angle אם labels ארוכים
        try:
            xd = []
            for tr in (fig.data or []):
                xs = getattr(tr, "x", None)
                if xs is not None and len(xd) < 12:
                    xd.extend(list(xs)[:12])
            if any(isinstance(v, str) for v in xd) and len(xd) > 6:
                u["xaxis_tickangle"] = -30
        except Exception:
            pass

        existing_title = None
        try:
            existing_title = (fig.layout.title.text if fig.layout and fig.layout.title else None)
        except Exception:
            pass
        final_title = title if title is not None else existing_title
        if final_title:
            u["title_text"] = final_title
            u["title_font"] = dict(size=13, color="#0F172A", family="Inter,Segoe UI")
            u["title_x"] = 0.02
            u["title_xanchor"] = "left"
            u["title_y"] = 0.97
            u["title_yanchor"] = "top"
        fig.update_layout(**u)
    except Exception:
        pass
    return fig


# ── Section heading ──────────────────────────────────────────
def sec(title: str, meta: str = "") -> None:
    """כותרת סקציה עם פס כתום מימין."""
    meta_html = f'<span class="sec-meta">{meta}</span>' if meta else ""
    st.markdown(f'<div class="sec">{title}{meta_html}</div>', unsafe_allow_html=True)


# ── Block card ───────────────────────────────────────────────
def blk(label: str, body: str, cls: str = "") -> None:
    """כרטיס תוכן עם תווית קטנה למעלה. cls אופציונלית: 'warm' / 'dark'."""
    st.markdown(
        f'<div class="blk {cls}"><div class="blk-lbl">{label}</div>'
        f'<div class="blk-body">{body}</div></div>',
        unsafe_allow_html=True,
    )


# ── Insight card (colored border) ────────────────────────────
def ins(color: str, icon: str, title: str, body: str) -> None:
    """כרטיס תובנה עם פס צבעוני. color: red/amber/green/blue."""
    st.markdown(
        f'<div class="ins {color}"><div class="ins-icon">{icon}</div>'
        f'<div><div class="ins-title">{title}</div>'
        f'<div class="ins-body">{body}</div></div></div>',
        unsafe_allow_html=True,
    )


# ── KPI block ────────────────────────────────────────────────
_ACCENT_TO_HEX = {
    "orange": "#B45309", "green": "#0F6E56", "red": "#A32D2D",
    "amber": "#BA7517", "blue": "#1D4ED8", "slate": "#64748B",
}


def kpi_block(
    label: str,
    value: str,
    *,
    prev_value: float | None = None,
    target: float | None = None,
    good: str = "low",                # "low" / "high"
    accent: str = "blue",             # orange/green/red/amber/blue/slate
    icon: str = "",                   # ti-xxx (Tabler) או אמוג'י
    chips: str = "",                  # מופרד ב-' · ', שורות חדשות ב-'<br>'
    tooltip: str = "",
) -> str:
    """מייצר HTML של כרטיס KPI יחיד. מחזיר string, לא מרנדר.

    שימוש: list הופך לקבוצה דרך render_kpi_group().
    """
    # אייקון
    if icon and icon.startswith("ti-"):
        clr = _ACCENT_TO_HEX.get(accent, "#9CA3AF")
        icon_html = f'<i class="ti {icon}" style="color:{clr}"></i>'
    elif icon:
        icon_html = f'<span style="font-size:13px;line-height:1">{icon}</span>'
    else:
        icon_html = ""

    # vs prev
    vs_prev = ""
    if prev_value is not None and prev_value != 0:
        try:
            v = float(str(value).replace("₪", "").replace(",", "")
                      .replace("%", "").replace("h", "").strip())
            change = (v - prev_value) / abs(prev_value) * 100
            improving = (change < 0) if good == "low" else (change > 0)
            cls = "dn-good" if improving else "up-bad"
            arrow = "▼" if change < 0 else "▲"
            vs_prev = f'<span class="{cls}">{arrow}{abs(change):.1f}%</span>'
        except Exception:
            pass

    # vs target
    tgt_badge = ""
    if target is not None:
        try:
            v = float(str(value).replace("₪", "").replace(",", "")
                      .replace("%", "").replace("h", "").strip())
            if good == "low":
                stt = "good" if v <= target else "warn" if v <= target * 1.15 else "bad"
            else:
                stt = "good" if v >= target else "warn" if v >= target * 0.85 else "bad"
            sym = {"good": "✓", "warn": "●", "bad": "⚠"}[stt]
            clr = {"good": "#0F6E56", "warn": "#BA7517", "bad": "#A32D2D"}[stt]
            tgt_badge = f'<span style="color:{clr}"> {sym} יעד&thinsp;{target}</span>'
        except Exception:
            pass

    badges_line = vs_prev + tgt_badge

    # chips
    chips_html = ""
    if chips:
        for row in chips.split("<br>"):
            pieces = [p.strip() for p in row.split(" · ") if p.strip()]
            if not pieces:
                continue
            chip_row = "".join(f'<span class="kpi-chip">{p}</span>' for p in pieces)
            chips_html += f'<div class="kpi-chip-row">{chip_row}</div>'

    tooltip_attr = f' title="{tooltip}"' if tooltip else ""
    info_icon = (
        '<i class="ti ti-info-circle" style="font-size:11px;color:#94A3B8;margin-right:auto"></i>'
        if tooltip else ""
    )

    return (
        f'<div class="kpi-cell" data-accent="{accent}"{tooltip_attr}>'
        f'<div class="kpi-lbl">{icon_html}{label}{info_icon}</div>'
        f'<div class="kpi-val">{value}</div>'
        f'<div class="kpi-delta">{badges_line}</div>'
        f'{chips_html}'
        f'</div>'
    )


def render_kpi_group(kpis: list[str], group_label: str, group_icon: str = "ti-activity") -> None:
    """מרנדר קבוצת כרטיסי KPI כ-strip אחד. icon: שם Tabler."""
    if not kpis:
        return
    n = len(kpis)
    st.markdown(
        f'<div class="kpi-group">'
        f'  <div class="kpi-group-head">'
        f'    <i class="ti {group_icon}"></i>{group_label}'
        f'    <span class="kpi-group-count">{n} מדדים</span>'
        f'  </div>'
        f'  <div class="kpi-strip" style="grid-template-columns:repeat({n},minmax(0,1fr));">'
        f'    {"".join(kpis)}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Executive summary ────────────────────────────────────────
def exec_summary(
    title: str,
    status: str,           # good / warn / bad
    status_text: str,
    questions: list[tuple[str, str, str]],  # (label, value, sub)
) -> None:
    """כרטיס סיכום מנהלים: סטטוס + 3 שאלות-מפתח עם תשובה קצרה."""
    q_html = ""
    for label, value, sub in questions:
        q_html += (
            f'<div class="exec-sum-q">'
            f'  <div class="exec-sum-q-label">{label}</div>'
            f'  <div class="exec-sum-q-value">{value}</div>'
            f'  <div class="exec-sum-q-sub">{sub}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="exec-summary">'
        f'  <div class="exec-summary-head">'
        f'    <div class="exec-summary-title">'
        f'      <i class="ti ti-clipboard-check"></i>{title}'
        f'    </div>'
        f'    <div class="exec-summary-status {status}">{status_text}</div>'
        f'  </div>'
        f'  <div class="exec-summary-body">{q_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Empty state ──────────────────────────────────────────────
def empty_state(
    icon: str,            # ti-xxx
    title: str,
    body_html: str,
    action: str = "",
) -> None:
    """מסך 'אין נתונים' ידידותי, עם הוראות המשך."""
    action_html = f'<div class="empty-state-action">{action}</div>' if action else ""
    st.markdown(
        f'<div class="empty-state">'
        f'  <div class="empty-state-icon"><i class="ti {icon}"></i></div>'
        f'  <div class="empty-state-title">{title}</div>'
        f'  <div class="empty-state-body">{body_html}</div>'
        f'  {action_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Top bar ──────────────────────────────────────────────────
def render_top_bar(
    company_name: str,
    system_name: str,
    *,
    status: str = "ok",          # ok / warn / bad
    status_text: str = "המערכת תקינה",
    meta_text: str = "",
    logo_emoji: str = "🏗️",
) -> None:
    """כותרת עליונה דביקה. status: ok/warn/bad → צבע ה-pill."""
    status_cls = {"ok": "sys-pill", "warn": "sys-pill warn", "bad": "sys-pill bad"}.get(status, "sys-pill")
    meta_html = (
        f'<span class="meta-pill"><i class="ti ti-calendar"></i>{meta_text}</span>'
        if meta_text else ""
    )
    st.markdown(
        f'<div class="top-bar">'
        f'  <div class="top-bar-brand">'
        f'    <div class="top-bar-logo">{logo_emoji}</div>'
        f'    <div class="top-bar-title">'
        f'      <span>{company_name}</span>'
        f'      <span class="sep">·</span>'
        f'      <span class="sys">{system_name}</span>'
        f'    </div>'
        f'  </div>'
        f'  <div class="top-bar-actions">'
        f'    <span class="{status_cls}"><span class="dot"></span>{status_text}</span>'
        f'    {meta_html}'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Bar chart helper ─────────────────────────────────────────
def bar_h(x_vals, y_vals, colors, texts, title: str = "", height: int = 280, xvis: bool = False):
    """גרף עמודות אופקיות (מתאים ל-Top N)."""
    if not HAS_PLOTLY:
        return None
    fig = go.Figure(go.Bar(
        x=x_vals, y=y_vals, orientation="h",
        marker_color=colors, opacity=0.88, text=texts, textposition="outside",
        hovertemplate="<b>%{y}</b><br>%{x}<extra></extra>",
    ))
    fig.update_layout(
        **{**PLOTLY_LAYOUT, "height": max(height, len(y_vals) * 28)},
        showlegend=False,
        title=dict(text=title, font=dict(size=12)),
        xaxis=dict(visible=xvis),
        yaxis=dict(showgrid=False, tickfont=dict(size=10)),
    )
    return fig
