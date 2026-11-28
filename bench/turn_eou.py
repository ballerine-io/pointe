"""A text model's end-of-turn probability as one more signal for the wait, replayed on what Soniox heard (turn_rules.py).

LiveKit's turn detector (Hugging Face livekit/turn-detector) reads the transcript, not the sound: a Qwen2.5-0.5B
fine-tune that gives the probability of <|im_end|> after the user's words, in the chat template, with the closing tag
left off. Two variants, both an int8 ONNX file: `multilingual` (tag v0.4.1-intl, the one LiveKit recommends, 14
languages, no Hebrew) and `en` (tag v1.2.2-en, deprecated). Each is pinned below by commit and by the SHA-256 of every
file. Its license (the LiveKit Model License) allows use only together with the LiveKit Agents framework: this bench
runs it through that framework's own inference runner (livekit-plugins-turn-detector), so the input is formatted
exactly as LiveKit does it, and nothing of the model may go into Pointe without the owner's decision.

    .venv/bin/python -I bench/turn_eou.py fetch          # the two models into bench/.eou/ (ignored by git), 0.5 GB
    <ENV below> bench/turn_eou.py score [--threads 1]   # every text the replay can judge -> SCORES, and the latency
    .venv/bin/python -I bench/turn_eou.py sweep          # rules on the score, chosen on the `train` speakers
    .venv/bin/python -I bench/turn_eou.py report         # the chosen rules on `test` (held-out speakers) and `all`

`score` runs in a throwaway environment (ENV), never the repository's lock. SCORES holds each judged text, which is
the Soniox words already in turn-human.jsonl joined as the replay joins them, and the two probabilities; it is
committed, so `sweep` and `report` need neither the model nor the environment.

The model sees one user message and no history: the rows are meeting speech, with no assistant turn before them. In a
call the daemon would have the bot's last reply to give it, which the model was trained to use.
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "pointe"), str(HERE.parent)]
import no_telemetry  # noqa: E402,F401  (before the model's runtime loads)

ENV = ("uv run --no-project --python 3.12 --exclude-newer 2026-11-28T00:00:00Z --with livekit-agents==1.9.0 "
       "--with livekit-plugins-turn-detector==1.9.0 --with onnxruntime==1.32.0 --with transformers==5.24.1 "
       "--with tokenizers==0.23.3 --with huggingface-hub==2.5.0 python -I")
CACHE = HERE / ".eou"
RUN = HERE / "results" / "2026-11-25-v0.8.5"
ROWS = RUN / "turn-human.jsonl"
SCORES = HERE / "results" / "turn-human.eou.jsonl"  # beside the release, not in it: the release's rows are published as they were
REPO = "livekit/turn-detector"
MODELS = {  # variant -> (commit, {file: SHA-256})
    "multilingual": ("87e35fcb1e60a569bea70346191c4886ea92e281", {  # tag v0.4.1-intl
        "onnx/model_q8.onnx": "bd2c30776882138a1d95a07faddc13756fe1a35bef6323505f1124fca349bc9c",
        "tokenizer.json": "9c5ae00e602b8860cbd784ba82a8aa14e8feecec692e7076590d014d7b7fdafa",
        "tokenizer_config.json": "83df6c86106c7f332995b3c456bc6a424cc46ee348bf4e0ae1b5410c63f4393f",
        "special_tokens_map.json": "76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd",
        "added_tokens.json": "58b54bbe36fc752f79a24a271ef66a0a0830054b4dfad94bde757d851968060b",
        "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
        "merges.txt": "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
        "config.json": "ce173959a04af7e0a3219cf97ee70cc4635f97272ee885e8fc855bde6012c787",
        "languages.json": "05a16e11e4282173331dbf140624048e581a727ba45c361bed35e3014ad68187",
        "LICENSE": "4f5b74db4fd26299a166688de8a3bde046fd7d9cc13ecab64532c24310bc18d7",
    }),
    "en": ("ebcab0c09c2b62d926e92180d364df3aaae68a09", {  # tag v1.2.2-en
        "onnx/model_q8.onnx": "fdd695a99bda01155fb0b5ce71d34cb9fd3902c62496db7a6c2c7bdeac310ac7",
        "tokenizer.json": "6f0dc4b1306b1b17da46b55b696c8f54ba7cb05a1b91dc526fd143f31e882fcb",
        "tokenizer_config.json": "d396075fb874a5344ce13dbfcdc0e7fb64605c676b47ff8d982e2be468a75e20",
        "special_tokens_map.json": "0c2d25cda8444610bbdef00b04df893332b56d9773744e3399dbd7b8f7ada877",
        "added_tokens.json": "831c3eb42bcb8dd3eb44adaa4321fb70c771c8567df644a027f19706989a3015",
        "vocab.json": "82b84012e3add4d01d12ba14442026e49b8cbbaead1f79ecf3d919784f82dc79",
        "merges.txt": "0b54e8aa4e53d5383e2e4bc635a56b43f9647f7b13832d5d9ecd8f82dac4f510",
        "config.json": "30d28a219b65aedf6026b24cfe9e0f7e445b20de469f9053f218799ddc64406e",
        "languages.json": "973d5136344f6a0999540386bc2f5c24520906042c349cab7dc6ed46411ee681",
        "LICENSE": "4f5b74db4fd26299a166688de8a3bde046fd7d9cc13ecab64532c24310bc18d7",
    }),
}


def fetch() -> None:
    for variant, (commit, files) in MODELS.items():
        for name, digest in files.items():
            path = CACHE / variant / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                print(f"fetching {variant}/{name}", flush=True)
                urllib.request.urlretrieve(f"https://huggingface.co/{REPO}/resolve/{commit}/{name}", path)
            got = hashlib.sha256(path.read_bytes()).hexdigest()
            if got != digest:
                raise SystemExit(f"{variant}/{name}: SHA-256 {got}, expected {digest}")


def judged_texts(row: dict) -> list[str]:
    """Every text turn_rules.replay can hand a rule for this clip: each final joined to the ones held before it."""
    held, out = "", []
    for _, text, _ in row["segments"]:
        if text:
            held = f"{held} {text}".strip()
            out.append(held)
    return out


def _rows() -> list[dict]:
    return [r for r in map(json.loads, ROWS.read_text().splitlines()) if r["policy"] == "before" and not r.get("error")]


def score(threads: int) -> None:
    """Runs in ENV. The runner is LiveKit's own; only its loading is replaced, to read the pinned files from CACHE and
    to keep to `threads` cores."""
    import onnxruntime as ort
    from livekit.plugins.turn_detector.english import _EUORunnerEn
    from livekit.plugins.turn_detector.multilingual import _EUORunnerMultilingual
    from transformers import AutoTokenizer

    texts = sorted({t for r in _rows() for t in judged_texts(r)})
    got: dict[str, dict] = {t: {"text": t} for t in texts}
    for variant, runner_class in (("multilingual", _EUORunnerMultilingual), ("en", _EUORunnerEn)):
        folder = CACHE / variant
        runner = runner_class()
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
        runner._session = ort.InferenceSession(str(folder / "onnx" / "model_q8.onnx"), providers=["CPUExecutionProvider"],
                                               sess_options=options)
        runner._tokenizer = AutoTokenizer.from_pretrained(str(folder), truncation_side="left")
        ask = lambda t: json.loads(runner.run(json.dumps({"chat_ctx": [{"role": "user", "content": t}]}).encode()))  # noqa: E731
        for t in texts[:5]:
            ask(t)  # warm
        ms = []
        for t in texts:
            began = time.perf_counter()
            got[t][variant] = round(ask(t)["eou_probability"], 6)
            ms.append((time.perf_counter() - began) * 1000)
        size = (folder / "onnx" / "model_q8.onnx").stat().st_size / 1e6
        print(f"{variant}: {len(texts)} texts, {size:.0f} MB, {threads} thread(s): median {statistics.median(ms):.0f} ms, "
              f"p90 {sorted(ms)[int(0.9 * (len(ms) - 1))]:.0f} ms", flush=True)
    SCORES.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in got.values()))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def eou_rule(variant: str, sure=None, sure_wait=1.0, doubt=None, doubt_wait=2.0, base=1.3, scores=None):
    """Normal's text rules first (a hold, a stop, a short answer, words that read unfinished, a sentence said in parts);
    a sentence that reads whole waits `sure_wait` when the model's probability is `sure` or over, `doubt_wait` when it
    is under `doubt`, and `base` otherwise or when it was not scored. The `sound` the rows carry adds nothing here: the
    best rule that also asked for it, on train, asked for none."""
    import turns
    normal = turns.LEVELS["normal"]
    table = scores if scores is not None else SCORE_TABLE

    def wait(text: str, held: bool, sound, endpoint: bool, paused: bool) -> float:
        w = turns.settle(text, held, "normal")
        if w != normal.complete or held:
            return w
        p = table.get(text, {}).get(variant)
        if p is None:
            return base
        if sure is not None and p >= sure:
            return sure_wait
        if doubt is not None and p < doubt:
            return doubt_wait
        return base
    return wait


SCORE_TABLE: dict[str, dict] = {}


def _load_scores() -> None:
    if not SCORES.exists():
        raise SystemExit(f"{SCORES} is missing: run `score` first (see the header)")
    SCORE_TABLE.update({s["text"]: s for s in map(json.loads, SCORES.read_text().splitlines())})


def _summary(out: dict) -> dict:
    k, n, d = len(out["cuts"]), len(out["pauses"]), out["delays"]
    import turn_rules
    return {"k": k, "n": n, "rate": k / max(1, n), "ci": wilson(k, n), "median": statistics.median(d),
            "mean": statistics.mean(d), "p90": turn_rules.p90(d), "over": sum(x > 1.05 for x in d) / len(d)}


# The multilingual model's probabilities sit far lower than the English one's (LiveKit's own English threshold is
# 0.011 for it and 0.0289 for `en`), so each has its own thresholds, spanning the deciles of its scores on these rows.
THRESHOLDS = {"multilingual": ((0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4), (0.002, 0.005, 0.01, 0.02, 0.03, 0.05)),
              "en": ((0.3, 0.5, 0.7, 0.8, 0.9, 0.95), (0.05, 0.1, 0.2, 0.3))}


def _grid():
    for variant, (sures, doubts) in THRESHOLDS.items():
        for sure in (None, *sures):
            for sure_wait in ((1.0,) if sure is None else (0.5, 0.7, 0.8, 0.9, 1.0, 1.1)):
                for doubt in (None, *doubts):
                    for doubt_wait in ((2.0,) if doubt is None else (1.6, 2.0, 2.5, 3.0)):
                        for base in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5):
                            if sure is None and doubt is None:
                                continue
                            yield (variant, sure, sure_wait, doubt, doubt_wait, base)


def _name(variant, sure, sure_wait, doubt, doubt_wait, base) -> str:
    parts = [variant[:5], f"{base} s"]
    if sure is not None:
        parts.append(f"p>={sure}: {sure_wait} s")
    if doubt is not None:
        parts.append(f"p<{doubt}: {doubt_wait} s")
    return ", ".join(parts)


# Chosen by `sweep` on the train speakers only (its docstring says how); `report` shows them on the others.
CHOSEN = [  # `sweep` prints this list
    ('multilingual', 0.08, 0.9, 0.05, 2.5, 1.3),
    ('multilingual', 0.08, 1.1, 0.05, 1.6, 1.3),
    ('multilingual', 0.4, 0.5, None, 2.0, 1.3),
    ('multilingual', None, 1.0, 0.05, 2.0, 1.1),
    ('en', 0.8, 0.5, 0.1, 1.6, 1.3),
    ('multilingual', 0.05, 0.5, None, 2.0, 1.0),
    ('multilingual', 0.05, 0.5, None, 2.0, 1.2),
    ('multilingual', 0.05, 0.5, 0.002, 2.0, 1.1),
    ('multilingual', 0.05, 0.5, 0.05, 1.6, 1.0),
]


def _baselines() -> dict:
    import turn_rules
    return {"Normal now (1.3 s)": turn_rules.RULES["Normal now (1.3 s, the narrow list)"],
            "every whole sentence 1.0 s": turn_rules.RULES["Normal before (1.0 s)"],
            "every whole sentence 1.1 s": turn_rules.RULES["every whole sentence 1.1 s"],
            "every whole sentence 1.2 s": turn_rules.RULES["every whole sentence 1.2 s"]}


def _separation(rows: list, variant: str) -> tuple[float, int, int]:
    """How well the score tells the first final inside a real pause from a real end, over texts that read whole: the
    probability that an end scores over a pause (0.5 is a coin)."""
    import turns
    pause, end = [], []
    for r in rows:
        texts = judged_texts(r)
        if not texts:
            continue
        text = texts[0] if r["pause"] is not None else texts[-1]
        if turns.settle(text, False, "normal") != turns.LEVELS["normal"].complete or text not in SCORE_TABLE:
            continue
        (pause if r["pause"] is not None else end).append(SCORE_TABLE[text][variant])
    wins = sum((e > p) + 0.5 * (e == p) for e in end for p in pause)
    return wins / max(1, len(end) * len(pause)), len(pause), len(end)


def sweep() -> None:
    """Every rule of the grid on the train speakers. For each fixed wait, the rules that cut in no more often than it
    there: the one with the lowest median end delay and the one with the lowest mean; then, at or under Normal, the best
    rule that only shortens, the best that only lengthens, and the best on the English model. These are CHOSEN."""
    import turn_rules
    _load_scores()
    rows, when = turn_rules.load(str(ROWS))
    train = [r for r in rows if turn_rules.half(r) == "train"]
    for variant in ("multilingual", "en"):
        auc, np_, ne = _separation(train, variant)
        print(f"train, {variant}: an end scores over a pause {auc:.2f} of the time ({np_} pauses, {ne} ends that read whole)")
    results = [(params, _summary(turn_rules.evaluate(train, eou_rule(*params), when))) for params in _grid()]
    line = lambda name, s: (f"  {name:50s} {s['k']:3d}/{s['n']} ({s['rate']:5.1%})  median {s['median']:.2f} "  # noqa: E731
                            f"mean {s['mean']:.2f} p90 {s['p90']:.2f}")
    chosen = []
    for base_name, wait in _baselines().items():
        b = _summary(turn_rules.evaluate(train, wait, when))
        fit = [x for x in results if x[1]["k"] <= b["k"]]
        print(f"\nat or under {base_name}'s cut-ins on train ({len(fit)} of {len(results)} rules):\n{line(base_name, b)}")
        picks = {"lowest median": min(fit, key=lambda x: (x[1]["median"], x[1]["mean"])),
                 "lowest mean": min(fit, key=lambda x: (x[1]["mean"], x[1]["median"]))}
        if base_name.startswith("Normal"):
            picks |= {"only shortens, lowest mean": min((x for x in fit if x[0][3] is None), key=lambda x: x[1]["mean"]),
                      "only lengthens, lowest mean": min((x for x in fit if x[0][1] is None), key=lambda x: x[1]["mean"]),
                      "English model, lowest mean": min((x for x in fit if x[0][0] == "en"), key=lambda x: x[1]["mean"])}
        for why, (params, s) in picks.items():
            print(line(f"{why}: {_name(*params)}", s))
            chosen.append(params)
    print("\nThe lowest mean end delay at each count of cut-ins:")
    best: dict[int, tuple] = {}
    for params, s in results:
        if s["k"] not in best or s["mean"] < best[s["k"]][1]["mean"]:
            best[s["k"]] = (params, s)
    for k in sorted(best)[:25]:
        print(line(_name(*best[k][0]), best[k][1]))
    print("\nCHOSEN = " + repr(list(dict.fromkeys(chosen))))


def report() -> None:
    import turn_rules
    _load_scores()
    rows, when = turn_rules.load(str(ROWS))
    rules = {**_baselines(), **{_name(*c): eou_rule(*c) for c in CHOSEN}}
    for split in ("test", "all"):
        part = [r for r in rows if split == "all" or turn_rules.half(r) == split]
        pauses = sum(r["pause"] is not None for r in part)
        print(f"\n{split}: {len({r['voice'] for r in part})} speakers, {pauses} pauses, {len(part) - pauses} ends")
        for variant in ("multilingual", "en"):
            auc, np_, ne = _separation(part, variant)
            print(f"  {variant}: an end scores over a pause {auc:.2f} of the time ({np_} pauses, {ne} ends that read whole)")
        print(f"| Rule | Cut-ins on pauses | 95% interval | End delay median | mean | p90 | over 1.05 s |\n|---|---|---|---|---|---|---|")
        for name, wait in rules.items():
            s = _summary(turn_rules.evaluate(part, wait, when))
            print(f"| {name} | {s['k']} ({s['rate']:.1%}) | {s['ci'][0]:.1%} to {s['ci'][1]:.1%} | {s['median']:.2f} s | "
                  f"{s['mean']:.2f} s | {s['p90']:.2f} s | {s['over']:.0%} |")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["fetch", "score", "sweep", "report"])
    p.add_argument("--threads", type=int, default=1)
    a = p.parse_args()
    {"fetch": fetch, "score": lambda: score(a.threads), "sweep": sweep, "report": report}[a.step]()


if __name__ == "__main__":
    main()
