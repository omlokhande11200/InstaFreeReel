import os
import glob
import instaloader
import moviepy.editor as mp
import re
import shutil
import requests
from stem import Signal
from stem.control import Controller
from flask import Flask, request, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import time

# Load environment variables
load_dotenv()
API_KEY = os.getenv("API_KEY", "default-api-key")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:5000")
VERSAL_URL = os.getenv("VERSAL_URL", "http://127.0.0.1:5000")

# Flask app initialization
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Flask-Limiter for rate limiting
limiter = Limiter(get_remote_address, app=app, default_limits=["1000 per hour"])

# Instaloader initialization
L = instaloader.Instaloader()

# Thread-based execution to prevent high memory usage
executor = ThreadPoolExecutor(max_workers=2)

# Function to renew Tor IP
def renew_tor_ip():
    with Controller.from_port(port=9051) as controller:
        controller.authenticate()
        controller.signal(Signal.NEWNYM)

# Function to get a Tor session
def get_tor_session():
    session = requests.Session()
    session.proxies = {
        'http': 'socks5h://127.0.0.1:9050',
        'https': 'socks5h://127.0.0.1:9050'
    }
    return session

### ---- FUNCTION: Extract Shortcode from URL ---- ###
def extract_shortcode_from_url(url):
    url = url.strip()
    match = re.search(r"instagram\\.com/reel/([^/?#&]+)", url)
    return match.group(1) if match else None

### ---- FUNCTION: Validate Instagram URL ---- ###
def is_valid_instagram_url(url):
    return bool(re.match(r"https?://(www\\.)?instagram\\.com/reel/[^\\s/]+", url))

### ---- FUNCTION: Download Instagram Reel Using Tor ---- ###
def download_reel(url):
    try:
        shortcode = extract_shortcode_from_url(url)
        if not shortcode:
            return {"error": "Invalid Instagram Reel URL format"}

        print(f"Processing Reel: {shortcode}")
        
        renew_tor_ip()
        
        L.context.proxy = "socks5://127.0.0.1:9050"
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

        video_files = glob.glob(os.path.join(shortcode, "*.mp4"))
        if not video_files:
            return {"error": "No MP4 file found."}

        video_file = video_files[0]

        txt_files = glob.glob(os.path.join(shortcode, "*.txt"))
        caption = (
            open(txt_files[0], "r", encoding="utf-8").read().strip().replace("\n", " ")
            if txt_files
            else "No caption available."
        )
        
        hashtags = re.findall(r"#\\w+", caption)

        static_folder = os.path.join("static", shortcode)
        os.makedirs(static_folder, exist_ok=True)
        new_video_path = os.path.join(static_folder, f"{shortcode}.mp4")
        shutil.move(video_file, new_video_path)

        mp3_audio_path = convert_video_to_mp3(new_video_path)
        new_mp3_path = os.path.join(static_folder, "audio.mp3")
        shutil.move(mp3_audio_path, new_mp3_path)

        executor.submit(delayed_delete, static_folder, shortcode)

        return {
            "status": "success",
            "caption": caption,
            "hashtags": hashtags,
            "video_download_url": f"{RENDER_EXTERNAL_URL}/static/{shortcode}/{shortcode}.mp4",
            "mp3_download_url": f"{RENDER_EXTERNAL_URL}/static/{shortcode}/audio.mp3",
        }
    except Exception as e:
        return {"error": str(e)}

### ---- FUNCTION: Convert Video to MP3 ---- ###
def convert_video_to_mp3(video_path):
    try:
        video = mp.VideoFileClip(video_path)
        mp3_audio_path = os.path.join(os.path.dirname(video_path), "audio.mp3")
        video.audio.write_audiofile(mp3_audio_path, codec="mp3")
        video.close()
        return mp3_audio_path
    except Exception as e:
        return {"error": f"MP3 extraction failed: {str(e)}"}

### ---- FUNCTION: Delayed Deletion ---- ###
def delayed_delete(static_folder, shortcode):
    time.sleep(240)
    delete_folder(static_folder)
    delete_folder(shortcode)

def delete_folder(folder_path):
    try:
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            print(f"Deleted folder: {folder_path}")
    except Exception as e:
        print(f"Error deleting folder {folder_path}: {str(e)}")

### ---- FLASK API ROUTES ---- ###
@app.route("/")
def home():
    return jsonify({"message": "Instagram Bot API is Running!"})

@app.route("/download/reel", methods=["GET"])
@limiter.limit("100/minute")
def download_instagram_reel():
    try:
        api_key = request.headers.get("X-API-Key")
        if api_key != API_KEY:
            abort(401, "Unauthorized: Invalid API Key")
        
        url = request.args.get("url")
        if not url or not is_valid_instagram_url(url):
            return jsonify({"error": "Invalid or missing Instagram URL"})

        result = download_reel(url)
        if "error" in result and result["error"]:
            return jsonify({"error": result["error"]})

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Unexpected server error: {str(e)}"})

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
