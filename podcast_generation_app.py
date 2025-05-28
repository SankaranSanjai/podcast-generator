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
import base64
import urllib.parse

# Load environment variables
load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PODBEAN_CLIENT_ID = os.getenv("PODBEAN_CLIENT_ID")
PODBEAN_CLIENT_SECRET = os.getenv("PODBEAN_CLIENT_SECRET")
PODBEAN_REDIRECT_URI = os.getenv("PODBEAN_REDIRECT_URI", "http://localhost:8501")

# Voice IDs
MALE_VOICES = [
    "iP95p4xoKVk53GoZ742B",
    "wViXBPUzp2ZZixB1xQuM",
    "TxGEqnHWrfWFTfGW9XjX"
]

FEMALE_VOICES = [
    "XcXEQzuLXRU9RcfWzEJt",
    "ADd2WEtjmwokqUr0Y5Ad",
    "AZnzlk1XvdvUeBnXmlld"
]


# ======================
# Utility Functions
# ======================

def cleanup_temp_files(output_folder="audio_clips"):
    """Clean up temporary audio files"""
    if not os.path.exists(output_folder):
        return

    for filename in os.listdir(output_folder):
        file_path = os.path.join(output_folder, filename)
        if filename != "final_podcast.mp3" and (filename.endswith(".mp3") or filename == "files.txt"):
            try:
                os.remove(file_path)
            except Exception as e:
                st.warning(f"Could not delete {filename}: {str(e)}")


# ======================
# Podcast Generation
# ======================

def get_character_info(num_speakers):
    """Get character details from user input"""
    characters = []
    for i in range(num_speakers):
        with st.expander(f"Speaker {i + 1} Details", expanded=(i == 0)):
            cols = st.columns([2, 1, 2])
            name = cols[0].text_input("Full Name", key=f"name_{i}", placeholder="e.g. John, Joe")
            gender = cols[1].selectbox("Gender", ["male", "female"], key=f"gender_{i}")
            profession = cols[2].text_input("Profession", key=f"prof_{i}", placeholder="e.g. Host, Engineer")
            background = st.text_input("Background", key=f"bg_{i}", placeholder="e.g. City, Education, Hobbies")
            personality = st.text_input("Personality Traits", key=f"personality_{i}",
                                        placeholder="e.g. Funny, Curious, Sarcastic")

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
    """Assign unique voices to each character"""
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
    """Generate podcast script using OpenAI"""
    character_descriptions = "\n".join([
        f"- {char['name']} ({char['gender']}), {char['profession']} from {char['background']}, {char['personality']}"
        for char in characters
    ])

    prompt = f"""Create a {duration_minutes}-minute podcast script about {topic} with about 150 words per minute.  
Setting: {setting}  
Participants:  
{character_descriptions}  

Format Requirements:
- Dialogue-only format (no narration or stage directions)
- Natural conversational flow with interruptions
- Include a rapid-fire question round in the last third
- Each speaker should have distinct personality shining through
- End with a memorable closing line

Example Style:
Alex: "I can't believe you think pineapple belongs on pizza!"
Jamie: "Oh come on, it's the perfect sweet and savory combo!"
Taylor: "You're both wrong - the real crime is no pineapple!" """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system",
                 "content": "You are a professional podcast writer. Create engaging, natural-sounding dialogue."},
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
    """Generate audio clips for each line of dialogue"""
    output_folder = "audio_clips"
    os.makedirs(output_folder, exist_ok=True)

    # Improved regex to handle various name formats and punctuation
    lines = re.findall(r"^([A-Za-z][A-Za-z\s]+?):\s*([^\n]+)", script, re.MULTILINE)
    if not lines:
        st.error("No dialogue lines found in script!")
        return False

    progress_bar = st.progress(0)
    status_text = st.empty()
    generated_files = []

    for idx, (speaker, line) in enumerate(lines):
        progress = (idx + 1) / len(lines)
        progress_bar.progress(progress)
        status_text.text(f"Generating audio for {speaker.strip()}...")

        first_name = speaker.strip().split()[0].lower()
        voice_id = voice_mapping.get(first_name)
        if not voice_id:
            st.warning(f"No voice assigned for speaker: {speaker}")
            continue

        filename = os.path.join(output_folder, f"{idx + 1:03d}_{speaker.strip()}.mp3")

        for attempt in range(3):  # Retry up to 3 times
            try:
                response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={"xi-api-key": ELEVENLABS_API_KEY},
                    json={
                        "text": line.strip(),
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {
                            "stability": 0.7,
                            "similarity_boost": 0.8,
                            "style": 0.5,
                            "speaker_boost": True
                        }
                    },
                    timeout=30
                )

                if response.status_code == 200 and response.content:
                    with open(filename, "wb") as f:
                        f.write(response.content)
                    generated_files.append(filename)
                    break
                else:
                    st.warning(f"Attempt {attempt + 1} failed for {speaker}: {response.text}")
            except Exception as e:
                st.warning(f"Attempt {attempt + 1} error: {str(e)}")
                time.sleep(2)  # Wait before retrying

    progress_bar.empty()
    status_text.empty()

    if not generated_files:
        st.error("No audio files were generated!")
        return False

    return True


