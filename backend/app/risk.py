def calculate_response_window(
    fire_eta_minutes: int,
    response_time_minutes: int,
    safety_buffer_minutes: int
):
    return (
        fire_eta_minutes
        - response_time_minutes
        - safety_buffer_minutes
    )


def calculate_priority(
    risk_score: float,
    response_window_minutes: int
):
    if response_window_minutes <= 0:
        return "ALTERNATIVE RESPONSE"

    if risk_score >= 0.8:
        return "CRITICAL"

    if risk_score >= 0.5:
        return "HIGH"

    return "MODERATE"