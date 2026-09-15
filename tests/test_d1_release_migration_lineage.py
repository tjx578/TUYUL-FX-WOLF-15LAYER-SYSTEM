"""The composed release must include both independent schema capabilities."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_admission_and_d0_are_both_required_before_composed_head() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(root / "storage/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260915_01"]
    merge = scripts.get_revision("20260908_01")
    assert merge is not None
    assert isinstance(merge.down_revision, tuple)
    assert set(merge.down_revision) == {"20260826_01", "20260905_01"}
    for starting_head, missing_parent in (("20260826_01", "20260905_01"), ("20260905_01", "20260826_01")):
        # Match Alembic's upgrade planning, which includes the missing branch.
        revisions = {
            revision.revision
            for revision in scripts.iterate_revisions("20260908_01", starting_head, implicit_base=True)
        }
        assert missing_parent in revisions
        assert "20260908_01" in revisions


def test_current_release_upgrade_requires_both_published_histories() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(root / "storage/migrations"))
    scripts = ScriptDirectory.from_config(config)
    for starting_head, missing_parent in (
        ("20260908_01", "20260911_01"),
        ("20260911_01", "20260908_01"),
    ):
        revisions = {
            revision.revision for revision in scripts.iterate_revisions("head", starting_head, implicit_base=True)
        }
        assert missing_parent in revisions
        assert "20260915_01" in revisions
