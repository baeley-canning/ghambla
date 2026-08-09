"""Test the claim that momentum's drawdowns are a correlation problem.

Control matters: any 10 US large caps are correlated. The question is whether
the momentum book is MORE correlated than an arbitrary book of the same size,
drawn from the same universe on the same day.
"""
import datetime as dt, math, random, statistics, sys
sys.path.insert(0, "src")
from ghambla.store.store import FeatureStore
from ghambla.signals.momentum import MomentumSignal
from ghambla.portfolio import equal_weight_top_n
from ghambla.diagnose import average_pairwise_correlation, diversification_ratio
from ghambla.vol import annualised_vol

HOLD = 21
store = FeatureStore("data/market.db")
sig = MomentumSignal()
rng = random.Random(20260809)

dates = store.trading_dates(dt.date(2018, 1, 1), dt.date(2026, 8, 1))
rebalances = dates[::HOLD][:-1]

def book_stats(symbols, day_idx):
    """Correlation and diversification of an equal-weighted book over HOLD days."""
    window = dates[day_idx: day_idx + HOLD + 1]
    if len(window) < HOLD + 1:
        return None
    hist = store.bars_as_of(window[-1], symbols, lookback=HOLD + 1)
    rets, vols = {}, {}
    for s in symbols:
        bars = [b for b in hist.get(s, []) if b.date >= window[0]]
        closes = [b.adj_close for b in bars]
        if len(closes) < HOLD + 1 or any(c <= 0 for c in closes):
            continue
        r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        rets[s], vols[s] = r, statistics.stdev(r) * math.sqrt(252)
    if len(rets) < 3:
        return None
    corr = average_pairwise_correlation(rets)
    n = len(rets)
    w = {s: 1 / n for s in rets}
    port = [sum(rets[s][i] for s in rets) / n for i in range(HOLD)]
    pvol = statistics.stdev(port) * math.sqrt(252)
    return corr, diversification_ratio(w, vols, pvol)

mom_c, mom_d, rnd_c, rnd_d = [], [], [], []
for k, day in enumerate(rebalances):
    i = dates.index(day)
    universe = store.universe_as_of(day)
    if len(universe) < 50:
        continue
    scores = sig.score(store, day, universe)
    picks = [t.symbol for t in equal_weight_top_n(scores, 10)]
    if len(picks) < 3:
        continue
    for src, cs, ds in ((picks, mom_c, mom_d),
                        (rng.sample(sorted(universe), 10), rnd_c, rnd_d)):
        out = book_stats(src, i)
        if out and out[0] is not None:
            cs.append(out[0])
            if out[1] is not None:
                ds.append(out[1])
    if k % 20 == 0:
        print(f"  {day} ... {len(mom_c)} books measured", flush=True)

def show(name, c, d):
    print(f"\n{name}")
    print(f"  avg pairwise correlation : {statistics.mean(c):+.3f}   "
          f"(median {statistics.median(c):+.3f}, n={len(c)})")
    print(f"  diversification ratio    : {statistics.mean(d):.3f}   "
          f"(1.00 = one bet, higher = diversified)")

show("MOMENTUM top-10 book", mom_c, mom_d)
show("RANDOM 10 from same universe (control)", rnd_c, rnd_d)
print(f"\nCorrelation excess of momentum over random: "
      f"{statistics.mean(mom_c) - statistics.mean(rnd_c):+.3f}")
store.close()
