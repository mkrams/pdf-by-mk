import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/pdf-by-mk")
JOB_EXPIRY_SECONDS = 3600  # 1 hour
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
