"""Unit tests for the detector: synthetic data, no database, no HTTP."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from vigia_analytics.anomaly import (
    DetectorConfig,
    Episode,
    binomial_tail_score,
    classify_severity,
    detect,
    score_buckets,
)

BUCKET_MINUTES = 15
CONFIG = DetectorConfig()


def make_series(n=400, seed=0, requests=200, p95=300.0, noise=0.06, error_rate=0.002):
    """A healthy service: Poisson traffic, binomial errors, log-normal p95 noise."""
    rng = np.random.default_rng(seed)
    req = rng.poisson(requests, n)
    return pd.DataFrame(
        {
            "bucket": pd.date_range("2026-01-01", periods=n, freq=f"{BUCKET_MINUTES}min", tz="UTC"),
            "requests": req,
            "errors_5xx": rng.binomial(req, error_rate),
            "p95_latency_ms": p95 * np.exp(rng.normal(0, noise, n)),
        }
    )


def test_quiet_series_raise_no_alarms():
    """20 independent healthy series (8 000 buckets): the detector stays silent."""
    episodes = [ep for seed in range(20) for ep in detect(make_series(seed=seed), CONFIG, BUCKET_MINUTES)[1]]
    assert episodes == []


def test_latency_spike_becomes_one_episode():
    series = make_series(seed=1)
    series.loc[300:305, "p95_latency_ms"] *= 3  # 6 buckets = 90 minutes

    _, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.metrics == ("latency_p95",)
    assert episode.start == series.loc[300, "bucket"]
    assert episode.end == series.loc[305, "bucket"] + pd.Timedelta(minutes=BUCKET_MINUTES)
    assert episode.buckets == 6


def test_error_burst_is_detected():
    series = make_series(seed=2)
    series.loc[250:252, "errors_5xx"] = (series.loc[250:252, "requests"] * 0.2).astype(int)

    _, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert [ep.metrics for ep in episodes] == [("error_rate",)]
    assert episodes[0].peak_error_rate == pytest.approx(0.2, abs=0.01)


def test_a_handful_of_errors_does_not_page_anyone():
    series = make_series(seed=3, error_rate=0.0)
    series.loc[200, "errors_5xx"] = CONFIG.min_errors - 1  # statistically odd, practically harmless

    scored, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert episodes == []
    assert scored.loc[200, "error_score"] > CONFIG.error_threshold  # significant, but below min_errors


def test_exact_binomial_tail_is_not_fooled_by_small_counts():
    """One error expected, five observed: unusual (p ~ 0.4 %) but not a 4-sigma event."""
    score = binomial_tail_score(np.array([5.0]), np.array([1000.0]), np.array([0.001]))[0]
    normal_approximation = (5 - 1) / np.sqrt(1000 * 0.001 * 0.999)

    assert normal_approximation > 4  # the textbook formula would page someone
    assert score == pytest.approx(stats.norm.isf(stats.binom.sf(4, 1000, 0.001)))
    assert score < 3


def test_tiny_probabilities_still_give_finite_scores():
    score = binomial_tail_score(np.array([400.0]), np.array([1000.0]), np.array([0.001]))[0]
    assert np.isfinite(score) and score > 30


def test_a_single_moderate_blip_is_not_an_episode():
    series = make_series(seed=9)
    series.loc[260, "p95_latency_ms"] *= 1.45  # one bucket, +45 %: significant but alone

    scored, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert scored.loc[260, "latency_anomaly"]  # flagged as a bucket...
    assert episodes == []  # ...but persistence is required to become an episode


def test_small_latency_wobble_is_ignored_even_if_significant():
    """Statistical significance is not enough: the jump must also matter (min_relative_increase)."""
    series = make_series(seed=4, noise=0.01)  # very stable history: tiny MAD
    series.loc[220, "p95_latency_ms"] *= 1.10  # +10 %: many MADs away, operationally irrelevant

    _, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert episodes == []


def test_nearby_anomalies_merge_and_distant_ones_split():
    series = make_series(seed=5)
    series.loc[[300, 301, 303], "p95_latency_ms"] *= 3  # one normal bucket in between: same episode
    series.loc[340, "p95_latency_ms"] *= 3  # far away: a second episode

    _, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert [ep.buckets for ep in episodes] == [3, 1]


def test_gaps_in_traffic_do_not_break_the_baseline():
    series = make_series(seed=6)
    series = series.drop(index=range(150, 190)).reset_index(drop=True)  # 10 hours without traffic
    spike_bucket = series.loc[160, "bucket"]
    series.loc[160, "p95_latency_ms"] *= 4

    _, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert [ep.start for ep in episodes] == [spike_bucket]


def test_low_volume_buckets_are_not_judged_on_latency():
    series = make_series(seed=7)
    series.loc[210, ["requests", "p95_latency_ms"]] = [4, 5_000.0]  # 4 requests: p95 is meaningless

    scored, episodes = detect(series, CONFIG, BUCKET_MINUTES)

    assert episodes == []
    assert np.isnan(scored.loc[210, "latency_score"])


def test_baseline_never_includes_the_bucket_being_scored():
    series = make_series(seed=8)
    scored = score_buckets(series, CONFIG)
    first_scored = scored["latency_baseline_ms"].first_valid_index()
    expected = series["p95_latency_ms"].iloc[:first_scored].median()
    assert scored.loc[first_scored, "latency_baseline_ms"] == pytest.approx(expected)


def test_missing_columns_are_reported():
    with pytest.raises(ValueError, match="p95_latency_ms"):
        score_buckets(pd.DataFrame({"bucket": [], "requests": [], "errors_5xx": []}), CONFIG)


def test_empty_series_returns_no_episodes():
    scored, episodes = detect(make_series(n=0), CONFIG, BUCKET_MINUTES)
    assert episodes == [] and scored.empty


def _episode(peak_latency=300.0, peak_error_rate=0.001):
    now = pd.Timestamp("2026-01-01", tz="UTC")
    return Episode(now, now, 1, ("latency_p95",), peak_latency, peak_error_rate, 5.0, 100, 1)


@pytest.mark.parametrize(
    ("episode", "tier", "expected"),
    [
        (_episode(peak_error_rate=0.15), 3, "SEV1"),  # 15 % errors is critical anywhere
        (_episode(peak_latency=1_000), 3, "SEV2"),  # 2.5x the 400 ms objective
        (_episode(peak_latency=500), 3, "SEV3"),  # mild
        (_episode(peak_latency=500), 1, "SEV2"),  # mild, but on a critical app
        (_episode(peak_latency=1_000), 1, "SEV1"),
    ],
)
def test_severity_depends_on_impact_and_tier(episode, tier, expected):
    assert classify_severity(episode, tier=tier, slo_latency_p95_ms=400) == expected
