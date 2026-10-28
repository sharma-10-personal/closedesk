"""Streamlit placeholder. Replace once matching numbers exist."""

import streamlit as st

st.set_page_config(page_title="CloseDesk", layout="wide")
st.title("CloseDesk")
st.write(
    "A payments-operations analyst at a mid-size bank can't close the day's UPI "
    "reconciliation, because the settlement file, the core-banking ledger and the "
    "merchant records disagree on thousands of transactions, and she traces each one "
    "by hand across spreadsheets."
)
st.info("Matching UI is not wired yet. Run make schema to create Exasol tables.")
