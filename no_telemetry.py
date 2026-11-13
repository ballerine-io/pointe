"""Imported before anything that can load onnxruntime (the voice detector, the voice lock, kokoro-onnx, faster-whisper).

onnxruntime 1.31 opens a connection to Microsoft's telemetry collector (*.events.data.microsoft.com) when it is imported,
from native code; this variable, set before that import, stops it. Child processes inherit it. tests/test_no_telemetry.py
fails if a module reaches onnxruntime without it.
"""

import os

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
