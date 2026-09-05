from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "claude" / "app" / "mp_v01" / "tests"))

from harness import test, run_all           # noqa: E402
import dashboard as dash                     # noqa: E402


PICKS = {
    "schema": "moneyprinter.picks",
    "decision_date": "2026-09-04",
    "universe": ["MSFT", "SPY"],
    "n_picks": 1, "n_abstentions": 1,
    "picks_sha256": "abc123def456abc123def456",
    "exit_policy": {"horizon_trading_days": 5},
    "exit_policy_plain_english": ["PRIMARY: mark to market after 5 trading days."],
    "picks": [
        {"variant": "momentum", "ticker": "MSFT", "action": "PAPER_LONG_CALL",
         "composite_score": 0.41, "entry_fill_estimate": 13.64,
         "breakeven_move_pct": 0.0013, "gate_decision": "PASS",
         "gate_failed": ["missing:independent_events"],
         "rationale": "The momentum variant scores MSFT +0.41 (bullish).",
         "contract": {"expiration": "2026-10-16", "strike": 466.1, "type": "CALL",
                      "dte": 42, "delta": 0.39, "iv_solved": 0.339, "bid": 13.23,
                      "ask": 13.64, "relative_spread": 0.031,
                      "open_interest": 5000, "volume": 900}},
        {"variant": "reversion", "ticker": "SPY", "action": "ABSTAIN",
         "reason": "conviction 0.03 below the variant's 0.20 floor"},
    ],
}

BACKTEST = {
    "observations": 1836, "sessions": 700,
    "first_decision": "2023-04-27", "last_decision": "2025-08-29",
    "settings": {"train_sessions": 180, "test_sessions": 30,
                 "label_horizon_sessions": 5, "n_permutations": 200},
    "splits": [{"index": 0}, {"index": 1}],
    "rank_ic": [
        {"component": "momentum_20d", "mean": 0.026, "stdev": 0.21,
         "hit_rate": 0.56, "t_stat": 0.5, "per_fold": [0.1, -0.05]},
        {"component": "reversion", "mean": -0.031, "stdev": 0.19,
         "hit_rate": 0.5, "t_stat": -0.6, "per_fold": [0.1, -0.2]},
    ],
    "variants": [{
        "variant": "momentum", "description": "Trend continuation.",
        "n_train": 8181, "n_test": 1440,
        "report": {"strategy_name": "momentum", "accuracy": 0.5632,
                   "majority_class_rate": 0.5556, "permutation_mean": 0.5343,
                   "permutation_std": 0.0119, "z_vs_noise": 2.42,
                   "permutation_p_value": 0.0165,
                   "verdict": "SIGNAL_CANDIDATE (z=2.42, p=0.017) - NOT validated.",
                   "folds": [{"index": 0}, {"index": 1}]},
    }],
}


def _render(picks=None, bt=None) -> str:
    return dash.render(picks, Path("picks_x.json") if picks else None,
                       bt, Path("backtest_x.json") if bt else None)


@test
def the_page_carries_no_external_references_so_it_works_offline():
    """The whole reason this is a file and not a window. One fetched asset and
    it degrades on the machine it exists to serve."""
    html = _render(PICKS, BACKTEST)
    for bad in ("http://", "https://", "<script", "src=", "@import", "cdn"):
        assert bad not in html.lower(), f"external reference: {bad}"

@test
def a_pick_appears_with_its_contract_its_gate_verdict_and_its_full_rationale():
    html = _render(PICKS, BACKTEST)
    assert "MSFT" in html and "PAPER_LONG_CALL" in html
    assert "466.1 CALL" in html
    assert "GATE PASS" in html, "the gate verdict must be visible, not buried"
    assert "The momentum variant scores MSFT +0.41 (bullish)." in html
    assert "missing:independent_events" in html, "gate failures are part of the record"

@test
def abstentions_are_shown_rather_than_hidden():
    """A variant that abstains every run is telling you something about the
    variant. Rendering only the proposals would throw that away."""
    html = _render(PICKS, BACKTEST)
    assert "Abstentions (1)" in html
    assert "conviction 0.03 below the variant" in html

@test
def the_page_states_that_it_is_not_an_options_backtest():
    """The single most misleading thing this page could imply. Yahoo has no
    historical chains, so an options equity curve would be fabricated."""
    html = _render(PICKS, BACKTEST)
    assert "not an options backtest" in html.lower()
    assert "fabricated" in html.lower()

