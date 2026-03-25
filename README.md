# AI DJ Set Maker

Python project for:

- analyzing songs with `librosa` + `allin1`
- extracting stems with `demucs`
- ordering tracks into a BPM-based setlist
- rendering DJ-style transitions with `pydub` + `rubberband`
- previewing uploads through a small local web app

## Repo Layout

- [get_song_metadata.py](/Users/Varun/DJ_Set_Maker/get_song_metadata.py): analyzes audio files and writes metadata JSON
- [separate_stems.py](/Users/Varun/DJ_Set_Maker/separate_stems.py): runs Demucs stem separation
- [build_setlist.py](/Users/Varun/DJ_Set_Maker/build_setlist.py): simple BPM/key set ordering
- [render_transition.py](/Users/Varun/DJ_Set_Maker/render_transition.py): renders 3 transition styles for a song pair
- [main.py](/Users/Varun/DJ_Set_Maker/main.py): end-to-end CLI pipeline
- [web_app.py](/Users/Varun/DJ_Set_Maker/web_app.py): local upload + processing web app
- [frontend](/Users/Varun/DJ_Set_Maker/frontend): static frontend files

## What Is Ignored

The repo is configured to ignore generated/local-only data such as:

- `songs/`
- `songs_not_needed/`
- `metadata/`
- `stems/`
- `outputs/`
- `demix/`
- `spec/`
- `setlist.json`
- virtualenvs, caches, `.DS_Store`, and generated `.wav` files

That keeps Git focused on source code and setup files instead of large audio artifacts.

## Requirements

### System tools

On macOS, install the audio tools first:

```bash
brew install ffmpeg rubberband
```

### Python

Recommended:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel Cython
python -m pip install -r requirements.txt
```

## Apple Silicon note

`allin1`, `natten`, `madmom`, and `torch` can be finicky on macOS ARM.

If a clean `pip install -r requirements.txt` is not enough, the working sequence used in this repo was:

```bash
python -m pip install cmake ninja
python -m pip install --no-build-isolation natten==0.17.1
python -m pip install --force-reinstall git+https://github.com/CPJKU/madmom.git
```

There is no API key or secret required for this project.

## CLI Pipeline

Drop songs into a local `songs/` folder, then run:

```bash
python main.py
```

That pipeline will:

1. analyze songs and cache metadata in `metadata/`
2. generate stems in `stems/`
3. sort tracks by BPM
4. render adjacent-pair transitions into `outputs/<track_a>_to_<track_b>/`

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
- trigger metadata, stems, and transition rendering
- preview the rendered result in-browser
- switch between rendered pair/style outputs

Rendered mixes are still written to the `outputs/` folder on disk.

## Important Local-Only Note

There are no obvious API keys or secrets in the repo files.

One reproducibility caveat:

- a local `natten` compatibility fix was previously applied inside the `venv` site-packages on this machine
- that patch is not stored in the repo because the whole virtual environment is ignored

If someone else reproduces the environment and hits a `natten` / `torch.cuda._device_t` import issue, they may need to pin compatible versions or apply the same environment-level fix.
