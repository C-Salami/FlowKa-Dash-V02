# streamlit_app.py
# Spa Scheduler — Form + Mic (preview before applying)

import io
import re
import requests
import pandas as pd
import plotly.express as px
import streamlit as st
from pydub import AudioSegment              # -> requirements: pydub==0.25.1, ffmpeg-python==0.2.0
from rapidfuzz import process, fuzz         # -> requirements: rapidfuzz==3.9.6

# -------------------- App config --------------------
st.set_page_config(page_title="Spa Scheduler (Form + Mic)", layout="wide")

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
if "plan" not in st.session_state:
    st.session_state.plan = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]

# voice temp state
for k in ("mic_audio_bytes", "mic_audio_mime", "mic_transcript", "mic_cmd"):
    st.session_state.setdefault(k, None)

# -------------------- Helpers -----------------------
def push_to_plan(customer: str, service_id: str, worker_id: str):
    st.session_state.seq += 1
    task = {"id": f"t{st.session_state.seq}", "customer": customer, "service_id": service_id}
    for col in st.session_state.plan:
        if col["worker_id"] == worker_id:
            col["tasks"].append(task)
            break

def build_schedule_df():
    rows = []
    start_hour = 9
    today9 = pd.Timestamp.now().replace(hour=start_hour, minute=0, second=0, microsecond=0)
    for col in st.session_state.plan:
        cur = today9
        for t in col["tasks"]:
            svc = services_idx[t["service_id"]]
            dur = pd.Timedelta(minutes=svc["duration_min"])
            rows.append({
                "TaskId": t["id"],
                "Customer": t["customer"],
                "Service": svc["name"],
                "Worker": workers_idx[col["worker_id"]]["name"],
                "Start": cur,
                "Finish": cur + dur,
                "Duration(min)": svc["duration_min"],
            })
            cur += dur
    return pd.DataFrame(rows)

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
    name, score, _ = process.extractOne(text, SERVICE_CATALOG, scorer=fuzz.WRatio, score_cutoff=80) or (None, 0, None)
    if not name:
        return None
    canon = SERVICE_ALIASES.get(name.lower(), name)
    return next((s for s in SERVICES if s["name"].lower() == canon.lower()), None)

def _best_worker_match(text: str):
    name, score, _ = process.extractOne(text, WORKER_CATALOG, scorer=fuzz.WRatio, score_cutoff=80) or (None, 0, None)
    if not name:
        return None
    return next((w for w in WORKERS if w["name"].lower() == name.lower()), None)

def interpret_command(utterance: str):
    t = utterance.strip()

    # customer (quoted first; else after "customer"; else simple "book/gives <name>")
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

    m_w = re.search(r'\bwith\s+([A-Za-z]+)\b', t, flags=re.IGNORECASE) \
          or re.search(r'\bto\s+([A-Za-z]+)\b', t, flags=re.IGNORECASE)
    worker = _best_worker_match(m_w.group(1)) if m_w else _best_worker_match(t)
    service = _best_service_match(t)

    if service and worker and customer:
        return {"action": "add", "service_id": service["id"], "worker_id": worker["id"], "customer": customer}
    return None

def apply_command(cmd: dict):
    if not cmd or cmd.get("action") != "add":
        return False, "Unsupported or empty command."
    push_to_plan(cmd["customer"], cmd["service_id"], cmd["worker_id"])
    svc_name = next(s["name"] for s in SERVICES if s["id"] == cmd["service_id"])
    w_name   = next(w["name"] for w in WORKERS  if w["id"] == cmd["worker_id"])
    return True, f"Added {svc_name} for {cmd['customer']} → {w_name}"

# -------------------- Layout ------------------------
left, right = st.columns([1, 4], gap="large")

