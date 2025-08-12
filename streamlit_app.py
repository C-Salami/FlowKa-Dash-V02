import streamlit as st
import pandas as pd
import plotly.express as px
import json
import io
import requests
from pydub import AudioSegment  # make sure to add to requirements.txt

# ---- YOUR DATA ----
WORKERS = [
    {"id": "w1", "name": "Ayu"},
    {"id": "w2", "name": "Budi"},
    {"id": "w3", "name": "Chandra"},
    {"id": "w4", "name": "Dewi"}
]

SERVICES = [
    {"id": "s1", "name": "Thai Massage", "duration_min": 60},
    {"id": "s2", "name": "Deep Tissue", "duration_min": 120},
    {"id": "s3", "name": "Swedish Massage", "duration_min": 90},
    {"id": "s4", "name": "Hot Stone", "duration_min": 90},
    {"id": "s5", "name": "Facial Treatment", "duration_min": 60},
    {"id": "s6", "name": "Reflexology", "duration_min": 45},
]

services_idx = {s["id"]: s for s in SERVICES}
workers_idx = {w["id"]: w for w in WORKERS}
worker_name_to_id = {w["name"].lower(): w["id"] for w in WORKERS}

# ---- APP STATE ----
if "state" not in st.session_state:
    st.session_state.state = {"seq": 0, "workers": [{"worker_id": w["id"], "tasks": []} for w in WORKERS]}

def push_to_plan(customer, service_id, worker_id):
    st.session_state.state["seq"] += 1
    task = {"id": f"t{st.session_state.state['seq']}", "customer": customer, "service_id": service_id}
    for col in st.session_state.state["workers"]:
        if col["worker_id"] == worker_id:
            col["tasks"].append(task)
            break

def build_schedule_df(state):
    rows = []
    start_hour = 9
    for w in state["workers"]:
        cur_time = pd.Timestamp.now().replace(hour=start_hour, minute=0, second=0, microsecond=0)
        for t in w["tasks"]:
            svc = services_idx[t["service_id"]]
            dur = pd.Timedelta(minutes=svc["duration_min"])
            rows.append({
                "TaskId": t["id"],
                "Customer": t["customer"],
                "Service": svc["name"],
                "Worker": workers_idx[w["worker_id"]]["name"],
                "Start": cur_time,
                "Finish": cur_time + dur,
                "Duration(min)": svc["duration_min"],
            })
            cur_time += dur
    return pd.DataFrame(rows)

# ---- FORM BOOKING ----
st.sidebar.header("Add Booking")
customer = st.sidebar.text_input("Customer name")
service_id = st.sidebar.selectbox("Service", [s["id"] for s in SERVICES], format_func=lambda x: next(s["name"] for s in SERVICES if s["id"] == x))
worker_id = st.sidebar.selectbox("Worker", [w["id"] for w in WORKERS], format_func=lambda x: next(w["name"] for w in WORKERS if w["id"] == x))
if st.sidebar.button("Push to plan"):
    if customer and service_id and worker_id:
        push_to_plan(customer, service_id, worker_id)
        st.sidebar.success(f"Added {services_idx[service_id]['name']} for {customer}")
    else:
        st.sidebar.warning("Please fill in all fields.")

# ---- GANTT CHART ----
df = build_schedule_df(st.session_state.state)
if not df.empty:
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Worker", color="Service", text="Customer")
    fig.update_yaxes(autorange="reversed")
    fig.update_traces(textposition="inside", insidetextanchor="start")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No bookings yet.")

# ---- VOICE COMMANDS ----
SERVICE_ALIASES = {
    "swedish massage": "Swedish Massage",
    "swedish": "Swedish Massage",
    "thai massage": "Thai Massage",
    "thai": "Thai Massage",
    "deep tissue": "Deep Tissue",
    "hot stone": "Hot Stone",
    "facial": "Facial Treatment",
    "reflexology": "Reflexology",
}

def parse_voice_command(cmd: str):
    t = cmd.strip()
    svc = None
    for k, proper in SERVICE_ALIASES.items():
        if k in t.lower():
            svc = next((s for s in SERVICES if s["name"] == proper), None)
            break
    wrk = None
    for w in WORKERS:
        if w["name"].lower() in t.lower():
            wrk = w
            break
    cust = None
    import re
    m = re.search(r'customer\s+"([^"]+)"', t, flags=re.IGNORECASE) \
        or re.search(r"customer\s+'([^']+)'", t, flags=re.IGNORECASE) \
        or re.search(r'customer\s+([A-Za-z][A-Za-z\-]+)', t, flags=re.IGNORECASE)
    if m:
        cust = m.group(1).strip()
    if svc and wrk and cust:
        return {"service_id": svc["id"], "worker_id": wrk["id"], "customer": cust}
    return None

def convert_to_wav(audio_bytes: bytes, mime_type: str) -> bytes:
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=mime_type.split("/")[-1])
    except:
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
        r = requests.post(url, params=params, headers=headers, data=wav_bytes)
        if not r.ok:
            raise RuntimeError(f"Deepgram API error {r.status_code}: {r.text}")
        data = r.json()
        return (data.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", ""))

    else:
        raise RuntimeError("Unsupported STT_PROVIDER")

st.markdown("### 🎙 Voice booking")
AUDIO_INPUT_AVAILABLE = hasattr(st, "audio_input")

if AUDIO_INPUT_AVAILABLE:
    audio = st.audio_input("Press to record, then stop", key="voice_mic_record")
    if audio is not None:
        try:
            transcript = transcribe_via_api(audio.getvalue(), audio.type or "audio/webm")
            if transcript:
                st.write(f"**Heard:** {transcript}")
                parsed = parse_voice_command(transcript)
                if parsed:
                    push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
                    st.success(f"Added {services_idx[parsed['service_id']]['name']} for {parsed['customer']} → {workers_idx[parsed['worker_id']]['name']}")
                else:
                    st.info('Try: `add a swedish massage to Budi for customer "Ali"`')
            else:
                st.warning("No speech detected.")
        except Exception as e:
            st.error(f"Transcription error: {e}")
else:
    st.warning("Mic capture not supported in this Streamlit version. Use uploader instead.")
    uploaded = st.file_uploader("Upload a short voice note", key="voice_mic_upload", type=["webm", "wav", "m4a", "mp3"])
    if uploaded is not None:
        try:
            transcript = transcribe_via_api(uploaded.getvalue(), uploaded.type or "audio/webm")
            if transcript:
                st.write(f"**Heard:** {transcript}")
                parsed = parse_voice_command(transcript)
                if parsed:
                    push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
                    st.success(f"Added {services_idx[parsed['service_id']]['name']} for {parsed['customer']} → {workers_idx[parsed['worker_id']]['name']}")
                else:
                    st.info('Try: `add a swedish massage to Budi for customer "Ali"`')
            else:
                st.warning("No speech detected.")
        except Exception as e:
            st.error(f"Transcription error: {e}")
