"""Controlled local demo API, never a production target."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        encoded = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if urlsplit(self.path).path == '/health':
            self.reply(200, {'status': 'ok', 'version': '1.0'})
        elif urlsplit(self.path).path == '/private':
            if self.headers.get('Authorization') == 'Bearer demo-token':
                self.reply(200, {'user': {'id': 1, 'name': 'Demo user'}})
            else:
                self.reply(401, {'error': 'Unauthorized'})
        else:
            self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if urlsplit(self.path).path != '/echo':
            return self.reply(405, {'error': 'Method not allowed'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 65536:
                return self.reply(413, {'error': 'Payload too large'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not data['name']:
                return self.reply(400, {'error': 'name must be a nonempty string'})
            self.reply(201, {'name': data['name']})
        except (ValueError, UnicodeDecodeError):
            self.reply(400, {'error': 'Invalid JSON'})


def create_server(port=8765):
    return ThreadingHTTPServer(('127.0.0.1', port), DemoHandler)


if __name__ == '__main__':
    server = create_server()
    print('Controlled fixture: http://127.0.0.1:8765')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