def combine_audio_clips_ffmpeg():
    """Combine all audio clips into final podcast"""
    output_folder = "audio_clips"
    list_file = os.path.join(output_folder, "files.txt")
    final_output = os.path.join(output_folder, "final_podcast.mp3")

    if os.path.exists(final_output):
        os.remove(final_output)

    # Get all MP3 files except the final output
    mp3_files = sorted(
        [f for f in os.listdir(output_folder)
         if f.endswith(".mp3") and f != "final_podcast.mp3"],
        key=lambda x: int(x.split("_")[0])

    if not mp3_files:
        st.error("No audio clips found to combine!")
    return False

    # Create input file for ffmpeg
    with open(list_file, "w") as f:
        for file in mp3_files:
            f.write(f"file '{file}'\n")

    try:
        # Use ffmpeg to concatenate files
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", "files.txt", "-c", "copy", "final_podcast.mp3"
            ],
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

        # Add metadata
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", "final_podcast.mp3",
                "-metadata", "title=AI Generated Podcast",
                "-metadata", "artist=AI Podcast Generator",
                "-c", "copy", "final_podcast_with_metadata.mp3"
            ],
            cwd=output_folder
        )

        # Replace original with metadata version
        os.replace(
            os.path.join(output_folder, "final_podcast_with_metadata.mp3"),
            final_output
        )

        cleanup_temp_files()
        return True

    except Exception as e:
        st.error(f"Error combining audio: {str(e)}")
        return False


# ======================
# Podbean Integration
# ======================

def get_podbean_auth_url():
    """Generate Podbean OAuth authorization URL"""
    params = {
        "client_id": PODBEAN_CLIENT_ID,
        "redirect_uri": PODBEAN_REDIRECT_URI,
        "response_type": "code",
        "scope": "podcast_upload"
    }
    return f"https://api.podbean.com/v1/oauth/authorize?{urllib.parse.urlencode(params)}"


