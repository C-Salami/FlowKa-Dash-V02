import io
import requests
from pydub import AudioSegment  # add to requirements.txt: pydub==0.25.1

# --- convert audio bytes to WAV ---
def convert_to_wav(audio_bytes: bytes, mime_type: str) -> bytes:
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=mime_type.split("/")[-1])
    except:
        # fallback: try guessing as webm if mime unknown
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")
    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()

# --- transcribe using API ---
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

# --- UI for mic capture ---
st.markdown("### Voice booking (mic)")

AUDIO_INPUT_AVAILABLE = hasattr(st, "audio_input")

if AUDIO_INPUT_AVAILABLE:
    audio = st.audio_input("Press to record, then stop", key="voice_mic_record")
    if audio is not None:
        try:
            transcript = transcribe_via_api(audio.getvalue(), audio.type or "audio/webm")
            if transcript:
                st.write(f"**Heard:** {transcript}")
                parsed = parse_voice_command(
                    transcript,
                    {s["name"].lower(): s for s in SERVICES},
                    {w["name"].lower(): w for w in WORKERS},
                )
                if parsed:
                    push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
                    st.success(
                        f"Added {services_idx[parsed['service_id']]['name']} "
                        f"for {parsed['customer']} → {workers_idx[parsed['worker_id']]['name']}"
                    )
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
                parsed = parse_voice_command(
                    transcript,
                    {s["name"].lower(): s for s in SERVICES},
                    {w["name"].lower(): w for w in WORKERS},
                )
                if parsed:
                    push_to_plan(parsed["customer"], parsed["service_id"], parsed["worker_id"])
                    st.success(
                        f"Added {services_idx[parsed['service_id']]['name']} "
                        f"for {parsed['customer']} → {workers_idx[parsed['worker_id']]['name']}"
                    )
                else:
                    st.info('Try: `add a swedish massage to Budi for customer "Ali"`')
            else:
                st.warning("No speech detected.")
        except Exception as e:
            st.error(f"Transcription error: {e}")
