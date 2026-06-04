"""AI Accountant — Streamlit entry point.

Run with:  streamlit run app.py
All logic lives in the `ai_accountant` package; this file just launches the UI.
"""
from ai_accountant.ui import render

render()
