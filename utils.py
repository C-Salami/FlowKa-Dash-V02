from datetime import datetime, timedelta, date
import pandas as pd

def round_up_minutes(dt: datetime, minutes: int) -> datetime:
    q, r = divmod(dt.minute, minutes)
    if r == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt.replace(second=0, microsecond=0)
    new_min = (q + 1) * minutes
    hour_add, minute = divmod(new_min, 60)
    return dt.replace(hour=(dt.hour + hour_add), minute=minute, second=0, microsecond=0)

def build_schedule_df(state, services_index, workers_index, day_start, slot_min=15):
    """Return a DataFrame for px.timeline, including TaskId so the JS can identify bars."""
    today = date.today()
    day_start_dt = datetime.combine(today, day_start)
    rows = []
    for w in state.get("workers", []):
        cur = round_up_minutes(day_start_dt, slot_min)
        for item in w.get("tasks", []):
            svc = services_index[item["service_id"]]
            start = cur
            end = start + timedelta(minutes=svc["duration_min"])
            rows.append({
                "TaskId": item["id"],
                "Worker": workers_index[w["worker_id"]]["name"],
                "Customer": item["customer"],
                "Service": svc["name"],
                "Start": start,
                "Finish": end,
                "Duration(min)": svc["duration_min"],
            })
            cur = end
    if not rows:
        return pd.DataFrame(columns=["TaskId","Worker","Customer","Service","Start","Finish","Duration(min)"])
    return pd.DataFrame(rows)
