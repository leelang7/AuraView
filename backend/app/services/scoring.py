def calculate_risk(event_duration, obstacle_type, signal_state, count):
    score = 0

    if event_duration >= 3:
        score += 3
    if event_duration >= 5:
        score += 2

    if obstacle_type in ["bus", "truck", "top_truck", "van"]:
        score += 2

    if signal_state == "stop-And-Remain":
        score += 3
    elif signal_state == "protected-Movement-Allowed":
        score += 1

    score += min(count, 10)

    return score