"""Live check of the relevance gate against synthetic conversations. RUN_LIVE=1 uv run pytest -q tests/test_relevance_live.py"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="calls the Gemini API; set RUN_LIVE=1")


@pytest.fixture(autouse=True)
def fresh_clients():
    """Each case runs its own event loop, and a cached SDK client stays bound to the loop that first used it."""
    import vendors

    vendors._clients.clear()

BAKERY_TALK = [  # confirmations here are answers to the open question, so the gate must let them through
    ("user", "Okay, so Oakridge Bakery is the customer we build the ordering app for. What is the question about Crumbly and beta?"),
    ("assistant", "Should Crumbly be in the beta track for the next two sprints, or is it a separate use case?"),
    ("user", "Yeah, I think it's the same use case."),
    ("assistant", "Got it. And for the first coverage region: the north side plus the coast, Saltway's stores, "
                  "or both?"),
]
FIVE_QUESTIONS = [("assistant", "Claude Code has five questions. First: which customer is this for?"),
                  ("user", "Oakridge Bakery."), ("assistant", "Second: which track?"), ("user", "Beta."),
                  ("assistant", "Third: which region first?"), ("user", "the north side and the coast."),
                  ("assistant", "Fourth: is Crumbly included?"), ("user", "Yes."),
                  ("assistant", "Last: any deadline?"), ("user", "End of next sprint."),
                  ("assistant", "That's all five. Shall I send the answers?")]
CONVERSATION_CASES = [
    ([("assistant", "Option 1 keeps going, option 2 stops and finds out why. Which one?")],
     "option 2, stop. tell it to find out why october retries double paid and to tell Ines today.", [],
     "Stop the rollout, find out why October retries double-paid, and tell Ines today.", True),
    ([("assistant", "The rollback plan is not in anything I have.")], "how would we roll this back?", [],
     "How would we roll back the search index change? Give the steps and how long it takes.", True),
    ([("assistant", "Billing asks about a hotfix and 31 invoices.")], "rotate it and reprocess the invoices", [],
     "Rotate secrets now, declare the security incident, and reprocess the invoices.", False),
    ([("assistant", "Should it merge with the flag on or off?")], "what would you do?", [],
     "Merge with the flag off.", False),
    ([("user", "Do not apply the migration to staging yet."), ("assistant", "Understood, I will not."),
      ("assistant", "The fix is ready on the branch.")], "I want to test it", [],
     "Apply the migration to staging so the user can test.", False),  # (conversation, user said, sent before, proposed, should send)
    (BAKERY_TALK, "Both.", [],
     "Update the documentation to include both the north side plus the coast and Saltway's stores as the "
     "first coverage region.", True),
    (BAKERY_TALK + [("user", "Both."), ("assistant", "Shall I send all of this to Claude Code?")], "So do it.", [],
     "Update the documentation: Oakridge Bakery is the ordering-app customer, Crumbly is in beta, and the first coverage "
     "region includes both the north side/coast and Saltway's stores.", True),
    (BAKERY_TALK[:2], "Yeah, I think it's the same use case.", [],
     "Update the documentation to put Crumbly in the beta track as the same use case.", True),
    (BAKERY_TALK + [("user", "Both.")], "What time is it in New York?",
     ["Update the documentation to include both regions as the first coverage region."],
     "Update the documentation to include both regions as the first coverage region.", False),
    (FIVE_QUESTIONS, "Yes, send it.", [],
     "Answers to your five questions: 1. Customer: Oakridge Bakery. 2. Track: beta. 3. First region: the north side and the "
     "coast. 4. Crumbly: included. 5. Deadline: end of next sprint.", True),
    ([("user", "The pricing page is slow, it's the discount calculation, it loops over every customer."),
      ("assistant", "Want Claude Code to look at it?")],
     "Yeah, uh, have it, you know, fix that but don't touch the API.", [],
     "Goal: speed up the pricing page. Context: the user found the slowness in the discount calculation, which "
     "loops over every customer. Deliver: fix the discount calculation so it no longer iterates over all "
     "customers. Constraint: do not change the API.", True),
    ([("user", "A change I want: when I stop talking you pick up really fast; if I take a second to think you "
               "already start talking. I need some delay."),
      ("assistant", "Got it, I'll wait longer before responding."), ("user", "Yeah, but you didn't send anything to Claude."),
      ("assistant", "I adjusted it internally.")],
     "Just, uh, tell Claude to handle what I've asked.", [],
     "Adjust the voice assistant so it waits longer before responding, giving the user time to think during pauses.", True),
    ([("user", "Can you rename the session? Bluebell dev doesn't mean a lot to me."),
      ("assistant", "What would you like to call it?"), ("user", "You infer it from the context."),
      ("assistant", "I can only rename a session to a name you say."),
      ("user", "No, let's change that feature: I want you to be able to infer it and change the name if I ask."),
      ("assistant", "I can't change my own features, but Claude Code can.")],
     "Okay, so go back to Voice session and tell them, tell him to enable it for you.", [],
     "Enable the capability to infer and apply session names from context as requested by the user.", True),
    (BAKERY_TALK, "Switch to the voice session.", [],
     "Update the documentation to include both regions as the first coverage region.", False),
]

CASES = [  # (user said, sent before, proposed, should send)
    ("Switch to cv-notes.", ["Tell me what files are in this repo."], "tell me what files are in this repo", False),
    ("Ask Claude Code what the launch date in the notes is.", ["Tell me what files are in this repo."],
     "List all the files in this repository.", False),
    ("Ask Claude Code what the launch date in the notes is.", ["Tell me what files are in this repo."],
     "What is the launch date mentioned in the notes?", True),
    ("Tell the cv-repo session to print the README file.", ["What is the launch date?"], "print the README file", True),
    ("Tell the cv-repo session to print the README file.", ["List all the files in this repository."],
     "what is the launch date in the notes?", False),
    ("תבקש מקלוד קוד לתקן את הבאג בפונקציית ההנחה ולהריץ את הבדיקות.", [],
     "Fix the bug in the discount function and run the tests.", True),
    ("Run the tests again.", ["Run the tests in the repository."], "Run the tests in the repository.", True),
    ("Yes, go ahead.", ["Shall I fix the discount bug?"], "Fix the discount bug in pricing.py.", True),
    ("What time zone is Tel Aviv in?", [], "Check the time zone configuration in the repo.", False),
    ("Switch to cv repo multi.", ["Create an empty file called voice-check.txt."],
     "Create an empty file called voice-check.txt.", False),
]


@pytest.mark.parametrize("said,earlier,proposed,expected", CASES)
def test_relevance(said, earlier, proposed, expected, tmp_path):
    (tmp_path / "token").write_text("t")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp_path)
    os.environ.setdefault("GOOGLE_API_KEY", subprocess.run(
        ["security", "find-generic-password", "-s", "gemini-api-key-paid", "-w"],
        capture_output=True, text=True, check=True).stdout.strip())
    import daemon

    assert asyncio.run(daemon._is_current_request(proposed, said, earlier)) is expected


@pytest.mark.parametrize("conversation,said,earlier,proposed,expected", CONVERSATION_CASES)
def test_relevance_in_conversation(conversation, said, earlier, proposed, expected, tmp_path):
    (tmp_path / "token").write_text("t")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp_path)
    os.environ.setdefault("GOOGLE_API_KEY", subprocess.run(
        ["security", "find-generic-password", "-s", "gemini-api-key-paid", "-w"],
        capture_output=True, text=True, check=True).stdout.strip())
    import daemon

    assert asyncio.run(daemon._is_current_request(proposed, said, earlier, conversation)) is expected
