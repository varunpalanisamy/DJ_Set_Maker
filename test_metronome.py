import json
import librosa
import soundfile as sf

def create_metronome_test(json_path, audio_path, output_path):
    print("Loading JSON data...")
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    beat_times = data['beat_times']
    
    print(f"Loading original audio from {audio_path}...")
    # Load the audio (keeping the original sample rate)
    y, sr = librosa.load(audio_path, sr=None)
    
    print("Generating click track from JSON timestamps...")
    # librosa.clicks generates a track of metronome ticks at the specified times
    # We pass length=len(y) so the click track is the exact same length as the song
    clicks = librosa.clicks(times=beat_times, sr=sr, length=len(y))
    
    print("Mixing original audio with the metronome...")
    # Add the click track to the original audio
    # Multiplying 'y' by 0.8 slightly lowers the original song volume so the clicks pop more
    y_mixed = (y * 0.8) + clicks
    
    print(f"Exporting test file to {output_path}...")
    # Save the result
    sf.write(output_path, y_mixed, sr)
    print("Done! Go give it a listen.")

# --- Run the test ---
# Replace these paths with your actual file locations
JSON_FILE = "metadata/just_wanna_rock.json" 
AUDIO_FILE = "songs/just_wanna_rock.mp3"
OUTPUT_FILE = "fein_metronome_test.wav"

create_metronome_test(JSON_FILE, AUDIO_FILE, OUTPUT_FILE)