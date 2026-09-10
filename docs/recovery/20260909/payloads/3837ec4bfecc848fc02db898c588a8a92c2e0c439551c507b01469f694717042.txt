"""The composed release must include both independent schema capabilities."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_admission_and_d0_are_both_required_before_composed_head() -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(root / "storage/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260908_01"]
    merge = scripts.get_revision("20260908_01")
    assert merge is not None
    assert set(merge.down_revision) == {"20260826_01", "20260905_01"}
    for starting_head, missing_parent in (("20260826_01", "20260905_01"), ("20260905_01", "20260826_01")):
        # Match Alembic's upgrade planning, which includes the missing branch.
        revisions = {
            revision.revision
            for revision in scripts.iterate_revisions("20260908_01", starting_head, implicit_base=True)
        }
        assert missing_parent in revisions
        assert "20260908_01" in revisions
