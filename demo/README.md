# Demo video

A real call, recorded from the real software. `storyboard.md` lists the beats and the exact lines.

```
# needs: Chrome, ffmpeg, Keychain items anthropic/soniox/elevenlabs/gemini-api-key; for the phone beat a booted iPhone simulator
uv run --with pyte python -u -I demo/capture.py              # or --no-phone; writes demo/out/take-N/
uv run python -I demo/compose.py demo/out/take-N              # demo/out/take-N/pointe-demo.mp4 and .srt
```

The capture uses its own daemon state and ports (`/tmp/cv-state-demo`, 7873, TLS 7473), so a voice you are using is not
touched. One take takes about 10 to 12 minutes and costs well under a dollar in vendor calls (the user's lines through
ElevenLabs, the call's own ears, brain and mouth, two Claude Code sessions on Haiku).

What is real and what is not:

- Real: the daemon, the page, the iPhone app, Claude Code, every model reply, every approval, the audio the page received.
- Synthesized: the user's voice. The video says so on every frame.
- Cut: quiet stretches longer than 2 s are shortened to 2 s, and each cut shows the seconds skipped.
- Not recorded: the bot's audio during the phone beat (the simulator records video only). Those lines are captioned from
  the daemon log and labeled "on the phone".
- Hidden: the recording machine's home path and status line.

For the site: copy `pointe-demo.mp4` to `site/demo.mp4`, convert the `.srt` to `.vtt`
(`ffmpeg -i pointe-demo.srt site/demo.vtt`), and save a poster frame
(`ffmpeg -ss 20 -i pointe-demo.mp4 -frames:v 1 site/poster.jpg`). The page shows the poster with no play control
until `demo.mp4` loads.
