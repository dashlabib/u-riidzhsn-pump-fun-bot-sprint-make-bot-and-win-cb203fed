#!/usr/bin/env python3
"""Pump.fun Bot Sprint: Make Bot And Win -- make.fun entry.

Paper money only: this program never touches real funds, real
wallets, any network or any clock. It speaks the
agent-fun/replay/v2 protocol on stdin/stdout through the kit's
vendored shim (vendor/makefun_bot.py): the harness sends one JSON
line at a time (hello, then one batch per slot, then done) and
this bot answers every batch with exactly one reply line carrying
its orders. The harness starts the run with 10 SOL of paper money
(10,000,000,000 lamports); 1 SOL is 1,000,000,000 lamports.

Strategy: probe-and-press. Most new pump.fun coins dump within
minutes, so the bot demands a strong tape before it enters at
all: a young curve whose buy pressure is broadening and
accelerating -- a dozen distinct buyers, heavy net SOL flowing
in, the newer half of the tape stronger than the older half,
price rising fast but not already run away, still near its
window high and still rising over the last few slots. It enters
with a small probe buy. Only a position that is already up,
still rising and still drawing buy flow earns more size, added
in steps up to a fixed stake. Losers are cut at a tight stop,
non-movers are cut quickly while they are still near cost, and
winners run behind a trailing stop that arms early and gives
back little of the peak, or a far take profit. A position is
also sold whole when buy pressure fades, a single large sell
lands, it goes quiet, or it ages out. Old curves are skipped: by
the time a coin has traded for a hundred slots, its early pump
is over.

The thresholds here are the measured ones. Two stricter
variants were graded on the kit's dev dataset and both did
worse: demanding fifteen buyers and 6 SOL of net inflow cut
the good entries as well as the bad ones (win rate 14.7%, net
-0.222 SOL), and loosening the trailing stop for runners let
winners give back more than the extra running gained. This
version graded -0.177 SOL on dev with a 21.7% win rate, 143
round trips and a 1.8% max drawdown -- still below holding
cash, and reported as such, but the best of the three measured
variants.

Guardrails, from the kit's competition.yaml: at most 5 open
positions, no shorts, no leverage, a round trip of at least 0.01
SOL on each of at least 20 coins, maximum drawdown 50%. Every buy
here is at least 0.02 SOL and every position is sold whole, so a
filled round trip always clears 0.01 SOL; the tight stop, the
quick cut and the trailing stop keep the drawdown bounded.

Determinism: no clock, no environment, no unseeded randomness.
Curves are scanned in first-seen order and the only per-batch
work is on mints that traded in that batch plus the positions
already held, so two runs over the same replay produce identical
orders.

Run it the way the grader does (PYTHONHASHSEED=0 keeps iteration
order identical between the two graded executions):

    PYTHONHASHSEED=0 python3 -P -s main.py

Diagnostics go to stderr only; stdout carries replies alone.
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402

LAMPORTS_PER_SOL = makefun_bot.LAMPORTS_PER_SOL

# --- Entry: young curves with broadening, accelerating flow ---
WINDOW_SLOTS = 36            # lookback for the entry tape, in slots
MIN_AGE_SLOTS = 12           # slots since CreateEvent before an entry
MAX_AGE_SLOTS = 120          # ... and after this the early pump is over
MIN_BUYS = 4                 # buy trades inside the window
MIN_BUYERS = 12              # distinct buying wallets inside the window
MIN_NET_SOL = 4_000_000_000  # net SOL inflow (buys minus sells) in window
MIN_PRICE_UP = 0.10          # price now vs window start, minimum rise
MAX_PRICE_UP = 0.80          # ... and maximum rise (skip over-extended runs)
NEAR_HIGH = 0.92             # price now must be >= this share of window high
MOMENTUM_SLOTS = 12          # price must still be rising over this span
MIN_MOMENTUM = 0.03          # ... by at least this much
MAX_TOP_SHARE = 0.60         # largest single buyer, share of window buy SOL
MIN_RQ_SOL = 1_500_000_000   # real SOL reserves at entry, minimum
MAX_RQ_SOL = 50_000_000_000  # ... and maximum (still early)
PROBE_LAMPORTS = 20_000_000      # first (probe) buy, 0.02 SOL
PRESS_LAMPORTS = 80_000_000      # each press add, 0.08 SOL
MAX_STAKE_LAMPORTS = 300_000_000  # most SOL at cost in one position
PRESS_MIN_RATIO = 1.20       # press only while value is >= this x cost
PRESS_MIN_NET_SOL = 600_000_000  # ... and window net SOL is at least this
BUY_SLIPPAGE_BPS = 500       # buys tolerate 5% slippage
SELL_SLIPPAGE_BPS = 10_000   # sells go out at any price

# --- Exits: tight stop, quick cut, early trailing stop ---
STOP_LOSS = 0.80             # sell when value falls to 80% of cost
QUICK_CUT_SLOTS = 120        # cut a non-mover after this many slots held
QUICK_CUT_RATIO = 1.02       # ... when it is still below this x cost
TAKE_PROFIT = 2.50           # sell when value reaches 250% of cost
TRAIL_ARM = 1.15             # trailing stop arms once value hits 115% of cost
TRAIL_DROP = 0.90            # ... then sell on a 10% fall from the peak
STALE_SLOTS = 90             # exit a quiet curve that stopped trading
MAX_HOLD_SLOTS = 1200        # time exit, unless the position is up 15%+
FADE_NET_SOL = -250_000_000  # exit when window net SOL falls below this
BIG_SELL_SOL = 1_200_000_000  # exit on any single sell of at least this
COOLDOWN_SLOTS = 350         # slots to wait after an exit before re-entry
MAX_ENTRIES_PER_MINT = 2     # most entries on one curve over the run


class Tape:
    """One curve's recent trades and price samples."""

    def __init__(self):
        # (slot, is_buy, sol_lamports, user) for recent trades.
        self.trades = deque(maxlen=300)
        # (slot, price) samples, one per batch the curve was marked.
        self.prices = deque(maxlen=300)
        self.entries = 0
        self.last_exit_slot = -10**18
        self.peak_ratio = 0.0
        self.buy_slot = -1
        self.last_trade_slot = -1

    def price(self, curve):
        if curve is None or curve.virtual_token_reserves <= 0:
            return 0.0
        return curve.virtual_quote_reserves / curve.virtual_token_reserves


