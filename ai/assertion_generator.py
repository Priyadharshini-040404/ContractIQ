def generate_assertions(summary, clauses, risk_score, compliance_score):

    assertions = []

    # Summary Assertions
    for key, value in summary.items():

        assertions.append({

            "field": key,

            "assertion": f"{key} should not be empty.",

            "expected": value

        })

    # Clause Assertions
    for clause, exists in clauses.items():

        assertions.append({

            "field": clause,

            "assertion": f"{clause} clause should exist.",

            "expected": exists

        })

    # Risk Assertion
    assertions.append({

        "field": "risk_score",

        "assertion": "Risk score should be calculated.",

        "expected": risk_score

    })

    # Compliance Assertion
    assertions.append({

        "field": "compliance_score",

        "assertion": "Compliance score should be calculated.",

        "expected": compliance_score

    })

    return assertions