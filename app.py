import dash
from dash import Dash, html, dcc, Input, Output, State, no_update
from dash.exceptions import PreventUpdate
from dash_extensions import EventListener
import plotly.express as px
import json

from spa_data import WORKERS, SERVICES, DAY_START, SLOT_MIN
from utils import build_schedule_df

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

services_idx = {s["id"]: s for s in SERVICES}
workers_idx  = {w["id"]: w for w in WORKERS}

def initial_state():
    return {
        "seq": 6,
        "backlog":[
            {"id":"t1","customer":"Lina","service_id":"svc_thai"},
            {"id":"t2","customer":"Rafi","service_id":"svc_deep"},
            {"id":"t3","customer":"Maya","service_id":"svc_facial"},
            {"id":"t4","customer":"Irfan","service_id":"svc_hot"},
            {"id":"t5","customer":"Sari","service_id":"svc_reflex"},
        ],
        "workers":[
            {"worker_id": w["id"], "tasks": []} for w in WORKERS
        ]
    }

def task_card(task):
    svc = services_idx[task["service_id"]]
    return html.Div(
        [
            html.Div(task["customer"], className="card-title"),
            html.Div(f"{svc['name']} • {svc['duration_min']}m", className="card-sub"),
        ],
        className="card dnd-item",
        id=f"card-{task['id']}",
        **{"data-task-id": task["id"]},
    )

def backlog_container(children=None):
    return html.Div(
        children or [],
        id="list-backlog",
        className="dnd-list",
        **{"data-list-id": "backlog"},
    )

def worker_container(worker_id, children=None):
    return html.Div(
        [
            html.Div(workers_idx[worker_id]["name"], className="worker-name"),
            html.Div(
                children or [],
                id=f"list-worker-{worker_id}",
                className="dnd-list",
                **{"data-list-id": f"worker-{worker_id}"},
            ),
        ],
        className="worker-block",
    )

app.layout = EventListener(
    id="dnd_listener",
    events=[{"event": "dnd"}],
    children=html.Div(
        [
            dcc.Store(id="state", data=initial_state()),
            html.Div(
                [
                    # LEFT 20%
                    html.Div(
                        [
                            html.H1("Spa Scheduler"),
                            html.Div(
                                [
                                    html.H3("New booking"),
                                    dcc.Input(id="in_customer", placeholder="Customer name", type="text"),
                                    dcc.Dropdown(
                                        id="in_service",
                                        options=[{"label": f"{s['name']} ({s['duration_min']}m)", "value": s["id"]} for s in SERVICES],
                                        placeholder="Select service",
                                        clearable=False,
                                    ),
                                    html.Button("Add to backlog", id="btn_add", n_clicks=0, className="btn primary"),
                                ],
                                className="panel",
                            ),
                            html.Div(
                                [
                                    html.H3("Backlog"),
                                    backlog_container()
                                ],
                                className="panel grow",
                            ),
                            html.Div(
                                [
                                    html.H3("Workers"),
                                    html.Div(
                                        [worker_container(w["id"]) for w in WORKERS],
                                        className="workers-stack",
                                    ),
                                ],
                                className="panel grow",
                            ),
                        ],
                        className="left",
                    ),
                    # RIGHT 80%
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

# ---------- RENDERERS

@app.callback(Output("list-backlog", "children"), Input("state", "data"))
def render_backlog(state):
    return [task_card(t) for t in state["backlog"]]

for w in WORKERS:
    wid = w["id"]
    @app.callback(Output(f"list-worker-{wid}", "children"), Input("state", "data"))
    def render_worker(state, worker_id=wid):
        col = next(c for c in state["workers"] if c["worker_id"] == worker_id)
        if not col["tasks"]:
            return [html.Div("Drop tasks here", className="empty")]
        return [task_card(t) for t in col["tasks"]]

# ---------- ADD BOOKING

@app.callback(
    Output("state", "data"),
    Input("btn_add", "n_clicks"),
    State("in_customer", "value"),
    State("in_service", "value"),
    State("state", "data"),
    prevent_initial_call=True,
)
def add_to_backlog(n_clicks, customer, service_id, state):
    if not customer or not service_id:
        raise PreventUpdate
    state = json.loads(json.dumps(state))
    state["seq"] += 1
    task = {"id": f"t{state['seq']}", "customer": customer, "service_id": service_id}
    state["backlog"].append(task)
    return state

# ---------- DND HANDLER

@app.callback(Output("state", "data"), Input("dnd_listener", "event"), State("state", "data"), prevent_initial_call=True)
def on_dnd(event, state):
    if not event or event.get("type") != "dnd":
        raise PreventUpdate
    detail = event.get("detail") or {}
    item_id = detail.get("itemId")
    from_id = detail.get("fromId")
    to_id   = detail.get("toId")
    new_idx = int(detail.get("newIndex", 0))

    if not (item_id and from_id and to_id):
        raise PreventUpdate

    state = json.loads(json.dumps(state))

    def get_list(list_id):
        if list_id == "backlog":
            return state["backlog"]
        if list_id.startswith("worker-"):
            w = list_id.split("-", 1)[1]
            return next(c for c in state["workers"] if c["worker_id"] == w)["tasks"]
        raise ValueError("Unknown list id")

    src_list = get_list(from_id)
    dst_list = get_list(to_id)

    task = None
    for i, t in enumerate(src_list):
        if t["id"] == item_id:
            task = src_list.pop(i)
            break
    if task is None:
        raise PreventUpdate

    new_idx = max(0, min(new_idx, len(dst_list)))
    dst_list.insert(new_idx, task)

    return state

# ---------- GANTT

@app.callback(Output("gantt", "figure"), Input("state", "data"))
def update_gantt(state):
    df = build_schedule_df(state, services_idx, workers_idx, DAY_START)
    if df.empty:
        fig = px.timeline()
        fig.update_layout(title="No tasks scheduled yet.", height=700, margin=dict(l=20,r=20,t=40,b=20))
        return fig
    fig = px.timeline(
        df, x_start="Start", x_end="Finish",
        y="Worker", color="Service", text="Customer", hover_data=["Duration(min)"]
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_traces(textposition="inside", insidetextanchor="start", textfont_size=12, cliponaxis=False)
    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=700)
    return fig

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8050, debug=True)
