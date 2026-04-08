# AI DJ Set Maker

Python project for:

- analyzing songs with `librosa` + `allin1`
- extracting stems with `demucs`
- ordering tracks into a BPM-aware setlist
- rendering DJ-style transitions with `pydub` + `rubberband`
- previewing uploaded songs in a small local web app

## What The Project Does

Given two songs, the transition engine can:

- detect a structural exit point in Song A
- detect a usable entry point and drop point in Song B
- skip slow or unstable intros in Song B
- detect beat-switch songs and treat them differently from stable-tempo songs
- support standard, double-time, and half-time BPM matching
- render both constant-BPM and gradual-BPM transitions
- preserve short pickups / anacrusis around transition cues
- export three transition styles:
  - `Style_A`
  - `Style_B`
  - `Style_C`

## Repo Layout

- [`get_song_metadata.py`](./get_song_metadata.py): analyzes audio files in `songs/` and writes metadata JSON to `metadata/`
- [`separate_stems.py`](./separate_stems.py): runs Demucs stem separation for either the setlist or explicit track IDs
- [`build_setlist.py`](./build_setlist.py): builds a BPM/key-aware setlist from metadata
- [`render_transition.py`](./render_transition.py): compatibility wrapper for rendering one explicit transition pair
- [`main.py`](./main.py): compatibility wrapper for the transition renderer
- [`web_app.py`](./web_app.py): local upload + preview web app
- [`transitions/`](./transitions): modular transition engine package
- [`transitions/core/audio_math.py`](./transitions/core/audio_math.py): BPM math, beat indexing, checkpoint builders, timestamp helpers
- [`transitions/core/structural_logic.py`](./transitions/core/structural_logic.py): metadata loading, structure detection, intro/chorus/tempo-zone logic
- [`transitions/tools/audio_utils.py`](./transitions/tools/audio_utils.py): `pydub` helpers
- [`transitions/tools/warper.py`](./transitions/tools/warper.py): `ffmpeg` / `rubberband` wrappers and tempo map generation
- [`transitions/styles/style_router.py`](./transitions/styles/style_router.py): Style A / B / C routing and Song A / Song B window handling
- [`transitions/main.py`](./transitions/main.py): pipeline orchestration for pair rendering

## What Is Ignored

The repo is configured to ignore generated/local-only data such as:

- `songs/`
- `songs_not_needed/`
- `metadata/`
- `stems/`
- `outputs/`
- `demix/`
- `spec/`
- `stems_temp/`
- `setlist.json`
- generated `.wav` / `.mp3` files
- virtualenvs, caches, `__pycache__`, `.DS_Store`

That keeps Git focused on source code instead of large audio artifacts.

## Requirements

### System tools

On macOS, install the required audio tools first:

```bash
brew install ffmpeg rubberband
```

You also need Demucs available on your PATH. Installing Python dependencies from `requirements.txt` usually covers that inside the active virtualenv.

### Python setup

