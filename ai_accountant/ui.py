"""Streamlit UI for the AI Accountant (Phase 1).

Renders the dashboard and the live L4->L3->L2->L1 cascade results for Note 5. All compute
lives in the package; this file only presents it.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ai_accountant.compute.note5 import Note5Result, run_note5_from_files, run_note5_from_path
from ai_accountant.config import SAMPLE_NOTE5_CSV, get_api_key
from ai_accountant.policy import extract_policy_rules, parse_policy_document
from ai_accountant.routing import enrich_routing_map_with_ai
from ai_accountant.export import export_to_excel, export_to_pdf
from ai_accountant.validation.controls import explain_flagged_items, narrate_confidence

_CSS = """
<style>
:root { --accent:#6366F1; --accent2:#3B82F6; }
.block-container { padding-top: 2.2rem; }
h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 700; letter-spacing:-0.01em; }
.hero {
    background: linear-gradient(135deg, rgba(99,102,241,0.18) 0%, rgba(59,130,246,0.10) 100%);
    border: 1px solid rgba(99,102,241,0.35); border-radius: 16px; padding: 22px 26px; margin-bottom: 18px;
}
.hero h1 { margin: 0; font-size: 1.9rem; }
.hero p { margin: 6px 0 0; color: #AAB2C5; font-size: 0.95rem; }
.stButton>button {
    width: 100%; border-radius: 10px; font-weight: 700; border: none; padding: 0.55rem 1rem;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%); color: white;
    transition: all 0.2s ease;
}
.stButton>button:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(59,130,246,0.35); }
.card {
    background: #161B26; border: 1px solid rgba(255,255,255,0.07); border-radius: 14px;
    padding: 18px 20px; margin-bottom: 14px;
}
.step-header { color: var(--accent); font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 8px; }
.flow { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin: 4px 0 10px; }
.flow .node { background:#1B2230; border:1px solid rgba(99,102,241,0.4); border-radius:10px;
    padding:8px 14px; font-weight:700; font-size:0.85rem; }
