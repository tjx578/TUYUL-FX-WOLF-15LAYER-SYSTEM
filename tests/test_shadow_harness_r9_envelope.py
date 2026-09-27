"""Policy 1.4.0: the harness is bound to the owner-frozen R9EnvelopeV1 (PR #517).

* the frozen schema document is verified against the policy pin at load (fail closed);
* EXACT_S acceptance comes only from ``verify_r9_envelope_v1(envelope, artifact_bytes).exact_s_accepted``;
* a capture binds by ``exact_s_id = snapshot_s.snapshot_id`` and ``exact_s_sha256 = snapshot_s.snapshot_sha256``;
* ``shadow_acceptance_passed = gate_passed AND EXACT_S_ACCEPTED AND r9_envelope_status == FROZEN``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from contracts.r9_envelope_v1 import R9EnvelopeVerdictV1, verify_r9_envelope_v1
from tests.shadow_harness_helpers import (
    POLICY_PATH,
    R9_ARTIFACT_BYTES,
    R9_ARTIFACT_SHA256,
    R9_SCHEMA_DOC,
    REPO_ROOT,
    S_ID,
    S_SHA256,
    bound_exact_s,
    bundle,
    digest,
    encode,
    evaluate,
    load_pin,
    load_real,
    natural_chain,
    r9_envelope,
)
from tools.shadow_harness import evaluator as evaluator_module
from tools.shadow_harness.cli import EXIT_GATE_PASSED, EXIT_INPUT_REJECTED, main
from tools.shadow_harness.evaluator import (
    R9EnvelopeVerification,
    ShadowHarnessReport,
    evaluate_bundle_bytes,
    verify_r9_inputs,
)
from tools.shadow_harness.manifest import (
    R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256,
    R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
    HarnessInputError,
    R9EnvelopePin,
    load_r9_envelope_pin,
    load_r9_envelope_pin_bytes,
    sha256_hex,
)

FROZEN_SHA = "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2"
SUCCESSOR_DOC_SHA = "2a5826a36f1ed9f0a099f1fd03aad52629141e76fdb9d5c7978aa2626f660f82"
SHA_LINE = f"frozen_schema_sha256           = {FROZEN_SHA}"
STATUS_LINE = "envelope_status                = FROZEN"


def _doc() -> bytes:
    return R9_SCHEMA_DOC.read_bytes()


def _pin_error(raw: bytes) -> str:
    loaded, _ = load_real()
    with pytest.raises(HarnessInputError) as info:
        load_r9_envelope_pin_bytes(raw, loaded)
    return info.value.code


def _bound_chain(universe: Any, symbol: str = "EURUSD", **exact_overrides: Any) -> list[dict[str, Any]]:
    chain = natural_chain(symbol, universe)
    chain[1] = bound_exact_s(symbol, **exact_overrides)
    return chain


# --- the pin: R9 envelope FROZEN, verified at load ------------------------------------------------------------


def test_real_schema_document_carries_the_pinned_owner_freeze() -> None:
    loaded, _ = load_real()
    pin = load_pin(loaded)
    assert pin.envelope_status == "FROZEN"
    assert pin.schema_relpath == "docs/governance/r9-envelope-v1.md"
    assert pin.frozen_schema_sha256 == R9_ENVELOPE_FROZEN_SCHEMA_SHA256 == FROZEN_SHA
    assert pin.frozen_normative_span_sha256 == R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256
    assert pin.schema_document_sha256 == sha256_hex(_doc()) == SUCCESSOR_DOC_SHA
    text = _doc().decode("utf-8")
    assert SHA_LINE + "\n" in text and STATUS_LINE + "\n" in text


@pytest.mark.parametrize(
    "raw",
    [
        _doc().replace(STATUS_LINE.encode(), b"envelope_status                = NOT_FROZEN"),
        _doc().replace(STATUS_LINE.encode(), b"envelope_status                = DRAFT"),
        _doc().replace(STATUS_LINE.encode() + b"\n", b""),
        _doc().replace(STATUS_LINE.encode(), STATUS_LINE.encode() + b"\n" + STATUS_LINE.encode()),
        _doc().replace(STATUS_LINE.encode(), b"envelope_status = FROZEN"),
        _doc() + b"\nstatus: NOT_FROZEN\n",
    ],
    ids=["not-frozen", "other-status", "missing", "duplicated", "misaligned", "not-frozen-anywhere"],
)
def test_schema_document_not_frozen_rejects(raw: bytes) -> None:
    assert _pin_error(raw) == "R9_ENVELOPE_NOT_FROZEN"


@pytest.mark.parametrize(
    "raw",
    [
        _doc().replace(SHA_LINE.encode(), f"frozen_schema_sha256           = {'0' * 64}".encode()),
        _doc().replace(SHA_LINE.encode() + b"\n", b""),
        _doc().replace(SHA_LINE.encode(), SHA_LINE.encode() + b"\n" + SHA_LINE.encode()),
        _doc().replace(b"verify_r9_envelope_v1 verdict ONLY", b"verify_r9_envelope_v1 verdict OR hash match"),
        _doc().replace(b"artifact_bytes                 = REQUIRED", b"artifact_bytes                 = OPTIONAL"),
        _doc().replace(b"## 1. Purpose", b"## 1. Purposes"),
        _doc().replace(b"artifact bytes are mandatory", b"artifact bytes are optional"),
        _doc().replace(b"\n## 8. Freeze record", b"\n## 9. Freeze record"),
        _doc() + b"\xff",
    ],
    ids=[
        "sha-changed",
        "sha-missing",
        "sha-duplicated",
        "authority-changed",
        "bytes-optional",
        "span-start-moved",
        "normative-text-edited",
        "span-end-missing",
        "not-utf8",
    ],
)
def test_schema_document_not_matching_the_pin_rejects(raw: bytes) -> None:
    assert _pin_error(raw) == "R9_ENVELOPE_PIN_MISMATCH"


def test_missing_schema_document_rejects(tmp_path: Path) -> None:
    loaded, _ = load_real()
    with pytest.raises(HarnessInputError) as info:
        load_r9_envelope_pin(loaded, tmp_path)
    assert info.value.code == "R9_ENVELOPE_SCHEMA_UNREADABLE"


def test_pin_cannot_carry_another_freeze() -> None:
    loaded, _ = load_real()
    dumped = load_pin(loaded).model_dump()
    for field in ("frozen_schema_sha256", "frozen_normative_span_sha256"):
        with pytest.raises(ValidationError):
            R9EnvelopePin.model_validate(dumped | {field: "0" * 64})
    with pytest.raises(ValidationError):
        R9EnvelopePin.model_validate(dumped | {"envelope_status": "NOT_FROZEN"})


def test_evaluator_rejects_a_pin_that_does_not_match_the_policy() -> None:
    loaded, universe = load_real()
    forged = load_pin(loaded).model_copy(update={"frozen_schema_sha256": "0" * 64})
    with pytest.raises(HarnessInputError) as info:
        evaluate_bundle_bytes(
            encode(bundle(loaded, universe)),
            loaded,
            universe,
            r9_envelope_pin=forged,
            r9_envelope=None,
            r9_artifact=None,
        )
    assert info.value.code == "R9_ENVELOPE_PIN_MISMATCH"


def _repo_copy(tmp_path: Path, doc: bytes) -> Path:
    root = tmp_path / "repo"
    loaded, _ = load_real()
    symbol_map = root / loaded.policy.symbol_map_relpath
    symbol_map.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / loaded.policy.symbol_map_relpath, symbol_map)
    schema = root / loaded.policy.r9_envelope_schema_relpath
    schema.parent.mkdir(parents=True)
    schema.write_bytes(doc)
    return root


@pytest.mark.parametrize(
    ("doc", "code"),
    [
        (
            _doc().replace(STATUS_LINE.encode(), b"envelope_status                = NOT_FROZEN"),
            "R9_ENVELOPE_NOT_FROZEN",
        ),
        (_doc().replace(FROZEN_SHA.encode(), b"f" * 64), "R9_ENVELOPE_PIN_MISMATCH"),
    ],
)
def test_cli_fails_closed_when_the_envelope_is_not_frozen_or_not_pinned(tmp_path: Path, doc: bytes, code: str) -> None:
    loaded, universe = load_real()
    root = _repo_copy(tmp_path, doc)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe, {"EURUSD": _bound_chain(universe)})))
    envelope = tmp_path / "envelope.json"
    envelope.write_bytes(encode(r9_envelope()))
    artifact = tmp_path / "r9.bin"
    artifact.write_bytes(R9_ARTIFACT_BYTES)
    out = tmp_path / "report.json"
    argv = [
        *("--policy", str(POLICY_PATH), "--bundle", str(bundle_path), "--out", str(out)),
        *("--repo-root", str(root), "--r9-envelope", str(envelope), "--r9-artifact", str(artifact)),
    ]
    assert main(argv) == EXIT_INPUT_REJECTED
    written = json.loads(out.read_text(encoding="utf-8"))
    assert (written["status"], written["rejection_code"]) == ("INPUT_REJECTED", code)
    assert (written["gate_passed"], written["shadow_acceptance_passed"]) == (False, False)
    # the identical inputs against an intact copy of the frozen document are accepted
    intact_out = tmp_path / "intact.json"
    intact = [*argv[:5], str(intact_out), "--repo-root", str(_repo_copy(tmp_path / "intact", _doc())), *argv[8:]]
    assert main(intact) == EXIT_GATE_PASSED
    assert json.loads(intact_out.read_text(encoding="utf-8"))["shadow_acceptance_passed"] is True


# --- EXACT_S: the verify_r9_envelope_v1 verdict is the only authority ------------------------------------------


def test_verification_is_exactly_the_frozen_verifier_verdict() -> None:
    envelope = r9_envelope()
    verification = verify_r9_inputs(encode(envelope), R9_ARTIFACT_BYTES)
    assert verification.verdict == verify_r9_envelope_v1(envelope, R9_ARTIFACT_BYTES)
    assert verification.exact_s_accepted is True
    assert verification.envelope_input == "PARSED"
    assert verification.envelope_sha256 == sha256_hex(encode(envelope))
    assert verification.artifact_sha256 == verification.envelope_artifact_sha256 == R9_ARTIFACT_SHA256
    assert verification.snapshot_s is not None
    assert (verification.snapshot_s.snapshot_id, verification.snapshot_s.snapshot_sha256) == (S_ID, S_SHA256)


@pytest.mark.parametrize(
    ("envelope", "artifact", "envelope_input", "reasons"),
    [
        (None, None, "NOT_SUPPLIED", None),
        (None, R9_ARTIFACT_BYTES, "NOT_SUPPLIED", None),
        (r9_envelope(), None, "PARSED", ("ARTIFACT_BYTES_REQUIRED",)),
        (r9_envelope(), b"other artifact bytes", "PARSED", ("ARTIFACT_SHA256_MISMATCH",)),
        (r9_envelope(), b"", "PARSED", ("ARTIFACT_SHA256_MISMATCH",)),
        (r9_envelope(source_artifact="R8"), R9_ARTIFACT_BYTES, "PARSED", ("SOURCE_ARTIFACT_NOT_R9",)),
        (
            r9_envelope(active_readback=r9_envelope()["active_readback"] | {"status": "REVOKED"}),
            R9_ARTIFACT_BYTES,
            "PARSED",
            ("ACTIVE_READBACK_STATUS_NOT_ACTIVE",),
        ),
        (
            r9_envelope(capability=r9_envelope()["capability"] | {"status": "NOT_MEASURED"}),
            R9_ARTIFACT_BYTES,
            "PARSED",
            ("CAPABILITY_STATUS_NOT_MEASURED",),
        ),
        (
            r9_envelope() | {"exact_s_accepted": True},
            R9_ARTIFACT_BYTES,
            "PARSED",
            ("EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT",),
        ),
        (
            {k: v for k, v in r9_envelope().items() if k != "capability"},
            R9_ARTIFACT_BYTES,
            "PARSED",
            ("ENVELOPE_SCHEMA_INVALID",),
        ),
        (b"{not json", R9_ARTIFACT_BYTES, "UNPARSEABLE", ("ENVELOPE_SCHEMA_INVALID",)),
        (b"[]", R9_ARTIFACT_BYTES, "UNPARSEABLE", ("ENVELOPE_SCHEMA_INVALID",)),
        (
            encode(r9_envelope()).replace(b'"schema_version"', b'"schema_version": "v1", "schema_version"', 1),
            R9_ARTIFACT_BYTES,
            "UNPARSEABLE",
            ("ENVELOPE_SCHEMA_INVALID",),
        ),
    ],
    ids=[
        "nothing",
        "artifact-only",
        "envelope-only",
        "wrong-bytes",
        "empty-bytes",
        "not-r9",
        "readback-revoked",
        "capability-not-measured",
        "acceptance-supplied",
        "schema-invalid",
        "invalid-json",
        "not-object",
        "duplicate-key",
    ],
)
def test_every_missing_or_failing_r9_piece_keeps_exact_s_and_final_acceptance_false(
    envelope: dict[str, Any] | bytes | None,
    artifact: bytes | None,
    envelope_input: str,
    reasons: tuple[str, ...] | None,
) -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, {"EURUSD": _bound_chain(universe)}),
        loaded,
        universe,
        r9_envelope=envelope,
        r9_artifact=artifact,
    )
    verification = report.dependent_acceptance.r9_envelope_verification
    assert verification.envelope_input == envelope_input
    if reasons is None:
        assert verification.verdict is None
    else:
        assert verification.verdict is not None and verification.verdict.failure_reasons == reasons
    assert verification.exact_s_accepted is False
    assert report.gate_passed is True  # the five-flag gate is unchanged
    assert [row.exact_s_evaluation for row in report.dependent_acceptance.candidates] == ["R9_ENVELOPE_NOT_ACCEPTED"]
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance_passed is False
    assert report.shadow_acceptance.blockers == ("EXACT_S_NOT_ACCEPTED",)


def test_unparseable_envelope_records_the_parse_error_code() -> None:
    assert verify_r9_inputs(b"{not json", R9_ARTIFACT_BYTES).envelope_input_error == "INVALID_JSON"
    assert verify_r9_inputs(b"[]", R9_ARTIFACT_BYTES).envelope_input_error == "R9_ENVELOPE_NOT_OBJECT"
    duplicate = encode(r9_envelope()).replace(b'"schema_id"', b'"schema_id": "x", "schema_id"', 1)
    assert verify_r9_inputs(duplicate, R9_ARTIFACT_BYTES).envelope_input_error == "DUPLICATE_JSON_KEY"


def test_a_rejecting_verifier_is_final_even_when_everything_else_binds(monkeypatch: pytest.MonkeyPatch) -> None:
    rejected = R9EnvelopeVerdictV1(
        exact_s_accepted=False, failure_reasons=("ARTIFACT_SHA256_MISMATCH",), artifact_bytes_verified=False
    )
    monkeypatch.setattr(evaluator_module, "verify_r9_envelope_v1", lambda envelope, artifact: rejected)
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, {"EURUSD": _bound_chain(universe)}),
        loaded,
        universe,
        r9_envelope=r9_envelope(),
        r9_artifact=R9_ARTIFACT_BYTES,
    )
    assert report.dependent_acceptance.r9_envelope_verification.verdict == rejected
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance_passed is False


# --- capture binding: exact_s_id = snapshot_s.snapshot_id, exact_s_sha256 = snapshot_s.snapshot_sha256 ----------


@pytest.mark.parametrize(
    ("overrides", "evaluation"),
    [
        ({}, "R9_ENVELOPE_BOUND"),
        ({"exact_s_id": "snap-some-other-s"}, "SNAPSHOT_S_NOT_BOUND"),
        ({"exact_s_sha256": digest("other-s")}, "SNAPSHOT_S_NOT_BOUND"),
        ({"r9_artifact_sha256": digest("other-artifact")}, "R9_ARTIFACT_NOT_BOUND"),
    ],
)
def test_capture_must_bind_to_the_verified_envelope(overrides: dict[str, Any], evaluation: str) -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe, {"EURUSD": _bound_chain(universe, **overrides)}),
        loaded,
        universe,
        r9_envelope=r9_envelope(),
        r9_artifact=R9_ARTIFACT_BYTES,
    )
    assert report.dependent_acceptance.r9_envelope_verification.exact_s_accepted is True
    row = report.dependent_acceptance.candidates[0]
    assert row.exact_s_evaluation == evaluation
    accepted = evaluation == "R9_ENVELOPE_BOUND"
    assert row.exact_s_accepted is accepted
    assert report.dependent_acceptance.exact_s_accepted is accepted
    assert report.shadow_acceptance_passed is accepted


def test_verified_envelope_without_candidates_is_not_exact_s_accepted() -> None:
    loaded, universe = load_real()
    report = evaluate(
        bundle(loaded, universe), loaded, universe, r9_envelope=r9_envelope(), r9_artifact=R9_ARTIFACT_BYTES
    )
    assert report.dependent_acceptance.r9_envelope_verification.exact_s_accepted is True
    assert report.dependent_acceptance.exact_s_accepted is False
    assert report.shadow_acceptance_passed is False


def test_same_s_bound_under_two_pairs_is_not_cross_pair_contamination() -> None:
    """Owner decision D1 (policy 1.5.0): S is an ACCOUNT snapshot, so one S bound under two pairs is not reuse.

    EXACT_S stays PAIR-scoped; only exact_s_id / exact_s_sha256 / r9_artifact_sha256 are exempt from the
    cross-pair count (full 30-pair coverage: ``tests/test_shadow_harness_account_snapshot.py``).
    """

    loaded, universe = load_real()
    captures = {"EURUSD": _bound_chain(universe, "EURUSD"), "GBPUSD": _bound_chain(universe, "GBPUSD")}
    report = evaluate(
        bundle(loaded, universe, captures), loaded, universe, r9_envelope=r9_envelope(), r9_artifact=R9_ARTIFACT_BYTES
    )
    assert report.dependent_acceptance.exact_s_accepted is True
    assert report.acceptance.cross_pair_contamination == 0
    assert report.contamination_findings == ()
    assert report.gate_failures == ()
    assert report.shadow_acceptance_passed is True


def test_verification_block_cannot_be_forged_true() -> None:
    base = verify_r9_inputs(None, R9_ARTIFACT_BYTES).model_dump()
    with pytest.raises(ValidationError):
        R9EnvelopeVerification.model_validate(base | {"exact_s_accepted": True})
    accepted = verify_r9_inputs(encode(r9_envelope()), R9_ARTIFACT_BYTES).model_dump()
    for forged in (
        {"verdict": None},
        {"snapshot_s": None},
        {"artifact_sha256": digest("other"), "artifact_supplied": True},
        {"envelope_input": "NOT_SUPPLIED", "envelope_sha256": None},
    ):
        with pytest.raises(ValidationError):
            R9EnvelopeVerification.model_validate(accepted | forged)


def test_report_rejects_a_bound_row_that_differs_from_snapshot_s() -> None:
    loaded, universe = load_real()
    original = evaluate(
        bundle(loaded, universe, {"EURUSD": _bound_chain(universe)}),
        loaded,
        universe,
        r9_envelope=r9_envelope(),
        r9_artifact=R9_ARTIFACT_BYTES,
    ).to_json_dict()
    assert ShadowHarnessReport.model_validate(original).shadow_acceptance_passed is True
    dependent = original["dependent_acceptance"]
    forged_row = dependent["candidates"][0] | {"exact_s_id": "snap-some-other-s"}
    forged = original | {"dependent_acceptance": dependent | {"candidates": [forged_row]}}
    with pytest.raises(ValidationError):
        ShadowHarnessReport.model_validate(forged)


# --- CLI inputs ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--r9-envelope", "--r9-artifact"])
def test_cli_accepts_one_envelope_and_one_artifact_only(tmp_path: Path, flag: str) -> None:
    loaded, universe = load_real()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe)))
    extra = tmp_path / "x.bin"
    extra.write_bytes(b"x")
    argv = ["--policy", str(POLICY_PATH), "--bundle", str(bundle_path), "--out", str(tmp_path / "r.json")]
    with pytest.raises(SystemExit):
        main([*argv, flag, str(extra), flag, str(extra)])


@pytest.mark.parametrize(
    ("flag", "code"), [("--r9-envelope", "R9_ENVELOPE_UNREADABLE"), ("--r9-artifact", "R9_ARTIFACT_UNREADABLE")]
)
def test_cli_unreadable_r9_input_is_rejected(tmp_path: Path, flag: str, code: str) -> None:
    loaded, universe = load_real()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(encode(bundle(loaded, universe)))
    out = tmp_path / "report.json"
    argv = ["--policy", str(POLICY_PATH), "--bundle", str(bundle_path), "--out", str(out)]
    assert main([*argv, flag, str(tmp_path / "missing")]) == EXIT_INPUT_REJECTED
    written = json.loads(out.read_text(encoding="utf-8"))
    assert (written["rejection_code"], written["shadow_acceptance_passed"]) == (code, False)
