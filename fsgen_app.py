"""FS-Gen — Streamlit UI.

The seed-driven Master-FS confirm-chain is the ONLY flow: the AI PROPOSES (columns, sign, archetype,
account→concept, maturity); a human CONFIRMS at every gate; the engine computes every number. The legacy
GL "statement-first" pipeline (and its View toggle) was removed — the whole UI lives in `fsgen_mfs.py`.

Run:  streamlit run fsgen_app.py
"""
from __future__ import annotations

import streamlit as st

import fsgen_mfs

st.set_page_config(page_title="FS-Gen", layout="wide")
fsgen_mfs.render_master_fs(st.session_state)
