# Third-party components

Pointe is MIT-licensed. It depends on the components below, each under its own license. Versions are the ones pinned
in `uv.lock` and `channel/package-lock.json` at release 1.0.0. Licenses are as declared in each package's metadata;
check the package itself for the authoritative text.

## Models downloaded at runtime

| Model | Used for | License | Downloaded from |
|---|---|---|---|
| 3D-Speaker ERes2Net base (`3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`, 40 MB) | the [voice lock](docs/features/voice-lock.md), on first enrolment | Apache-2.0 ([3D-Speaker](https://github.com/modelscope/3D-Speaker); ModelScope `iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k`) | https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx, checked against the SHA-256 pinned in `assets.py` |
| Whisper large-v3-turbo, MLX conversion (`mlx-community/whisper-large-v3-turbo`) | local ears on Apple silicon, only with `ears: local` | MIT (OpenAI Whisper); the conversion's repository states no license of its own | Hugging Face, at the commit pinned in `assets.py` |
| Whisper large-v3-turbo, CTranslate2 conversion (`deepdml/faster-whisper-large-v3-turbo-ct2`) | local ears on other machines, only with `ears: local` | MIT | Hugging Face, at the commit pinned in `assets.py` |
| Kokoro-82M, MLX conversion (`mlx-community/Kokoro-82M-bf16`, 0.4 GB with its voices) | local mouth on Apple silicon, only with `mouth: local:kokoro-mlx` ("Voice stays on your Mac") | Apache-2.0 ([Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)) | Hugging Face, at the commit pinned in `assets.py`, by `pointe local voice` or on first use |
| spaCy English pipeline `en_core_web_sm` 3.8.0 | misaki's part-of-speech tags for English, with `mouth: local:kokoro-mlx` | MIT | installed by uv from the [spaCy models release](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0) (pinned in `pyproject.toml`), not at runtime |
| Kokoro v1.0 (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) | local mouth, only with `mouth: local` | Apache-2.0 ([Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)) | https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/, checked against the SHA-256s pinned in `assets.py` (Pipecat's own downloader, which checks nothing, never runs) |
| Gemma 4 26B A4B instruct, MLX 4-bit conversion (`mlx-community/gemma-4-26b-a4b-it-4bit`, 15.4 GB) | local brain, reader and gate, only with `pointe local` | Apache-2.0 ([google/gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it)) | Hugging Face, at the commit pinned in `assets.py`, by `pointe local` |

Silero VAD (MIT) ships inside the `pipecat-ai` package; it is not downloaded.

## Fonts in the repository

Bundled, never downloaded by the software: the page loads them from the daemon (`/voice/font/…`), the iPhone app from
its bundle. Each file's SHA-256 is pinned in `assets/theme.json` and checked by `tests/test_theme.py`.

| Font | Files | License | Taken from |
|---|---|---|---|
| Bricolage Grotesque (display, 300 and 400) | `assets/fonts/BricolageGrotesque-{Light,Regular}.ttf`, the same files in `ios/Pointe/Fonts/` | OFL-1.1, no reserved font name (`assets/fonts/OFL-BricolageGrotesque.txt`; identical to the copy in google/fonts `ofl/bricolagegrotesque`) | [ateliertriay/bricolage](https://github.com/ateliertriay/bricolage) at commit `84745e5b96261ae5f8c6c856e262fe78d1d6efdd`, `fonts/ttf/` |
| Instrument Sans (text, 400, 500 and 600) | `assets/fonts/InstrumentSans-{Regular,Medium,SemiBold}.ttf`, the same files in `ios/Pointe/Fonts/` | OFL-1.1, no reserved font name (`assets/fonts/OFL-InstrumentSans.txt`; identical to the copy in google/fonts `ofl/instrumentsans`) | [Instrument/instrument-sans](https://github.com/Instrument/instrument-sans) at commit `7fa22308a3d0c94ee2b3cd537a1196b65db34a3e`, `fonts/ttf/` |

## Python runtime dependencies

Direct dependencies, from `pyproject.toml`:

| Package | Version | License |
|---|---|---|
| [pipecat-ai](https://github.com/pipecat-ai/pipecat) (with `google`, `openai`, `silero`, `soniox`, `websocket` extras) | 1.15.0 | BSD-2-Clause |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 2.0.1 | Apache-2.0 |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | 2.6.0 | Apache-2.0 |
| [aiohttp](https://github.com/aio-libs/aiohttp) | 3.14.5 | Apache-2.0 AND MIT |
| [segno](https://github.com/heuer/segno) | 1.6.6 | BSD (variant not declared in its metadata) |
| [uvicorn](https://github.com/encode/uvicorn) | 0.54.0 | BSD-3-Clause |

Installed with them (transitive), by license:

| License | Packages |
|---|---|
| Apache-2.0 | aiofiles, aiosignal, distro, flatbuffers, frozenlist, google-api-core, google-auth, google-cloud-speech, google-cloud-texttospeech, google-genai, googleapis-common-protos, grpcio, grpcio-status, multidict, openai, opentelemetry-api, propcache, proto-plus, requests, sherpa-onnx-core, tenacity, yarl |
| MIT | annotated-doc, annotated-types, anyio, attrs, charset-normalizer, docopt, docstring-parser, fastapi, h11, h2, hpack, hyperframe, jiter, loguru, loudness, onnxruntime, pydantic, pydantic-core, pyyaml, sentencex, sniffio, truststore, typing-inspection, urllib3 |
| MIT-0 | cffi |
| MIT-CMU | pillow |
| BSD-2-Clause | pyasn1 |
| BSD-3-Clause | click, httpcore, httpcore2, httpx2, idna, markdown, protobuf, pycparser, python-dotenv, starlette, websockets |
| BSD (variant not declared in metadata) | httpx, numba, pyasn1-modules, soundfile |
| BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | llvmlite |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | numpy |
| Apache-2.0 OR BSD-3-Clause | cryptography |
| Apache-2.0 OR BSD-2-Clause | packaging |
| ISC | resampy |
| PSF-2.0 | aiohappyeyeballs, typing-extensions |
| MPL-2.0 | certifi |
| LGPL-2.1-or-later | soxr |
| LGPL (version not declared in metadata) | num2words |

## Optional: local models (`local` extra)

Installed only when ears or mouth are set to `local`:

| Package | Version | License |
|---|---|---|
| mlx-whisper (Apple silicon) | 0.4.3 | MIT |
| mlx (Apple silicon) | 0.32.4 | MIT |
| faster-whisper (other machines) | 1.2.1 | MIT |
| ctranslate2 (other machines) | 4.8.5 | MIT |
| kokoro-onnx | 0.6.1 | MIT |
| espeakng-loader | 0.2.4 | MIT; it loads eSpeak NG, which is GPL-3.0-or-later |
| phonemizer | 3.6.0 | GPL-3.0-or-later |
| mlx-audio (Apple silicon) | 0.6.5 | MIT |
| misaki, with `en` (Apple silicon) | 0.9.4 | Apache-2.0 |
| phonemizer-fork (Apple silicon; misaki's eSpeak fallback) | 3.3.2 | GPL-3.0-or-later |
| spaCy (Apple silicon) | 3.8.18 | MIT |
| en-core-web-sm (Apple silicon) | 3.8.0 | MIT |

On Apple silicon mlx-audio, misaki and spaCy bring these in with them, by license: MIT: addict, catalogue, cloudpathlib,
confection, curated-tokenizers, curated-transformers, cymem, jsonschema, jsonschema-specifications, language-tags,
markdown-it-py, mdurl, miniaudio, murmurhash, preshed, pyparsing, referencing, rich, rpds-py, smart-open,
spacy-curated-transformers, spacy-legacy, spacy-loggers, srsly, termcolor, thinc, typer, wasabi, weasel. Apache-2.0:
csvw, rfc3986, safetensors, segments, sentencepiece, transformers, tzdata. BSD-3-Clause: babel, python-dateutil, rdflib.
BSD (variant not declared): blis, isodate. BSD-2-Clause: wrapt. BSD-3-Clause OR Apache-2.0: uritemplate. ISC: shellingham.

The `local` extra therefore brings in GPL-3.0 components (eSpeak NG, through phonemizer and phonemizer-fork). They run
as separate libraries in your own environment; they are not part of Pointe's source, and nothing outside the `local`
extra installs them.

No permissive local voice that we could measure replaces Kokoro yet: Kokoro's other runtimes (mlx-audio, misaki) also use
eSpeak NG for English words misaki does not know, and Chatterbox Multilingual (MIT, no eSpeak, claims Hebrew) took 2.4 s to its first English audio
on an M5 Pro, and its Hebrew was not intelligible ([docs/features/local.md](docs/features/local.md)). So the GPL-3.0 parts stay, only in the optional extra.

## Optional: the local text-model server (`pointe local`)

`pointe local` installs [mlx-lm](https://github.com/ml-explore/mlx-lm) 0.32.2 (MIT) in its own uv environment under
`~/.claude-voice/local/mlx-lm`, separate from Pointe's, from the `mlx-lm` dependency group of `pyproject.toml`: its
packages are the versions and hashes in `uv.lock`, by license:

| License | Packages |
|---|---|
| MIT | mlx, mlx-metal, mlx-lm, annotated-doc, annotated-types, anyio, filelock, h11, markdown-it-py, mdurl, pydantic, pydantic-core, pyyaml, rich, truststore, typer, typing-inspection |
| Apache-2.0 | transformers, tokenizers, safetensors, sentencepiece, huggingface-hub, hf-xet |
| Apache-2.0 AND CNRI-Python | regex |
| BSD-3-Clause | click, fsspec, httpcore2, httpx2, idna, markupsafe, protobuf |
| BSD | jinja2 |
| BSD-2-Clause | pygments |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | numpy |
| Apache-2.0 OR BSD-2-Clause | packaging |
| ISC | shellingham |
| MPL-2.0 AND MIT | tqdm |
| PSF-2.0 | typing-extensions |

None is GPL.

## Claude Code channel (`channel/`, Node.js)

Used only by channel mode (`bin/pointe start`): [@modelcontextprotocol/sdk](https://github.com/modelcontextprotocol/typescript-sdk)
1.32.2 (MIT) and [zod](https://github.com/colinhacks/zod) 3.25.76 (MIT). Their dependencies are MIT (85 packages), ISC
(7), BSD-3-Clause (2) and BSD-2-Clause (1); the full list is in `channel/package-lock.json`.

## iPhone app

The app uses Apple's frameworks only, with no third-party Swift packages.

## Vendor APIs

Pointe calls these services with your own keys, for the roles you configure. Their terms, pricing and data retention
apply to what you send them; see [Privacy](README.md#privacy) for what each receives.

| Vendor | Used for |
|---|---|
| [Anthropic](https://www.anthropic.com) (Claude API) | brain, reader, checker |
| [Google](https://ai.google.dev) (Gemini API) | ears, brain, reader, checker, mouth, realtime front |
| [OpenAI](https://platform.openai.com) | ears, brain, reader, checker, mouth, realtime front |
| [Soniox](https://soniox.com) | ears (with the echo guard's mirror stream), meeting ears, mouth |
| [ElevenLabs](https://elevenlabs.io) | ears, mouth |

Optional, only if you choose them: an OpenAI-compatible local server for local text models (`pointe local` installs
mlx-lm's; [Ollama](https://ollama.com) or another works when set by hand); [Tailscale](https://tailscale.com) or [Twingate](https://www.twingate.com) (`twingate/connector` container
image) for phone access. Setup installs [uv](https://docs.astral.sh/uv/) if it is missing, with Astral's installer for one pinned version, checked against a SHA-256 before it runs (`bin/install-uv`).