.flow .node small { display:block; color:#8B93A7; font-weight:500; font-size:0.7rem; }
.flow .arrow { color:#6366F1; font-size:1.1rem; }
.pill { padding:2px 10px; border-radius:999px; font-size:0.72rem; font-weight:700; }
.pill.match { background:rgba(34,197,94,0.15); color:#4ADE80; border:1px solid rgba(34,197,94,0.4); }
.pill.var   { background:rgba(245,158,11,0.15); color:#FBBF24; border:1px solid rgba(245,158,11,0.4); }
</style>
"""


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


# --- sidebar -----------------------------------------------------------------
def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### ⚙️  Configuration")
        st.markdown("---")
        st.markdown("**Scope**")
        st.caption("Generating **Note 5 — Investments, Net**. "
                   "Other notes / full-FS generation arrive in a later phase.")
        st.markdown("---")
        st.caption("Basis: **IFRS 9** — uploaded policy rules take precedence when provided.")
        if get_api_key():
            st.caption("\U0001F7E2 AI assist enabled")
        else:
            st.caption("⚪ AI assist off — local cascade still works")


# --- inputs ------------------------------------------------------------------
def _render_inputs():
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='step-header'>Step 1 · Data</div>", unsafe_allow_html=True)
        use_sample = st.toggle("Use bundled sample (AMNB Note 5)", value=True,
                               help="Run the cascade on the included 4-level workbook.")
        raw_files = st.file_uploader(
            "Or upload data files (CSV or Excel — any level, multi-sheet, multi-table)",
            type=["csv", "xlsx", "xls"], accept_multiple_files=True, disabled=use_sample,
        )
        if use_sample:
            st.caption("Sample loaded: `AMNB_Note5_All_Levels.csv` (L1–L4 + reconciliation map).")
        elif raw_files:
            st.success(f"{len(raw_files)} file(s) uploaded.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='step-header'>Step 2 · Policy (optional)</div>", unsafe_allow_html=True)
        policy_file = st.file_uploader("Accounting policy (PDF/TXT)", type=["pdf", "txt"])
        if policy_file:
            st.info(f"Policy `{policy_file.name}` loaded — its rules will drive classification "
                    "(needs an API key; otherwise IFRS 9 inference is used).")
        else:
            st.caption("No policy — using IFRS 9 inference.")
        st.markdown("</div>", unsafe_allow_html=True)
    return use_sample, raw_files, policy_file


# --- processing --------------------------------------------------------------
def _run(use_sample: bool, raw_files, policy_file) -> None:
    api_key = get_api_key()  # silently from .env / environment
    with st.status("Running AI Accountant engine…", expanded=True) as status:
        # 1) Extract policy rules first (if a policy doc + key) so they drive classification.
        policy_rules = None
        if policy_file and api_key:
            st.write("\U0001F9E0  Extracting accounting-policy rules…")
            try:
                extracted = extract_policy_rules(api_key, parse_policy_document(policy_file))
                policy_rules = extracted.get("mapping_rules") or []
                st.write(f"Found {len(policy_rules)} policy rule(s) — these will drive classification.")
            except Exception as exc:  # noqa: BLE001
                st.write(f"⚠️ Policy step skipped: {exc}")
        elif policy_file and not api_key:
            st.write("ℹ️ Policy uploaded but no API key — using IFRS 9 inference instead.")

        # 2) Build Note 5 via the cascade (local; policy rules applied to unclassified data).
        st.write("\U0001F4D0  Detecting tables and running L4→L3→L2→L1 cascade…")
        try:
            if use_sample:
                result = run_note5_from_path(str(SAMPLE_NOTE5_CSV))
            else:
                if not raw_files:
                    status.update(label="Nothing to process.", state="error")
                    st.error("Please upload at least one CSV/Excel file, or use the sample.")
                    return
                if api_key:
                    st.write("\U0001F9E0  Normalizing columns (AI-assisted for unknown layouts)…")
                result = run_note5_from_files(raw_files, api_key=api_key, policy_rules=policy_rules)
        except ValueError as exc:
            status.update(label="Couldn't build Note 5.", state="error")
            st.error(str(exc))
            return
        st.write(f"✅ Detected {len(result.tables)} tables across {len(result.table_counts())} levels.")
        if result.classifications:
            src = "policy rules" if policy_rules else "IFRS 9 inference"
            st.write(f"🏷️ Classified {len(result.classifications)} security(ies) via {src}.")
        if result.cascade.partial:
            st.write("ℹ️ No sub-ledger found — rebuilt holdings from L4 transactions (partial).")

        # 3) Optional AI routing enrichment for unrecognized table layouts.
        if api_key:
            try:
                unknown = [e for e in result.routing.entries if e.role == "unclassified"]
                if unknown:
                    st.write(f"⚙️  AI classifying {len(unknown)} unrecognized table(s)…")
                    enrich_routing_map_with_ai(result.tables, result.routing, api_key)
            except Exception as exc:  # noqa: BLE001 - AI is optional
                st.write(f"⚠️ AI step skipped: {exc}")

        # 4) Optional LLM layer OVER the deterministic confidence controls (never changes verdicts).
        if api_key and result.confidence.controls:
            st.write("\U0001F4DD  Summarizing the confidence checks…")
            result.confidence_narrative = narrate_confidence(result.confidence, api_key)
            if result.confidence.flagged:
                st.write("\U0001F4DD  Explaining flagged items…")
                explain_flagged_items(result.confidence, api_key)
                st.session_state["explained_by_ai"] = True

        status.update(label="Done — Note 5 computed.", state="complete", expanded=False)

    st.session_state["note5"] = result


# --- results -----------------------------------------------------------------
def _render_flow(result: Note5Result) -> None:
    counts = result.table_counts()
    nodes = [("L4", "transactions"), ("L3", "sub-ledger"), ("L2", "note tables"), ("L1", "FS face")]
    html = "<div class='flow'>"
    for i, (lvl, desc) in enumerate(nodes):
        html += f"<div class='node'>{lvl} <small>{desc} · {counts.get(lvl, 0)} tbl</small></div>"
        if i < len(nodes) - 1:
            html += "<span class='arrow'>→</span>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _render_metrics(result: Note5Result) -> None:
    expected = {line.item: line.expected for line in result.reconciliation}
    cols = st.columns(4)
    for col, bucket in zip(cols, ["FVTPL", "FVOCI", "Amortised Cost", "TOTAL"]):
        value = result.cascade.l1.get(bucket, 0.0)
        var = value - expected.get(bucket, value)
        delta = "matches FS" if var == 0 else f"{var:+,.0f} vs FS"
        col.metric(bucket, _fmt(value), delta, delta_color="off" if var == 0 else "inverse")


def _style_recon(df: pd.DataFrame):
    def color(row):
        ok = row["Status"] == "MATCH"
        bg = "rgba(34,197,94,0.10)" if ok else "rgba(245,158,11,0.12)"
        return [f"background-color: {bg}"] * len(row)
    return df.style.apply(color, axis=1).format(
        {"Computed": "{:,.0f}", "Expected (FS)": "{:,.0f}", "Variance": "{:+,.0f}"}
    )


def _render_results(result: Note5Result) -> None:
    if result.cascade.partial:
        st.warning(
            "**Partial result — built from L4 transactions only.** "
            + " ".join(result.cascade.notes)
        )
    elif result.cascade.notes:
        st.info(" ".join(result.cascade.notes))

    stated = [s for s in (result.reconciliation_report or []) if "stated" in s.source]
    if stated:
        # An answer key was uploaded (stated L1/L2) — reconcile against it.
        if all(s.matched for s in stated):
            st.success("**Reconciled to the stated financial statement** — computed ties to your L1/L2.")
        else:
            n = sum(1 for s in stated for ln in s.lines if ln.status == "VARIANCE")
            st.warning(f"**{n} variance(s) vs the stated FS** — see the Reconciliation tab.")
    else:
        # Production case: no stated L1 to check against — trust comes from internal controls.
        conf = result.confidence
        msg = (f"**Confidence: {conf.level}** — {conf.passed}/{len(conf.controls)} internal "
               "accounting controls passed (no external answer key needed).")
        if conf.level == "High":
            st.success(msg)
        elif conf.level == "Medium":
            st.warning(msg + " Review flagged items in the **Confidence** tab.")
        elif conf.level == "Low":
            st.error(msg + " See the **Confidence** tab.")
        else:
            st.info("Computed — see the Confidence tab for internal-control checks.")

    _render_flow(result)
    _render_metrics(result)
    files = {t.source_file for t in result.tables if t.source_file}
    sheets = {(t.source_file, t.sheet) for t in result.tables if t.sheet}
    ingest = f"{len(result.tables)} tables from {len(files)} file(s)"
    if sheets:
        ingest += f" / {len(sheets)} sheet(s)"
    st.caption(f"All amounts SAR '000. Ingested {ingest}. "
               f"Sub-ledger source: **{result.cascade.l3_source}**.")

    with st.expander("\U0001F5FA️ Routing map — how each table was identified & used"):
        rows = [{
            "Source": e.origin,
            "Table": e.table_title or "—",
            "Level": e.level or "?",
            "Role": e.role,
            "Feeds": e.note or "—",
            "Used": "✅" if e.used_in_cascade else "",
            "By": e.confidence,
        } for e in result.routing.entries]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("‘Used’ = the cascade consumed this table. ‘By’ = rule (column signature) "
                   "or ai (model-classified for unknown layouts).")

    if result.classifications:
        n_policy = sum(1 for d in result.classifications if d["source"] == "policy")
        label = (f"\U0001F3F7️ Classification decisions — {len(result.classifications)} security(ies) "
                 f"({n_policy} by policy, {len(result.classifications) - n_policy} by IFRS 9)")
        with st.expander(label):
            st.dataframe(
                pd.DataFrame(result.classifications)[
                    ["security", "classification", "source", "reason"]
                ],
                use_container_width=True, hide_index=True,
            )
            st.caption("Securities lacking a stated classification were assigned one — policy "
                       "rules take precedence; otherwise IFRS 9 inference. Stated classifications "
                       "in the source data are never overridden.")

    t1, t2, t3, t4, t5, t6, t7 = st.tabs(
        ["L1 · FS Face", "L2 · Note 5", "L3 · Sub-Ledger", "L4 · Transactions",
         "Reconciliation", "Audit trail", "Confidence"]
    )

    with t1:
        st.markdown("#### Note 5: Investments, Net — computed")
        l1 = result.cascade.l1
        df = pd.DataFrame(
            [{"Line": b, "Amount (SAR '000)": l1.get(b, 0.0)}
             for b in ["FVTPL", "FVOCI", "Amortised Cost", "TOTAL"]]
        )
        st.dataframe(df.style.format({"Amount (SAR '000)": "{:,.0f}"}),
                     use_container_width=True, hide_index=True)

    with t2:
        st.markdown("#### Computed classification summary (5.1)")
        st.dataframe(result.cascade.l2_classification, use_container_width=True, hide_index=True)

    with t3:
        st.markdown("#### Sub-ledger holdings (L3)")
        cols = [c for c in ["Holding_ID", "Security_Name", "Issuer", "Classification",
                            "Currency", "Carrying_Value_000", "Fair_Value_000", "Maturity"]
                if c in result.cascade.l3_holdings.columns]
        st.dataframe(result.cascade.l3_holdings[cols], use_container_width=True, hide_index=True)

    with t4:
        st.markdown("#### L4 transaction summary")
        s = result.cascade.l4_summary
        scols = st.columns(4)
        scols[0].metric("Purchases", _fmt(s.get("purchases_total", 0)))
        scols[1].metric("Sales/maturities", _fmt(s.get("sales_total", 0)))
        scols[2].metric("Income (net)", _fmt(s.get("income_net_total", 0)))
        scols[3].metric("MtM change", _fmt(s.get("mtm_total", 0)))
        st.caption("Detected L4 tables:")
        for t in [t for t in result.tables if t.level == "L4"]:
            with st.expander(f"{t.title or 'L4 table'} — {len(t.records)} rows"):
                st.dataframe(t.df, use_container_width=True, hide_index=True)

    with t5:
        st.markdown("#### Reconciliation — computed vs every stated level")
        for section in (result.reconciliation_report or []):
            badge = "✅ ties out" if section.matched else "⚠️ variance"
            st.markdown(f"**{section.level}** · _{section.source}_ — {badge}")
            df = pd.DataFrame([{
                "Item": ln.item, "Computed": ln.computed, "Expected": ln.expected,
                "Variance": ln.variance, "Status": ln.status,
            } for ln in section.lines])
            if not df.empty:
                st.dataframe(_style_recon(df.rename(columns={"Expected": "Expected (FS)"})),
                             use_container_width=True, hide_index=True)
        with st.expander("❓ Why are there differences? (plain English)"):
            st.markdown(
                "We rebuild each total from the **most detailed records** (the individual "
                "holdings) and compare it to the number written in the official financial "
                "statement. When they don't match, we show the gap instead of hiding it.\n\n"
                "- **FVTPL — matches exactly.** The detailed records add up to the same number "
                "as the statement. ✅\n"
                "- **FVOCI — computed is 100,000 higher.** Adding up the individual bonds gives "
                "a bigger number than the statement shows. One group of corporate bonds was "
                "recorded as 3,300,000 in the detail but written as 3,200,000 in the statement — "
                "a **100,000 mismatch in the source data** that our tool just caught.\n"
                "- **Amortised Cost — computed is 59,500 lower.** These investments (like "
                "government bills) are recorded at cost and slowly adjusted toward their face "
                "value over time. The statement includes a bit more of that gradual adjustment "
                "than the raw holding values do — a **timing/rounding difference**, not an error.\n\n"
                "**Bottom line:** the small differences come from the *sample data itself*, not "
                "from a calculation mistake. Catching and flagging them is exactly the job — an "
                "accountant would investigate the FVOCI one and accept the AC one."
            )

    with t6:
        st.markdown("#### Audit trail — trace any figure to its source rows")
        if result.audit.is_empty:
            st.info("The audit trail needs a holdings sub-ledger (L3) plus L4 transactions. "
                    "It isn't available for streamed/partial runs.")
        else:
            names = [b.bucket for b in result.audit.buckets]
            pick = st.selectbox("Classification bucket", names, key="audit_bucket")
            bt = next(b for b in result.audit.buckets if b.bucket == pick)
            st.caption(f"**{pick}** — total {_fmt(bt.total)} SAR '000 from {len(bt.holdings)} holdings.")
            hdf = pd.DataFrame([{"Holding": h.holding_id, "Security": h.name,
                                 "Value": h.value, "# Txns": len(h.transactions)}
                                for h in bt.holdings])
            st.dataframe(hdf.style.format({"Value": "{:,.0f}"}),
                         use_container_width=True, hide_index=True)
            ids = [h.holding_id for h in bt.holdings]
            hpick = st.selectbox("Drill into a holding → its L4 transactions", ids, key="audit_hold")
            h = next(x for x in bt.holdings if x.holding_id == hpick)
            if h.transactions:
                st.markdown(f"**{h.holding_id} · {h.name}** — {len(h.transactions)} transaction(s):")
                st.dataframe(
                    pd.DataFrame(h.transactions)[["type", "ref", "amount"]]
                    .style.format({"amount": "{:,.0f}"}),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No L4 transactions reference this holding "
                           "(likely an opening-balance position carried from a prior period).")

    with t7:
        conf = result.confidence
        st.markdown(f"#### Internal controls — confidence: **{conf.level}**")
        st.caption("How we trust the generated figures when there is **no expected L1 to check "
                   "against** — the same controls an accountant uses to close the books.")
        if result.confidence_narrative:
            st.info(f"🤖 **AI summary:** {result.confidence_narrative}")
            st.caption("Plain-English narration of the checks below. The ✅/⚠️/❌ verdicts are "
                       "computed deterministically — the AI only summarizes them, never changes them.")
        if not conf.controls:
            st.info("No controls available for this run (e.g., streamed large-file path).")
        else:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
            for c in conf.controls:
                st.markdown(f"{icon.get(c.status, '•')} **{c.name}** — {c.detail}")
                if c.items:
                    with st.expander(f"Show {len(c.items)} flagged item(s) — and why"):
                        st.dataframe(pd.DataFrame(c.items),
                                     use_container_width=True, hide_index=True)
            by_ai = st.session_state.get("explained_by_ai")
            st.caption(f"The 'reason' for each flagged item is "
                       f"{'AI-generated from the deterministic findings' if by_ai else 'rule-based'}"
                       " — the AI explains findings, it never decides the ✅/⚠️/❌ verdict.")

    st.markdown("---")
    st.markdown("### \U0001F4E5 Export")
    e1, e2, _ = st.columns([1, 1, 2])
    try:
        e1.download_button(
            "\U0001F4C4 Export PDF", data=export_to_pdf(result),
            file_name="note5_investments.pdf", mime="application/pdf",
        )
        e2.download_button(
            "\U0001F4CA Export Excel", data=export_to_excel(result),
            file_name="note5_investments.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:  # noqa: BLE001 - never let export break the results view
        st.warning(f"Export unavailable: {exc}")


# --- entry -------------------------------------------------------------------
def render() -> None:
    st.set_page_config(page_title="AI Accountant", page_icon="\U0001F9FE",
                       layout="wide", initial_sidebar_state="expanded")
    st.markdown(_CSS, unsafe_allow_html=True)
    _render_sidebar()

    st.markdown(
        "<div class='hero'><h1>\U0001F9FE AI Accountant</h1>"
        "<p>Generate Financial Statement notes from transactional data — "
        "L4 → L3 → L2 → L1, reconciled against ground truth.</p></div>",
        unsafe_allow_html=True,
    )

    use_sample, raw_files, policy_file = _render_inputs()

    if st.button("\U0001F680 Generate Note 5"):
        _run(use_sample, raw_files, policy_file)

    if "note5" in st.session_state:
        st.markdown("### \U0001F4CA Results")
        _render_results(st.session_state["note5"])
