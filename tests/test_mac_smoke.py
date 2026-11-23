"""macos/e2e/smoke.py refuses an app whose resource bundle carries the app's own identifier: such a build has no Chorus
mark, which a QA round once filed as a product bug. Synthetic bundles; nothing is built or launched."""

import importlib.util
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mac_smoke", ROOT / "macos" / "e2e" / "smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _app(tmp_path: Path, resources_id: str) -> Path:
    app = tmp_path / "Pointe.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "io.example.pointe.mac"}))
    res = app / "Contents" / "Resources" / "PointeKit_PointeUI.bundle" / "Contents"
    res.mkdir(parents=True)
    (res / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": resources_id}))
    return app


def test_a_plain_build_keeps_the_resource_bundles_own_identifier(tmp_path):
    assert smoke.shared_bundle_ids(_app(tmp_path, "PointeKit.PointeUI.resources")) == []


def test_a_command_line_bundle_id_that_renamed_the_resource_bundle_is_named(tmp_path):
    assert smoke.shared_bundle_ids(_app(tmp_path, "io.example.pointe.mac")) == ["PointeKit_PointeUI.bundle"]


def test_the_advice_no_longer_says_to_build_under_another_bundle_id():
    text = (ROOT / "macos" / "e2e" / "smoke.py").read_text()
    assert "under its own bundle id" not in text
    assert "never pass PRODUCT_BUNDLE_IDENTIFIER to xcodebuild" in text
