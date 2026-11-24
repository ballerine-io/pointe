import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from rig import Browser, ClaudeSession, transcribe

async def main():
    session = ClaudeSession(Path("/tmp/cv-repo"), "--model", "sonnet")
    session.start()
    b = Browser()
    try:
        t0 = time.time(); await b.connect(); print("connected")
        await asyncio.sleep(8)
        spans = b.speaker.speech_spans()
        print("spans", [(round(a - t0, 2), round(z - t0, 2)) for a, z in spans])
        if spans:
            print("greeting:", await transcribe(b.speaker.audio(spans[0][0], spans[-1][1])))
    finally:
        await b.close(); session.stop()
asyncio.run(main())
