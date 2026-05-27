import os, requests, json, subprocess
import moviepy.editor as mpe
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, CompositeVideoClip, TextClip, ColorClip, concatenate_videoclips
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HINDI_FONT_FILE = "Hindi.ttf"

full_text = os.environ.get('FULL_TEXT', 'Ek baar ki baat hai.')
chat_id = os.environ.get('CHAT_ID')
webhook_url = os.environ.get('WEBHOOK_URL')
pexels_key = os.environ.get('PEXELS_API_KEY')
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
resume_url = os.environ.get('RESUME_URL')

print(f"Total Scenes to render: {len(scenes_data)}")

# 1. FREE AI Voiceover
subprocess.run(['edge-tts', '--voice', 'hi-IN-MadhurNeural', '--text', full_text, '--write-media', 'voiceover.mp3'])
voiceover = AudioFileClip("voiceover.mp3")

total_chars = sum(len(s['text']) for s in scenes_data)
headers = {"Authorization": pexels_key}
current_time = 0.0

try:
    whoosh_sfx = AudioFileClip("whoosh.mp3").volumex(0.25)
    pop_sfx = AudioFileClip("pop.mp3").volumex(0.15)        
except:
    whoosh_sfx = pop_sfx = None

viral_colors = ['#FFD400', '#00FFFF', '#FFFFFF', '#39FF14'] 
TARGET_W, TARGET_H = 1080, 1920

scene_files = [] # Store filenames instead of video objects
audio_clips = [voiceover]

# 2. Process Each Scene & Save to Disk Immediately (Memory Fix)
for i, scene in enumerate(scenes_data):
    keyword = scene.get('keyword', 'nature')
    text_line = scene.get('text', '')
    scene_duration = voiceover.duration * (len(text_line) / max(total_chars, 1))
    if scene_duration < 1.0: scene_duration = 1.0
    
    try:
        res = requests.get(f"https://api.pexels.com/videos/search?query={keyword}&per_page=1&orientation=portrait", headers=headers, timeout=10).json()
        if not res.get('videos'): continue
        
        video_url = res['videos'][0]['video_files'][0]['link']
        vid_path = f"raw_vid_{i}.mp4"
        
        with open(vid_path, "wb") as f:
            f.write(requests.get(video_url, timeout=30).content)
            
        clip = VideoFileClip(vid_path).subclip(0, scene_duration)
        clip = clip.resize(height=TARGET_H)
        if clip.w < TARGET_W:
            clip = clip.resize(width=TARGET_W)
        clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=TARGET_W, height=TARGET_H)
        
        zoomed_clip = clip.resize(lambda t: 1.0 + 0.04 * (t / scene_duration)).set_position(('center', 'center'))
        dark_overlay = ColorClip(size=(TARGET_W, TARGET_H), color=(0,0,0)).set_opacity(0.35).set_position(('center', 'center')).set_duration(scene_duration)
        
        words = text_line.split(' ')
        chunk_size = 2
        chunks = [' '.join(words[j:j + chunk_size]) for j in range(0, len(words), chunk_size)]
        
        word_clips = []
        duration_per_chunk = scene_duration / len(chunks)
        
        for w_i, chunk in enumerate(chunks):
            current_color = viral_colors[w_i % len(viral_colors)]
            
            bg_txt = TextClip(chunk, fontsize=120, color='black', font=HINDI_FONT_FILE, stroke_color='black', stroke_width=18, method='caption', size=(950, None))
            bg_txt = bg_txt.set_position(('center', 'center')).set_duration(duration_per_chunk).set_start(w_i * duration_per_chunk)
            
            main_txt = TextClip(chunk, fontsize=120, color=current_color, font=HINDI_FONT_FILE, stroke_color='black', stroke_width=3, method='caption', size=(950, None))
            main_txt = main_txt.set_position(('center', 'center')).set_duration(duration_per_chunk).set_start(w_i * duration_per_chunk)
            
            word_clips.extend([bg_txt, main_txt])
        
        final_scene = CompositeVideoClip([zoomed_clip, dark_overlay] + word_clips, size=(TARGET_W, TARGET_H)).set_duration(scene_duration)
        
        # WRITE TO DISK AND FREE MEMORY IMMEDIATELY
        scene_filename = f"rendered_scene_{i}.mp4"
        final_scene.write_videofile(scene_filename, fps=24, codec="libx264", preset="ultrafast", logger=None)
        scene_files.append(scene_filename)
        
        # Close objects to free RAM
        clip.close()
        zoomed_clip.close()
        final_scene.close()
        
        if whoosh_sfx: audio_clips.append(whoosh_sfx.set_start(current_time))
        if pop_sfx: audio_clips.append(pop_sfx.set_start(current_time + 0.1))
                
        current_time += scene_duration
        print(f"Scene {i+1} Rendered & Saved: {keyword}")
        
    except Exception as e:
        print(f"Error on scene {i}: {e}")

# 3. Stitch Everything using FFmpeg Concat (Extremely Memory Efficient)
print("Concatenating scenes...")
with open("concat_list.txt", "w") as f:
    for sf in scene_files:
        f.write(f"file '{sf}'\n")

subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "concat_list.txt", "-c", "copy", "stitched_video.mp4"])

# Load stitched video to add final audio, music, and progress bar
final_video = VideoFileClip("stitched_video.mp4")

# Progress Bar
final_duration = final_video.duration
progress_bar = ColorClip(size=(TARGET_W, 15), color=(255, 0, 0))
progress_bar = progress_bar.set_position(lambda t: (-TARGET_W + int(TARGET_W * (t / max(final_duration, 1))), 'bottom')).set_duration(final_duration)
final_video = CompositeVideoClip([final_video, progress_bar])

# Background Music Mix
try:
    bgm = AudioFileClip("bgm.mp3").volumex(0.30)
    if bgm.duration < final_video.duration: bgm = moviepy.audio.fx.all.audio_loop(bgm, duration=final_video.duration)
    else: bgm = bgm.subclip(0, final_video.duration)
    audio_clips.append(bgm)
except: pass

final_audio = CompositeAudioClip(audio_clips)
final_video = final_video.set_audio(final_audio)

print("Rendering Final SHORTS Video...")
final_video.write_videofile("final_video.mp4", fps=24, codec="libx264", audio_codec="aac", threads=2, bitrate="1500k", preset="ultrafast")

# (The rest of your upload logic remains identical)
print("Starting 5-Layer Indestructible Upload System...")
video_link = "Upload Failed"

if not video_link.startswith("http"):
    try:
        res = requests.post("https://0x0.st", files={'file': open('final_video.mp4', 'rb')}, timeout=600)
        if res.text.startswith("http"): video_link = res.text.strip()
    except Exception as e: print(f"0x0.st failed: {e}")

# ... (Keep the rest of your API upload and webhook code exactly as it was) ...
