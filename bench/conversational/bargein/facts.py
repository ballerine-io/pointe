"""The fact matcher: does a recognized utterance (or the agent's text) state the expected fact?

Facts were chosen to survive speech recognition: small numbers, one common word, a yes or no. Numbers match as digits
or words. The same matcher scores every adapter, on Whisper's transcript of the recorded audio (keyboard: the text).
"""

import re

# fact -> (pattern that must match, pattern that must not match or None, a canonical spoken answer for the tests)
FACTS = {
    "tests_failed": (r"\b(7|seven)\b", None, "Seven tests failed."),
    "tests_total": (r"\b(120|one hundred (and )?twenty|a hundred (and )?twenty)\b", None, "There are one hundred and twenty tests in total."),
    "worst_file": (r"\bvouchers?\b", None, "Most failures are in test voucher dot py."),
    "build_failed": (r"\b(no|nope)\b|\b(did not|didn't|does not|doesn't|has not|hasn't) (pass|go through)\b|"
                     r"\bnot (green|passing)\b|\bisn't green\b|\b(build|bill|built) (has )?(failed|is failing|is broken|is red)\b|"
                     r"\bfailed build\b",
                     r"\b(yes|it passed|build passed|is green|went through)\b", "No, the build failed."),
    "lint_errors": (r"\b(12|twelve)\b", None, "There are twelve lint errors."),
    "coverage": (r"\b(64|sixty four)\b", None, "Coverage is sixty-four percent."),
    "waiting_service": (r"\bgarden\b", None, "The garden service is waiting for your review."),
    "port": (r"\b(8080|80 80|eighty eighty|eight thousand (and )?eighty)\b", None, "It runs on port eighty eighty."),
    "branch": (r"\bcedar\b", None, "You're on the cedar branch."),
    "deploy_day": (r"\btuesday\b", None, "The last deploy was on Tuesday."),
}


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"(?<=\d)[,.](?=\d{3}\b)", "", text)  # 8,080 -> 8080
    text = re.sub(r"(?<=\d)%", " percent", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)  # sixty-four -> sixty four
    return re.sub(r"\s+", " ", text).strip()


def states(fact: str, text: str) -> bool:
    must, must_not, _ = FACTS[fact]
    norm = normalize(text)
    if not re.search(must, norm):
        return False
    return not (must_not and re.search(must_not, norm))