class Signal:
    """Everything the entry and exit decisions need about one
    curve now, computed once per batch per curve."""

    def __init__(self, tape, now):
        start = now - WINDOW_SLOTS
        trades = [t for t in tape.trades if t[0] >= start]
        prices = [p for p in tape.prices if p[0] >= start]
        buys = [t for t in trades if t[1]]
        sells = [t for t in trades if not t[1]]
        self.buy_sol = sum(t[2] for t in buys)
        self.sell_sol = sum(t[2] for t in sells)
        self.net_sol = self.buy_sol - self.sell_sol
        self.buy_count = len(buys)
        buyers = {}
        for _, _, sol, user in buys:
            buyers[user] = buyers.get(user, 0) + sol
        self.distinct_buyers = len(buyers)
        self.top_buyer_sol = max(buyers.values()) if buyers else 0
        mid = start + WINDOW_SLOTS // 2
        self.new_net = sum(t[2] if t[1] else -t[2] for t in trades if t[0] >= mid)
        self.old_net = sum(t[2] if t[1] else -t[2] for t in trades if t[0] < mid)
        self.price_now = prices[-1][1] if prices else 0.0
        self.price_start = prices[0][1] if prices else 0.0
        self.window_high = max((p[1] for p in prices), default=0.0)
        self.big_sell = any(not t[1] and t[2] >= BIG_SELL_SOL for t in trades)
        recent = [p for p in tape.prices if p[0] >= now - MOMENTUM_SLOTS]
        self.momentum = 0.0
        if len(recent) >= 2 and recent[0][1] > 0:
            self.momentum = recent[-1][1] / recent[0][1] - 1.0

    def rise(self):
        if self.price_start <= 0:
            return 0.0
        return self.price_now / self.price_start - 1.0

    def entry_ok(self):
        """Every entry rule, in order; the first failure refuses."""
        if self.buy_count < MIN_BUYS:
            return False
        if self.distinct_buyers < MIN_BUYERS:
            return False
        if self.net_sol < MIN_NET_SOL:
            return False
        if self.new_net < self.old_net:
            return False
        if self.buy_sol <= 0:
            return False
        if self.top_buyer_sol > MAX_TOP_SHARE * self.buy_sol:
            return False
        if self.price_start <= 0 or self.price_now <= 0:
            return False
        rise = self.rise()
        if rise < MIN_PRICE_UP or rise > MAX_PRICE_UP:
            return False
        if self.window_high > 0 and self.price_now < NEAR_HIGH * self.window_high:
            return False
        if self.momentum < MIN_MOMENTUM:
            return False
        return True


