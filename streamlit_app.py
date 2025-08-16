# streamlit_app.py
# Spa Scheduler — 2D Gantt (time × workers), seeded 3/4 days + Form + Mic + Click-to-edit
# - One row per worker, tasks laid out over multiple days on the same row
# - Mic block on top-left
# - Reset moved under 3-dots popover
# - Click a bar to edit/delete

import io
import re
import random
from datetime import datetime, timedelta, date
import requests
import pandas as pd
import plotly.express as px
import streamlit as st
from pydub import AudioSegment                      # pydub==0.25.1, ffmpeg-python==0.2.0
from streamlit_plotly_events import plotly_events   # streamlit-plotly-events==0.0.6

# ---------- optional fuzzy: try rapidfuzz, else difflib fallback ----------
try:
    from rapidfuzz import process, fuzz
    def best_extract_one(query, choices, cutoff=80):
        res = process.extractOne(query, choices, scorer=fuzz.WRatio, score_cutoff=cutoff)
        return (res[0], res[1]) if res else (None, 0)
except Exception:
    from difflib import get_close_matches
    def best_extract_one(query, choices, cutoff=80):
        match = get_close_matches(query, choices, n=1, cutoff=cutoff/100.0)
        return (match[0], 100) if match else (None, 0)

# -------------------- App config --------------------
st.set_page_config(page_title="Spa Scheduler (2D • Mic • Edit)", layout="wide")

# -------------------- Demo data ---------------------
WORKERS = [
    {"id": "w1", "name": "Ayu"},
    {"id": "w2", "name": "Budi"},
    {"id": "w3", "name": "Citra"},
    {"id": "w4", "name": "Dewa"},
]

SERVICES = [
    {"id": "svc_thai",   "name": "Thai Massage",      "duration_min": 60},
    {"id": "svc_deep",   "name": "Deep Tissue",       "duration_min": 120},
    {"id": "svc_swed",   "name": "Swedish Massage",   "duration_min": 90},
    {"id": "svc_hot",    "name": "Hot Stone",         "duration_min": 90},
    {"id": "svc_facial", "name": "Facial Treatment",  "duration_min": 60},
    {"id": "svc_reflex", "name": "Reflexology",       "duration_min": 45},
]
services_idx = {s["id"]: s for s in SERVICES}
workers_idx  = {w["id"]: w for w in WORKERS}

# -------------------- App state ---------------------
if "seq" not in st.session_state:
    st.session_state.seq = 0
if "plan_by_day" not in st.session_state:
    def seed_day(d: date):
        customers = ["Ali", "Maya", "Rafi", "Lina", "John", "Emma", "Tom", "Sara"]
        svc_ids = [s["id"] for s in SERVICES]
        seeded = []
        for w in WORKERS:
            tasks = []
            slots = random.choice([1, 2])  # leave gaps
            for _ in range(slots):
                st.session_state.seq += 1
                tasks.append({
                    "id": f"t{st.session_state.seq}",
                    "customer": random.choice(customers),
                    "service_id": random.choice(svc_ids),
                })
            seeded.append({"worker_id": w["id"], "tasks": tasks})
        return seeded

    today = date.today()
    st.session_state.plan_by_day = {
        (today + timedelta(days=i)).isoformat(): seed_day(today + timedelta(days=i))
        for i in range(3)
    }

# temp voice state
for k in ("mic_audio_bytes", "mic_audio_mime", "mic_transcript", "mic_cmd"):
    st.session_state.setdefault(k, None)
# selected task for edit
if "selected_task" not in st.session_state:
    st.session_state.selected_task = None  # {"day","task_id","worker_id"}

# -------------------- Helpers -----------------------
def ensure_day_exists(day_iso: str):
    if day_iso not in st.session_state.plan_by_day:
        st.session_state.plan_by_day[day_iso] = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]

def push_to_plan(day_iso: str, customer: str, service_id: str, worker_id: str):
    ensure_day_exists(day_iso)
    st.session_state.seq += 1
    task = {"id": f"t{st.session_state.seq}", "customer": customer, "service_id": service_id}
    for col in st.session_state.plan_by_day[day_iso]:
        if col["worker_id"] == worker_id:
            col["tasks"].append(task)
            break

