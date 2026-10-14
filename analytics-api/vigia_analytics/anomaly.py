"""Statistical anomaly detection over bucketed request metrics.

Pure functions: no database, no HTTP. They take a DataFrame and return a
DataFrame, which makes them trivial to unit test with synthetic data.

Two signals, two statistical tools
----------------------------------
1. Latency (p95 per bucket) is a continuous measurement with outliers, so it
   uses a *robust* z-score: distance to the median of the previous N buckets,
   measured in MADs (median absolute deviation) instead of standard deviations.
   A single huge spike barely moves a median, but it drags a mean a lot.

       z = 0.6745 * (x - median) / MAD          (Iglewicz and Hoaglin, 1993)

   0.6745 is the 75th percentile of the standard normal distribution; it makes
   the MAD comparable to a standard deviation when the data is Gaussian.

2. Server errors are *counts*: with n requests and a normal error probability
   p0, the number of errors follows a Binomial(n, p0). The detector computes
   the exact tail probability P(X >= observed) and converts it into an
   equivalent z-score. The usual normal approximation (k - n*p0) / sqrt(n*p0*(1-p0))
   is badly wrong when n*p0 is around 1: it turns five errors where one was
   expected into a "4 sigma" event, while the exact probability is about 0.4 %.

Both baselines only look at buckets *before* the current one (``shift(1)``),
otherwise an incident would be part of its own baseline and hide itself.

Finally, an alarm needs persistence: a lone anomalous bucket only becomes an
episode if its score is very high. Real incidents last; noise does not.

Calibration
-----------
The defaults in ``DetectorConfig`` were chosen by simulation, not by taste:
``scripts/calibrate_detector.py`` replays ten days of synthetic traffic many
times with different random seeds and counts misses and false alarms for each
candidate setting. Two findings:

* Most false alarms came from night buckets of small applications, where the
  p95 of 40 requests is really the second slowest call. Judging latency only in
  buckets with at least 100 requests cut them from 18 to 4 in 40 runs.
* With that rule, a latency threshold of 4.5 instead of the textbook 3.5 left
  a single false alarm in 2 400 application-days, and no incident was missed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import special, stats

MAD_TO_SIGMA = 0.6745
REQUIRED_COLUMNS = {"bucket", "requests", "errors_5xx", "p95_latency_ms"}


@dataclass(frozen=True)
class DetectorConfig:
    window: int = 16  # trailing buckets in the latency baseline (16 x 15 min = 4 h)
    latency_threshold: float = 4.5  # robust z-score above which latency is anomalous (calibrated)
    min_relative_increase: float = 1.3  # ...and p95 must also be 30 % above its baseline
    error_threshold: float = 4.0  # equivalent z-score of the exact binomial tail
    min_requests: int = 100  # a p95 needs about 5 requests above it, or it is one slow call (calibrated)
    min_errors: int = 5  # never open an incident for fewer errors than this
    max_gap_buckets: int = 1  # anomalous buckets this close belong to one episode
    min_episode_buckets: int = 2  # a lone anomalous bucket is usually noise...
    strong_score: float = 10.0  # ...unless its score is at least this high


@dataclass(frozen=True)
class Episode:
    """A run of consecutive anomalous buckets: one problem, one incident."""

    start: pd.Timestamp
    end: pd.Timestamp
    buckets: int
    metrics: tuple[str, ...]
    peak_latency_p95_ms: float
    peak_error_rate: float
    max_score: float
    requests: int
    errors_5xx: int


def _mad(values: np.ndarray) -> float:
    """Median absolute deviation, ignoring missing values."""
    median = np.nanmedian(values)
    return float(np.nanmedian(np.abs(values - median)))


def binomial_tail_score(errors: np.ndarray, requests: np.ndarray, p0: np.ndarray) -> np.ndarray:
    """Equivalent one-sided z-score of P(X >= errors) for X ~ Binomial(requests, p0).

    Works in log space (logsf + ndtri_exp) so that astronomically small
    probabilities still give finite scores instead of overflowing.
    """
    errors = np.asarray(errors, dtype=float)
    requests = np.asarray(requests, dtype=float)
    p0 = np.asarray(p0, dtype=float)
    scores = np.full(errors.shape, np.nan)
    valid = np.isfinite(p0) & (requests > 0) & (errors > 0)
    k, n, p = errors[valid], requests[valid], p0[valid]
    log_tail = stats.binom.logsf(k - 1, n, p)
    # When the tail is so small that even logsf underflows to -inf, the first
    # term of the tail (the pmf at k) dominates it: a conservative lower bound.
    log_tail = np.where(np.isneginf(log_tail), stats.binom.logpmf(k, n, p), log_tail)
    scores[valid] = -special.ndtri_exp(log_tail)
    scores[np.isfinite(p0) & (requests > 0) & (errors == 0)] = 0.0  # nothing unusual about zero errors
    return scores


def score_buckets(series: pd.DataFrame, config: DetectorConfig) -> pd.DataFrame:
    """Return a copy of ``series`` with baselines, scores and anomaly flags.

    Buckets without traffic must simply be absent: baselines are computed over
    the previous *observed* buckets, so a gap in traffic does not break them.
    """
    missing = REQUIRED_COLUMNS - set(series.columns)
    if missing:
        raise ValueError(f"series is missing columns: {sorted(missing)}")

    df = series.sort_values("bucket").reset_index(drop=True).copy()
    requests = df["requests"].astype(float)
    errors = df["errors_5xx"].astype(float)
    df["error_rate"] = errors / requests.where(requests > 0)
    min_periods = max(3, config.window // 2)

    # 1) Latency: robust z-score of p95 against the previous `window` buckets
    latency = df["p95_latency_ms"].astype(float).where(requests >= config.min_requests)
    rolling = latency.rolling(config.window, min_periods=min_periods)
    baseline = rolling.median().shift(1)
    mad = rolling.apply(_mad, raw=True).shift(1)
    # A perfectly flat history has MAD = 0; a floor of 5 % of the baseline
    # (and at least 1 ms) avoids dividing by ~0 and flagging tiny wiggles.
    mad_floor = np.maximum(0.05 * baseline, 1.0)
    df["latency_baseline_ms"] = baseline
    df["latency_score"] = MAD_TO_SIGMA * (latency - baseline) / np.maximum(mad, mad_floor)

    # 2) Errors: exact binomial tail against the pooled error rate of a longer
    #    trailing window. "+1 / +2" is Laplace smoothing (pseudo-counts), so the
    #    baseline rate is never exactly zero even after hours without errors.
    long_window = 4 * config.window
    error_sum = errors.rolling(long_window, min_periods=min_periods).sum().shift(1)
    request_sum = requests.rolling(long_window, min_periods=min_periods).sum().shift(1)
    p0 = (error_sum + 1) / (request_sum + 2)
    df["error_baseline_rate"] = p0
    df["error_score"] = binomial_tail_score(errors.to_numpy(), requests.to_numpy(), p0.to_numpy())

    # 3) Flags. Each one needs statistical significance (the score) AND practical
    #    significance (an effect big enough to matter to a customer).
    #    Comparisons against NaN are False, so warm-up buckets never fire.
    df["latency_anomaly"] = (df["latency_score"] > config.latency_threshold) & (
        latency >= config.min_relative_increase * baseline
    )
    df["error_anomaly"] = (
        (df["error_score"] > config.error_threshold) & (errors >= config.min_errors) & (df["error_rate"] >= 2 * p0)
    )
    df["anomalous"] = df["latency_anomaly"] | df["error_anomaly"]
    return df


def group_episodes(scored: pd.DataFrame, bucket: pd.Timedelta, config: DetectorConfig) -> list[Episode]:
    """Merge nearby anomalous buckets into episodes and drop one-bucket noise.

    Classic pandas idiom: mark where a new group starts (gap too large), then
    ``cumsum()`` turns those marks into group ids for ``groupby``.
    """
    flagged = scored[scored["anomalous"]]
    if flagged.empty:
        return []

    starts_new_episode = flagged["bucket"].diff() > bucket * (config.max_gap_buckets + 1)
    episode_ids = starts_new_episode.cumsum()

    episodes: list[Episode] = []
    for _, group in flagged.groupby(episode_ids, sort=True):
        scores = np.concatenate([group["latency_score"].to_numpy(float), group["error_score"].to_numpy(float)])
        max_score = float(np.nanmax(scores))
        if len(group) < config.min_episode_buckets and max_score < config.strong_score:
            continue  # short and weak: most likely noise

        metrics = []
        if group["latency_anomaly"].any():
            metrics.append("latency_p95")
        if group["error_anomaly"].any():
            metrics.append("error_rate")
        episodes.append(
            Episode(
                start=group["bucket"].min(),
                end=group["bucket"].max() + bucket,
                buckets=len(group),
                metrics=tuple(metrics),
                peak_latency_p95_ms=float(group["p95_latency_ms"].max()),
                peak_error_rate=float(group["error_rate"].max()),
                max_score=max_score,
                requests=int(group["requests"].sum()),
                errors_5xx=int(group["errors_5xx"].sum()),
            )
        )
    return episodes


def detect(series: pd.DataFrame, config: DetectorConfig, bucket_minutes: int) -> tuple[pd.DataFrame, list[Episode]]:
    """Score every bucket and group the anomalous ones into episodes."""
    if series.empty:
        return series.assign(anomalous=pd.Series(dtype=bool)), []
    scored = score_buckets(series, config)
    episodes = group_episodes(scored, pd.Timedelta(minutes=bucket_minutes), config)
    return scored, episodes


def classify_severity(episode: Episode, tier: int, slo_latency_p95_ms: int) -> str:
    """Business impact, not statistics, decides how loud the alarm is."""
    latency_ratio = episode.peak_latency_p95_ms / slo_latency_p95_ms
    if episode.peak_error_rate >= 0.10 or latency_ratio >= 4:
        level = 1
    elif episode.peak_error_rate >= 0.02 or latency_ratio >= 2:
        level = 2
    else:
        level = 3
    if tier == 1 and level > 1:
        level -= 1  # business-critical applications escalate one level
    return f"SEV{level}"
