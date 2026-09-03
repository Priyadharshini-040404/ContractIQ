import json
import os


def generate_postman_collection():
    """
    Generates a Postman collection for ContractIQ API
    with a sample PDF attached for automated Newman testing.
    """

    # Absolute path to sample PDF
    sample_pdf = os.path.abspath(
        os.path.join("sample_contracts", "Document 2.pdf")
    )

    collection = {
        "info": {
            "name": "ContractIQ API Tests",
            "_postman_id": "contractiq-001",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },

        "item": [
            {
                "name": "Upload Contract",

                "request": {
                    "method": "POST",

                    "header": [],

                    "body": {
                        "mode": "formdata",

                        "formdata": [
                            {
                                "key": "file",
                                "type": "file",
                                "src": sample_pdf
                            }
                        ]
                    },

                    "url": {
                        "raw": "http://127.0.0.1:8000/upload",

                        "protocol": "http",

                        "host": [
                            "127.0.0.1"
                        ],

                        "port": "8000",

                        "path": [
                            "upload"
                        ]
                    }
                },

                "response": []
            }
        ]
    }

    # Create output folder if not exists
    os.makedirs("output", exist_ok=True)

    output_file = os.path.join(
        "output",
        "ContractIQ.postman_collection.json"
    )

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=4)

    print(f"✅ Postman Collection generated at: {output_file}")

    return output_file


# Run directly
if __name__ == "__main__":
    generate_postman_collection()