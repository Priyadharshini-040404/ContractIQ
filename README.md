# ContractIQ – AI Contract Validation System

## Overview

ContractIQ is an AI-powered contract validation platform developed using FastAPI and Python.

The system automatically:

- Extracts text from PDF contracts
- Generates contract summary
- Detects mandatory clauses
- Identifies missing clauses
- Performs risk analysis
- Calculates compliance score
- Generates positive & negative API test cases
- Generates automated assertions
- Creates Postman collections
- Supports AI review using Gemini
- Integrates Schemathesis and Dredd for API contract testing

---

## Tech Stack

- Python
- FastAPI
- Swagger / OpenAPI
- PyMuPDF
- Google Gemini
- Schemathesis
- Dredd
- Newman
- GitHub Actions

---

## Run

```bash
uvicorn api.main:app --reload
```

Swagger

```
http://127.0.0.1:8000/docs
```

---

## Features

- PDF Upload
- Contract Summary
- Clause Detection
- Missing Clause Detection
- Risk Engine
- Compliance Engine
- AI Test Case Generation
- Assertion Generation
- Postman Collection Export
- AI Review