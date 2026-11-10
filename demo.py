"""Launch an isolated demonstration workspace and its exact-origin local fixture."""
import threading
from config import ROOT
from app import create_app
from examples.mock_api import create_server


if __name__ == '__main__':
    server = create_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    app = create_app({'DATABASE': str(ROOT / 'instance' / 'demo.sqlite3'), 'LOCAL_ORIGINS': ['http://127.0.0.1:8765']})
    print('DEMO workspace: http://127.0.0.1:5001 | Fixture: http://127.0.0.1:8765')
    print('Demo history is separate. All results come from real local HTTP requests.')
    try:
        app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)
    finally:
        server.shutdown()
        server.server_close()