Recommended:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel Cython
python -m pip install -r requirements.txt
```

## Apple Silicon Note

`allin1`, `natten`, `madmom`, and `torch` can be finicky on macOS ARM.

If a clean `pip install -r requirements.txt` is not enough, this repo previously worked with:

```bash
python -m pip install cmake ninja
python -m pip install --no-build-isolation natten==0.17.1
python -m pip install --force-reinstall git+https://github.com/CPJKU/madmom.git
```

There is no API key or secret required for this project.

## Minimal Terminal Workflow

If someone new clones the repo and wants to render one transition from the terminal, this is the current workflow.

### 1. Add songs

Put your source audio files into:

```text
songs/
```

Supported formats are defined in [`get_song_metadata.py`](./get_song_metadata.py) and currently include:

- `.mp3`
- `.wav`
- `.flac`
- `.m4a`
- `.ogg`

### 2. Generate metadata

Analyze all songs in `songs/`:

```bash
python get_song_metadata.py
```

This writes per-track JSON files into:

```text
metadata/
```

Each metadata file includes fields such as:

- `track_id`
- `bpm`
- `segments`
- `beat_times`
- `bar_start_times`

### 3. Find the track IDs

The transition renderer uses metadata `track_id` values, not raw filenames.

To see them:

```bash
ls metadata
```

Example:

```bash
ls metadata | grep rihanna
```

### 4. Generate stems

To generate stems for two specific tracks:

```bash
python separate_stems.py "song_a_track_id" "song_b_track_id"
```

Example:

```bash
python separate_stems.py rihanna_where_have_you_been_lyrics don_toliver_no_pole_lyrics
```

This creates:

```text
stems/<track_id>/vocals.mp3
stems/<track_id>/drums.mp3
stems/<track_id>/bass.mp3
stems/<track_id>/other.mp3
```

If you want to process the current setlist instead, run:

```bash
python separate_stems.py
```

### 5. Render one transition pair

Render one pair directly:

```bash
python render_transition.py "song_a_track_id" "song_b_track_id"
```

Example:

```bash
python render_transition.py rihanna_where_have_you_been_lyrics don_toliver_no_pole_lyrics
```

Outputs are written to:

```text
outputs/<song_a_id>_to_<song_b_id>/
```

The renderer produces:

- `Style_A.mp3`
- `Style_B.mp3`
- `Style_C.mp3`
- and a `gradual_bpm/` version of those styles

You can also set the post-transition tail length:

```bash
python render_transition.py "song_a_track_id" "song_b_track_id" --tail-beats 16
```

## Optional Setlist Workflow

If you want to create an ordered setlist from existing metadata:

```bash
python build_setlist.py
```

That writes:

```text
setlist.json
```

You can also force a specific starting track:

```bash
python build_setlist.py --start-track-id rihanna_where_have_you_been_lyrics
```

## Web App

Start the local server:

```bash
source venv/bin/activate
python web_app.py
```

Then open:

```text
http://localhost:8080
```

The web app lets you:

- upload one or more songs
- save those songs into the local `songs/` folder
- generate metadata
- generate stems
- render transitions
- preview exported mixes in-browser

Rendered mixes are still written to `outputs/` on disk.

## Current Transition Logic Highlights

These are the larger transition-engine behaviors currently implemented in the repo.

### Song A exit logic

- chorus blocks are merged from consecutive chorus segments
- stable-tempo songs use a second-to-last chorus rule by default
- if a song has exactly 2 chorus blocks, the second chorus is used directly
- long-chorus override logic can promote an earlier large chorus under the current rules
- beat-switch songs do not use the standard single-BPM chorus logic
- phrase alignment now snaps forward to the next valid phrase boundary first, and only falls back backward if needed

### Song B entry logic

- the engine checks whether the opening BPM is stable relative to the global BPM
- slow or unstable intros can be skipped
- entry locking is based on beat stability, not just the first file sample

### Beat-switch handling

- major tempo zones are detected from stable beat windows
- beat-switch tracks use the final stable tempo zone for exit selection
- gradual ramps anchor to Song A’s measured local exit BPM, not just the global BPM

### BPM matching

- standard, double-time, and half-time interpretations are compared
- Song A can be treated as double-time or half-time when that matches Song B better
- the same interpretation feeds both constant and gradual transition math

### Pickup handling

- Song B supports preroll pickup extraction before the structural downbeat
- pickup-aware tempo maps keep the true downbeat aligned after warping
- Song A supports a cue pickup when jumping backward into an earlier chorus loop
- Song A cue pickup currently uses a soft exponential fade-in so it stays subtle unless needed

## Helpful Commands

Analyze songs:

```bash
python get_song_metadata.py
```

Generate stems for explicit tracks:

```bash
python separate_stems.py "track_id_1" "track_id_2"
```

Build setlist:

```bash
python build_setlist.py
```

Render one pair:

```bash
python render_transition.py "song_a_track_id" "song_b_track_id"
```

Run the web app:

```bash
python web_app.py
```

## Notes

- Track IDs containing shell characters like `&` should be quoted on the command line:

```bash
python render_transition.py "young_thug_&_meek_mill_that_go_lyrics_feat_t_shyne" yeat_hardy_boys_2_prod_sky_x_keenex
```

- The renderer expects metadata and stems to exist for the tracks you reference.
- If rendering fails because stems are missing, run `separate_stems.py` for those track IDs first.

## Important Local-Only Note

There are no obvious API keys or secrets in the repo files.

One reproducibility caveat:

- a local `natten` compatibility fix was previously applied inside the `venv` site-packages on one machine
- that patch is not stored in the repo because the whole virtual environment is ignored

If someone else reproduces the environment and hits a `natten` / `torch.cuda._device_t` import issue, they may need to pin compatible versions or apply the same environment-level fix.
