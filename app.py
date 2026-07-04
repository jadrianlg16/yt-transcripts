import json
import os
import re
import html
import threading
import requests
import scrapetube
import time
import random
import subprocess
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from tkinter import Tk, Label, Entry, Button, Text, END, messagebox, Listbox, Scrollbar, RIGHT, Y, LEFT, BOTH, Frame, ttk, PanedWindow, VERTICAL, HORIZONTAL

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    raise SystemExit("Missing dependency: youtube-transcript-api")

DATA_FILE = "transcripts_store.json"
CHANNELS_DIR = "channels"

# --- Business Logic ---

class TranscriptStore:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.file_path): return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f: return json.load(f)
        except: return []

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_entry(self, entry):
        # Prevent duplicates in the UI list if video_id matches
        self.data = [e for e in self.data if e.get('video_id') != entry['video_id']]
        self.data.append(entry)
        self.save()

    def all_entries(self):
        return self.data

def extract_video_id(url: str):
    value = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    if "://" not in value and (
        value.startswith("youtube.com")
        or value.startswith("www.youtube.com")
        or value.startswith("m.youtube.com")
        or value.startswith("youtu.be")
    ):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    def valid_video_id(video_id):
        return video_id if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or "") else None

    if host == "youtu.be":
        return valid_video_id(parsed.path.strip("/").split("/")[0])

    if host == "youtube.com" or host.endswith(".youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id:
            return valid_video_id(video_id)

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
            return valid_video_id(path_parts[1])

    return None

def segment_to_dict(item):
    if isinstance(item, dict):
        return {
            "text": item.get("text", ""),
            "start": item.get("start", 0),
            "duration": item.get("duration", 0),
        }

    return {
        "text": getattr(item, "text", ""),
        "start": getattr(item, "start", 0),
        "duration": getattr(item, "duration", 0),
    }

def fetch_transcript(video_id: str):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    try: transcript = transcript_list.find_transcript(['en'])
    except: transcript = next(iter(transcript_list))
    items = transcript.fetch()
    segments = [segment_to_dict(i) for i in items]
    return segments, " ".join(s["text"] for s in segments)

def fetch_metadata(video_id: str):
    url = f"https://www.youtube.com/watch?v={video_id}"
    title, channel = "Unknown Title", "Unknown Channel"
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=h, timeout=10)
        t_m = re.search(r'<title>(.*?)</title>', r.text)
        if t_m: title = html.unescape(t_m.group(1).replace(" - YouTube", ""))
        c_m = re.search(r'\"ownerChannelName\":\"(.*?)\"', r.text)
        if c_m: channel = html.unescape(c_m.group(1))
    except: pass
    return title, channel

