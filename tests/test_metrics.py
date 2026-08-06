"""§10 Metrics: pure unit tests with known inputs. No LLM in the loop."""

import math

import pytest

from insight_engine.analysis import metrics


def test_pe_ratio_known_value():
    assert metrics.pe_ratio(100.0, 5.0) == 20.0


def test_pe_ratio_zero_eps_is_undefined():
    assert metrics.pe_ratio(100.0, 0.0) is None


def test_net_margin():
    assert metrics.net_margin(25000, 100000) == 0.25


def test_gross_margin():
    assert metrics.gross_margin(45000, 100000) == 0.45


def test_margin_zero_revenue_is_undefined():
    assert metrics.net_margin(10, 0) is None
    assert metrics.gross_margin(10, 0) is None


def test_growth_rate():
    assert metrics.growth_rate(80000, 100000) == pytest.approx(0.25)


def test_growth_rate_zero_base_is_undefined():
    assert metrics.growth_rate(0, 100) is None


def test_simple_returns():
    assert metrics.simple_returns([100, 110, 121]) == pytest.approx([0.10, 0.10])


def test_volatility_constant_returns_is_zero():
    # two identical returns -> sample stdev 0
    assert metrics.daily_volatility([100, 110, 121]) == pytest.approx(0.0)


def test_volatility_known_value():
    # closes [100, 110, 99] -> returns [0.10, -0.10] -> sample stdev sqrt(0.02)
    assert metrics.daily_volatility([100, 110, 99]) == pytest.approx(math.sqrt(0.02))


def test_volatility_needs_at_least_two_returns():
    assert metrics.daily_volatility([100, 110]) is None
    assert metrics.daily_volatility([100]) is None
