def calculate_risk_score(risks):

    score = 0

    for risk in risks:

        severity = risk["severity"]

        if severity == "High":
            score += 20

        elif severity == "Medium":
            score += 10

        elif severity == "Low":
            score += 5

    if score >= 80:
        overall = "High"

    elif score >= 40:
        overall = "Medium"

    else:
        overall = "Low"

    return {
        "risk_score": score,
        "overall_risk": overall
    }