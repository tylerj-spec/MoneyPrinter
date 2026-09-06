"""PR11 regressions: offline fixtures only; never a real credential or live feed."""
from __future__ import annotations

import contextlib
import copy
import getpass
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "claude/app/mp_v01/src"))
sys.path.insert(0, str(ROOT / "claude/app/mp_v01/tests"))
from adapters import massive_options as mv
from strategy.contract_selection import ContractSelectionPolicy, rank_contracts, selection_metrics
from strategy.picks import ExitPolicy, freeze, generate_picks, select_contract, verify
from strategy.variants import BY_NAME
from test_strategy_picks import opt
import export_research as research
import fetch_massive as cli
import ui_theme


def fixture_pick(policy=None):
    payload = {"AAA": {"components": {"raw": {}, "scaled": {
        "momentum_20d": .8, "momentum_60d": .6, "trend_50d": .7,
        "low_volatility": .1, "reversion": -.7}}, "option_rows": [opt()]}}
    return generate_picks("2026-03-02", payload, variants=[BY_NAME["momentum"]],
                          exit_policy=ExitPolicy(), selection_policy=policy or ContractSelectionPolicy())[0]


def frozen(picks=None):
    return freeze("2026-03-02", [fixture_pick()] if picks is None else picks,
                  exit_policy=ExitPolicy(), universe=["AAA"],
                  generated_utc="2026-03-02T19:00:00+00:00", source_files={})


class SelectionTests(unittest.TestCase):
    def test_baseline_is_default_and_cost_policy_is_opt_in(self):
        exact = {**opt(delta=.35, strike=100), "round_trip_cost_1x": 20}
        near = {**opt(delta=.39, strike=102), "round_trip_cost_1x": 5}
        self.assertEqual(select_contract([near, exact], kind="CALL", target_abs_delta=.35)[0], exact)
        selected = select_contract([exact, near], kind="CALL", target_abs_delta=.35,
                                   selection_policy=ContractSelectionPolicy(mode="cost_aware"))[0]
        self.assertEqual(selected, near)

    def test_outside_delta_band_falls_back_to_nearest_delta_before_cost(self):
        close = {**opt(delta=.50), "round_trip_cost_1x": 20}
        remote = {**opt(delta=.95), "round_trip_cost_1x": .01}
        self.assertEqual(rank_contracts([remote, close], .35,
                         ContractSelectionPolicy(mode="cost_aware"))[0], close)

    def test_ties_are_independent_of_input_order(self):
        a, b = opt(strike=99), opt(strike=101)
        for policy in (ContractSelectionPolicy(), ContractSelectionPolicy(mode="cost_aware")):
            self.assertEqual(rank_contracts([a, b], .35, policy), rank_contracts([b, a], .35, policy))

    def test_every_row_is_validated_not_just_the_first(self):
        good = opt(delta=.4)
        for key, value in (("delta", float("nan")), ("ask", float("inf")), ("bid", True),
                           ("open_interest", 4000.5), ("volume", -1), ("dte", 1),
                           ("expiration", "wrong"), ("delta", -.35), ("ask", 1), ("iv_solved", None)):
            bad = {**opt(), key: value}
            chosen, _ = select_contract([good, bad], kind="CALL", target_abs_delta=.35)
            self.assertEqual(chosen, good, (key, value))
        chosen, _ = select_contract([None, {}, good], kind="CALL", target_abs_delta=.35)
        self.assertEqual(chosen, good)

    def test_missing_keys_later_in_chain_cannot_crash_or_win(self):
        bad = opt(); del bad["ask"]
        self.assertEqual(select_contract([opt(delta=.6), bad], kind="CALL", target_abs_delta=.35)[0]["delta"], .6)

    def test_invalid_policy_is_rejected(self):
        for args in ({"delta_tolerance": float("nan")}, {"delta_tolerance": -1},
                     {"preferred_dte": True}, {"preferred_dte": 0}, {"mode": "magic"}):
            with self.assertRaises(ValueError):
                ContractSelectionPolicy(**args)

    def test_cost_and_theta_units_are_explicit(self):
        metrics = selection_metrics(opt(), .35)
        self.assertAlmostEqual(metrics["round_trip_cost_pct_premium"], 15 / 420)
        self.assertAlmostEqual(metrics["theta_pct_premium_per_day"], .05 / 4.2)
        self.assertEqual(metrics["contract_multiplier_assumption"], 100)
        self.assertEqual(metrics["quote_age_status"], "UNVERIFIED")
        self.assertEqual(selection_metrics({**opt(), "theta_per_day": .05}, .35)["theta_pct_premium_per_day"], 0)

    def test_audit_is_hashed_with_pick_and_abstentions_record_policy(self):
        record = frozen()
        audit = record["picks"][0]["selection_audit"]
        self.assertEqual(audit["eligible_count"], 1)
        self.assertEqual(audit["policy"]["mode"], "delta")
        self.assertEqual(record["picks"][0]["gate_decision"], "PASS")
        self.assertTrue(verify(record))
        audit["top_candidates"][0]["metrics"]["delta_gap"] = .99
        self.assertFalse(verify(record))
        pick = generate_picks("2026-03-02", {"AAA": {}}, variants=[BY_NAME["momentum"]],
                              exit_policy=ExitPolicy())[0]
        self.assertEqual(pick["action"], "ABSTAIN")
        self.assertEqual(pick["selection_policy"]["mode"], "delta")

    def test_existing_connector_snapshot_cannot_become_a_trade_without_quotes(self):
        doc = json.loads((ROOT / "connector_exports/optionscalc_spy_20260906.json").read_text())
        # Recorded connector marks contain no bid/ask, OI, volume or quote times.
        picked, _ = select_contract(doc["refreshed_marks"], kind="CALL", target_abs_delta=.3)
        self.assertIsNone(picked)


