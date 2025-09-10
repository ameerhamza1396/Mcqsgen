from http.server import BaseHTTPRequestHandler
import cgi
import json
import os
import io
import google.generativeai as genai
import pdfplumber

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_type = self.headers.get('content-type')
            
            # Check if the content type is for a form with a file
            if content_type and content_type.startswith('multipart/form-data'):
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={'REQUEST_METHOD': 'POST',
                             'CONTENT_TYPE': self.headers['Content-Type']}
                )
                
                source = form.getvalue('source', '').decode('utf-8')
                num_options = int(form.getvalue('numOptions', '5').decode('utf-8'))
                api_key = form.getvalue('apiKey', '').decode('utf-8')
                
                text_content = ""
                if source == 'pdf':
                    if 'pdf' in form:
                        pdf_item = form['pdf']
                        pdf_file = io.BytesIO(pdf_item.file.read())
                        with pdfplumber.open(pdf_file) as pdf:
                            for page in pdf.pages:
                                text_content += page.extract_text() or ""
                
            else:
                content_length = int(self.headers['Content-Length'])
                post_body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(post_body)
                
                text_content = data.get('text', '')
                num_options = data.get('numOptions', 5)
                api_key = data.get('apiKey', '')
                source = data.get('source', '')

            if not text_content:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'No text or PDF content provided.'}).encode())
                return

            if not api_key:
                self.send_response(401)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'No API key provided.'}).encode())
                return

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-pro-latest')

            num_options_char = chr(ord('A') + num_options - 1)
            
            prompt = f"""
            Generate a JSON array of multiple-choice questions (MCQs) from the following text.
            Each question object in the array must have the following keys:
            - question (string): The question text.
            - option_a (string): Option A.
            - option_b (string): Option B.
            - option_c (string): Option C.
            - option_d (string): Option D.
            - option_e (string): Option E.
            - correct_answer (string): The single letter of the correct option (e.g., "A").

            The number of options per question should be {num_options}.
            The correct answer should be one of the provided options.

            TEXT:
            {text_content}
            """

            response = model.generate_content(prompt, stream=False)
            
            mcqs_json_string = response.text.replace('```json', '').replace('```', '').strip()
            mcqs_data = json.loads(mcqs_json_string)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(mcqs_data).encode())

        except json.JSONDecodeError as e:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': f'Invalid JSON in request body: {e}'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())
