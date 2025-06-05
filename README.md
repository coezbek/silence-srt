
# Silence-Srt

The goal of this project is to provide a simple and efficient way to perform the following minor adjustments to SRT files based on existing audio files:

- Remove leading silence from timestamps based on voice energy. Helpful for Cross-Entropy-based timestamps which often include too much leading silence.

- Expand start of timestamp to earlier time if silence is detected before audio. Helpful for Whisper-based timestamps which cut off stretched pronunciations of words (e.g. 'aaaaaaand action' might just start in the middle of the long 'aaaaaa' sound).

- Similarly expand and trim trailing silence.

Invariants / assumptions:

- Silence-Srt will not change timestamps of one segment to accomodate another.
- Silence-Srt assumes that the audio is just speech (use e.g. PAFTS to remove background music/noise/non-speech).

## Installation

```bash
uv sync
```

## Usage

```bash
uv run main.py --help
usage: main.py [-h] -i INPUT [-f FILE_TO_FIX] [-o OUTPUT] [-t THRESHOLD] [-m MIN_DUR] [-M MAX_DUR] [-s MIN_SILENCE_DUR] [-n] [--subtract_only]

Silence SRT

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        Input .wav file (just speech)
  -f FILE_TO_FIX, --file_to_fix FILE_TO_FIX, --file FILE_TO_FIX
                        Input .srt file to fix. If not given outputs just the silence segments
  -o OUTPUT, --output OUTPUT
                        Output srt file
  -t THRESHOLD, --threshold THRESHOLD
                        Detection threshold - energy-based. If energy exceeds this value, the event is considered valid.
  -m MIN_DUR, --min_dur MIN_DUR
                        Minimum duration of a valid audio event in seconds
  -M MAX_DUR, --max_dur MAX_DUR
                        Maximum duration of an event
  -s MIN_SILENCE_DUR, --min_silence_dur MIN_SILENCE_DUR
                        Minimum duration of silence in seconds
  -n, --negate          Report events, rather than silence
  --subtract_only, --subtract-only
                        Only shorten the attached SRT file segments by the silence detected. Do not extend.
```