def get_podbean_access_token(auth_code):
    """Exchange authorization code for access token"""
    auth_string = f"{PODBEAN_CLIENT_ID}:{PODBEAN_CLIENT_SECRET}"
    auth_bytes = auth_string.encode("ascii")
    auth_base64 = base64.b64encode(auth_bytes).decode("ascii")

    headers = {
        "Authorization": f"Basic {auth_base64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": PODBEAN_REDIRECT_URI
    }

    try:
        response = requests.post(
            "https://api.podbean.com/v1/oauth/token",
            headers=headers,
            data=data,
            timeout=30
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to get Podbean access token: {str(e)}")
        if response:
            st.error(f"Response: {response.text}")
        return None


def upload_to_podbean(file_path, title, description):
    """Upload podcast episode to Podbean"""
    if "podbean_access_token" not in st.session_state:
        st.error("Not authenticated with Podbean!")
        return False

    try:
        with open(file_path, "rb") as audio_file:
            files = {
                "file": (os.path.basename(file_path), audio_file, "audio/mpeg"),
                "title": (None, title),
                "description": (None, description),
                "content_type": (None, "episode"),
                "status": (None, "publish"),  # Change to "draft" if you want to review first
                "logo": (None, ""),  # Can add cover image here if needed
                "explicit": (None, "no")
            }

            response = requests.post(
                "https://api.podbean.com/v1/episodes",
                headers={"Authorization": f"Bearer {st.session_state.podbean_access_token}"},
                files=files,
                timeout=60  # Longer timeout for large files
            )

            if response.status_code == 200:
                return True
            else:
                st.error(f"Podbean upload failed (Status {response.status_code}): {response.text}")
                return False
    except Exception as e:
        st.error(f"Error uploading to Podbean: {str(e)}")
        return False


# ======================
# Main App
# ======================

def main():
    st.set_page_config(
        page_title="AI Podcast Generator",
        layout="wide",
        menu_items={
            'Get Help': 'https://github.com/your-repo',
            'Report a bug': "https://github.com/your-repo/issues",
            'About': "# AI Podcast Generator with Podbean Upload"
        }
    )

    st.title("🎙️ AI Podcast Generator with Podbean Upload")
    st.markdown("---")

    # Initialize session state
    if "podcast_ready" not in st.session_state:
        st.session_state.podcast_ready = False
    if "podbean_access_token" not in st.session_state:
        st.session_state.podbean_access_token = None
    if "podbean_authenticated" not in st.session_state:
        st.session_state.podbean_authenticated = False

    # Handle OAuth callback
    query_params = st.experimental_get_query_params()
    if "code" in query_params and not st.session_state.podbean_authenticated:
        with st.spinner("Authenticating with Podbean..."):
            access_token = get_podbean_access_token(query_params["code"][0])
            if access_token:
                st.session_state.podbean_access_token = access_token
                st.session_state.podbean_authenticated = True
                st.success("✅ Successfully authenticated with Podbean!")
                # Clear the code from URL
                st.experimental_set_query_params()
                time.sleep(2)
                st.rerun()
            else:
                st.error("Failed to authenticate with Podbean")

    # Authentication section
    if not st.session_state.podbean_authenticated:
        st.warning("Please authenticate with Podbean to enable uploads")
        auth_url = get_podbean_auth_url()
        st.markdown(f"""
        ### Podbean Authentication Required
        1. [Click here to authenticate with Podbean]({auth_url})
        2. You'll be redirected back to this app after login
        """)
        st.stop()

    # Podcast settings sidebar
    with st.sidebar:
        st.header("Podcast Settings")
        topic = st.text_input("Main Topic", placeholder="e.g. Future of AI", key="topic")
        duration = st.slider("Duration (minutes)", 5, 60, 20, key="duration")
        setting = st.text_area("Environment/Setting",
                               placeholder="e.g. Casual coffee shop setting",
                               key="setting")
        num_speakers = st.number_input("Number of Speakers", 1, 5, 2, key="num_speakers")

        st.markdown("---")
        st.header("Advanced Options")
        st.checkbox("Add intro/outro music", value=False, key="add_music")
        st.checkbox("Include ad breaks", value=False, key="include_ads")

        st.markdown("---")
        if st.button("🔒 Logout from Podbean"):
            st.session_state.podbean_authenticated = False
            st.session_state.podbean_access_token = None
            st.success("Logged out successfully")
            time.sleep(1)
            st.rerun()

    # Podcast generation main section
    st.header("Hosts & Guests")
    characters = get_character_info(num_speakers)
    if not characters:
        st.stop()

    if st.button("🚀 Generate Podcast", type="primary", use_container_width=True):
        with st.status("Building Your Podcast...", expanded=True) as status:
            try:
                st.write("🔊 Assigning Voices...")
                voice_mapping, assignments = assign_voices_to_characters(characters)
                st.session_state.voice_mapping = voice_mapping
                st.session_state.assignments = assignments

                st.write("📝 Writing Script...")
                script = generate_podcast_script(
                    topic,
                    duration,
                    setting,
                    characters
                )
                if not script:
                    st.stop()

                st.session_state.script = script
                with st.expander("View Script"):
                    st.code(script)

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

    # Results section
    if st.session_state.get("podcast_ready"):
        st.markdown("---")
        st.header("Results")

        col1, col2 = st.columns(2)

        with col1:
            with st.expander("📜 Podcast Script", expanded=True):
                st.code(st.session_state.script, language="text