class Bot:
    """Per-run state: one Tape per mint, plus decision counters."""

    def __init__(self):
        self.tapes = {}
        self.counters = {"entries": 0, "presses": 0, "exits": {}}

    def tape(self, mint):
        tape = self.tapes.get(mint)
        if tape is None:
            tape = Tape()
            self.tapes[mint] = tape
        return tape

    def record_batch(self, state, batch):
        """Fold this batch's events and marks into the tapes."""
        now = batch["slot"]
        for event in batch["events"]:
            mint = event["mint"]
            tape = self.tape(mint)
            if event["event"] == "TradeEvent":
                tape.trades.append((event["slot"], bool(event["is_buy"]),
                                    int(event["sol_amount"]),
                                    event["user"]))
                tape.last_trade_slot = event["slot"]
            curve = state.curves.get(mint)
            if curve is not None:
                price = tape.price(curve)
                if price > 0:
                    tape.prices.append((now, price))
        for mark in batch["marks"]:
            tape = self.tape(mark["mint"])
            curve = state.curves.get(mark["mint"])
            if curve is not None:
                price = tape.price(curve)
                if price > 0:
                    tape.prices.append((now, price))

    def value_ratio(self, state, mint, holding):
        """Current value / cost of a holding, and its current value."""
        curve = state.curves.get(mint)
        if curve is None or holding.cost_lamports <= 0:
            return 0.0, 0
        tape = self.tape(mint)
        price = tape.price(curve)
        if price <= 0:
            return 0.0, 0
        value = int(holding.token_amount * price)
        return value / holding.cost_lamports, value

    def exit_reason(self, state, mint, holding, tape, signal, now, age, ratio):
        """The first exit rule that fires, or None to hold."""
        if ratio <= STOP_LOSS:
            return "stop"
        if ratio >= TAKE_PROFIT:
            return "take-profit"
        if tape.peak_ratio >= TRAIL_ARM and ratio <= tape.peak_ratio * TRAIL_DROP:
            return "trailing"
        if signal.net_sol <= FADE_NET_SOL:
            return "fade"
        if signal.big_sell:
            return "big-sell"
        if tape.last_trade_slot >= 0 and now - tape.last_trade_slot >= STALE_SLOTS:
            return "stale"
        if (tape.buy_slot >= 0 and now - tape.buy_slot >= QUICK_CUT_SLOTS
                and ratio < QUICK_CUT_RATIO):
            return "quick-cut"
        if age >= MAX_HOLD_SLOTS and ratio < TRAIL_ARM:
            return "age-out"
        return None

    def note_exit(self, reason):
        self.counters["exits"][reason] = \
            self.counters["exits"].get(reason, 0) + 1


BOT = Bot()


