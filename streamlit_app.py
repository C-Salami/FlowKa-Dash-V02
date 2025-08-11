import streamlit as st
import plotly.express as px
from spa_data import WORKERS, SERVICES, DAY_START
from utils import build_schedule_df

st.set_page_config(page_title="Spa Scheduler — Streamlit (Form + Gantt)", layout="wide")

# indexes
services_idx = {s["id"]: s for s in SERVICES}
workers_idx  = {w["id"]: w for w in WORKERS}

# ---- app state (no backlog, no worker columns UI)
if "seq" not in st.session_state:
    st.session_state.seq = 0
if "workers" not in st.session_state:
    st.session_state.workers = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]

def push_to_plan(customer: str, service_id: str, worker_id: str):
    st.session_state.seq += 1
    st.session_state.workers = list(st.session_state.workers)  # shallow copy
    for col in st.session_state.workers:
        if col["worker_id"] == worker_id:
            col["tasks"].append({"id": f"t{st.session_state.seq}", "customer": customer, "service_id": service_id})
            break

# ---- layout: 20% form | 80% gantt
left, right = st.columns([1,4], gap="large")

with left:
    st.title("Spa Scheduler")
    st.subheader("Add booking")
    customer = st.text_input("Customer")
    service_id = st.selectbox(
        "Service",
        options=[s["id"] for s in SERVICES],
        format_func=lambda sid: f"{services_idx[sid]['name']} ({services_idx[sid]['duration_min']}m)",
        index=0 if SERVICES else None,
    )
    worker_id = st.selectbox(
        "Worker",
        options=[w["id"] for w in WORKERS],
        format_func=lambda wid: workers_idx[wid]["name"],
        index=0 if WORKERS else None,
    )

    c1, c2 = st.columns([2,1])
    with c1:
        if st.button("Push to plan", use_container_width=True, type="primary") and customer and service_id and worker_id:
            push_to_plan(customer, service_id, worker_id)
    with c2:
        if st.button("Reset day", help="Clear all bookings"):
            st.session_state.seq = 0
            st.session_state.workers = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]

    st.caption("This Streamlit view matches your UI rules: only the form and the Gantt. "
               "Drag & drop on the chart is available in the Dash app.")

with right:
    st.subheader("Schedule")
    df = build_schedule_df(
        {"workers": st.session_state.workers},
        services_idx, workers_idx, DAY_START
    )
    if df.empty:
        st.info("No bookings yet. Add one on the left.")
    else:
        fig = px.timeline(
            df, x_start="Start", x_end="Finish",
            y="Worker", color="Service", text="Customer", hover_data=["Duration(min)"]
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_traces(textposition="inside", insidetextanchor="start", textfont_size=12, cliponaxis=False)
        fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=760)
        st.plotly_chart(fig, use_container_width=True)