with left:
    st.title("Spa Scheduler")

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

    c1, c2 = st.columns([2,1])
    with c1:
        if st.button("Push to plan", type="primary", use_container_width=True):
            if m_customer and m_service and m_worker:
                push_to_plan(m_customer, m_service, m_worker)
                st.success(f"Added {services_idx[m_service]['name']} for {m_customer} → {workers_idx[m_worker]['name']}")
            else:
                st.warning("Please complete all fields.")
    with c2:
        if st.button("Reset day", use_container_width=True):
            st.session_state.seq = 0
            st.session_state.plan = [{"worker_id": w["id"], "tasks": []} for w in WORKERS]
            st.session_state.mic_audio_bytes = None
            st.session_state.mic_audio_mime  = None
            st.session_state.mic_transcript  = None
            st.session_state.mic_cmd         = None

    st.divider()

    # Mic section (preview before applying)
    st.subheader("🎙 Voice booking (preview first)")

    AUDIO_INPUT_AVAILABLE = hasattr(st, "audio_input")
    if AUDIO_INPUT_AVAILABLE:
        audio_file = st.audio_input("Record, then stop", key="voice_mic_record")
    else:
        st.info("Mic capture requires Streamlit ≥ 1.40. Use the uploader instead.")
        audio_file = st.file_uploader("Upload a short voice note", type=["webm","wav","m4a","mp3"], key="voice_mic_upload")

    # Step 1: capture
    if audio_file is not None:
        st.session_state.mic_audio_bytes = audio_file.getvalue()
        st.session_state.mic_audio_mime  = audio_file.type or "audio/webm"
        st.audio(st.session_state.mic_audio_bytes, format=st.session_state.mic_audio_mime)

        # Step 2: transcribe (if not already done for this recording)
        if st.button("Transcribe", key="transcribe_btn", use_container_width=True):
            try:
                txt = transcribe_via_api(st.session_state.mic_audio_bytes, st.session_state.mic_audio_mime)
                st.session_state.mic_transcript = txt
                st.session_state.mic_cmd = interpret_command(txt) if txt else None
            except Exception as e:
                st.error(f"Transcription error: {e}")

    # Step 3: show transcript + parsed command
    if st.session_state.mic_transcript is not None:
        st.markdown("**Transcript:**")
        st.code(st.session_state.mic_transcript)
        if st.session_state.mic_cmd:
            cmd = st.session_state.mic_cmd
            svc_name = next(s["name"] for s in SERVICES if s["id"] == cmd["service_id"])
            w_name   = next(w["name"] for w in WORKERS  if w["id"] == cmd["worker_id"])
            st.success(f"Parsed → Service: {svc_name} | Worker: {w_name} | Customer: {cmd['customer']}")
            pc1, pc2 = st.columns(2)
            with pc1:
                if st.button("Push to plan (voice)", type="primary", use_container_width=True):
                    ok, msg = apply_command(cmd)
                    if ok:
                        st.success(msg)
                        # clear transcript after apply (optional)
                        st.session_state.mic_transcript = None
                        st.session_state.mic_cmd = None
            with pc2:
                if st.button("Record again", use_container_width=True):
                    st.session_state.mic_audio_bytes = None
                    st.session_state.mic_audio_mime  = None
                    st.session_state.mic_transcript  = None
                    st.session_state.mic_cmd         = None
                    st.experimental_rerun()
        else:
            st.warning("I couldn’t understand a full booking. Try: `add a swedish massage to Budi for customer \"Ali\"`")
            if st.button("Record again", key="retry_btn", use_container_width=True):
                st.session_state.mic_audio_bytes = None
                st.session_state.mic_audio_mime  = None
                st.session_state.mic_transcript  = None
                st.session_state.mic_cmd         = None
                st.experimental_rerun()

with right:
    st.subheader("Schedule")
    df = build_schedule_df()
    if df.empty:
        st.info("No bookings yet. Use the form or voice on the left.")
    else:
        fig = px.timeline(
            df, x_start="Start", x_end="Finish",
            y="Worker", color="Service", text="Customer", hover_data=["Duration(min)"]
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_traces(textposition="inside", insidetextanchor="start", textfont_size=12, cliponaxis=False)
        fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=760)
        st.plotly_chart(fig, use_container_width=True)

st.caption("Tip: for best accuracy, say: “add a swedish massage to Budi for customer ‘Ali’”.")
