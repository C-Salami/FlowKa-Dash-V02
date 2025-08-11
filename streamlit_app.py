import streamlit as st
import pandas as pd
import plotly.express as px
from spa_data import WORKERS, SERVICES, DAY_START
from utils import build_schedule_df

st.set_page_config(page_title="Spa Scheduler (Streamlit test)", layout="wide")

services_idx = {s["id"]: s for s in SERVICES}
workers_idx  = {w["id"]: w for w in WORKERS}

st.title("Spa Scheduler — Streamlit (Test Viewer)")

backlog = st.session_state.setdefault("backlog", [
    {"id":"t1","customer":"Lina","service_id":"svc_thai"},
    {"id":"t2","customer":"Rafi","service_id":"svc_deep"},
    {"id":"t3","customer":"Maya","service_id":"svc_facial"},
])
workers = st.session_state.setdefault("workers", [{"worker_id": w["id"], "tasks": []} for w in WORKERS])
seq = st.session_state.setdefault("seq", 3)

with st.sidebar:
    st.header("Add booking")
    cust = st.text_input("Customer")
    svc  = st.selectbox("Service", options=[s["id"] for s in SERVICES], format_func=lambda i: f"{services_idx[i]['name']} ({services_idx[i]['duration_min']}m)")
    if st.button("Add to backlog") and cust and svc:
        st.session_state["seq"] += 1
        backlog.append({"id": f"t{st.session_state['seq']}", "customer": cust, "service_id": svc})

st.subheader("Backlog")
for t in list(backlog):
    c1,c2 = st.columns([2,1])
    with c1:
        st.write(f"**{t['customer']}** — {services_idx[t['service_id']]['name']}")
    with c2:
        dest = st.selectbox("Assign to", options=["-"] + [w["id"] for w in WORKERS],
                            key=f"assign_{t['id']}", label_visibility="collapsed",
                            format_func=lambda i: "-" if i=="-" else workers_idx[i]["name"])
        if dest != "-":
            backlog.remove(t)
            [col for col in workers if col["worker_id"]==dest][0]["tasks"].append(t)

st.subheader("Workers")
for col in workers:
    wname = workers_idx[col["worker_id"]]["name"]
    with st.expander(wname, expanded=True):
        for i,t in enumerate(list(col["tasks"])):
            c1,c2,c3,c4 = st.columns([3,1,1,1])
            c1.write(f"**{t['customer']}** — {services_idx[t['service_id']]['name']}")
            if c2.button("↑", key=f"up_{col['worker_id']}_{i}") and i>0:
                col["tasks"][i-1], col["tasks"][i] = col["tasks"][i], col["tasks"][i-1]
            if c3.button("↓", key=f"down_{col['worker_id']}_{i}") and i<len(col["tasks"])-1:
                col["tasks"][i+1], col["tasks"][i] = col["tasks"][i], col["tasks"][i+1]
            if c4.button("Remove", key=f"rm_{col['worker_id']}_{i}"):
                col["tasks"].pop(i)

df = build_schedule_df({"workers": workers}, services_idx, workers_idx, DAY_START)
st.subheader("Schedule")
if df.empty:
    st.info("No tasks scheduled yet.")
else:
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Worker", color="Service", text="Customer", hover_data=["Duration(min)"])
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

st.caption("This Streamlit app validates schedule logic; the Dash app provides drag & drop.")
