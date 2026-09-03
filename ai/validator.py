from ai.clause_detector import detect_clauses
from ai.missing_clause import find_missing_clauses
from ai.risk_detector import detect_risks
from ai.risk_score import calculate_risk_score
from ai.summary import generate_summary
from ai.compliance import compliance_score
from ai.test_case_generator import generate_test_cases
from ai.assertion_generator import generate_assertions
from ai.postman_generator import generate_postman_collection


def validate_contract(text):

    summary = generate_summary(text)

    clauses = detect_clauses(text)

    missing = find_missing_clauses(clauses)

    risks = detect_risks(clauses, text)

    score = calculate_risk_score(risks)

    compliance = compliance_score(clauses)

    test_cases = generate_test_cases(summary, clauses)

    assertions = generate_assertions(
        summary,
        clauses,
        score["risk_score"],
        compliance["compliance_score"]
    )

    postman_file = generate_postman_collection()

    return {

        "summary": summary,

        "clauses": clauses,

        "present_clauses": missing["present_clauses"],

        "missing_clauses": missing["missing_clauses"],

        "risks": risks,

        "risk_score": score["risk_score"],

        "overall_risk": score["overall_risk"],

        "compliance_score": compliance["compliance_score"],

        "contract_health": compliance["contract_health"],

        "positive_test_cases": test_cases["positive_test_cases"],

        "negative_test_cases": test_cases["negative_test_cases"],

        "assertions": assertions,

        "postman_collection_file": postman_file

    }