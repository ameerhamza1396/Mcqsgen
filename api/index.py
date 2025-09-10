from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import fitz # PyMuPDF
import pandas as pd
import json
import os
import re
import google.generativeai as genai
import traceback
import io

app = Flask(__name__)

# --- MCQ Prompt (Dynamic based on number of options) ---
def get_mcq_prompt(num_options):
    options = ["A", "B", "C", "D"]
    if num_options == 5:
        options.append("E")
    
    option_keys = [f"`option_{opt.lower()}`" for opt in options]

    prompt_template = f"""
You are an expert educator and assessment creator. Your task is to meticulously analyze the provided text and formulate challenging multiple-choice questions (MCQs).
For each distinct and crucial piece of information, generate ONE highly challenging MCQ.
Output ONLY a valid JSON array of MCQ objects. Each object MUST contain the following keys:
- `question`: The full MCQ question string.
- {",\n- ".join(option_keys)}: The text for each option.
- `correct_answer`: The letter of the correct option (must be "A", "B", "C", "D", or "E").
- `explanation`: A detailed explanation for the correct answer.
- `topic`: The inferred specific topic of the MCQ.
- `chapter`: The inferred chapter from which the information is drawn.
- `subject`: The overarching subject.

If fewer than {num_options} meaningful options can be extracted, generate additional plausible but incorrect distractors.  
If any question is incomplete or unclear, refine and fix it before outputting.  
Ensure that the correct answer is always properly validated with a clear explanation.
---
{{text_chunk}}
---
"""
    return prompt_template

def extract_text_from_pdf(pdf_path):
    """Extracts all text content from a given PDF file."""
    try:
        document = fitz.open(pdf_path)
        text = "".join(page.get_text() for page in document)
        document.close()
        return text
    except Exception as e:
        return None

def call_gemini_api(text_chunk, prompt_template, api_key):
    """A generic function to call the Gemini API with retry logic."""
    GEMINI_MODEL = 'gemini-2.5-flash'
    retries = 3

    for i in range(retries):
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(GEMINI_MODEL)
            
            response = model.generate_content(
                contents=[{"role": "user", "parts": [{"text": prompt_template.format(text_chunk=text_chunk)}]}],
                request_options={"timeout": 60}
            )
            raw_text = response.text.strip()
            
            match = re.search(r'```json\s*(\[.*?\])\s*```', raw_text, re.DOTALL)
            json_str = match.group(1) if match else raw_text

            extracted_data = json.loads(json_str)
            return extracted_data if isinstance(extracted_data, list) else []

        except Exception as e:
            traceback.print_exc()
            if i >= retries - 1:
                return []
    return []

def process_text_and_create_excel(full_text, num_options, api_key):
    """Process text input and return an in-memory Excel file."""
    chunk_size = 3000
    text_len = len(full_text)
    all_data = []
    num_chunks = (text_len // chunk_size) + 1
    
    prompt_template = get_mcq_prompt(num_options)

    for i in range(0, text_len, chunk_size):
        chunk = full_text[i:i + chunk_size]
        chunk_data = call_gemini_api(chunk, prompt_template, api_key)
        if chunk_data:
            all_data.extend(chunk_data)

    if not all_data:
        return None, "No data was generated from the provided text."

    try:
        df = pd.DataFrame(all_data)

        column_order = [
            "question", "option_a", "option_b", "option_c", "option_d",
            "correct_answer", "explanation", "topic", "chapter", "subject"
        ]
        if num_options == 5:
            column_order.insert(4, "option_e")
        else: # 4 options
            column_order.remove("option_e")

        existing_columns = [col for col in column_order if col in df.columns]
        df = df[existing_columns]
        df.insert(0, "S.No", range(1, len(df) + 1))

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="MCQs")
        output.seek(0)
        return output, None

    except Exception as e:
        traceback.print_exc()
        return None, f"An error occurred while creating the Excel file: {e}"

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    # This route is a placeholder to satisfy Vercel's build process.
    # The vercel.json file handles routing requests to the correct functions.
    return jsonify({"message": "API is running."})

@app.route("/api/generate-mcqs-pdf", methods=["POST"])
def generate_mcqs_from_pdf_route():
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file provided."}), 400
    
    pdf_file = request.files["pdf"]
    api_key = request.form.get("apiKey")
    num_options = int(request.form.get("numOptions", 5))

    if not api_key:
        return jsonify({"error": "API key is required."}), 400

    filename = secure_filename(pdf_file.filename)
    filepath = os.path.join("/tmp", filename)
    pdf_file.save(filepath)

    full_text = extract_text_from_pdf(filepath)
    os.remove(filepath)
    
    if not full_text:
        return jsonify({"error": "Could not extract text from PDF."}), 500
    
    excel_file, error = process_text_and_create_excel(full_text, num_options, api_key)

    if error:
        return jsonify({"error": error}), 500

    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="generated_mcqs.xlsx"
    )

@app.route("/api/generate-mcqs-text", methods=["POST"])
def generate_mcqs_from_text_route():
    data = request.json
    text_input = data.get("text")
    api_key = data.get("apiKey")
    num_options = int(data.get("numOptions", 5))

    if not text_input or not api_key:
        return jsonify({"error": "Text input and API key are required."}), 400
    
    excel_file, error = process_text_and_create_excel(text_input, num_options, api_key)

    if error:
        return jsonify({"error": error}), 500

    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="generated_mcqs.xlsx"
    )

if __name__ == "__main__":
    app.run(debug=True)
