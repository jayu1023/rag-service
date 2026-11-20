"""The W&B offline-run verifier.

An offline W&B run writes to a binary transaction log, so "the directory
exists" is not evidence anything was logged. These pin the check that is.
"""

from evals.wandb_check import EXPECTED_KEYS, check


def make_run(tmp_path, keys, name="offline-run-20260101_000000-abc123"):
    run = tmp_path / name
    run.mkdir()
    (run / "run-abc123.wandb").write_bytes(b"".join(k.encode() + b"\x00" for k in keys))
    return run


def test_a_run_with_every_metric_passes(tmp_path):
    ok, missing = check(make_run(tmp_path, EXPECTED_KEYS))
    assert ok
    assert missing == []


def test_a_run_missing_a_metric_fails_and_names_it(tmp_path):
    ok, missing = check(make_run(tmp_path, [k for k in EXPECTED_KEYS if k != "mrr_at_5"]))
    assert not ok
    assert missing == ["mrr_at_5"]


def test_a_run_directory_with_no_transaction_log_fails(tmp_path):
    run = tmp_path / "offline-run-empty"
    run.mkdir()
    ok, missing = check(run)
    assert not ok
    assert "no .wandb" in missing[0]


def test_the_per_question_table_is_part_of_the_contract(tmp_path):
    """The aggregate is already in the eval table; the per-question miss list
    is the reason a W&B run is worth opening at all."""
    assert "per_question" in EXPECTED_KEYS
    ok, missing = check(make_run(tmp_path, [k for k in EXPECTED_KEYS if k != "per_question"]))
    assert not ok and missing == ["per_question"]
