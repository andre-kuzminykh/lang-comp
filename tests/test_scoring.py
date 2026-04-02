"""Tests for accint.scoring — Bayesian Beta-posterior scoring."""

import math
import time
import pytest

from accint.scoring import BetaScore, thompson_sample, decay_confidence, rank_entries


class TestBetaScore:
    def test_initial_state(self):
        bs = BetaScore()
        assert bs.alpha == 1.0
        assert bs.beta == 1.0
        assert bs.mean == 0.5  # uniform prior
        assert bs.evidence == 0.0
        assert bs.confidence == 0.0

    def test_record_success(self):
        bs = BetaScore()
        bs.record_success()
        assert bs.alpha == 2.0
        assert bs.beta == 1.0
        assert bs.mean == pytest.approx(2 / 3)

    def test_record_failure(self):
        bs = BetaScore()
        bs.record_failure()
        assert bs.alpha == 1.0
        assert bs.beta == 2.0
        assert bs.mean == pytest.approx(1 / 3)

    def test_weighted_update(self):
        bs = BetaScore()
        bs.record_success(weight=0.5)
        assert bs.alpha == 1.5
        bs.record_failure(weight=2.0)
        assert bs.beta == 3.0

    def test_confidence_increases_with_evidence(self):
        bs = BetaScore()
        c0 = bs.confidence
        bs.record_success()
        bs.record_success()
        bs.record_failure()
        assert bs.confidence > c0
        assert bs.evidence == 3.0

    def test_record_usage(self):
        bs = BetaScore()
        assert bs.usage_count == 0
        bs.record_usage()
        bs.record_usage()
        assert bs.usage_count == 2
        assert bs.last_used > 0

    def test_eight_out_of_ten_beats_one_out_of_one(self):
        """Paper example: 8/10 should rank above 1/1."""
        strong = BetaScore(alpha=9.0, beta=3.0)  # 8 successes, 2 failures + prior
        weak = BetaScore(alpha=2.0, beta=1.0)     # 1 success, 0 failures + prior
        assert strong.confidence > weak.confidence
        assert strong.evidence > weak.evidence

    def test_serialization_roundtrip(self):
        bs = BetaScore(alpha=5.0, beta=3.0, last_used=100.0, last_updated=200.0, usage_count=7)
        d = bs.to_dict()
        bs2 = BetaScore.from_dict(d)
        assert bs2.alpha == 5.0
        assert bs2.beta == 3.0
        assert bs2.last_used == 100.0
        assert bs2.last_updated == 200.0
        assert bs2.usage_count == 7

    def test_from_dict_defaults(self):
        bs = BetaScore.from_dict({})
        assert bs.alpha == 1.0
        assert bs.beta == 1.0


class TestThompsonSampling:
    def test_returns_float_in_range(self):
        bs = BetaScore(alpha=5.0, beta=2.0)
        for _ in range(100):
            sample = thompson_sample(bs)
            assert 0.0 <= sample <= 1.0

    def test_high_score_samples_higher(self):
        good = BetaScore(alpha=50.0, beta=2.0)
        bad = BetaScore(alpha=2.0, beta=50.0)
        good_samples = [thompson_sample(good) for _ in range(200)]
        bad_samples = [thompson_sample(bad) for _ in range(200)]
        assert sum(good_samples) / len(good_samples) > sum(bad_samples) / len(bad_samples)


class TestDecayConfidence:
    def test_no_decay_when_fresh(self):
        now = time.time()
        bs = BetaScore(alpha=5.0, beta=2.0, last_updated=now)
        decay_confidence(bs, now=now)
        assert bs.alpha == pytest.approx(5.0)
        assert bs.beta == pytest.approx(2.0)

    def test_decay_toward_prior(self):
        old_time = time.time() - 60 * 86400  # 60 days ago
        bs = BetaScore(alpha=10.0, beta=3.0, last_updated=old_time)
        decay_confidence(bs, now=time.time(), half_life_days=30.0)
        # After 2 half-lives, evidence should be ~25% of original
        assert bs.alpha < 10.0
        assert bs.alpha > 1.0  # Still above prior
        assert bs.beta < 3.0
        assert bs.beta > 1.0

    def test_no_decay_if_never_updated(self):
        bs = BetaScore(alpha=5.0, beta=3.0, last_updated=0)
        decay_confidence(bs)
        assert bs.alpha == 5.0  # unchanged


class TestRankEntries:
    def test_ranks_by_thompson_sample(self):
        entries = [
            {"id": "good", "score": BetaScore(alpha=50.0, beta=2.0).to_dict()},
            {"id": "bad", "score": BetaScore(alpha=2.0, beta=50.0).to_dict()},
            {"id": "mid", "score": BetaScore(alpha=10.0, beta=10.0).to_dict()},
        ]
        # Run many times — "good" should be first most often
        first_counts = {"good": 0, "bad": 0, "mid": 0}
        for _ in range(100):
            ranked = rank_entries(entries, top_k=3)
            first_counts[ranked[0]["id"]] += 1
        assert first_counts["good"] > first_counts["bad"]

    def test_top_k_limits_output(self):
        entries = [{"id": f"e{i}", "score": BetaScore().to_dict()} for i in range(20)]
        ranked = rank_entries(entries, top_k=5)
        assert len(ranked) == 5

    def test_empty_input(self):
        assert rank_entries([], top_k=5) == []
