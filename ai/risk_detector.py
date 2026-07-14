def detect_risks(clauses, text):

    text = text.lower()

    risks = []

    # Missing mandatory clauses

    if not clauses["Salary"]:
        risks.append({
            "risk": "Salary Clause Missing",
            "severity": "High"
        })

    if not clauses["Working Hours"]:
        risks.append({
            "risk": "Working Hours Clause Missing",
            "severity": "Medium"
        })

    if not clauses["Leave Policy"]:
        risks.append({
            "risk": "Leave Policy Missing",
            "severity": "Medium"
        })

    if not clauses["Termination"]:
        risks.append({
            "risk": "Termination Clause Missing",
            "severity": "High"
        })

    if not clauses["Governing Law"]:
        risks.append({
            "risk": "Governing Law Missing",
            "severity": "Medium"
        })

    if not clauses["Confidentiality"]:
        risks.append({
            "risk": "Confidentiality Clause Missing",
            "severity": "High"
        })

    if not clauses["Non-Compete"]:
        risks.append({
            "risk": "Non-Compete Clause Missing",
            "severity": "Medium"
        })

    if not clauses["Indemnity"]:
        risks.append({
            "risk": "Indemnity Clause Missing",
            "severity": "High"
        })

    if not clauses["Force Majeure"]:
        risks.append({
            "risk": "Force Majeure Clause Missing",
            "severity": "Medium"
        })

    if not clauses["Arbitration"]:
        risks.append({
            "risk": "Arbitration Clause Missing",
            "severity": "Medium"
        })

    if not clauses["Intellectual Property"]:
        risks.append({
            "risk": "Intellectual Property Clause Missing",
            "severity": "High"
        })

    # Short termination notice

    if "30 days" in text or "30 day" in text:
        risks.append({
            "risk": "Short Termination Notice",
            "severity": "Medium"
        })

    return risks