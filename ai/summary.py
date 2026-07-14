import re


def extract_field(pattern, text):

    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        return match.group(1).strip()

    return "Not Found"


def generate_summary(text):

    return {

        "employee_name": extract_field(
            r"Employee Name:\s*(.+)",
            text
        ),

        "position": extract_field(
            r"Position:\s*(.+)",
            text
        ),

        "salary": extract_field(
            r"Salary:\s*(.+)",
            text
        ),

        "working_hours": extract_field(
            r"Working Hours:\s*([\s\S]*?)Leave Policy:",
            text
        ),

        "leave_policy": extract_field(
            r"Leave Policy:\s*([\s\S]*?)Termination:",
            text
        ),

        "termination": extract_field(
            r"Termination:\s*([\s\S]*?)This agreement",
            text
        ),

        "governing_law": extract_field(
            r"laws of\s*(.+?)\.",
            text
        )

    }