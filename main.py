import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Disable logging for simplicity

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        html_content = """
        <html>
            <head>
                <title>Trading Bot Dashboard</title>
            </head>
            <body>
                <h1>Welcome to the Trading Bot Dashboard</h1>
                <p>This is a simple dashboard for your trading bot.</p>
            </body>
        </html>
        """
        self.wfile.write(html_content.encode('utf-8'))

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        response = f"Received POST request with data: {post_data.decode('utf-8')}"
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

def _run_http_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, DashboardHandler)
    print("Starting httpd server on port 8000...")
    httpd.serve_forever()

if __name__ == '__main__':
    _run_http_server()
