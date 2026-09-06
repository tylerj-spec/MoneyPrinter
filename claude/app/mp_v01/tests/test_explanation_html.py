import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from strategy.picks import freeze, ExitPolicy
from pick_review import render


def test_review_rejects_tampering_and_escapes_text():
    record = freeze("2026-03-02", [{"ticker": "<script>x</script>", "variant": "v",
                    "action": "ABSTAIN", "reason": "<img src=x onerror=x>", "weights": {}}],
                    exit_policy=ExitPolicy(), universe=[], generated_utc="2026-03-02T19:00:00Z", source_files={})
    page = render(record, "test.json")
    assert "<details>" in page and "&lt;script&gt;" in page and "<img src=x" not in page
    record["picks"][0]["reason"] = "modified"
    try:
        render(record, "test.json")
    except ValueError:
        pass
    else:
        assert False, "edited records must not acquire an explanation"
