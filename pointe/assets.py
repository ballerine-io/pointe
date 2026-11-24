"""Everything Pointe downloads at run time, pinned in one place: a file by its SHA-256, a Hugging Face repository by one commit.

GitHub release assets and Hub repositories can both be replaced under the same name by whoever owns them. So no model is
fetched by name alone: a release asset is hashed before it is used, and refused when the hash is wrong; a Hub repository is
read at the commit named here, never at `main`, and huggingface_hub checks each file against that commit's metadata.

Adding a download: its hash or commit here, its host in docs/security/egress-allowlist.txt, a row in THIRD_PARTY.md.
tests/test_supply_chain.py checks that every fetch in the source goes through here. Why: docs/security/supply-chain.md.
"""

import no_telemetry  # noqa: F401  (kokoro_paths imports a Pipecat module that loads onnxruntime)
import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Asset:
    name: str  # the file name on disk
    url: str
    sha256: str
    mb: int
    license: str


ASSETS = {
    "speaker": Asset(
        "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b", 40,
        "Apache-2.0: 3D-Speaker ERes2Net base (modelscope iic/speech_eres2net_base_sv_zh-cn_3dspeaker_16k)"),
    "kokoro-model": Asset(
        "kokoro-v1.0.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5", 311,
        "Apache-2.0: Kokoro-82M (hexgrad), ONNX export by kokoro-onnx"),
    "kokoro-voices": Asset(
        "voices-v1.0.bin",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", 28,
        "Apache-2.0: Kokoro-82M voices"),
}

# Hugging Face repository -> the commit Pointe reads. A model the user names by hand (`pointe local --model`) is not here
# and is their own choice: it is read at `main`.
HF_MODELS = {
    "mlx-community/whisper-large-v3-turbo": "a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",  # local ears, Apple silicon
    "deepdml/faster-whisper-large-v3-turbo-ct2": "4df90f75321148c3a29a9e2351b7ddf8f5b115a8",  # local ears, elsewhere
    "mlx-community/Kokoro-82M-bf16": "a71e4d38b236d968966a2002c4c895dbd12b1c3c",  # mouth: local:kokoro-mlx
    "mlx-community/gemma-4-26b-a4b-it-4bit": "0d77464eeb233a2da68ebf9d7dc4edaac7db956d",  # pointe local, text model
}


def revision(repo: str) -> str | None:
    return HF_MODELS.get(repo)


def snapshot(repo: str, **kwargs) -> str:
    """huggingface_hub.snapshot_download at the pinned commit: the folder of the files, downloading them when missing
    (unless local_files_only=True, which raises instead)."""
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, revision=revision(repo), **kwargs)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(asset: Asset, path: Path, timeout: float = 60) -> Path:
    """Download the asset to `path`: written to a .part file first, hashed as it streams, moved into place only when the
    hash is the pinned one. A mismatch deletes the .part and raises ValueError, so a wrong file is never on disk by name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(asset.url, timeout=timeout) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 20):
                digest.update(chunk)
                f.write(chunk)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != asset.sha256:
        part.unlink(missing_ok=True)
        raise ValueError(f"{asset.name}: the downloaded file's SHA-256 does not match the one pinned in assets.py")
    os.replace(part, path)
    return path


def ensure(asset: Asset, path: Path) -> Path:
    """The asset at `path`, verified: a file already there is hashed too, so a copy an older downloader left unverified,
    or a file for an older pin, is replaced."""
    if path.exists() and sha256_of(path) == asset.sha256:
        return path
    return fetch(asset, path)


def kokoro_paths() -> tuple[Path, Path]:
    """Where Pipecat's Kokoro service keeps its model and voices: the same folder, so a download made before this pin
    is reused once it is verified."""
    from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR

    return KOKORO_CACHE_DIR / ASSETS["kokoro-model"].name, KOKORO_CACHE_DIR / ASSETS["kokoro-voices"].name


def ensure_kokoro() -> tuple[Path, Path]:
    """Kokoro v1.0's model and voices, verified, to hand to Pipecat by path so its own unverified download never runs."""
    model, voices = kokoro_paths()
    return ensure(ASSETS["kokoro-model"], model), ensure(ASSETS["kokoro-voices"], voices)
