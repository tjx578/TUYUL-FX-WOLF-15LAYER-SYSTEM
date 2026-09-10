"""Pure binding checks for the explicit, attested prebuilt-image T14 mode."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUNTIME_FIELDS = (
    "User",
    "WorkingDir",
    "Entrypoint",
    "Cmd",
    "Env",
    "ExposedPorts",
    "Healthcheck",
    "Volumes",
    "StopSignal",
    "Shell",
)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_config_hash(config: dict[str, Any]) -> str:
    return canonical_hash({key: config.get(key) for key in RUNTIME_FIELDS})


def prebuilt_inputs(environment: Any, commit: str, tree: str) -> tuple[str, dict[str, Any]] | None:
    image = environment.get("WOLF15_T14_PREBUILT_IMAGE_ID", "").strip()
    locator = environment.get("WOLF15_T14_IMAGE_ATTESTATION", "").strip()
    if not image and not locator:
        return None
    if not image or not locator or not DIGEST.fullmatch(image):
        raise ValueError("prebuilt mode requires an immutable image ID and its attestation together")
    evidence = json.loads(Path(locator).read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ValueError("attestation must be an object")
    if evidence.get("schema") != "wolf15.runtime-source-image/v1":
        raise ValueError("unsupported image attestation schema")
    if evidence.get("verdict") != "PASS_BUILD_AND_IMAGE_BINDING":
        raise ValueError("image build and binding did not pass")
    if evidence.get("source") != {"commit": commit, "tree": tree}:
        raise ValueError("attested source differs from the expected final Git source")
    if evidence.get("image_id") != image:
        raise ValueError("attested image differs from the supplied immutable image")
    if evidence.get("build_mode") != "retained-runtime-full-source-replacement":
        raise ValueError("prebuilt image has no explicit supported derivation")
    for key in ("archive_sha256", "projection_sha256", "runtime_config_sha256", "base_export_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key, ""))):
            raise ValueError(f"missing or malformed {key}")
    if not DIGEST.fullmatch(str(evidence.get("base_image_id", ""))):
        raise ValueError("missing base image identity")
    layers = evidence.get("base_rootfs_diff_ids")
    if not isinstance(layers, list) or not layers or any(not DIGEST.fullmatch(str(x)) for x in layers):
        raise ValueError("missing base rootfs identity")
    return image, evidence


def validate_image_binding(image: dict[str, Any], evidence: dict[str, Any]) -> None:
    if image.get("Id") != evidence["image_id"]:
        raise ValueError("actual Docker image identity differs")
    if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
        raise ValueError("expected linux/amd64 image")
    config = image.get("Config", {})
    if runtime_config_hash(config) != evidence["runtime_config_sha256"]:
        raise ValueError("actual runtime configuration differs from the retained base")
    labels = config.get("Labels") or {}
    required = {
        "org.opencontainers.image.revision": evidence["source"]["commit"],
        "org.wolf15.source.commit": evidence["source"]["commit"],
        "org.wolf15.source.tree": evidence["source"]["tree"],
        "org.wolf15.base.image": evidence["base_image_id"],
        "org.wolf15.build.mode": evidence["build_mode"],
    }
    if any(labels.get(key) != value for key, value in required.items()):
        raise ValueError("actual source/base/build-mode labels differ")
    base = evidence["base_rootfs_diff_ids"]
    layers = image.get("RootFS", {}).get("Layers", [])
    if layers[: len(base)] != base or len(layers) <= len(base):
        raise ValueError("image does not preserve the base layer prefix plus new source layers")


def filesystem_inventory(root: str) -> tuple[dict[str, Any], bool]:
    """Do not follow symlinks; hash every file, directory and link under root."""
    root_info = os.lstat(root)
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("application root must be a real non-symlink directory")
    result = {}
    owners_match = True
    for folder, directories, files in os.walk(root, followlinks=False):
        relative_folder = os.path.relpath(folder, root).replace(os.sep, "/")
        names = [(relative_folder, folder)] if relative_folder == "." else []
        names.extend(
            (os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/"), os.path.join(folder, name))
            for name in sorted(directories + files)
        )
        for relative, full in names:
            info = os.lstat(full)
            owners_match = owners_match and info.st_uid == 1000 and info.st_gid == 1000
            record = {"mode": stat.S_IMODE(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                record.update(type="symlink", target=os.readlink(full))
            elif stat.S_ISDIR(info.st_mode):
                record.update(type="directory")
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open(full, "rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                record.update(type="file", sha256=digest.hexdigest(), bytes=info.st_size)
            else:
                raise ValueError("unexpected special file in application projection")
            result[relative] = record
    return result, owners_match


def validate_runtime_probe(probe: dict[str, Any], evidence: dict[str, Any]) -> None:
    expected = {
        "source": evidence["source"],
        "projection_sha256": evidence["projection_sha256"],
        "actual_projection_sha256": evidence["projection_sha256"],
        "archive_sha256": evidence["archive_sha256"],
        "uid": 1000,
        "gid": 1000,
        "all_application_owners_1000": True,
        "verdict": "PASS_ACTUAL_IMAGE_FILESYSTEM",
    }
    if any(probe.get(key) != value for key, value in expected.items()):
        raise ValueError("actual inside-image filesystem or effective user does not match")


# The harness supplies this stdlib-only code directly to the image interpreter.
# It does not trust or execute a verifier copied into the image.
IN_IMAGE_PROBE = (
    "import hashlib,json,os,stat\nfrom typing import Any\n"
    + inspect.getsource(canonical_hash)
    + "\n"
    + inspect.getsource(filesystem_inventory)
    + "\nwith open('/usr/share/wolf15-build/projection.json',encoding='utf-8') as stream: receipt=json.load(stream)\n"
    + "actual,owners=filesystem_inventory('/app')\n"
    + "assert canonical_hash(actual)==receipt['projection_sha256']\n"
    + "assert actual==receipt['projected_inventory']\n"
    + "assert owners and os.getuid()==1000 and os.getgid()==1000\n"
    + "print(json.dumps({'source':receipt['source'],'archive_sha256':receipt['archive_sha256'],"
    + "'projection_sha256':receipt['projection_sha256'],'actual_projection_sha256':canonical_hash(actual),"
    + "'uid':os.getuid(),'gid':os.getgid(),'all_application_owners_1000':owners,"
    + "'path_count':len(actual),'verdict':'PASS_ACTUAL_IMAGE_FILESYSTEM'}))\n"
)
