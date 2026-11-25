# The recorded-human set

The suite's speech is synthetic (Kokoro, and OpenAI for Hebrew). This set replaces it with recorded people for the
turns a word or a sound can carry: the yes and the no to a permission request that was just read out, a stop, and
the sounds a listener makes.

## What it is

- **Source.** Speech Commands v0.02, test set. Pete Warden, Google, 2018. "Speech Commands: A Dataset for
  Limited-Vocabulary Speech Recognition", https://arxiv.org/abs/1804.03209.
- **Licence.** Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/.
  The archive carries its own `LICENSE` and `README.md`; both stay beside the clips in `.human/`.
- **Where it comes from.** `http://download.tensorflow.org/data/speech_commands_test_set_v0.02.tar.gz`, 112,563,277
  bytes, SHA-256 `cc2a00c1147c2254e9be3fa0f779d8c17421dc349b86366567a8edfa9acd51df`. `run.py human` downloads it,
  refuses any other hash, and unpacks it into `.human/` (ignored by git: the clips are not redistributed here).
- **What is in it.** One-second recordings of single words by volunteers, each on their own microphone in their own
  room, 16 kHz. The file name starts with a hash of the speaker. 115 speakers recorded both "yes" and "no".
- **What is changed.** Each clip is scaled to half of full scale (the volunteers' levels differ by about 30 dB) and
  resampled to 24 kHz. Nothing is cut, denoised or re-recorded.

## What it tests

`human.toml` (written by `run.py human`): 20 speakers of each set, in a fixed order.

| Dialogue | The recorded sound | From | Passes when |
|---|---|---|---|
| `hum-yes-NNN` | "yes", after the request's read-out ended | Speech Commands | the requested command runs |
| `hum-no-NNN` | "no", after the read-out ended | Speech Commands | the requested command does not run |
| `hum-stop-NNN` | "stop", over a long answer | Speech Commands | the voice stops (the time is the measure) |
| `hum-listen-NNN` | "yeah", "okay" or "mm-hmm", over a long answer | AMI Meeting Corpus | the voice goes on, or resumes, and nothing is sent |

The backchannels are one a speaker from the AMI Meeting Corpus (Carletta et al., 2005, CC BY 4.0,
https://groups.inf.ed.ac.uk/ami/corpus/): what a meeting participant said, into their own headset, while a colleague
talked. `bench/human_turns.py` fetches the corpus (SHA-256 pinned), cuts the clips and names each in
`bench/human_turns.jsonl`; the same file holds the 291 mid-sentence pauses and 283 ends of turn the turn benchmark uses.

```
uv run --locked --extra local python bench/conversational/dialogues/run.py human
uv run --locked --extra local python bench/conversational/dialogues/run.py run --suite bench/conversational/dialogues/human.toml --arm pointe --label human
```

## What it does not prove

- The sentence that leads to the request ("Tell billing to run its unit tests…") is still a synthetic voice. The set
  holds no sentences, so time to first word, end of turn and routing are not measured on people here.
- English only. There is no recorded-human Hebrew yet.
- A one-second clip of one word is harder for a recognizer than a word inside a sentence, and easier than a word over
  a car's noise. Neither is what a call sounds like.
- 20 speakers, one clip each, one run: the interval on a pass rate from 20 trials is wide (20 of 20 still allows a
  true rate as low as 83%, at 95%).
- Nobody outside the team has run it.

The gap map's full recorded-human set (20 or more speakers reading every dialogue, Hebrew speakers, backchannels and
interruptions, three microphones, with consent to publish) still has to be recorded. No openly licensed corpus holds
those lines.
