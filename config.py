"""Local application configuration. Secrets never enter worker environments."""
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')


class Config:
    SECRET_KEY = os.getenv('TESTPILOT_SESSION_KEY') or secrets.token_hex(32)
    DATABASE = str(ROOT / 'instance' / 'testpilot.sqlite3')
    MAX_CONTENT_LENGTH = 512 * 1024
    ADAPTION_MODEL = os.getenv('ADAPTION_MODEL', 'qwen3.5-397b')
    AI_TIMEOUT = int(os.getenv('TESTPILOT_AI_TIMEOUT', '150'))
    WORKER_TIMEOUT = 90
    LOCAL_ORIGINS = [x.strip().rstrip('/') for x in os.getenv('TESTPILOT_LOCAL_ORIGINS', '').split(',') if x.strip()]
    TRUSTED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
