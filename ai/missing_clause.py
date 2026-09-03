def find_missing_clauses(clauses):

    present = []
    missing = []

    for clause, exists in clauses.items():

        if exists:
            present.append(clause)
        else:
            missing.append(clause)

    return {
        "present_clauses": present,
        "missing_clauses": missing
    }