class ResearchTests(unittest.TestCase):
    def test_future_outcomes_never_change_exported_inputs(self):
        record = frozen()
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        before = research.build_records(record, {}, {}, now)
        rows = [{"date": f"2026-03-{day:02d}", "close": 100 + day,
                 "available_time": f"2026-03-{day + 1:02d}T13:00:00+00:00"} for day in (3, 4, 5, 6, 9)]
        after = research.build_records(record, {"AAA": rows}, {}, now)
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1][0]["result"]["status"], "OPEN")
        self.assertEqual(after[1][0]["result"]["status"], "RESOLVED")
        self.assertEqual(after[1][0]["result"]["exit_path_provenance"], "MODELLED_ONLY")
        self.assertNotIn("exit_return_on_premium", after[0][0]["features"])
        self.assertEqual(after[1][0]["outcome_available_utc"], now.isoformat())

    def test_abstentions_remain_rows_not_zero_returns(self):
        pick = {"decision_date": "2026-03-02", "ticker": "AAA", "variant": "momentum",
                "action": "ABSTAIN", "reason": "no chain"}
        ins, outs = research.build_records(frozen([pick]), {}, {}, datetime(2026, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(len(ins), 1)
        self.assertEqual(outs[0]["result"]["status"], "ABSTAIN")
        self.assertIsNone(outs[0]["result"]["exit_return_on_premium"])

    def test_tampered_and_future_records_are_rejected(self):
        record = frozen(); record["picks"][0]["composite_score"] = .99
        with self.assertRaises(ValueError):
            research.build_records(record, {}, {}, datetime(2026, 5, 1, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            research.build_records(frozen(), {}, {}, datetime(2025, 5, 1, tzinfo=timezone.utc))

    def test_legacy_original_still_verifies_but_unprotected_metadata_is_not_training_data(self):
        record = frozen()
        record["contract_version"] = "0.1.0"; del record["record_sha256"]
        self.assertTrue(verify(record))
        with self.assertRaisesRegex(ValueError, "legacy"):
            research.build_records(record, {}, {}, datetime(2026, 5, 1, tzinfo=timezone.utc))

    def test_later_bar_availability_is_not_consumed_early(self):
        rows = [{"date": "2026-03-03", "close": 200, "available_time": "2030-01-01T00:00:00Z"}]
        ins, outs = research.build_records(frozen(), {"AAA": rows}, {}, datetime(2026, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(outs[0]["result"]["status"], "OPEN")

    def test_missing_bar_timestamps_do_not_silently_bridge_a_gap(self):
        _, outs = research.build_records(frozen(), {"AAA": [{"date": "2026-03-03", "close": 200}]},
                                        {}, datetime(2026, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(outs[0]["result"]["status"], "UNKNOWN_DATA")

    def test_file_export_deduplicates_preserves_sources_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); picks = root / "picks"; picks.mkdir()
            text = json.dumps(frozen())
            (picks / "picks_one.json").write_text(text)
            (picks / "picks_copy.json").write_text(text)
            (picks / "picks_bad.json").write_text('{"broken": true}')
            first, manifest = research.export(picks, root / "data", root / "output")
            second, _ = research.export(picks, root / "data", root / "output")
            self.assertNotEqual(first, second)
            self.assertEqual(manifest["input_count"], 1)
            self.assertEqual(len(manifest["rejected_sources"]), 1)
            self.assertEqual(len(manifest["duplicate_sources_skipped"]), 1)
            self.assertEqual((picks / "picks_one.json").read_text(), text)
            for name in ("inputs.jsonl", "outcomes.jsonl", "manifest.json"):
                self.assertTrue((first / name).is_file())


class MassiveTests(unittest.TestCase):
    def _call(self, body=None, error=None):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = body
        opener = Mock()
        opener.open.side_effect = error
        opener.open.return_value = response
        with patch.dict(os.environ, {mv.TOKEN_ENV_VAR: "TEST-ONLY-SECRET"}), \
                patch.object(mv.urllib.request, "build_opener", return_value=opener):
            return mv._get(mv.CONTRACTS_PATH, {"limit": 3})

    def test_authentication_rate_limit_and_access_denial_are_distinct(self):
        for code, expected in ((401, "AUTH_FAILED"), (402, "NOT_ENTITLED"),
                               (403, "NOT_ENTITLED"), (429, "RATE_LIMITED"), (500, "HTTP_ERROR")):
            error = urllib.error.HTTPError("https://api.massive.com", code, "secret", {}, io.BytesIO(b"TEST-ONLY-SECRET"))
            with self.assertRaises(mv.MassiveError) as caught:
                self._call(error=error)
            self.assertEqual(caught.exception.kind, expected)
            self.assertNotIn("TEST-ONLY", str(caught.exception))

    def test_bad_json_shape_is_controlled_error_not_empty_success(self):
        for body in (b"not json", b"[]", b'{"status":"OK","results":{}}',
                     b'{"status":"OK","results":[null]}', b'{"status":"OK","results":null}'):
            with self.assertRaises(mv.MassiveError) as caught:
                self._call(body=body)
            self.assertEqual(caught.exception.kind, "INVALID_RESPONSE")
        self.assertEqual(self._call(body=b'{"status":"OK","results":[]}')["results"], [])

    def test_network_and_proxy_403_are_not_entitlement_answers(self):
        for error in (TimeoutError(), urllib.error.URLError("Tunnel 403 SECRET")):
            with self.assertRaises(mv.MassiveError) as caught:
                self._call(error=error)
            self.assertEqual(caught.exception.kind, "UNREACHABLE")
            self.assertNotIn("SECRET", str(caught.exception))

    def test_redirect_is_rejected_without_following_location(self):
        with self.assertRaises(mv.MassiveError) as caught:
            mv._RejectRedirects().redirect_request(None, None, 302, "Found", {}, "https://other.test")
        self.assertEqual(caught.exception.kind, "REDIRECT_REFUSED")

    def test_malformed_contract_dates_are_not_ignored_filter_verdicts(self):
        with patch.object(mv, "_get", return_value={"results": [
                {"ticker": "X", "underlying_ticker": "SPY", "expiration_date": "nope"}]}):
            steps = mv.diagnose_access("SPY", "2025-08-01", 0)
            self.assertEqual(steps[0]["verdict"], "INVALID_RESPONSE")
            self.assertEqual(len(steps), 1)

    def test_empty_control_does_not_verify_as_of(self):
        row = {"ticker": "O:SPY260116C00500000", "underlying_ticker": "SPY", "expiration_date": "2026-01-16"}
        with patch.object(mv, "_get", side_effect=[{"results": [row]}] * 3 + [{"results": []}, {"results": [row]}]):
            steps = mv.diagnose_access("SPY", "2025-08-01", 0)
        self.assertEqual(steps[-1]["verdict"], "UNVERIFIED")

    def test_invalid_args_spend_no_calls(self):
        for args in (("", "2025-08-01"), ("SPY", "20250801"), ("../SPY", "2025-08-01")):
            with patch.object(mv, "_get") as request, self.assertRaises(ValueError):
                mv.diagnose_access(*args, pause_seconds=0)
            request.assert_not_called()
        with patch.object(mv, "_get") as request, self.assertRaises(ValueError):
            list(mv._paginate(mv.CONTRACTS_PATH, {}, max_pages=0))
        request.assert_not_called()

    def test_hidden_prompt_restores_key_even_when_diagnostic_fails(self):
        for original in (None, "ORIGINAL-TEST-KEY"):
            env = {} if original is None else {mv.TOKEN_ENV_VAR: original}
            with patch.dict(os.environ, env, clear=True), patch.object(cli.getpass, "getpass", return_value="TEST-KEY"), \
                    patch.object(cli, "do_diagnose", side_effect=RuntimeError("fixture failure")):
                with self.assertRaises(RuntimeError):
                    cli.main(["--diagnose", "--prompt-key", "--as-of", "2025-08-01"])
                self.assertEqual(os.environ.get(mv.TOKEN_ENV_VAR), original)

    def test_prompt_refuses_echo_fallback_before_any_request(self):
        with patch.object(cli.getpass, "getpass", side_effect=getpass.GetPassWarning()), \
                patch.object(mv, "_get") as request, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--diagnose", "--prompt-key"]), 1)
        request.assert_not_called()

    def test_immutable_output_does_not_overwrite_prior_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            cli._write(path, {"first": True})
            with self.assertRaises(FileExistsError):
                cli._write(path, {"second": True})
            self.assertEqual(json.loads(path.read_text()), {"first": True})

    def test_bad_aggregate_timestamp_and_fractional_count_are_unknown(self):
        row = mv.normalize_agg({"t": 1e300, "c": 1, "v": 4.5}, contract_symbol="X")
        self.assertEqual(row["status"], "UNKNOWN")
        self.assertIsNone(row["volume"])


class ThemeTests(unittest.TestCase):
    def test_palette_normalisation_and_copy_isolation(self):
        for bad in (None, "unexpected", [], {}):
            self.assertEqual(ui_theme.normalise_theme(bad), "light")
        changed = ui_theme.palette_for("dark"); changed["normal"] = "bad"
        self.assertNotEqual(ui_theme.palette_for("dark")["normal"], "bad")
        self.assertNotEqual(ui_theme.palette_for("dark"), ui_theme.palette_for("light"))

    def test_settings_save_theme_but_not_credentials(self):
        try:
            import gui
        except ImportError:
            self.skipTest("tkinter unavailable")
        with tempfile.TemporaryDirectory() as tmp, patch.object(gui, "SETTINGS_FILE", Path(tmp) / "settings.json"):
            var = lambda value: types.SimpleNamespace(get=lambda: value)
            app = types.SimpleNamespace(tickers_var=var("SPY"), start_var=var("2025-01-01"),
                mie_tickers_var=var("SPY"), paths=types.SimpleNamespace(root=Path(tmp)),
                theme_var=var("dark"), massive_key_var=var("NEVER-WRITE-ME"))
            gui.MoneyPrinterGUI._save_settings(app)
            saved = gui.SETTINGS_FILE.read_text()
            self.assertEqual(json.loads(saved)["theme"], "dark")
            self.assertNotIn("NEVER-WRITE-ME", saved)
            self.assertEqual(gui.MoneyPrinterGUI._load_settings(app)["theme"], "dark")

    def test_full_application_builds_and_switches_without_losing_controls(self):
        try:
            import tkinter as tk
            probe = tk.Tk()
            probe.destroy()
        except Exception as exc:
            if os.environ.get("MONEYPRINTER_REQUIRE_GUI_TESTS") == "1":
                raise
            self.skipTest(f"Tk display unavailable: {type(exc).__name__}")
        import gui
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"MONEYPRINTER_HOME": tmp + "/outputs"}), \
                patch.object(gui, "SETTINGS_FILE", Path(tmp) / "settings.json"):
            app = gui.MoneyPrinterGUI()
            try:
                app.update_idletasks()
                for theme in ("dark", "light"):
                    app.theme_var.set(theme)
                    app._change_theme()
                    app.update_idletasks()
                    self.assertEqual(app.text.cget("background"), ui_theme.palette_for(theme)["surface"])
                    self.assertGreater(app.stop_btn.winfo_width(), 30)
                    self.assertLess(app.stop_btn.winfo_rootx() + app.stop_btn.winfo_width(),
                                    app.winfo_rootx() + app.winfo_width())
                self.assertEqual(json.loads(gui.SETTINGS_FILE.read_text())["theme"], "light")
            finally:
                app._on_close()

    def test_real_widgets_switch_both_themes_when_display_available(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
        except Exception as exc:
            if os.environ.get("MONEYPRINTER_REQUIRE_GUI_TESTS") == "1":
                raise
            self.skipTest(f"Tk display unavailable: {type(exc).__name__}")
        try:
            root.withdraw()
            text = tk.Text(root)
            readonly = ttk.Entry(root, state="readonly")
            menu = tk.Menu(root, tearoff=False)
            for theme in ("dark", "light", "dark"):
                ui_theme.apply_theme(root, theme)
                root.update_idletasks()
                self.assertEqual(text.cget("background"), ui_theme.palette_for(theme)["surface"])
                self.assertEqual(str(readonly.cget("state")), "readonly")
                self.assertEqual(str(menu.cget("foreground")), ui_theme.palette_for(theme)["normal"])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
