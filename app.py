"""TestPilot AI: local, single-user API testing workspace."""
from io import BytesIO
import json
import os
import secrets
import threading
from flask import Flask, jsonify, render_template, request, session, send_file
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException
from config import Config
from models.database import Database
from models.schemas import APIInput, Suite, RunInput
from services.ai_service import AIService, AIError, validation_details
from services.redaction import redact
from services.openapi_service import parse_specification
from services.network import validate_url
from services.test_executor import execute_suite, RUN_LOCK
from services.test_generator import generate_pytest
from services.report_service import pdf_report


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    db = Database(app.config['DATABASE'])
    app.extensions.update(database=db, ai_service=AIService(app.config['ADAPTION_MODEL'], app.config['AI_TIMEOUT']))
    ai_lock = threading.BoundedSemaphore(1)

    @app.before_request
    def request_security():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            expected = session.get('csrf_token')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not secrets.compare_digest(expected, supplied):
                return jsonify(error='Your session expired. Refresh the page and retry.'), 403
            source = request.headers.get('Origin')
            if source and source != request.host_url.rstrip('/'):
                return jsonify(error='Cross-origin requests are not allowed.'), 403

    @app.after_request
    def response_security(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(ValidationError)
    def invalid_schema(error):
        return jsonify(error='Please correct the data.', details=validation_details(error)), 400

    @app.errorhandler(ValueError)
    def invalid_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    def missing_record(error):
        return jsonify(error='The requested record was not found.'), 404

    @app.errorhandler(AIError)
    def provider_error(error):
        return jsonify(error=str(error)), 502

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.error('Request failed: %s', type(error).__name__)
        return jsonify(error='An unexpected application error occurred. Your saved history is retained.'), 500

    def json_body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Send a JSON object.')
        return data

    def ai_call(callback):
        if not ai_lock.acquire(blocking=False):
            return jsonify(error='Another AI request is active. Wait for it to finish.'), 409
        try:
            return callback()
        finally:
            ai_lock.release()

    @app.get('/')
    def home():
        session.setdefault('csrf_token', secrets.token_urlsafe(32))
        return render_template('index.html', csrf_token=session['csrf_token'])

    @app.get('/api/settings')
    def settings():
        return jsonify(provider='Adaption', model=app.config['ADAPTION_MODEL'], configured=bool(os.getenv('ADAPTION_API_KEY')), max_cases=25, max_repeats=3, max_response_kb=256, worker_timeout=app.config['WORKER_TIMEOUT'], local_origins=app.config['LOCAL_ORIGINS'], storage='SQLite - local single-user workspace', secrets='Execution credentials are never saved. Use ${SECRET_NAME} placeholders.')

    @app.get('/api/dashboard')
    def dashboard():
        return jsonify(db.dashboard())

    @app.post('/api/openapi')
    def import_openapi():
        file = request.files.get('file')
        if not file:
            raise ValueError('Choose an OpenAPI JSON or YAML file.')
        try:
            content = file.read(256001).decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Upload a UTF-8 JSON or YAML file.') from None
        specification, operations = parse_specification(content)
        return jsonify(specification=redact(specification, placeholders=True), operations=operations)

    @app.post('/generate')
    @app.post('/api/generate')
    def generate():
        api_input = APIInput.model_validate(json_body())
        if api_input.specification:
            api_input.specification, _ = parse_specification(json.dumps(api_input.specification))
        api_input = APIInput.model_validate(redact(api_input.model_dump(), placeholders=True))
        def perform():
            suite = app.extensions['ai_service'].generate(api_input)
            suite_data = Suite.model_validate(redact(suite.model_dump(), placeholders=True)).model_dump()
            sid = db.save_suite(suite_data, api_input.model_dump())
            return jsonify(success=True, suite=db.suite(sid), test_cases=json.dumps(suite_data, indent=2))
        return ai_call(perform)

    @app.get('/api/suites')
    def suites():
        return jsonify(suites=db.suites())

    @app.get('/api/suites/<int:sid>')
    def get_suite(sid):
        return jsonify(db.suite(sid))

    @app.post('/api/suites')
    def create_suite():
        suite_data = Suite.model_validate(json_body()).model_dump()
        safe = Suite.model_validate(redact(suite_data, placeholders=True)).model_dump()
        sid = db.save_suite(safe, {}, source='manual')
        return jsonify(db.suite(sid)), 201

    @app.post('/api/validate-suite')
    def validate_suite():
        suite_data = Suite.model_validate(json_body()).model_dump()
        return jsonify(Suite.model_validate(redact(suite_data, placeholders=True)).model_dump())

    @app.put('/api/suites/<int:sid>')
    def edit_suite(sid):
        old = db.suite(sid)
        suite_data = Suite.model_validate(json_body()).model_dump()
        safe = Suite.model_validate(redact(suite_data, placeholders=True)).model_dump()
        new_id = db.save_suite(safe, {}, source='reviewed revision', project_id=old['project_id'], reviewed=True)
        return jsonify(db.suite(new_id))

    @app.post('/api/suites/<int:sid>/run')
    def run_suite(sid):
        suite = db.suite(sid)
        if not suite['reviewed']:
            raise ValueError('Review and save this suite before execution.')
        options = RunInput.model_validate(json_body())
        validate_url(options.base_url, app.config['LOCAL_ORIGINS'])
        if not RUN_LOCK.acquire(blocking=False):
            return jsonify(error='A test run is already active. Wait for it to finish.'), 409
        try:
            rid = db.start_run(sid, options.base_url)
            output = execute_suite(suite['data'], options.model_dump(), app.config['LOCAL_ORIGINS'], app.config['WORKER_TIMEOUT'])
            db.finish_run(rid, output)
            return jsonify(db.run(rid))
        finally:
            RUN_LOCK.release()

    @app.get('/api/runs')
    def history():
        return jsonify(runs=db.runs())

    @app.get('/api/runs/<int:rid>')
    def get_run(rid):
        return jsonify(db.run(rid))

    @app.post('/api/runs/<int:rid>/analyse')
    def analyse(rid):
        run = db.run(rid)
        if run['state'] != 'completed':
            raise ValueError('This run has not completed.')
        def perform():
            analysis = app.extensions['ai_service'].analyse(run)
            db.save_analysis(rid, analysis)
            return jsonify(analysis)
        return ai_call(perform)

    @app.get('/api/suites/<int:sid>/export.py')
    def export_pytest(sid):
        suite = db.suite(sid)
        if not suite['reviewed']:
            raise ValueError('Review and save this suite before exporting executable tests.')
        content = generate_pytest(suite['data']).encode('utf-8')
        db.report('pytest', sid=sid)
        return send_file(BytesIO(content), mimetype='text/x-python', as_attachment=True, download_name=f'test_suite_{sid}.py')

    @app.get('/api/runs/<int:rid>/export.<fmt>')
    def export_report(rid, fmt):
        run = db.run(rid)
        if run['state'] != 'completed':
            raise ValueError('Only completed runs can be exported.')
        if fmt == 'json':
            content, mime = json.dumps(run, indent=2, ensure_ascii=True).encode('utf-8'), 'application/json'
        elif fmt == 'pdf':
            content, mime = pdf_report(run), 'application/pdf'
        else:
            raise ValueError('Choose JSON or PDF.')
        db.report(fmt, rid=rid, sid=run['suite_id'])
        return send_file(BytesIO(content), mimetype=mime, as_attachment=True, download_name=f'testpilot_run_{rid}.{fmt}')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('TESTPILOT_PORT', '5000')), debug=False, threaded=True)
