def generate_test_cases(summary, clauses):

    positive_tests = []
    negative_tests = []

    # Positive Test Cases
    if clauses["Salary"]:
        positive_tests.append(
            "Verify Salary clause is present and populated."
        )

    if clauses["Working Hours"]:
        positive_tests.append(
            "Verify Working Hours are specified."
        )

    if clauses["Leave Policy"]:
        positive_tests.append(
            "Verify Leave Policy exists."
        )

    if clauses["Termination"]:
        positive_tests.append(
            "Verify Termination clause exists."
        )

    if clauses["Governing Law"]:
        positive_tests.append(
            "Verify Governing Law exists."
        )

    # Negative Test Cases

    for clause, exists in clauses.items():

        if not exists:

            negative_tests.append(
                f"Verify validation fails when '{clause}' clause is missing."
            )

    return {

        "positive_test_cases": positive_tests,

        "negative_test_cases": negative_tests

    }