# --- UI Application ---

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcript Pro")
        self.root.geometry("1200x800")
        self.root.configure(bg="#f5f6f7")
        
        self.store = TranscriptStore()
        self.current_entries = []
        self.filtered_entries = []

        self.setup_styles()
        self.build_ui()
        self.refresh_list()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Colors
        self.bg_color = "#f5f6f7"
        self.accent_color = "#1a73e8"
        self.sidebar_color = "#ffffff"
        
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("Card.TFrame", background="#ffffff", relief="flat")
        self.style.configure("TLabel", background=self.bg_color, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        self.style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=5)
        self.style.configure("TProgressbar", thickness=10)

    def build_ui(self):
        # --- Top Toolbar (Inputs) ---
        top_bar = ttk.Frame(self.root, padding=20)
        top_bar.pack(fill="x")

        # Video Input
        ttk.Label(top_bar, text="Single Video URL:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(top_bar, width=60)
        self.url_entry.grid(row=0, column=1, padx=10, pady=5)
        self.fetch_btn = ttk.Button(top_bar, text="Fetch Video", style="Action.TButton", command=self.start_video_fetch)
        self.fetch_btn.grid(row=0, column=2, padx=5)

        # Channel Input
        ttk.Label(top_bar, text="Channel URL:", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w")
        self.channel_entry = ttk.Entry(top_bar, width=60)
        self.channel_entry.grid(row=1, column=1, padx=10, pady=5)
        self.bulk_btn = ttk.Button(top_bar, text="Bulk Fetch Channel", style="Action.TButton", command=self.start_channel_fetch)
        self.bulk_btn.grid(row=1, column=2, padx=5)

        # Progress Section
        self.status_label = ttk.Label(top_bar, text="System Ready", foreground=self.accent_color)
        self.status_label.grid(row=0, column=3, padx=20, sticky="e")
        self.progress = ttk.Progressbar(top_bar, length=200, mode="determinate")
        self.progress.grid(row=1, column=3, padx=20, sticky="e")

        # --- Main Resizable Area ---
        self.paned = PanedWindow(self.root, orient=HORIZONTAL, bg="#d1d4d9", sashwidth=4)
        self.paned.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        # 1. Left Sidebar (Video List)
        sidebar = Frame(self.paned, bg=self.sidebar_color, width=350)
        self.paned.add(sidebar)

        search_frame = Frame(sidebar, bg=self.sidebar_color, padx=10, pady=10)
        search_frame.pack(fill="x")
        Label(search_frame, text="SEARCH SAVED VIDEOS", font=("Segoe UI", 8, "bold"), bg=self.sidebar_color, fg="#5f6368").pack(anchor="w")
        self.search_var = ttk.Entry(search_frame)
        self.search_var.pack(fill="x", pady=5)
        self.search_var.bind("<KeyRelease>", self.filter_list)

        list_container = Frame(sidebar, bg=self.sidebar_color)
        list_container.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.listbox = Listbox(list_container, font=("Segoe UI", 10), bd=0, highlightthickness=0, bg="#ffffff", selectbackground=self.accent_color)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        sb = ttk.Scrollbar(list_container, orient=VERTICAL, command=self.listbox.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.listbox.config(yscrollcommand=sb.set)

        # 2. Right Content (Transcript & Details)
        content_area = Frame(self.paned, bg=self.bg_color)
        self.paned.add(content_area)

        # Metadata Card
        meta_card = Frame(content_area, bg="#ffffff", padx=20, pady=15, highlightbackground="#e0e0e0", highlightthickness=1)
        meta_card.pack(fill="x", padx=20, pady=20)
        
        self.title_lbl = Label(meta_card, text="Select a video to view transcript", font=("Segoe UI", 14, "bold"), bg="#ffffff", wraplength=700, justify="left")
        self.title_lbl.pack(anchor="w")
        
        self.info_lbl = Label(meta_card, text="", font=("Segoe UI", 10), bg="#ffffff", fg="#5f6368", justify="left")
        self.info_lbl.pack(anchor="w", pady=(5, 0))

        # Transcript Area
        transcript_frame = Frame(content_area, bg=self.bg_color, padx=20)
        transcript_frame.pack(fill=BOTH, expand=True)
        
        Label(transcript_frame, text="FULL TRANSCRIPT", font=("Segoe UI", 8, "bold"), bg=self.bg_color, fg="#5f6368").pack(anchor="w")
        self.transcript_text = Text(transcript_frame, font=("Segoe UI", 11), wrap="word", bd=1, padx=15, pady=15, relief="flat", highlightthickness=1, highlightbackground="#e0e0e0")
        self.transcript_text.pack(fill=BOTH, expand=True, pady=5)

        # Bottom Actions
        actions = Frame(content_area, bg=self.bg_color, padx=20, pady=10)
        actions.pack(fill="x")
        
        ttk.Button(actions, text="Copy Text", command=self.copy_transcript).pack(side=LEFT, padx=5)
        ttk.Button(actions, text="Open Channels Folder", command=self.open_folder).pack(side=LEFT, padx=5)
        ttk.Button(actions, text="Refresh DB", command=self.refresh_list).pack(side=LEFT, padx=5)

    # --- UI Logic ---

    def set_status(self, text, color="#1a73e8"):
        self.status_label.config(text=text, foreground=color)
        self.root.update_idletasks()

    def filter_list(self, event=None):
        query = self.search_var.get().lower()
        self.listbox.delete(0, END)
        self.filtered_entries = [e for e in self.current_entries if query in e.get('title', '').lower() or query in e.get('video_id', '').lower()]
        for e in self.filtered_entries:
            self.listbox.insert(END, f" {e.get('title', 'Unknown')[:50]}...")

    def refresh_list(self):
        self.current_entries = list(reversed(self.store.all_entries()))
        self.filter_list()

    def on_select(self, event=None):
        idx = self.listbox.curselection()
        if not idx: return
        item = self.filtered_entries[idx[0]]
        
        self.title_lbl.config(text=item.get('title', 'Untitled Video'))
        self.info_lbl.config(text=f"Channel: {item.get('channel')}  |  ID: {item.get('video_id')}  |  Saved: {item.get('saved_at')}")
        
        self.transcript_text.delete("1.0", END)
        self.transcript_text.insert(END, item.get("transcript", ""))

    def open_folder(self):
        if not os.path.exists(CHANNELS_DIR): os.makedirs(CHANNELS_DIR)
        subprocess.Popen(f'explorer "{os.path.abspath(CHANNELS_DIR)}"')

    # --- Fetch Logic (Reusing your robust logic) ---

    def start_video_fetch(self):
        url = self.url_entry.get().strip()
        if not url: return
        self.fetch_btn.config(state="disabled")
        self.set_status("Fetching Video...", "blue")
        threading.Thread(target=self.run_video_fetch, args=(url,), daemon=True).start()

    def run_video_fetch(self, url):
        try:
            v_id = extract_video_id(url)
            if not v_id: raise ValueError("Invalid URL")
            items, text = fetch_transcript(v_id)
            title, channel = fetch_metadata(v_id)
            entry = {"video_id": v_id, "title": title, "channel": channel, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "transcript": text, "segments": items}
            self.store.add_entry(entry)
            self.root.after(0, self.finish_fetch, True, "Saved!")
        except Exception as e:
            self.root.after(0, self.finish_fetch, False, str(e))

    def start_channel_fetch(self):
        url = self.channel_entry.get().strip()
        if not url: return
        self.bulk_btn.config(state="disabled")
        threading.Thread(target=self.run_channel_fetch, args=(url,), daemon=True).start()

    def run_channel_fetch(self, url):
        try:
            self.root.after(0, lambda: self.set_status("Finding Videos...", "orange"))
            videos = list(scrapetube.get_channel(channel_url=url))
            if not videos: # Try handle
                if "@" in url:
                    handle = url.split("@")[-1].split("/")[0]
                    videos = list(scrapetube.get_channel(channel_username=handle))
            
            total = len(videos)
            if total == 0: raise ValueError("No videos found")
            
            folder = os.path.join(CHANNELS_DIR, "Bulk_Export_" + str(int(time.time())))
            os.makedirs(folder, exist_ok=True)

            for i, v in enumerate(videos, 1):
                v_id = v['videoId']
                self.root.after(0, lambda cur=i, tot=total: self.update_progress(cur, tot))
                
                # Deduplication
                if any(f.startswith(v_id) for f in os.listdir(folder)): continue
                
                try:
                    time.sleep(random.uniform(2, 4)) # sporadic timeout
                    items, text = fetch_transcript(v_id)
                    title, channel = fetch_metadata(v_id)
                    entry = {"video_id": v_id, "title": title, "channel": channel, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "transcript": text, "segments": items}
                    
                    with open(os.path.join(folder, f"{v_id}.json"), "w", encoding="utf-8") as f:
                        json.dump(entry, f, indent=2, ensure_ascii=False)
                    self.store.add_entry(entry)
                except: continue

            self.root.after(0, self.finish_fetch, True, f"Bulk Finished ({total} videos)")
        except Exception as e:
            self.root.after(0, self.finish_fetch, False, str(e))

    def update_progress(self, cur, tot):
        self.progress["value"] = (cur / tot) * 100
        self.set_status(f"Processing {cur}/{tot}...", "orange")

    def finish_fetch(self, success, msg):
        self.fetch_btn.config(state="normal")
        self.bulk_btn.config(state="normal")
        if success:
            self.set_status(msg, "green")
            self.refresh_list()
        else:
            self.set_status("Error", "red")
            messagebox.showerror("Task Failed", msg)

    def copy_transcript(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.transcript_text.get("1.0", END))
        messagebox.showinfo("Copied", "Transcript copied to clipboard!")

if __name__ == "__main__":
    root = Tk()
    App(root)
    root.mainloop()
