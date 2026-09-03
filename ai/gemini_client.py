import os
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()

# Read API Key
API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini Client
client = genai.Client(api_key=API_KEY)


def analyze_contract(text):

    prompt = f"""
You are an AI Legal Contract Reviewer.

Analyze the following employment contract.

Provide:

1. Contract Summary
2. Missing Clauses
3. Risks
4. Recommendations

Contract:

{text}
"""

    try:

        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=prompt
        )

        if response.text:
            return response.text

        return "AI review completed, but no response was generated."

    except Exception as e:

        print("Gemini Error:", e)

        return "Gemini AI temporarily unavailable due to API quota limitations."