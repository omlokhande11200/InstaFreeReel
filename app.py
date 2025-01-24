import os
import glob
import instaloader
import moviepy.editor as mp
import re
import shutil
from flask import Flask, request, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv
from multiprocessing import Pool
import time

if not os.path.exists("static"):
    os.makedirs("static")

# Load environment variables
load_dotenv()
API_KEY = os.getenv("API_KEY", "default-api-key")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "http://127.0.0.1:5000")
VERSAL_URL = os.getenv("VERSAL_URL", "http://127.0.0.1:5000")

# Flask app initialization
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": VERSAL_URL}})

# Flask-Limiter for rate limiting
limiter = Limiter(get_remote_address, app=app, default_limits=["1000 per hour"])

# Instaloader initialization
L = instaloader.Instaloader()

### ---- FUNCTION: Lazy Pool Initialization ---- ###
def get_pool():
    """Lazily create and return a multiprocessing Pool."""
    return Pool(processes=4)

### ---- FUNCTION: Extract Shortcode from URL ---- ###
def extract_shortcode_from_url(url):
    """Extract shortcode from an Instagram URL."""
    url = url.strip()
    match = re.search(r"instagram\.com/reel/([^/?#&]+)", url)
    return match.group(1) if match else None

### ---- FUNCTION: Validate Instagram URL ---- ###
def is_valid_instagram_url(url):
    """Validate that the provided URL is a valid Instagram reel URL."""
    return bool(re.match(r"https?://(www\.)?instagram\.com/reel/[^\s/]+", url))

### ---- FUNCTION: Download Instagram Reel ---- ###
def download_reel(url):
    """Download an Instagram Reel and serve files via static."""
    try:
        shortcode = extract_shortcode_from_url(url)
        if not shortcode:
            return {"error": "Invalid Instagram Reel URL format"}

        print(f"Processing Reel: {shortcode}")

        # Download Reel into a folder named after the shortcode
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

        # Check for MP4 file
        video_files = glob.glob(os.path.join(shortcode, "*.mp4"))
        if not video_files:
            return {"error": "No MP4 file found."}

        video_file = video_files[0]

        # Extract caption
        txt_files = glob.glob(os.path.join(shortcode, "*.txt"))
        caption = (
            open(txt_files[0], "r", encoding="utf-8").read().strip().replace("\n", " ")
            if txt_files
            else "No caption available."
        )

        # Extract hashtags from the caption
        hashtags = re.findall(r"#\w+", caption)

        # Move files to static folder
        static_folder = os.path.join("static", shortcode)
        os.makedirs(static_folder, exist_ok=True)
        new_video_path = os.path.join(static_folder, f"{shortcode}.mp4")
        shutil.move(video_file, new_video_path)

        # Convert Video to MP3
        mp3_audio_path = convert_video_to_mp3(new_video_path)
        new_mp3_path = os.path.join(static_folder, "audio.mp3")
        shutil.move(mp3_audio_path, new_mp3_path)

        # Schedule folder deletion
        schedule_folder_deletion(static_folder, shortcode)

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
    """Extract MP3 audio from video."""
    try:
        video = mp.VideoFileClip(video_path)
        mp3_audio_path = os.path.join(os.path.dirname(video_path), "audio.mp3")
        video.audio.write_audiofile(mp3_audio_path, codec="mp3")
        video.reader.close()
        video.audio.reader.close_proc()
        return mp3_audio_path
    except Exception as e:
        return {"error": f"MP3 extraction failed: {str(e)}"}

### ---- FUNCTION: Schedule Folder Deletion ---- ###
def schedule_folder_deletion(static_folder, shortcode):
    """Schedule the deletion of both the static folder and the Instaloader shortcode folder."""
    shortcode_folder = os.path.join(shortcode)  # Instaloader folder
    with get_pool() as pool:  # Lazily create a pool and ensure cleanup
        pool.apply_async(delayed_delete, args=(static_folder, shortcode_folder))

def delayed_delete(static_folder, shortcode_folder):
    """Delete the folders after a delay."""
    time.sleep(240)  # Wait for 4 minutes
    delete_folder(static_folder)
    delete_folder(shortcode_folder)

def delete_folder(folder_path):
    """Delete the specified folder and its contents."""
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
@limiter.limit("100/minute")  # Apply rate limiting to this endpoint
def download_instagram_reel():
    """API to download an Instagram Reel."""
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

### ---- MAIN ---- ###
if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
