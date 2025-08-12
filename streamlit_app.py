import io, os, requests, re
import streamlit as st

# --- simple aliases to recognize spa phrases in voice ---
SERVICE_ALIASES = {
    "swedish massage": "Swedish Massage", "swedish": "Swedish Massage",
    "thai massage": "Thai Massage", "thai": "Thai Massage",
    "deep tissue": "Deep Tissue", "hot stone": "Hot Stone",
    "facial": "Facial Treatment", "reflexology": "Reflexology",
}

def parse_voice_command(cmd: str, service_names, worker_names):
    t = cmd.strip()

    # service
    svc = None
    low = t.lower()
    for k, proper in SERVICE_ALIASES.items():
        if re.search(rf"\b{k}\b", low):
            svc = service_names.get(proper.lower()); break
    if not svc:
        for proper in service_names:
            if re.search(rf"\b{re.escape(proper)}\b", low):
                svc = service_names[proper]; break

    # worker (match by name token)
    wrk = None
    for wname in worker_names:
        if re.search(rf"\b{re.escape(wname)}\b", low):
            wrk = worker_names[wname]; break

    # customer: prefer quoted, else after "customer "
    cust = None
    m = re.search(r'customer\s+"([^"]+)"', t, flags=re.IGNORECASE) \
        or re.search(r"customer\s+'([^']+)'", t, flags=re.IGNORECASE) \
        or re.search(r'customer\s+([A-Za-z][A-Za-z\-]+(?:\s+[A-Za-z][A-Za-z\-]+)?)', t, flags=re.IGNORECASE)
    if m: cust = m.group(1).strip()

    if not all([svc, wrk, cust]): return None
    return {"service_id": svc["id"], "worker_id": wrk["id"], "customer": cust}

def transcribe_via_api(audio_bytes: bytes, mime_type: str) -> str:
    provider = st.secrets.get("STT_PROVIDER", "groq").lower()

    if provider == "groq":
        # OpenAI-compatible: /v1/audio/transcriptions
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {st.secrets['GROQ_API_KEY']}"}
        files = {
            "file": ("speech.webm", audio_bytes, mime_type),
            "model": (None, st.secrets.get("STT_MODEL", "whisper-large-v3-turbo")),
        }
        r = requests.post(url, headers=headers, files=files, timeout=60)
        r.raise_for_status()
        data = r.json()
        # Groq returns .text for plain text responses
        return data.get("text") or data

    elif provider == "deepgram":
        # Pre-recorded transcription endpoint ("listen")
        url = "https://api.deepgram.com/v1/listen"
        params = {"model": st.secrets.get("STT_MODEL", "nova-2-general"), "smart_format": "true"}
        headers = {"Authorization": f"Token {st.secrets['DEEPGRAM_API_KEY']}"}
        r = requests.post(url, params=params, headers=headers, data=audio_bytes)
        r.raise_for_status()
        data = r.json()
        # typical path: results.channels[0].alternatives[0].transcript
        return (data.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])[0]
                    .get("transcript", ""))

    else:
        raise RuntimeError("Unsupported STT_PROVIDER")

# --- UI: mic capture (Streamlit built-in) ---
st.markdown("### Voice booking (mic)")
audio = st.audio_input("Press to record, then stop", key="voice_mic")
if audio is not None:
    try:
        # audio is an UploadedFile with .getvalue() and .type (MIME), usually audio/webm
        transcript = transcribe_via_api(audio.getvalue(), audio.type or "audio/webm")
        if not transcript:
            st.warning("No speech detected")
        else:
            st.write(f"**Heard:** {transcript}")
            parsed = parse_voice_command(
                transcript,
                {s["name"].lower(): s for s in SERVICES},
                {w["name"].lower(): w for w in WORKERS},
            )
            if parsed:
                push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
                st.success(f"Added {services_idx[parsed['service_id']]['name']} for {parsed['customer']} → {workers_idx[parsed['worker_id']]['name']}")
            else:
                st.info('Try a phrasing like: `add a swedish massage to Budi for customer "Ali"`')
    except requests.HTTPError as e:
        st.error(f"STT API error: {e.response.text[:200]}")
    except Exception as e:
        st.error(f"Error: {e}")


import streamlit as st

# ... keep your other imports and functions ...

st.markdown("### Voice booking (mic)")

AUDIO_INPUT_AVAILABLE = hasattr(st, "audio_input")

if AUDIO_INPUT_AVAILABLE:
    audio = st.audio_input("Press to record, then stop", key="voice_mic")
    if audio is not None:
        transcript = transcribe_via_api(audio.getvalue(), audio.type or "audio/webm")
        st.write(f"**Heard:** {transcript}")
        parsed = parse_voice_command(
            transcript,
            {s["name"].lower(): s for s in SERVICES},
            {w["name"].lower(): w for w in WORKERS},
        )
        if parsed:
            push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
            st.success(
                f"Added {services_idx[parsed['service_id']]['name']} for {parsed['customer']} "
                f"→ {workers_idx[parsed['worker_id']]['name']}"
            )
        else:
            st.info('Try: `add a swedish massage to Budi for customer "Ali"`')
else:
    st.warning("This Streamlit version doesn’t support mic capture. Update to Streamlit ≥ 1.40, or use the uploader below.")
    audio_file = st.file_uploader("Upload a short voice note", type=["webm","wav","m4a","mp3"])
    if audio_file is not None:
        transcript = transcribe_via_api(audio_file.getvalue(), audio_file.type or "audio/webm")
        st.write(f"**Heard:** {transcript}")
        parsed = parse_voice_command(
            transcript,
            {s["name"].lower(): s for s in SERVICES},
            {w["name"].lower(): w for w in WORKERS},
        )
        if parsed:
            push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
            st.success(
                f"Added {services_idx[parsed['service_id']]['name']} for {parsed['customer']} "
                f"→ {workers_idx[parsed['worker_id']]['name']}"
            )
        else:
            st.info('Try: `add a swedish massage to Budi for customer "Ali"`')

