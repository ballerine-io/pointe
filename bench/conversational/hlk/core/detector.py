"""The question detector's tested spec: 48 labelled harness lines (questions and statements), each rendered through
Kokoro in one of the panel voices and read back by the scoring Whisper, then classified by core.user.is_question.
Under 95% correct the build stops and the rule list is fixed before any paid run. The measured accuracy is published."""

import json
from pathlib import Path

LABELLED = [
    ("Which file did you mean, cache dot py or cash dot py?", True),
    ("Should I run the tests now?", True),
    ("Do you want me to update the imports too?", True),
    ("Would you like me to fix the other two as well?", True),
    ("I couldn't find gauge v two dot py. Did you mean gauge dot py?", True),
    ("Which session should get this, tariff or depot?", True),
    ("Can you confirm the new name?", True),
    ("Is that the snake case one or the camel case one?", True),
    ("What should the timeout be in milliseconds?", True),
    ("How many decimal places do you want for the mean?", True),
    ("Shall I go ahead and rename it everywhere?", True),
    ("Do you mean compute charge or compute levy?", True),
    ("Where should the new package go?", True),
    ("Should this change only the api package?", True),
    ("The test file contradicts itself. Do you want me to change it?", True),
    ("Want me to run cleanup dot s h now?", True),
    ("Okay. Which one of the three tests should I fix?", True),
    ("Tariff wants to run python three dash m unittest. Should it?", True),
    ("I found two functions with that name. Which one did you mean?", True),
    ("Are you sure you want to delete the data folder?", True),
    ("Did you want the version as three point twelve point zero?", True),
    ("There is no function called nimbus total. What would you like me to do?", True),
    ("Could you spell the name again?", True),
    ("Before I start, do you want me to keep the old name as well?", True),
    ("Done. All the tests pass.", False),
    ("I renamed the function in the api package.", False),
    ("The limit in cash dot py is now twenty five.", False),
    ("Three tests are failing: units, timing and words.", False),
    ("I moved the module and fixed every import.", False),
    ("I stopped the rename and added a wrapper in utils dot py.", False),
    ("There is no function called nimbus total, so I changed nothing.", False),
    ("The tests in test ratio dot py contradict each other, so this cannot be done as stated.", False),
    ("Tariff finished its turn.", False),
    ("I sent that to depot.", False),
    ("Okay, I'll fix only the one about counting words.", False),
    ("The cleanup script was not run.", False),
    ("Got it, working on it now.", False),
    ("No, it is not done yet.", False),
    ("Yes, it is done and the tests pass.", False),
    ("I updated config dot py with the three values.", False),
    ("The new constant is set to seven.", False),
    ("Let me know if you need anything else.", False),
    ("All set. The field is now customer id in both repositories.", False),
    ("I added the function stack summary with all six requirements.", False),
    ("The camel case version in compat dot py is unchanged.", False),
    ("Running the tests now.", False),
    ("Sure, I'll leave the batch package alone.", False),
    ("Everything is in place and nothing else was changed.", False),
]
OUT = Path(__file__).resolve().parents[1] / "results" / "hlk-detector.json"


def measure() -> dict:
    from core import corpus
    from core.asr import Whisper
    from core.user import is_question
    rows = []
    panel = corpus.panel()
    for i, (text, label) in enumerate(LABELLED):
        voice = panel[i % len(panel)]
        heard = Whisper.transcribe(corpus.load(corpus.render(voice, text, None)), corpus.RATE)
        rows.append({"text": text, "question": label, "voice": voice, "heard": heard, "predicted": is_question(heard)})
    correct = sum(r["question"] == r["predicted"] for r in rows)
    out = {"lines": len(rows), "correct": correct, "accuracy": round(correct / len(rows), 4), "rows": rows,
           "recognizer": "mlx-community/whisper-large-v3-turbo (assets.py pin)", "tts": "Kokoro-82M v1.0"}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    return out
