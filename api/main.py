from fastapi import FastAPI, UploadFile, File

from ai.extractor import extract_pdf
from ai.validator import validate_contract
from ai.gemini_client import analyze_contract

app = FastAPI(
    title="ContractIQ API",
    version="1.0.0",
    description="""
## ContractIQ - AI Contract Validation System

ContractIQ is an AI-powered contract validation platform that automatically:

- Extracts text from PDF contracts
- Generates contract summaries
- Detects mandatory clauses
- Identifies missing clauses
- Performs legal risk analysis
- Calculates compliance score
- Generates positive & negative test cases
- Generates automated assertions
- Creates Postman collections
- Supports AI-based contract review using Gemini AI
""",
    contact={
        "name": "ContractIQ Team",
        "email": "support@contractiq.ai"
    },
    license_info={
        "name": "MIT License"
    },
    tags_metadata=[
        {
            "name": "General",
            "description": "General API endpoints."
        },
        {
            "name": "Contract Validation",
            "description": "Upload and validate contracts using AI."
        }
    ]
)


@app.get(
    "/",
    tags=["General"],
    summary="Home",
    description="Returns the application status."
)
def home():
    return {
        "message": "Welcome to ContractIQ",
        "status": "Running Successfully"
    }


@app.get(
    "/health",
    tags=["General"],
    summary="Health Check",
    description="Checks whether the API is healthy."
)
def health():
    return {
        "status": "Healthy"
    }


@app.post(
    "/upload",
    tags=["Contract Validation"],
    summary="Upload Contract",
    description="""
Upload a PDF contract for intelligent AI-based validation.

The API performs:

- PDF Text Extraction
- Contract Summary Generation
- Clause Detection
- Missing Clause Identification
- Risk Analysis
- Compliance Score Calculation
- Positive Test Case Generation
- Negative Test Case Generation
- Assertion Generation
- Postman Collection Generation
- AI Review (Gemini)
"""
)
async def upload_contract(file: UploadFile = File(...)):

    # Read uploaded PDF
    pdf_bytes = await file.read()

    # Extract text from PDF
    text, pages = extract_pdf(pdf_bytes)

    # Validate Contract
    validation = validate_contract(text)

    # AI Review
    try:
        ai_review = analyze_contract(text)

    except Exception:
        ai_review = (
            "Gemini AI temporarily unavailable due to API quota limitations."
        )

    return {

        "filename": file.filename,

        "pages": pages,

        "summary": validation["summary"],

        "clauses": validation["clauses"],

        "present_clauses": validation["present_clauses"],

        "missing_clauses": validation["missing_clauses"],

        "risks": validation["risks"],

        "risk_score": validation["risk_score"],

        "overall_risk": validation["overall_risk"],

        "compliance_score": validation["compliance_score"],

        "contract_health": validation["contract_health"],

        "positive_test_cases": validation["positive_test_cases"],

        "negative_test_cases": validation["negative_test_cases"],

        "assertions": validation["assertions"],

        "postman_collection_file": validation["postman_collection_file"],

        "ai_review": ai_review,

        "text": text
    }