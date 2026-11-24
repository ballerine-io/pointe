"""PreToolUse hook in every arm's settings file: a shell command that stays inside the item repo runs without a
permission prompt, the same in every arm, so no prompt stands between the scripted user and the outcome. Anything that
names a path outside the repo, the home folder, the network or privilege gets no decision and so asks as usual."""

import json
import re
import sys

OUTSIDE = re.compile(r"~|\$HOME|\.\.|\bsudo\b|\bcurl\b|\bwget\b|\bssh\b|\bscp\b|\bnc\b|\bgit\s+push\b|\bsecurity\b|"
                     r"\bosascript\b|\bopen\s|\bchmod\b|\bchown\b|\bdd\b|\bmkfs\b|\bnohup\b|&\s*$|\bdisown\b|\bsetsid\b")


def decide(command: str, repo: str) -> bool:
    if OUTSIDE.search(command):
        return False
    for path in re.findall(r"(?<![\w.])/[^\s'\";|&)]*", command):
        if path in ("/dev/null",) or path.startswith((repo.rstrip("/") + "/", "/private" + repo.rstrip("/") + "/")) \
                or path in (repo, "/private" + repo):
            continue
        return False
    return True


def main() -> int:
    event = json.load(sys.stdin)
    repo = sys.argv[1]
    command = str(event.get("tool_input", {}).get("command", ""))
    if event.get("tool_name") == "Bash" and command and decide(command, repo):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "permissionDecisionReason": "bench: stays inside the item repo"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
