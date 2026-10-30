import unittest

import pandas as pd

from engine.real_book import (
    account_mark,
    advance_pair,
    close_position,
    diversified,
    open_position,
    score_candidate,
    select_pairs,
)


class RealBookAccountingTest(unittest.TestCase):
    def test_long_round_trip_reconciles_cash_to_net_pnl(self):
        cash, pos = open_position(
            3000.0, "AAPL", "ensemble", "long", 100.0,
            "2026-10-27T10:00:00-04:00",
        )
        self.assertIsNotNone(pos)
        self.assertEqual(pos["shares"], 10.0)
        cash, trade = close_position(
            cash, pos, 110.0, "2026-10-28T10:00:00-04:00", "signal_off",
        )
        self.assertAlmostEqual(trade["pnl"], 100.0)
        self.assertGreater(trade["fees"], 0)
        self.assertGreater(trade["slippage"], 0)
        self.assertAlmostEqual(cash - 3000.0, trade["pnl_net"])

    def test_short_round_trip_reconciles_cash_and_borrow(self):
        cash, pos = open_position(
            3000.0, "SMCI", "macd_trend", "short", 100.0,
            "2026-10-27T10:00:00-04:00",
        )
        self.assertEqual(pos["shares"], 10)
        cash, trade = close_position(
            cash, pos, 90.0, "2026-10-29T10:00:00-04:00", "take_profit",
        )
        self.assertAlmostEqual(trade["pnl"], 100.0)
        self.assertGreater(trade["borrow"], 0)
        self.assertAlmostEqual(cash - 3000.0, trade["pnl_net"])

    def test_mark_to_liquidation_includes_entry_exit_and_borrow_costs(self):
        cash, pos = open_position(
            3000.0, "AAPL", "ensemble", "long", 100.0,
            "2026-10-27T10:00:00-04:00",
        )
        mark = account_mark(
            cash, [pos], {"AAPL": 110.0}, "2026-10-28T10:00:00-04:00",
        )
        self.assertAlmostEqual(mark["equity"] - 3000.0, mark["unrealized"])
        self.assertLess(mark["unrealized"], 100.0)
        self.assertAlmostEqual(mark["cash"], cash)

    def test_short_below_one_share_is_skipped(self):
        cash, pos = open_position(
            3000.0, "BKNG", "ensemble", "short", 1500.0,
            "2026-10-27T10:00:00-04:00",
        )
        self.assertIsNone(pos)
        self.assertEqual(cash, 3000.0)


class RealBookReplayTest(unittest.TestCase):
    def test_dropped_pair_exits_naturally_without_new_entry(self):
        state = {"cash": 3000.0, "positions": [], "eval_ts": {}}
        _, pos = open_position(
            state["cash"], "AAPL", "ensemble", "long", 100.0,
            "2026-10-27T10:00:00-04:00",
        )
        pos["last_mark_ts"] = pos["entry_date"]
        state["positions"].append(pos)
        actions = advance_pair(
            state, "AAPL|ensemble",
            ["2026-10-27T10:00:00-04:00", "2026-10-27T11:00:00-04:00"],
            [1, 0], [100.0, 105.0], set(), 70, 0.1, -0.05,
        )
        self.assertEqual(len(actions["closed"]), 1)
        self.assertEqual(actions["closed"][0]["exit_reason"], "signal_off")
        self.assertEqual(state["positions"], [])
        again = advance_pair(
            state, "AAPL|ensemble",
            ["2026-10-27T10:00:00-04:00", "2026-10-27T11:00:00-04:00"],
            [1, 0], [100.0, 105.0], set(), 70, 0.1, -0.05,
        )
        self.assertEqual(again["closed"], [])

    def test_selected_pair_opens_only_on_unseen_signal(self):
        state = {"cash": 3000.0, "positions": [], "eval_ts": {}}
        key = "AAPL|ensemble"
        actions = advance_pair(
            state, key,
            ["2026-10-27T10:00:00-04:00", "2026-10-27T11:00:00-04:00"],
            [0, 1], [100.0, 101.0], {key}, 70, 0.1, -0.05,
        )
        self.assertEqual(len(actions["opened"]), 1)
        self.assertEqual(state["positions"][0]["entry_price"], 101.0)


class RealBookSelectionTest(unittest.TestCase):
    def test_diversified_keeps_best_pair_per_symbol(self):
        rows = [
            {"symbol": "ARM", "strategy": "ensemble", "total_pnl": 30},
            {"symbol": "SMCI", "strategy": "macd_trend", "total_pnl": 20},
            {"symbol": "ARM", "strategy": "supertrend", "total_pnl": 25},
            {"symbol": "PLTR", "strategy": "macd_trend", "total_pnl": 10},
        ]
        selected = diversified(rows, 3)
        self.assertEqual([r["symbol"] for r in selected], ["ARM", "SMCI", "PLTR"])
        self.assertEqual(selected[0]["strategy"], "ensemble")

    def test_dual_window_selection_uses_net_scores_and_unique_symbols(self):
        dates = pd.date_range("2026-04-01", periods=180, freq="D")
        frame = pd.DataFrame({
            "date": dates, "open": range(100, 280), "high": range(100, 280),
            "low": range(100, 280), "close": range(100, 280), "volume": 1000,
        })
        signal = pd.Series([1, 0] * 90)
        frames = {"AAA": frame, "BBB": frame}
        sigs = {(sym, strat): signal for sym in frames for strat in ("one", "two")}
        selected = select_pairs(frames, sigs, ["one", "two"], "1h", 3,
                                as_of="2026-09-28")
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({r["symbol"] for r in selected}), 2)
        self.assertTrue(all(r["train_pnl"] > 0 for r in selected))

    def test_candidate_requires_positive_net_train_and_eight_validation_trades(self):
        train = [{"side": "long", "entry_price": 100, "exit_price": 101,
                  "entry_date": "2026-01-01", "exit_date": "2026-01-02",
                  "pnl_pct": 1.0}]
        validation = train * 8
        self.assertIsNotNone(score_candidate(train, validation))
        self.assertIsNone(score_candidate(train, validation[:7]))

    def test_candidate_scores_net_not_gross(self):
        losing = [{"side": "long", "entry_price": 100, "exit_price": 100,
                   "entry_date": "2026-01-01", "exit_date": "2026-01-02",
                   "pnl_pct": 0.0}]
        self.assertIsNone(score_candidate(losing, losing * 8))


if __name__ == "__main__":
    unittest.main()
