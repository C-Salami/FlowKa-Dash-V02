import dash
from dash import Dash, html, dcc, Input, Output, State
from dash.exceptions import PreventUpdate
from dash_extensions import EventListener
import plotly.express as px
import pandas as pd
from datetime import datetime
import json

from spa_data import WORKERS, SERVICES, DAY_START, SLOT_MIN
from utils import build_schedule_df

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

services_idx = {s["id"]: s for s in SERVICES}
workers_idx  = {w["id"]: w for w in WORKERS}
worker_name_to_id = {w["name"]: w["id"] for w in WORKERS}

def initial_state():
    # start empty; new bookings are pushed straight to plan
    return {
        "seq": 0,
        "workers":[{"worker_id": w["id"], "tasks": []} for w in WORKERS]
    }

def make_layout():
    return EventListener(
        id="gantt_dnd_listener",
        events=[{"event": "gantt-dnd-drop"}],  # custom event fired by our assets/gantt-dnd.js
        children=html.Div(
            [
                dcc.Store(id="state", data=initial_state()),
                html.Div(
                    [
                        # LEFT 20% — Add booking
                        html.Div(
                            [
                                html.H1("Spa Scheduler"),
                                html.Div(
                                    [
                                        html.H3("Add booking"),
                                        dcc.Input(id="in_customer", placeholder="Customer", type="text"),
                                        dcc.Dropdown(
                                            id="in_service",
                                            options=[{"label": f"{s['name']} ({s['duration_min']}m)", "value": s["id"]} for s in SERVICES],
                                            placeholder="Service", clearable=False
                                        ),
                                        dcc.Dropdown(
                                            id="in_worker",
                                            options=[{"label": w["name"], "value": w["id"]} for w in WORKERS],
                                            placeholder="Worker", clearable=False
                                        ),
                                        html.Button("Push to plan", id="btn_push", n_clicks=0, className="btn primary"),
                                    ],
                                    className="panel",
                                ),
                            ],
                            className="left",
                        ),
                        # RIGHT 80% — Gantt
                        html.Div(
                            [
                                html.H3("Schedule"),
                                dcc.Graph(id="gantt", config={"displaylogo": False})
                            ],
                            className="right",
                        ),
                    ],
                    className="split",
                ),
            ]
        ),
    )

app.layout = make_layout

# ---------------- ADD BOOKING ----------------
@app.callback(
    Output("state", "data"),
    Input("btn_push", "n_clicks"),
    State("in_customer", "value"),
    State("in_service", "value"),
    State("in_worker", "value"),
    State("state", "data"),
    prevent_initial_call=True,
)
def add_booking(n_clicks, customer, service_id, worker_id, state):
    if not customer or not service_id or not worker_id:
        raise PreventUpdate
    state = json.loads(json.dumps(state))
    state["seq"] += 1
    task = {"id": f"t{state['seq']}", "customer": customer, "service_id": service_id}
    # append to the chosen worker
    for col in state["workers"]:
        if col["worker_id"] == worker_id:
            col["tasks"].append(task)
            break
    return state

# ---------------- GANTT ----------------
@app.callback(Output("gantt", "figure"), Input("state", "data"))
def update_gantt(state):
    df = build_schedule_df(state, services_idx, workers_idx, DAY_START)
    if df.empty:
        fig = px.timeline()
        fig.update_layout(title="No bookings yet.", height=720, margin=dict(l=20,r=20,t=40,b=20))
        return fig
    # provide TaskId & WorkerName for the Gantt DnD JS to read
    fig = px.timeline(
        df, x_start="Start", x_end="Finish",
        y="Worker", color="Service", text="Customer",
        hover_data=["Duration(min)"],
        custom_data=["TaskId","Worker"]
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_traces(textposition="inside", insidetextanchor="start", textfont_size=12, cliponaxis=False,
                      hovertemplate="%{text}<br>%{customdata[1]} • %{customdata[0]}")
    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=760)
    return fig

# ---------------- HANDLE GANTT DRAG/DROP ----------------
@app.callback(
    Output("state", "data"),
    Input("gantt_dnd_listener", "event"),
    State("state", "data"),
    prevent_initial_call=True
)
def on_gantt_drop(event, state):
    """
    event.detail = {
      "taskId": "...",
      "dropWorkerName": "Ayu",
      "dropXISO": "2025-08-11T10:30:00.000Z"   # timeline x (UTC ISO)
    }
    We reassign to the chosen worker (by y drop) and compute the new index from dropX.
    """
    if not event or event.get("type") != "gantt-dnd-drop":
        raise PreventUpdate
    detail = event.get("detail") or {}
    task_id = detail.get("taskId")
    w_name  = detail.get("dropWorkerName")
    x_iso   = detail.get("dropXISO")
    if not (task_id and w_name and x_iso):
        raise PreventUpdate

    try:
        drop_ts = pd.to_datetime(x_iso)
    except Exception:
        raise PreventUpdate

    dest_worker_id = worker_name_to_id.get(w_name)
    if not dest_worker_id:
        raise PreventUpdate

    # deep copy
    state = json.loads(json.dumps(state))

    # 1) Remove task from wherever it currently is
    task = None
    for col in state["workers"]:
        for i, t in enumerate(list(col["tasks"])):
            if t["id"] == task_id:
                task = col["tasks"].pop(i)
                break
        if task: break
    if task is None:
        raise PreventUpdate

    # 2) Compute insert index based on dropX relative to current schedule of dest worker
    # Build schedule for current state (WITHOUT the dragged task)
    df = build_schedule_df(state, services_idx, workers_idx, DAY_START)
    # rows for destination worker
    w_rows = df[df["Worker"] == workers_idx[dest_worker_id]["name"]].sort_values("Start")
    # Count how many tasks start before the drop time → that’s our insertion index
    insert_idx = int((w_rows["Start"] <= drop_ts).sum())

    # 3) Insert into destination worker at computed index
    dest_col = next(c for c in state["workers"] if c["worker_id"] == dest_worker_id)
    insert_idx = max(0, min(insert_idx, len(dest_col["tasks"])))
    dest_col["tasks"].insert(insert_idx, task)

    return state

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8050, debug=True)