@test
def accuracy_is_never_shown_without_the_two_numbers_that_make_it_readable():
    """54% is unreadable alone: it might be an edge, or it might be worse than
    guessing the common answer. Both references travel with it."""
    html = _render(PICKS, BACKTEST)
    assert "0.5632" in html, "accuracy"
    assert "0.5556" in html, "majority-class rate"
    assert "0.5343" in html, "noise floor"
    assert "majority-class rate" in html.lower()
    assert "noise floor" in html.lower()

@test
def the_verdict_travels_with_every_result():
    html = _render(PICKS, BACKTEST)
    assert "SIGNAL_CANDIDATE" in html and "NOT validated" in html

@test
def rank_ic_reports_the_fold_spread_not_just_the_mean():
    """A mean IC whose sign does not hold across folds is no edge measured
    several times. The page has to make that visible."""
    html = _render(PICKS, BACKTEST)
    assert "momentum_20d" in html
    assert "sign held" in html.lower()
    assert "+0.026" in html or "+0.0260" in html

@test
def paper_only_is_stated_on_the_page_itself_not_only_in_the_source():
    html = _render(PICKS, BACKTEST)
    assert "paper/simulation only" in html.lower()
    assert "no live order path" in html.lower()

@test
def an_empty_state_names_the_button_that_fills_it():
    """A blank section that does not say why is a bug report waiting to happen."""
    html = _render(None, None)
    assert "Generate paper picks" in html
    assert "Backtest the signal" in html

@test
def content_from_a_pick_file_is_escaped_rather_than_injected():
    """Pick files are generated, but they carry ticker strings and rationale text
    that end up in the DOM. Escaping is cheap; a page that silently renders
    markup from its data is not something to reason about later."""
    hostile = json.loads(json.dumps(PICKS))
    hostile["picks"][0]["rationale"] = '<script>alert(1)</script> & "quoted"'
    hostile["picks"][0]["ticker"] = "<b>X</b>"
    html = _render(hostile, BACKTEST)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>X</b>" not in html

@test
def a_number_that_is_missing_renders_as_a_dash_not_as_zero():
    """A blank is honest. A zero is a measurement nobody took."""
    thin = json.loads(json.dumps(BACKTEST))
    thin["variants"][0]["report"]["accuracy"] = None
    thin["rank_ic"][0]["mean"] = None
    html = _render(PICKS, thin)
    assert "—" in html
    assert dash.num(None, ".4f") == "—"
    assert dash.num(float("nan"), ".4f") == "—"

@test
def the_quant_map_section_names_the_stage_that_is_actually_missing():
    """The map's value is that it makes the gap obvious. Here the gap is stage
    IV: every component is built and tested, and not one has a stated reason a
    market would pay for it."""
    html = _render(PICKS, BACKTEST)
    assert "Edge mechanisms" in html
    assert "not started" in html.lower()

@test
def the_file_written_to_disk_is_the_page_that_was_rendered():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "picks").mkdir()
        (tmp / "bt").mkdir()
        (tmp / "picks" / "picks_2026-09-04_1.json").write_text(json.dumps(PICKS))
        (tmp / "bt" / "backtest_1.json").write_text(json.dumps(BACKTEST))
        out = tmp / "d.html"
        rc = dash.main(["--picks-dir", str(tmp / "picks"), "--backtest-dir", str(tmp / "bt"),
                        "--out", str(out)])
        assert rc == 0
        html = out.read_text(encoding="utf-8")
        assert "MSFT" in html and "SIGNAL_CANDIDATE" in html

@test
def the_newest_pick_file_is_the_one_rendered():
    """Timestamped filenames sort lexicographically, which is the property the
    'newest' rule leans on. Worth pinning rather than assuming."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old = json.loads(json.dumps(PICKS)); old["decision_date"] = "2026-01-01"
        new = json.loads(json.dumps(PICKS)); new["decision_date"] = "2026-12-31"
        (tmp / "picks_2026-01-01_20260101-000000.json").write_text(json.dumps(old))
        (tmp / "picks_2026-12-31_20261231-000000.json").write_text(json.dumps(new))
        assert dash.newest(tmp, "picks_*.json").name.startswith("picks_2026-12-31")

@test
def a_missing_folder_is_an_empty_page_not_a_crash():
    assert dash.newest(Path("/definitely/not/here"), "picks_*.json") is None


if __name__ == "__main__":
    sys.exit(0 if run_all("DASHBOARD (offline HTML)") else 1)
