import streamlit as st
import openai
import requests
import time
import random
import re
import os
import subprocess
from io import BytesIO
from dotenv import load_dotenv


load_dotenv()

OPENAI_API_KEY =  os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

MALE_VOICES = [
    "YmpzixbkOaQ7t3lmyaRe",
    "wViXBPUzp2ZZixB1xQuM",
    "TxGEqnHWrfWFTfGW9XjX"
]

FEMALE_VOICES = [
    "XcXEQzuLXRU9RcfWzEJt",
    "ADd2WEtjmwokqUr0Y5Ad",
    "AZnzlk1XvdvUeBnXmlld"
]

def cleanup_temp_files(output_folder="audio_clips"):

    if not os.path.exists(output_folder):
        return

    for filename in os.listdir(output_folder):
        file_path = os.path.join(output_folder, filename)
        if filename != "final_podcast.mp3" and (filename.endswith(".mp3") or filename == "files.txt"):
            try:
                os.remove(file_path)
            except Exception as e:
                st.warning(f"Could not delete {filename}: {str(e)}")

def get_character_info(num_speakers):
    characters = []
    for i in range(num_speakers):
        with st.expander(f"Speaker {i + 1} Details", expanded=(i == 0)):
            cols = st.columns([2, 1, 2])
            name = cols[0].text_input("Full Name", key=f"name_{i}", placeholder="e.g. John, Joe")
            gender = cols[1].selectbox("Gender", ["male", "female"], key=f"gender_{i}" )
            profession = cols[2].text_input("Profession", key=f"prof_{i}", placeholder="e.g. Host, Engineer")
            background = st.text_input("Background", key=f"bg_{i}", placeholder="e.g. City, Education, Hobbies")
            personality = st.text_input("Personality Traits", key=f"personality_{i}", placeholder="e.g. Funny, Curious, Sarcastic")

            if not name:
                st.warning("Please enter a name for this speaker")
                return None

            characters.append({
                "name": name,
                "gender": gender,
                "profession": profession,
                "background": background,
                "personality": personality
            })
    return characters

def assign_voices_to_characters(characters):
    voice_mapping = {}
    used_voices = set()
    assignments = []

    for char in characters:
        first_name = char["name"].strip().split()[0].lower()
        available_voices = MALE_VOICES if char["gender"] == "male" else FEMALE_VOICES
        available = [v for v in available_voices if v not in used_voices]

        if available:
            chosen_voice = random.choice(available)
            used_voices.add(chosen_voice)
        else:
            chosen_voice = random.choice(available_voices)

        voice_mapping[first_name] = chosen_voice
        assignments.append(f"{char['name']} → Voice ID: {chosen_voice}")

    return voice_mapping, assignments

def generate_podcast_script(topic: str, duration_minutes: int, setting: str, characters: list):
    character_descriptions = "\n".join([
        f"- {char['name']} ({char['gender']}), {char['profession']} from {char['background']}, {char['personality']}"
        for char in characters
    ])

    prompt = f"""Create a {duration_minutes }-minute podcast script about {topic} with a word per minute of 400.
    Setting: {setting}
    Participants:
    {character_descriptions}
    Include natural conversation flow with interruptions and humor.
    Add a rapid-fire round in the last third.
    NO stage directions or annotations - dialogue only. Eg: avoid words like (laughs), (chuckling) etc in brackets."""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional podcast writer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Script generation failed: {str(e)}")
        return None

def extract_and_generate_audio(script: str, voice_mapping: dict):
    output_folder = "audio_clips"
    os.makedirs(output_folder, exist_ok=True)

    lines = re.findall(r"([A-Za-z ]+):\s*(.+)", script)
    if not lines:
        st.error("No dialogue lines found in script!")
        return False

    progress_bar = st.progress(0)
    status_text = st.empty()
    generated_files = []

    for idx, (speaker, line) in enumerate(lines):
        progress = (idx + 1) / len(lines)
        progress_bar.progress(progress)
        status_text.text(f"Generating audio for {speaker}...")

        first_name = speaker.strip().split()[0].lower()
        voice_id = voice_mapping.get(first_name)
        if not voice_id:
            st.warning(f"No voice assigned for speaker: {speaker}")
            continue

        filename = os.path.join(output_folder, f"{idx + 1:03d}_{speaker}.mp3")

        for attempt in range(3):
            try:
                response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={"xi-api-key": ELEVENLABS_API_KEY},
                    json={
                        "text": line,
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {"stability": 0.7, "similarity_boost": 0.8}
                    },
                    timeout=30
                )

                if response.status_code == 200 and response.content:
                    with open(filename, "wb") as f:
                        f.write(response.content)
                    generated_files.append(filename)
                    break
                else:
                    st.warning(f"Attempt {attempt + 1} failed for {speaker}")
            except Exception as e:
                st.warning(f"Attempt {attempt + 1} error: {str(e)}")
                time.sleep(2)

    progress_bar.empty()
    status_text.empty()

    if not generated_files:
        st.error("No audio files were generated!")
        return False

    return True

