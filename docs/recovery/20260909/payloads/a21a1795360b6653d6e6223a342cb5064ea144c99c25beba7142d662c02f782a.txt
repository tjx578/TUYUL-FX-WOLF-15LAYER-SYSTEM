from __future__ import annotations

import copy
import json

import pytest

from tests.integration.t14_image_binding import (
    canonical_hash,
    filesystem_inventory,
    prebuilt_inputs,
    runtime_config_hash,
    validate_image_binding,
    validate_runtime_probe,
)

COMMIT = "a" * 40
TREE = "b" * 40
IMAGE = "sha256:" + "c" * 64
BASE = "sha256:" + "d" * 64


@pytest.fixture
def binding():
    config = {"User": "appuser", "WorkingDir": "/app", "Cmd": ["python", "api_server.py"]}
    evidence = {
        "schema": "wolf15.runtime-source-image/v1",
        "verdict": "PASS_BUILD_AND_IMAGE_BINDING",
        "source": {"commit": COMMIT, "tree": TREE},
        "image_id": IMAGE,
        "base_image_id": BASE,
        "build_mode": "retained-runtime-full-source-replacement",
        "archive_sha256": "1" * 64,
        "projection_sha256": "2" * 64,
        "base_export_sha256": "3" * 64,
        "runtime_config_sha256": runtime_config_hash(config),
        "base_rootfs_diff_ids": [BASE],
    }
    config["Labels"] = {
        "org.opencontainers.image.revision": COMMIT,
        "org.wolf15.source.commit": COMMIT,
        "org.wolf15.source.tree": TREE,
        "org.wolf15.base.image": BASE,
        "org.wolf15.build.mode": evidence["build_mode"],
    }
    image = {"Id": IMAGE, "Os": "linux", "Architecture": "amd64", "Config": config, "RootFS": {"Layers": [BASE, IMAGE]}}
    return evidence, image


def test_default_mode_does_not_require_an_image_attestation():
    assert prebuilt_inputs({}, COMMIT, TREE) is None


@pytest.mark.parametrize(
    "environment",
    [
        {"WOLF15_T14_PREBUILT_IMAGE_ID": IMAGE},
        {"WOLF15_T14_IMAGE_ATTESTATION": "unused.json"},
        {"WOLF15_T14_PREBUILT_IMAGE_ID": "mutable:tag", "WOLF15_T14_IMAGE_ATTESTATION": "unused.json"},
    ],
)
def test_rejects_partial_or_mutable_image_inputs_before_reading_a_file(environment):
    with pytest.raises(ValueError):
        prebuilt_inputs(environment, COMMIT, TREE)


def test_accepts_explicit_exact_source_and_image(tmp_path, binding):
    evidence, image = binding
    path = tmp_path / "image.json"
    path.write_text(json.dumps(evidence))
    result = prebuilt_inputs(
        {"WOLF15_T14_PREBUILT_IMAGE_ID": IMAGE, "WOLF15_T14_IMAGE_ATTESTATION": str(path)}, COMMIT, TREE
    )
    assert result == (IMAGE, evidence)
    validate_image_binding(image, evidence)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", "unknown"),
        ("verdict", "DECLARED"),
        ("source", {"commit": COMMIT, "tree": "0" * 40}),
        ("image_id", BASE),
        ("build_mode", "unspecified"),
        ("archive_sha256", None),
        ("projection_sha256", ""),
        ("runtime_config_sha256", "not-a-hash"),
        ("base_export_sha256", None),
        ("base_image_id", "mutable:base"),
        ("base_rootfs_diff_ids", []),
    ],
)
def test_rejects_unbound_or_failed_receipts(tmp_path, binding, key, value):
    evidence, _ = binding
    evidence[key] = value
    path = tmp_path / "image.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError):
        prebuilt_inputs(
            {"WOLF15_T14_PREBUILT_IMAGE_ID": IMAGE, "WOLF15_T14_IMAGE_ATTESTATION": str(path)}, COMMIT, TREE
        )


@pytest.mark.parametrize("mutation", ["image", "platform", "user", "command", "source", "base_layers", "no_new_layer"])
def test_actual_image_inspection_must_match_receipt(binding, mutation):
    evidence, original = binding
    image = copy.deepcopy(original)
    if mutation == "image":
        image["Id"] = BASE
    elif mutation == "platform":
        image["Architecture"] = "arm64"
    elif mutation == "user":
        image["Config"]["User"] = "root"
    elif mutation == "command":
        image["Config"]["Cmd"] = ["false"]
    elif mutation == "source":
        image["Config"]["Labels"]["org.wolf15.source.tree"] = "0" * 40
    elif mutation == "base_layers":
        image["RootFS"]["Layers"] = [IMAGE, BASE]
    else:
        image["RootFS"]["Layers"] = [BASE]
    with pytest.raises(ValueError):
        validate_image_binding(image, evidence)


def test_actual_file_inventory_detects_missing_stale_and_modified_paths(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    current = app / "entry.py"
    current.write_bytes(b"current\n")
    baseline, _ = filesystem_inventory(str(app))
    current.write_bytes(b"changed\n")
    changed, _ = filesystem_inventory(str(app))
    assert canonical_hash(changed) != canonical_hash(baseline)
    current.write_bytes(b"current\n")
    (app / "obsolete.py").write_bytes(b"stale\n")
    stale, _ = filesystem_inventory(str(app))
    assert set(stale) - set(baseline) == {"obsolete.py"}
    current.unlink()
    missing, _ = filesystem_inventory(str(app))
    assert "entry.py" not in missing


@pytest.mark.parametrize("wrong_field", ["uid", "all_application_owners_1000", "actual_projection_sha256", "source"])
def test_runtime_probe_is_independent_of_labels(binding, wrong_field):
    evidence, _ = binding
    probe = {
        "source": evidence["source"],
        "archive_sha256": evidence["archive_sha256"],
        "projection_sha256": evidence["projection_sha256"],
        "actual_projection_sha256": evidence["projection_sha256"],
        "uid": 1000,
        "gid": 1000,
        "all_application_owners_1000": True,
        "verdict": "PASS_ACTUAL_IMAGE_FILESYSTEM",
    }
    validate_runtime_probe(probe, evidence)
    probe[wrong_field] = None
    with pytest.raises(ValueError):
        validate_runtime_probe(probe, evidence)