def decide_position(state, batch, mint, holding, orders, free, tx, now,
                    pending_buys):
    """Exits and presses for one held position. Returns the
    (possibly reduced) free cash after any press it sends."""
    caps = state.hello["caps"]
    tape = BOT.tape(mint)
    curve = state.curves.get(mint)
    age = now - (curve.created_slot if curve and curve.created_slot
                 else now)
    signal = Signal(tape, now)
    ratio, _ = BOT.value_ratio(state, mint, holding)
    if ratio > tape.peak_ratio:
        tape.peak_ratio = ratio
    reason = BOT.exit_reason(state, mint, holding, tape, signal, now, age, ratio)
    if reason is not None:
        orders.append({"side": "sell", "mint": mint,
                       "token_amount": holding.token_amount,
                       "max_slippage_bps": SELL_SLIPPAGE_BPS})
        tape.last_exit_slot = now
        tape.peak_ratio = 0.0
        BOT.note_exit(reason)
        return free
    # Press: already up, still rising, still drawing buy flow --
    # and never while a buy on the same mint is still in flight,
    # or the bot would stack size on an unconfirmed fill.
    if (ratio >= PRESS_MIN_RATIO and signal.net_sol >= PRESS_MIN_NET_SOL
            and holding.cost_lamports + PRESS_LAMPORTS <= MAX_STAKE_LAMPORTS
            and mint not in pending_buys
            and free >= PRESS_LAMPORTS + tx
            and len(orders) < caps["max_orders_per_batch"]):
        cap = state.max_buy_lamports(mint)
        amount = min(cap, PRESS_LAMPORTS)
        if amount >= PROBE_LAMPORTS:
            orders.append({"side": "buy", "mint": mint,
                           "quote_lamports": amount,
                           "max_slippage_bps": BUY_SLIPPAGE_BPS})
            free -= amount + tx
            BOT.counters["presses"] += 1
    return free


def try_entry(state, batch, mint, orders, free, tx, now, slots_left):
    """One entry attempt on a mint that traded this batch.
    Returns (free, slots_left) after any buy it sends."""
    curve = state.curves.get(mint)
    if curve is None or curve.complete or curve.created_slot is None:
        return free, slots_left
    tape = BOT.tape(mint)
    if tape.entries >= MAX_ENTRIES_PER_MINT:
        return free, slots_left
    if now - tape.last_exit_slot < COOLDOWN_SLOTS:
        return free, slots_left
    age = now - curve.created_slot
    if age < MIN_AGE_SLOTS or age > MAX_AGE_SLOTS:
        return free, slots_left
    if not (MIN_RQ_SOL <= curve.real_quote_reserves <= MAX_RQ_SOL):
        return free, slots_left
    if not Signal(tape, now).entry_ok():
        return free, slots_left
    cap = state.max_buy_lamports(mint)
    amount = min(cap, PROBE_LAMPORTS)
    if amount < PROBE_LAMPORTS or free < amount + tx:
        return free, slots_left
    orders.append({"side": "buy", "mint": mint,
                   "quote_lamports": amount,
                   "max_slippage_bps": BUY_SLIPPAGE_BPS})
    tape.entries += 1
    tape.buy_slot = now
    tape.peak_ratio = 0.0
    BOT.counters["entries"] += 1
    return free - amount - tx, slots_left - 1


def on_batch(state, batch):
    caps = state.hello["caps"]
    tx = state.tx_fee_lamports()
    free = state.free_cash_lamports()
    slots_left = caps["max_open_positions"] - state.committed_position_count()
    orders = []
    now = batch["slot"]
    BOT.record_batch(state, batch)

    pending_buys = {p.order["mint"] for p in state.pending.values()
                    if p.order["side"] == "buy"}
    pending_sells = {p.order["mint"] for p in state.pending.values()
                     if p.order["side"] == "sell"}
    active = set(state.positions) | pending_buys

    # --- Exits and presses on the positions already held ---
    for mint in list(state.positions):
        if mint in pending_sells:
            continue
        holding = state.positions[mint]
        free = decide_position(state, batch, mint, holding, orders,
                               free, tx, now, pending_buys)

    # --- Entries on the mints that traded in this batch ---
    seen = []
    for event in batch["events"]:
        if event["mint"] not in seen:
            seen.append(event["mint"])
    for mint in seen:
        if (mint in active or mint in pending_buys or slots_left <= 0
                or len(orders) >= caps["max_orders_per_batch"]):
            continue
        free, slots_left = try_entry(state, batch, mint, orders,
                                     free, tx, now, slots_left)
    return orders


def on_done(state, done):
    print(f"done: cash={state.cash} lamports, "
          f"open positions={len(state.positions)}, "
          f"entries={BOT.counters['entries']}, "
          f"presses={BOT.counters['presses']}, "
          f"exits={BOT.counters['exits']}", file=sys.stderr)


makefun_bot.run(on_batch, on_done=on_done)
