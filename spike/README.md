# Whisper accuracy spike (THROWAWAY)

Goal: check local Whisper on a real talk clip before building the website.
Delete this folder when done. The result is an answer, not code to keep.

## Run on your Mac (Apple Silicon)

```sh
brew install ffmpeg
cd spike
python3 -m venv .venv && source .venv/bin/activate
pip install mlx-whisper
```

1. Record a 5-10 minute clip of a real talk (Voice Memos or QuickTime is fine).
   Best: mixed Cantonese + English, with the laptop mic at the distance you really sit.
2. Run it:

```sh
python transcribe.py ~/Desktop/clip.m4a                    # auto language, both models
python transcribe.py ~/Desktop/clip.m4a --language yue     # force Cantonese
python transcribe.py ~/Desktop/clip.m4a --models turbo     # fast model only
```

3. Transcripts land in `out/`. The first run downloads the models (about 1.5 GB each for
   large), so run it twice to see the true speed.

## What to check

| Question | Pass looks like |
|---|---|
| Speed | real-time factor under 1.0 (a 60 min talk transcribes in under 60 min; under 0.2 is comfortable) |
| Cantonese words | written the way Cantonese is spoken, not turned into formal Mandarin |
| English terms inside Chinese sentences | kept as English, not dropped or garbled |
| Script | Traditional characters |
| Far-away mic | still readable |
| turbo vs large | note which one you would accept |

Report back: the printed numbers, and 10 lines of each transcript where you can judge accuracy.
