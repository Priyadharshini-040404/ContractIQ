def detect_clauses(text):

    text = text.lower()

    clauses = {
        "Salary": False,
        "Working Hours": False,
        "Leave Policy": False,
        "Termination": False,
        "Governing Law": False,
        "Confidentiality": False,
        "Non-Compete": False,
        "Indemnity": False,
        "Force Majeure": False,
        "Arbitration": False,
        "Intellectual Property": False
    }

    # Salary
    if any(keyword in text for keyword in [
        "salary",
        "annual salary",
        "monthly salary",
        "compensation",
        "remuneration",
        "pay"
    ]):
        clauses["Salary"] = True

    # Working Hours
    if any(keyword in text for keyword in [
        "working hours",
        "work hours",
        "office hours",
        "business hours",
        "9:00 am",
        "6:00 pm"
    ]):
        clauses["Working Hours"] = True

    # Leave Policy
    if any(keyword in text for keyword in [
        "leave policy",
        "annual leave",
        "paid leave",
        "casual leave",
        "sick leave",
        "vacation"
    ]):
        clauses["Leave Policy"] = True

    # Termination
    if any(keyword in text for keyword in [
        "termination",
        "terminate",
        "written notice",
        "notice period",
        "30 days notice"
    ]):
        clauses["Termination"] = True

    # Governing Law
    if any(keyword in text for keyword in [
        "governed by",
        "governing law",
        "laws of",
        "jurisdiction"
    ]):
        clauses["Governing Law"] = True

    # Confidentiality
    if any(keyword in text for keyword in [
        "confidential",
        "confidentiality",
        "non disclosure",
        "nda"
    ]):
        clauses["Confidentiality"] = True

    # Non-Compete
    if any(keyword in text for keyword in [
        "non compete",
        "non-compete",
        "competing business"
    ]):
        clauses["Non-Compete"] = True

    # Indemnity
    if any(keyword in text for keyword in [
        "indemnity",
        "indemnify",
        "hold harmless"
    ]):
        clauses["Indemnity"] = True

    # Force Majeure
    if any(keyword in text for keyword in [
        "force majeure",
        "act of god",
        "natural disaster",
        "pandemic"
    ]):
        clauses["Force Majeure"] = True

    # Arbitration
    if any(keyword in text for keyword in [
        "arbitration",
        "arbitrator",
        "dispute resolution"
    ]):
        clauses["Arbitration"] = True

    # Intellectual Property
    if any(keyword in text for keyword in [
        "intellectual property",
        "copyright",
        "patent",
        "trademark",
        "ownership"
    ]):
        clauses["Intellectual Property"] = True

    return clauses