def combine_audio_clips_ffmpeg():
    output_folder = "audio_clips"
    list_file = os.path.join(output_folder, "files.txt")
    final_output = os.path.join(output_folder, "final_podcast.mp3")

    if os.path.exists(final_output):
        os.remove(final_output)

    mp3_files = sorted([f for f in os.listdir(output_folder)
                        if f.endswith(".mp3") and f != "final_podcast.mp3"])

    if not mp3_files:
        st.error("No audio clips found to combine!")
        return False

    with open(list_file, "w") as f:
        for file in mp3_files:
            f.write(f"file '{file}'\n")

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "files.txt",
             "-c", "copy", "final_podcast.mp3"],
            cwd=output_folder,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            st.error(f"FFmpeg failed with error:\n{result.stderr}")
            return False

        if not os.path.exists(final_output):
            st.error("Final podcast file was not created")
            return False

        cleanup_temp_files()
        return True

    except Exception as e:
        st.error(f"Error combining audio: {str(e)}")
        return False

def main():
    st.set_page_config(page_title="AI Podcast Generator", layout="wide")
    st.title("🎧 AI Podcast Generator")
    st.markdown("---")

    if "podcast_ready" not in st.session_state:
        st.session_state.podcast_ready = False

    with st.sidebar:
        st.header("Podcast Settings")
        topic = st.text_input("Main Topic", placeholder="e.g. Future of AI")
        duration = st.slider("Duration (minutes)", 5, 30)
        setting = st.text_area("Environment/Setting", placeholder="e.g. Casual coffee shop setting")
        num_speakers = st.number_input("Number of Speakers", 1, 5, 2)

    st.header("Hosts & Guests")
    characters = get_character_info(num_speakers)
    if not characters:
        st.stop()

    if st.button("🚀 Generate Podcast", type="primary", use_container_width=True):
        with st.status("Building Your Podcast...", expanded=True) as status:
            try:
                st.write("🔊 Assigning Voices...")
                voice_mapping, assignments = assign_voices_to_characters(characters)

                st.write("📝 Writing Script...")
                script = generate_podcast_script(topic, duration, setting, characters)
                if not script:
                    st.stop()

                st.session_state.script = script
                st.session_state.assignments = assignments

                st.write("🔈 Creating Audio Clips...")
                if not extract_and_generate_audio(script, voice_mapping):
                    st.stop()

                st.write("🎚️ Mixing Final Podcast...")
                if not combine_audio_clips_ffmpeg():
                    st.stop()

                st.session_state.podcast_ready = True
                status.update(label="Podcast Ready! 🎉", state="complete")

            except Exception as e:
                st.error(f"Generation failed: {str(e)}")
                st.stop()

    if st.session_state.get("podcast_ready"):
        st.markdown("---")
        st.header("Results")

        with st.expander("📜 Show Podcast Script", expanded=True):
            st.code(st.session_state.script, language="text")

        st.subheader("Voice Assignments")
        for assignment in st.session_state.assignments:
            st.info(f"🎙️ {assignment}")

        st.subheader("Final Podcast")
        audio_file = os.path.join("audio_clips", "final_podcast.mp3")

        if os.path.exists(audio_file):
            audio_bytes = open(audio_file, "rb").read()
            st.audio(audio_bytes, format="audio/mp3")

            st.download_button(
                "⬇️ Download MP3",
                data=audio_bytes,
                file_name="ai_podcast.mp3",
                mime="audio/mpeg",
                use_container_width=True
            )
        else:
            st.error("Final podcast file not found. Please regenerate.")


if __name__ == "__main__":
    if os.path.exists("audio_clips"):
        cleanup_temp_files()
    main()