import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import pytest
from app import create_app
from models.schemas import Suite


@pytest.fixture
def suite_data():
    return Suite.model_validate({'api_name': 'Controlled fixture', 'test_cases': [{'id': 'TC-001', 'category': 'functional', 'scenario': 'Documented health response', 'method': 'GET', 'endpoint': '/health', 'request': {'body_type': 'none'}, 'expected': {'status_code': 200, 'content_type': 'application/json', 'required_fields': ['status'], 'rules': [{'path': 'status', 'operator': 'equals', 'value': 'ok'}]}, 'eligible': True}]}).model_dump()


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite'), 'SECRET_KEY': 'test-session-only'})


@pytest.fixture
def client(app):
    client = app.test_client()
    client.get('/')
    with client.session_transaction() as session:
        client.environ_base['HTTP_X_CSRF_TOKEN'] = session['csrf_token']
    return client


@pytest.fixture(scope='session')
def fixture_api():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/slow':
                time.sleep(1.5)
            if path == '/redirect':
                self.send_response(302)
                self.send_header('Location', 'http://169.254.169.254/latest/meta-data/')
                self.end_headers()
                return
            if path == '/large':
                body = b'x' * 270000
            elif path == '/text':
                body = b'not json'
            elif path == '/secret':
                body = json.dumps({'access_token': 'never-persist-this', 'echo': self.headers.get('Authorization')}).encode()
            else:
                body = json.dumps({'status': 'ok', 'count': 2, 'query': parse_qs(urlsplit(self.path).query), 'authenticated': bool(self.headers.get('Authorization'))}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Set-Cookie', 'session=never-persist-cookie')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            body = json.dumps({'method': self.command, 'received': data.decode(), 'content_type': self.headers.get('Content-Type')}).encode()
            self.send_response(201)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