def build_schedule_df(start_day: date, days: int = 3) -> pd.DataFrame:
    """One row per worker across the entire time axis; tasks placed on Start/Finish over actual dates."""
    rows = []
    for i in range(days):
        d = (start_day + timedelta(days=i))
        d_iso = d.isoformat()
        ensure_day_exists(d_iso)
        day_cols = st.session_state.plan_by_day[d_iso]

        start_hour = 9
        cur_start_by_worker = {
            c["worker_id"]: datetime.combine(d, datetime.min.time()).replace(hour=start_hour)
            for c in day_cols
        }
        for col in day_cols:
            worker_id = col["worker_id"]
            worker_name = workers_idx[worker_id]["name"]
            cur = cur_start_by_worker[worker_id]
            for t in col["tasks"]:
                svc = services_idx[t["service_id"]]
                dur = timedelta(minutes=svc["duration_min"])
                rows.append({
                    "Day": d_iso,
                    "TaskId": t["id"],
                    "Customer": t["customer"],
                    "Service": svc["name"],
                    "Worker": worker_name,     # y-axis uses single worker name across all days
                    "WorkerId": worker_id,
                    "Start": pd.Timestamp(cur),
                    "Finish": pd.Timestamp(cur + dur),
                    "Duration(min)": svc["duration_min"],
                })
                gap = timedelta(minutes=random.choice([15, 20, 30]))
                cur = cur + dur + gap
    return pd.DataFrame(rows)

def find_task(day_iso: str, task_id: str):
    ensure_day_exists(day_iso)
    for col in st.session_state.plan_by_day[day_iso]:
        for idx, t in enumerate(col["tasks"]):
            if t["id"] == task_id:
                return col, idx, t
    return None, None, None

def reassign_task(day_iso: str, task_id: str, new_worker_id: str):
    src_col, idx, task = find_task(day_iso, task_id)
    if not task:
        return False
    src_col["tasks"].pop(idx)
    for col in st.session_state.plan_by_day[day_iso]:
        if col["worker_id"] == new_worker_id:
            col["tasks"].append(task)
            return True
    return False

# -------------- STT: audio -> text (Groq/Deepgram) --------------
def convert_to_wav(audio_bytes: bytes, mime_type: str) -> bytes:
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=(mime_type or "audio/webm").split("/")[-1])
    except Exception:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")
    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()

