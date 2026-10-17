import pytest

from app.risk import calculate_priority, calculate_response_window


@pytest.mark.parametrize(
    "fire_eta,response_time,safety_buffer,expected",
    [(95, 40, 20, 35), (60, 40, 20, 0), (50, 40, 20, -10)],
)
def test_response_window_subtracts_travel_and_buffer(
    fire_eta, response_time, safety_buffer, expected
):
    assert calculate_response_window(fire_eta, response_time, safety_buffer) == expected


@pytest.mark.parametrize(
    "score,window,expected",
    [
        (0.8, 35, "CRITICAL"),
        (0.79, 35, "HIGH"),
        (0.5, 35, "HIGH"),
        (0.49, 35, "MODERATE"),
        (0.91, 0, "ALTERNATIVE RESPONSE"),
        (0.91, -1, "ALTERNATIVE RESPONSE"),
        (0.49, 0, "ALTERNATIVE RESPONSE"),
    ],
)
def test_priority_boundaries_and_nonpositive_window_precedence(score, window, expected):
    assert calculate_priority(score, window) == expected
