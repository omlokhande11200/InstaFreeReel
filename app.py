import os 
import glob
import instaloader
import moviepy.editor as mp
import re
import shutil
import requests
import logging
from stem import Signal
from stem.control import Controller
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import time

# Load environment variables
load_dotenv()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:5000")

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

# Function to log and return Tor IP
def get_tor_ip():
    try:
        session = get_tor_session()
        response = session.get("https://check.torproject.org/api/ip")
        tor_ip = response.json()
        logging.info(f"Current Tor IP: {tor_ip}")
        return tor_ip
    except Exception as e:
        logging.error(f"Failed to fetch Tor IP: {e}")
        return {"error": str(e)}

@app.route("/check-tor", methods=["GET"])
def check_tor():
    return jsonify({"Tor_IP": get_tor_ip()})

### ---- FUNCTION: Extract Shortcode from URL ---- ###
def extract_shortcode_from_url(url):
    url = url.strip()
    match = re.search(r"instagram\\.com/reel/([^/?#&]+)", url)
    return match.group(1) if match else None

### ---- FUNCTION: Validate Instagram URL ---- ###
def is_valid_instagram_url(url):
    return bool(re.match(r"https?://(www\\.)?instagram\\.com/reel/[^\\s/]+", url))

### ---- FUNCTION: Download Instagram Reel Using Tor ---- ###
@app.route("/download/reel", methods=["GET"])
@limiter.limit("100/minute")
def download_instagram_reel():
    try:
        url = request.args.get("url")
        if not url or not is_valid_instagram_url(url):
            return jsonify({"error": "Invalid or missing Instagram URL"})

        shortcode = extract_shortcode_from_url(url)
        if not shortcode:
            return jsonify({"error": "Invalid Instagram Reel URL format"})

        print(f"Processing Reel: {shortcode}")
        
        renew_tor_ip()
        
        L.context.proxy = "socks5://127.0.0.1:9050"
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

        video_files = glob.glob(os.path.join(shortcode, "*.mp4"))
        if not video_files:
            return jsonify({"error": "No MP4 file found."})

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

        return jsonify({
            "status": "success",
            "caption": caption,
            "hashtags": hashtags,
            "video_download_url": f"{RENDER_EXTERNAL_URL}/static/{shortcode}/{shortcode}.mp4",
            "mp3_download_url": f"{RENDER_EXTERNAL_URL}/static/{shortcode}/audio.mp3",
        })
    except Exception as e:
        return jsonify({"error": str(e)})

### ---- FLASK API ROUTES ---- ###
@app.route("/")
def home():
    return jsonify({"message": "Instagram Bot API is Running!"})

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