def transcribe_via_api(audio_bytes: bytes, mime_type: str) -> str:
    provider = st.secrets.get("STT_PROVIDER", "groq").lower()
    wav_bytes = convert_to_wav(audio_bytes, mime_type)

    if provider == "groq":
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {st.secrets['GROQ_API_KEY']}"}
        files = {
            "file": ("speech.wav", wav_bytes, "audio/wav"),
            "model": (None, st.secrets.get("STT_MODEL", "whisper-large-v3-turbo")),
        }
        r = requests.post(url, headers=headers, files=files, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Groq API error {r.status_code}: {r.text}")
        return r.json().get("text", "")

    elif provider == "deepgram":
        url = "https://api.deepgram.com/v1/listen"
        params = {"model": st.secrets.get("STT_MODEL", "nova-2-general"), "smart_format": "true"}
        headers = {"Authorization": f"Token {st.secrets['DEEPGRAM_API_KEY']}"}
        r = requests.post(url, params=params, headers=headers, data=wav_bytes, timeout=60)
        if not r.ok:
            raise RuntimeError(f"Deepgram API error {r.status_code}: {r.text}")
        data = r.json()
        return (data.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", ""))

    else:
        raise RuntimeError("Unsupported STT_PROVIDER; set STT_PROVIDER to 'groq' or 'deepgram' in secrets.")

# -------------- Interpreter: text -> command --------------
SERVICE_CATALOG = [s["name"] for s in SERVICES] + [
    "swedish", "swedish massage",
    "thai", "thai massage",
    "deep tissue",
    "hot stone",
    "facial", "facial treatment",
    "reflexology",
]
WORKER_CATALOG = [w["name"] for w in WORKERS]
SERVICE_ALIASES = {
    "swedish": "Swedish Massage",
    "swedish massage": "Swedish Massage",
    "thai": "Thai Massage",
    "thai massage": "Thai Massage",
    "deep tissue": "Deep Tissue",
    "hot stone": "Hot Stone",
    "facial": "Facial Treatment",
    "facial treatment": "Facial Treatment",
    "reflexology": "Reflexology",
}

def _best_service_match(text: str):
    for k, v in SERVICE_ALIASES.items():
        if re.search(rf"\b{k}\b", text, flags=re.IGNORECASE):
            return next(s for s in SERVICES if s["name"] == v)
    name, score = best_extract_one(text, SERVICE_CATALOG, cutoff=80)
    if not name:
        return None
    canon = SERVICE_ALIASES.get(name.lower(), name)
    return next((s for s in SERVICES if s["name"].lower() == canon.lower()), None)

def _best_worker_match(text: str):
    name, score = best_extract_one(text, WORKER_CATALOG, cutoff=80)
    if not name:
        return None
    return next((w for w in WORKERS if w["name"].lower() == name.lower()), None)

def interpret_command(utterance: str):
    t = utterance.strip()
    # customer (quoted; or after "customer"; or after "book"/"gives")
    m = re.search(r'customer\s+"([^"]+)"', t, flags=re.IGNORECASE) \
        or re.search(r"customer\s+'([^']+)'", t, flags=re.IGNORECASE)
    if m: customer = m.group(1).strip()
    else:
        m2 = re.search(r'customer\s+([A-Za-z][A-Za-z\-]+(?:\s+[A-Za-z][A-Za-z\-]+)?)', t, flags=re.IGNORECASE)
        customer = m2.group(1).strip() if m2 else None
        if not customer:
            m3 = re.search(r'\bbook\s+([A-Za-z][A-Za-z\-]+(?:\s+[A-Za-z][A-Za-z\-]+)?)\b', t, flags=re.IGNORECASE) \
                 or re.search(r'\bgives\s+([A-Za-z][A-Za-z\-]+(?:\s+[A-Za-z][A-Za-z\-]+)?)\b', t, flags=re.IGNORECASE)
            customer = m3.group(1).strip() if m3 else None

    # worker (with/to <name> … else fuzzy on whole)
    m_w = re.search(r'\bwith\s+([A-Za-z]+)\b', t, flags=re.IGNORECASE) \
          or re.search(r'\bto\s+([A-Za-z]+)\b', t, flags=re.IGNORECASE)
    worker = _best_worker_match(m_w.group(1)) if m_w else _best_worker_match(t)

    # service (aliases/fuzzy)
    service = _best_service_match(t)

    if service and worker and customer:
        return {"action": "add", "service_id": service["id"], "worker_id": worker["id"], "customer": customer}
    return None

def apply_command(day_iso: str, cmd: dict):
    if not cmd or cmd.get("action") != "add":
        return False, "Unsupported or empty command."
    push_to_plan(day_iso, cmd["customer"], cmd["service_id"], cmd["worker_id"])
    svc_name = next(s["name"] for s in SERVICES if s["id"] == cmd["service_id"])
    w_name   = next(w["name"] for w in WORKERS  if w["id"] == cmd["worker_id"])
    return True, f"Added {svc_name} for {cmd['customer']} → {w_name} on {day_iso}"

# -------------------- Layout ------------------------
left, right = st.columns([1, 4], gap="large")
today = date.today()

with left:
    st.title("Spa Scheduler")
    st.caption("One row per therapist. Add more via mic or form. Reset lives in the ⋮ menu.")

    # Mic FIRST (top)
    st.subheader("🎙 Voice booking (preview)")
    st.caption("Example: “add a swedish massage to Budi for customer ‘Ali’”.")
    AUDIO_INPUT_AVAILABLE = hasattr(st, "audio_input")
    if AUDIO_INPUT_AVAILABLE:
        audio_file = st.audio_input("Record, then stop", key="voice_mic_record")
    else:
        st.info("Mic capture requires Streamlit ≥ 1.40. Use the uploader instead.")
        audio_file = st.file_uploader("Upload a short voice note", type=["webm","wav","m4a","mp3"], key="voice_mic_upload")

    # Choose date span
    st.divider()
    st.subheader("Planning window")
    c_date, c_span, c_menu = st.columns([2, 1, 1])
    with c_date:
        sel_day = st.date_input("Start day", value=today, min_value=today, format="YYYY-MM-DD", key="start_day")
    with c_span:
        span_days = st.selectbox("Days", options=[3, 4], index=0, help="How many days to show on the timeline?")
    with c_menu:
        # neat 3-dots popover for admin tools (like reset)
        with st.popover("⋮"):
            st.write("Admin tools")
            if st.button("Reset seeded 3 days"):
                st.session_state.seq = 0
                st.session_state.plan_by_day = {}
                for i in range(3):
                    d = today + timedelta(days=i)
                    st.session_state.plan_by_day[d.isoformat()] = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]
                st.session_state.mic_audio_bytes = None
                st.session_state.mic_audio_mime  = None
                st.session_state.mic_transcript  = None
                st.session_state.mic_cmd         = None
                st.session_state.selected_task   = None
                st.experimental_rerun()

    # Voice flow: record -> transcribe -> preview -> push
    if audio_file is not None:
        st.session_state.mic_audio_bytes = audio_file.getvalue()
        st.session_state.mic_audio_mime  = audio_file.type or "audio/webm"
        st.audio(st.session_state.mic_audio_bytes, format=st.session_state.mic_audio_mime)
        if st.button("Transcribe", key="transcribe_btn", use_container_width=True):
            try:
                txt = transcribe_via_api(st.session_state.mic_audio_bytes, st.session_state.mic_audio_mime)
                st.session_state.mic_transcript = txt
                st.session_state.mic_cmd = interpret_command(txt) if txt else None
            except Exception as e:
                st.error(f"Transcription error: {e}")

    if st.session_state.mic_transcript is not None:
        st.markdown("**Transcript:**")
        st.code(st.session_state.mic_transcript)
        if st.session_state.mic_cmd:
            cmd = st.session_state.mic_cmd
            svc_name = next(s["name"] for s in SERVICES if s["id"] == cmd["service_id"])
            w_name   = next(w["name"] for w in WORKERS  if w["id"] == cmd["worker_id"])
            st.success(f"Parsed → Service: {svc_name} | Worker: {w_name} | Customer: {cmd['customer']}")
            if st.button("Push to plan (voice)", type="primary", use_container_width=True):
                ok, msg = apply_command(sel_day.isoformat(), cmd)
                if ok:
                    st.success(msg)
                    st.session_state.mic_transcript = None
                    st.session_state.mic_cmd = None
        else:
            st.warning("Couldn’t parse a full booking. Try the example above.")
            if st.button("Record again", key="retry_btn", use_container_width=True):
                st.session_state.mic_audio_bytes = None
                st.session_state.mic_audio_mime  = None
                st.session_state.mic_transcript  = None
                st.session_state.mic_cmd         = None
                st.experimental_rerun()

    st.divider()

    # Manual form
    st.subheader("Add booking (manual)")
    m_customer = st.text_input("Customer")
    m_service  = st.selectbox(
        "Service",
        options=[s["id"] for s in SERVICES],
        format_func=lambda sid: f"{services_idx[sid]['name']} ({services_idx[sid]['duration_min']}m)",
        key="manual_service",
    )
    m_worker = st.selectbox(
        "Worker",
        options=[w["id"] for w in WORKERS],
        format_func=lambda wid: workers_idx[wid]["name"],
        key="manual_worker",
    )
    if st.button("Push to plan", type="primary", use_container_width=True):
        if m_customer and m_service and m_worker:
            push_to_plan(sel_day.isoformat(), m_customer, m_service, m_worker)
            st.success(f"Added {services_idx[m_service]['name']} for {m_customer} → {workers_idx[m_worker]['name']} on {sel_day.isoformat()}")
        else:
            st.warning("Please complete all fields.")

    st.divider()

    # Edit panel (appears after clicking a bar)
    st.subheader("✏️ Edit booking (click a bar)")
    if st.session_state.selected_task:
        sel = st.session_state.selected_task
        day_iso = sel["day"]
        task_id = sel["task_id"]
        cur_worker_id = sel["worker_id"]
        _, _, t = find_task(day_iso, task_id)
        if t:
            cur_service_id = t["service_id"]
            cur_customer   = t["customer"]

            st.markdown(f"**Editing:** {task_id} on **{day_iso}**")
            e_customer = st.text_input("Customer", value=cur_customer, key="edit_customer")
            e_service  = st.selectbox(
                "Service",
                options=[s["id"] for s in SERVICES],
                index=[s["id"] for s in SERVICES].index(cur_service_id),
                format_func=lambda sid: f"{services_idx[sid]['name']} ({services_idx[sid]['duration_min']}m)",
                key="edit_service"
            )
            e_worker   = st.selectbox(
                "Worker",
                options=[w["id"] for w in WORKERS],
                index=[w["id"] for w in WORKERS].index(cur_worker_id),
                format_func=lambda wid: workers_idx[wid]["name"],
                key="edit_worker"
            )

            ec1, ec2, ec3 = st.columns([2,2,1])
            with ec1:
                if st.button("Save changes", type="primary", use_container_width=True):
                    if e_worker != cur_worker_id:
                        reassign_task(day_iso, task_id, e_worker)
                        cur_worker_id = e_worker
                    col, idx, task_ref = find_task(day_iso, task_id)
                    if task_ref:
                        task_ref["customer"]   = e_customer
                        task_ref["service_id"] = e_service
                        st.success("Booking updated.")
                        st.session_state.selected_task = None
                        st.experimental_rerun()
            with ec2:
                if st.button("Delete booking", use_container_width=True):
                    col, idx, task_ref = find_task(day_iso, task_id)
                    if task_ref:
                        col["tasks"].pop(idx)
                        st.success("Booking deleted.")
                        st.session_state.selected_task = None
                        st.experimental_rerun()
            with ec3:
                if st.button("Cancel", use_container_width=True):
                    st.session_state.selected_task = None
                    st.experimental_rerun()
    else:
        st.info("Click a bar in the chart to edit.")

with right:
    st.subheader(f"Schedule • {sel_day.isoformat()} → {(sel_day + timedelta(days=span_days-1)).isoformat()}")

    df = build_schedule_df(sel_day, days=span_days)
    if df.empty:
        st.info("No bookings yet. Use the mic or the form on the left.")
    else:
        # Colors by Service; one row per worker; full time axis over multiple days
        fig = px.timeline(
            df,
            x_start="Start",
            x_end="Finish",
            y="Worker",
            color="Service",
            text="Customer",
            hover_data=["Day", "Duration(min)"],
            category_orders={"Worker": [w["name"] for w in WORKERS]},
        )
        # Attach identifiers so clicks work
        fig.update_traces(customdata=df[["TaskId", "Day", "WorkerId"]].to_numpy().tolist())

        # Layout polish for 2D view
        fig.update_yaxes(autorange="reversed")  # Gantt convention
        fig.update_traces(textposition="inside", insidetextanchor="start", textfont_size=12, cliponaxis=False)
        fig.update_layout(
            margin=dict(l=20, r=20, t=40, b=20),
            height=900,
            xaxis_title=None,
            yaxis_title=None,
            legend_title_text="Service",
        )

        # Interactions: click a bar to edit
        events = plotly_events(
            fig, click_event=True, hover_event=False, select_event=False,
            override_height=900, key="gantt_click_events"
        )
        if events:
            pt = events[0]
            cd = pt.get("customdata") or []
            if isinstance(cd, list) and len(cd) >= 3:
                task_id, day_iso, worker_id = cd[0], cd[1], cd[2]
                st.session_state.selected_task = {"task_id": task_id, "day": day_iso, "worker_id": worker_id}
                st.rerun()

st.caption("Tip: Use mic or form to add on the selected start day. Chart shows 3–4 days on one timeline with one row per worker.")
