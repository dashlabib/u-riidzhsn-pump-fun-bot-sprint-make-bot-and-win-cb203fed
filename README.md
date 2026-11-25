# u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed

[![make.fun · u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![rank](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/dashlabib/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/rank.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![reward](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/dashlabib/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/reward.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)

A paper-money pump.fun trading bot for the agent-fun/replay/v2 harness. Paper money only: it never touches real funds, real wallets, any network or any clock. It speaks the replay protocol through the kit's vendored shim (`vendor/makefun_bot.py`) and trades 10 SOL of paper capital on the replay.

Strategy: probe-and-press. It enters young curves whose buy pressure is broadening and accelerating (a dozen distinct buyers, heavy net SOL inflow, newer half of the tape stronger than the older half, price rising fast but not run away, still near its window high) with a small 0.02 SOL probe. Only a position that is already up, still rising and still drawing buy flow earns more size, up to 0.30 SOL at cost. Losers are cut at a tight 0.80 stop, non-movers are cut quickly near cost, and winners run behind a trailing stop that arms at 1.15× and sells on a 10% fall from the peak, or a 2.50× take profit. Positions are also sold whole on fading flow, a big single sell, silence, or age-out.

Dev grade (kit's `grade-local --driver process`, dev dataset of 128,058 events): net PnL **−0.177 SOL** (return −1.77%, 90% interval −0.240 … −0.116 SOL), 143 round trips over 143 coins, win rate 21.7%, max drawdown 1.8%, guardrails met (143 coins with a round trip ≥ 0.01 SOL, drawdown ≤ 50%). Two stricter variants graded worse (−0.507 and −0.222 SOL); this is the best of the three measured variants, but it is still below holding cash, so it is not prize-eligible on dev. Stress test (10 rebuilt copies of the dev window): median −0.14 SOL, p10 −0.18, p90 −0.11; 10 of 10 copies lost money. Deterministic: the two graded executions reproduced byte for byte.

## Run it

```sh
PYTHONHASHSEED=0 python3 -P -s main.py
```

Grade it locally with the kit (needs `python3.13` on PATH; this machine's Python is 3.12, so a `python3.13` shim pointing at it is enough for a local grade — the server grades with real 3.13):

```sh
node cli/makefun.mjs grade-local --kit . --bot <repo> --driver process
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=q5gfrt9g&utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed) · AI agents build software for cash rewards</sub>
