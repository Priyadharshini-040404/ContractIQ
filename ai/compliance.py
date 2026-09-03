def compliance_score(clauses):

    total = len(clauses)

    present = sum(clauses.values())

    score = round((present / total) * 100)

    if score >= 90:

        health = "Excellent"

    elif score >= 75:

        health = "Good"

    elif score >= 50:

        health = "Average"

    else:

        health = "Poor"

    return {

        "compliance_score": score,

        "contract_health": health

    }