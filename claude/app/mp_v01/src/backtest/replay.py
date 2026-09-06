"""Observed-quote replay with decision-time features and separate later execution.

Input timestamps and provenance must come from the user's licensed dataset.
Internal validation cannot independently attest vendor history. The built-in
demo is explicitly synthetic and never supplies performance evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Iterable
from common.validation import digest, iso, number, utc, whole
from common.timezones import US_EASTERN
from strategy import components
from strategy.picks import generate_picks, freeze
from strategy.variants import BY_NAME
from strategy.contract_selection import ContractSelectionPolicy
from options.greeks import implied_volatility, greeks, years_to_expiry
from paper.quotes import quote_quality, simulate_fill


def eligible_observations(rows: Iterable[dict], *, decision_utc: str, contract_id: str) -> list[dict]:
    cutoff, out = utc(decision_utc), []
    for row in rows:
        if row.get("contract_id") != contract_id:
            continue
        try:
            observed, available = utc(row["observed_utc"]), utc(row["available_utc"])
        except (ValueError, TypeError, KeyError):
            continue
        if observed <= available <= cutoff:
            out.append(row)
    return sorted(out, key=lambda r: (utc(r["observed_utc"]), utc(r["available_utc"])))


def latest_predecision_quote(rows, *, decision_utc, contract_id):
    eligible = eligible_observations(rows, decision_utc=decision_utc, contract_id=contract_id)
    return eligible[-1] if eligible else None


def replay_fill(quote, *, side, multiplier=100, submitted_utc=None, execution_utc=None, limit_price=None):
    if quote is None or submitted_utc is None or execution_utc is None:
        return {"status": "NO_FILL", "reason": "post_submission_observation_required"}
    if type(multiplier) is not int or multiplier != 100:
        return {"status": "NO_FILL", "reason": "unsupported_multiplier"}
    if side not in {"BUY", "SELL"} or limit_price is None:
        return {"status": "NO_FILL", "reason": "explicit_side_and_limit_required"}
    return simulate_fill(quote, side=side, quantity=1, limit_price=limit_price,
                         submitted_utc=submitted_utc, execution_utc=execution_utc)


def _session(sessions, when, known_by):
    matches = [s for s in sessions if utc(s["open_utc"]) <= utc(when) < utc(s["close_utc"])]
    if len(matches) != 1:
        raise ValueError("one explicit exchange session must cover the decision/exit")
    s = matches[0]
    if not s.get("source") or utc(s["available_utc"]) > utc(known_by):
        raise ValueError("session schedule was not known at decision time")
    return s


def _bars(rows, cutoff):
    selected = {}
    for row in rows:
        observed, available = utc(row["event_time"]), utc(row["available_time"])
        if available < observed:
            raise ValueError("bar availability precedes its event")
        if available > utc(cutoff):
            continue
        number(row["close"], "close", minimum=.000001)
        number(row["daily_total_return"], "return", minimum=-1)
        day = date.fromisoformat(row["date"]).isoformat()
        if day != observed.astimezone(US_EASTERN).date().isoformat():
            raise ValueError("bar date and event time disagree")
        old = selected.get(day)
        if old and utc(old["available_time"]) == available and old != row:
            raise ValueError("conflicting bar vintages at the same availability time")
        if not old or utc(old["available_time"]) < available:
            selected[day] = row
    return [selected[d] for d in sorted(selected)]


@dataclass(frozen=True)
class ScheduledExit:
    exit_utc: str

    def to_dict(self):
        return {"mode": "SCHEDULED_EXIT_ONLY", "exit_utc": iso(self.exit_utc),
                "exit_limit": .01, "execution_window_seconds": 60, "latency_seconds": 1}

    def describe(self):
        return ["Submit a simulated sell at the pre-registered exit time, minimum price $0.01.",
                "Use a new observed bid within 60 seconds; no quote means unresolved, never a modelled fill.",
                "This replay does NOT implement intraday profit-target or stop-loss orders."]


def _first_fill(quotes, cid, when, side, limit, session):
    end = min(utc(when) + timedelta(seconds=60), utc(session["close_utc"]))
    for q in sorted(quotes, key=lambda r: (utc(r["available_utc"]), utc(r["observed_utc"]))):
        if q.get("contract_id") != cid or not utc(when) < utc(q["available_utc"]) < end:
            continue
        result = replay_fill(q, side=side, submitted_utc=when, execution_utc=q["available_utc"], limit_price=limit)
        if result["status"] == "FILLED":
            return result
    return {"status": "NO_FILL", "reason": "no_eligible_post_submission_quote_in_window"}


def run_replay(dataset: dict, *, policies=("delta", "cost_aware"), generated_utc=None) -> dict:
    if dataset.get("schema") != "moneyprinter.replay.v1":
        raise ValueError("unsupported replay dataset")
    if dataset.get("provenance") not in {"SYNTHETIC_DEMO", "USER_SUPPLIED_QUOTE_HISTORY"} or not dataset.get("source"):
        raise ValueError("explicit dataset source and provenance required")
    if not policies or len(set(policies)) != len(policies):
        raise ValueError("unique nonempty policy set required")
    for mode in policies:
        ContractSelectionPolicy(mode=mode)
    quotes = dataset["quotes"]
    for q in quotes:
        utc(q["available_utc"])
        utc(q["observed_utc"])
    specs = dataset["contracts"]
    if len({s["contract_id"] for s in specs}) != len(specs):
        raise ValueError("duplicate contract identity")
    identities = [(s["underlying"], s["expiration"], s["type"], s["strike"]) for s in specs]
    if len(set(identities)) != len(identities):
        raise ValueError("ambiguous contract specifications")
    quote_keys = {}
    for q in quotes:
        key = (q["contract_id"], iso(q["observed_utc"]), iso(q["available_utc"]))
        if key in quote_keys and quote_keys[key] != digest(q):
            raise ValueError("conflicting simultaneous quote versions")
        quote_keys[key] = digest(q)
    documents, outcomes, input_views = [], [], {}
    generated_utc = generated_utc or datetime.now(timezone.utc).isoformat()
    for decision in sorted(dataset["decisions"], key=lambda x: utc(x["decision_utc"])):
        cutoff = iso(decision["decision_utc"])
        exit_at = iso(decision["exit_utc"])
        if utc(exit_at) <= utc(cutoff):
            raise ValueError("planned exit must follow the decision")
        entry_session = _session(dataset["sessions"], cutoff, cutoff)
        exit_session = _session(dataset["sessions"], exit_at, cutoff)
        ticker = decision["ticker"]
        day = utc(cutoff).astimezone(US_EASTERN).date().isoformat()
        bars = _bars(dataset["bars"].get(ticker, []), cutoff)
        comps = components.compute(bars, day, cutoff)
        spot_q = latest_predecision_quote(dataset["underlying_quotes"], decision_utc=cutoff, contract_id=ticker)
        spot = None
        if spot_q and (utc(cutoff) - utc(spot_q["observed_utc"])).total_seconds() <= 60:
            bid = number(spot_q["bid"], "underlying bid", minimum=.000001)
            ask = number(spot_q["ask"], "underlying ask", minimum=bid)
            if spot_q.get("feed_type") == "CONSOLIDATED" and spot_q.get("delayed") is False:
                spot = (bid + ask) / 2
        rate_doc = dataset["rate"]
        if utc(rate_doc["available_utc"]) > utc(cutoff):
            raise ValueError("rate assumption was not known by the decision")
        rate = number(rate_doc["value"], "rate")
        rows, views = [], []
        for spec in specs:
            if spec["underlying"] != ticker or max(utc(spec["known_utc"]), utc(spec["listed_utc"])) > utc(cutoff):
                continue
            if (spec.get("standard_contract") is not True or spec.get("premium_multiplier") != 100
                    or spec.get("deliverable_shares") != 100 or not spec.get("spec_source")):
                continue
            q = latest_predecision_quote(quotes, decision_utc=cutoff, contract_id=spec["contract_id"])
            if not q or not quote_quality(q, decision_utc=cutoff)[0] or spot is None:
                continue
            if max(utc(q["oi_available_utc"]), utc(q["volume_available_utc"])) > utc(cutoff):
                continue
            T = years_to_expiry(day, spec["expiration"])
            if T is None or spec["type"] not in {"CALL", "PUT"}:
                continue
            strike = number(spec["strike"], "strike", minimum=.000001)
            mid = (q["bid"] + q["ask"]) / 2
            iv = implied_volatility(mid, spot, strike, T, rate, q=0.0, kind=spec["type"])
            if iv is None:
                continue
            g = greeks(spot, strike, T, rate, iv, 0.0, spec["type"])
            rows.append({"contract_symbol": spec["contract_id"], "type": spec["type"], "strike": strike,
                "expiration": spec["expiration"], "dte": round(T * 365), "bid": q["bid"], "ask": q["ask"], "mid": mid,
                "delta": g.delta, "gamma": g.gamma, "theta_per_day": g.theta, "vega": g.vega, "iv_solved": iv,
                "relative_spread": (q["ask"] - q["bid"]) / mid,
                "open_interest": whole(q["open_interest"], "OI"), "volume": whole(q["volume"], "volume"),
                "round_trip_cost_1x": (q["ask"] - q["bid"]) * 100 + 1.60,
                "underlying_close": spot, "underlying_close_date": day,
                "model_status": "OK", "liquidity_screen": "PASS"})
            views.append({"specification": spec, "quote": q})
        view = {"bars": bars, "contracts_and_quotes": views, "spot_quote": spot_q, "rate": rate_doc,
                "decision": decision, "entry_session": entry_session, "exit_session": exit_session}
        visible_hash = digest(view)
        input_views[visible_hash] = view
        for mode in policies:
            variant = BY_NAME[decision.get("variant", "momentum")]
            picks = generate_picks(day, {ticker: {"components": comps, "option_rows": rows}},
                                   variants=(variant,), exit_policy=ScheduledExit(exit_at),
                                   selection_policy=ContractSelectionPolicy(mode=mode))
            for pick in picks:
                pick.update(run_mode="HISTORICAL_REPLAY", decision_utc=cutoff, planned_exit_utc=exit_at)
                pick["valuation_assumptions"] = "European Black-Scholes Greeks, zero dividends; not an American-option valuation guarantee"
                result = {"decision_utc": cutoff, "ticker": ticker, "variant": variant.name,
                          "selection_policy": mode, "dataset_provenance": dataset["provenance"],
                          "comparison_type": "PAIRED_COUNTERFACTUAL_NOT_PORTFOLIO", "net_pnl": None}
                if pick["action"] == "ABSTAIN":
                    result.update(status="ABSTAIN", reason=pick["reason"])
                else:
                    chosen = next(v["specification"] for v in views
                                  if v["specification"]["type"] == pick["contract"]["type"]
                                  and v["specification"]["expiration"] == pick["contract"]["expiration"]
                                  and v["specification"]["strike"] == pick["contract"]["strike"])
                    cid = chosen["contract_id"]
                    pick["contract"]["contract_id"] = cid
                    entry = _first_fill(quotes, cid, cutoff, "BUY", pick["contract"]["ask"], entry_session)
                    result["entry"] = entry
                    if entry["status"] != "FILLED":
                        result["status"] = "NO_ENTRY_FILL"
                    else:
                        exit_fill = _first_fill(quotes, cid, exit_at, "SELL", .01, exit_session)
                        result["exit"] = exit_fill
                        result["status"] = "RESOLVED" if exit_fill["status"] == "FILLED" else "UNRESOLVED"
                        if result["status"] == "RESOLVED":
                            result["net_pnl"] = round((exit_fill["price"] - entry["price"]) * 100 - 1.60, 2)
                            result["return_on_premium"] = result["net_pnl"] / (entry["price"] * 100)
                outcomes.append(result)
            record = freeze(day, picks, exit_policy=ScheduledExit(exit_at), universe=[ticker], generated_utc=generated_utc,
                source_files={"visible_input_sha256": visible_hash, "decision_inputs_file": "inputs_" + visible_hash + ".json",
                              "dataset_source": dataset["source"], "dataset_provenance": dataset["provenance"],
                              "decision_cutoff_utc": cutoff, "execution_mode": "ONE_CONTRACT_COUNTERFACTUAL",
                              "entry_iv_pricing": "EUROPEAN_BS_ZERO_DIVIDENDS"})
            for index, outcome in enumerate(outcomes[-len(picks):]):
                outcome["row_id"] = record["record_sha256"] + ":" + str(index)
            documents.append(record)
    return {"schema": "moneyprinter.replay.result.v1", "dataset_sha256": digest(dataset),
            "dataset_provenance": dataset["provenance"], "generated_utc": iso(generated_utc),
            "pick_records": documents, "outcomes": outcomes, "decision_input_views": input_views,
            "warning": "Observed quotes are not guaranteed fills. No portfolio aggregation, stop/target simulation or predictive edge is claimed."}
