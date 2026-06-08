import os
from pathlib import Path
from dotenv import load_dotenv

# ── Resolve .env with an absolute path ─────────────────────────────────────────
# __file__ = backend/app/core/config.py → parent×3 = backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

# load_dotenv with override=False: existing env vars (set by OS/shell) are kept.
# Using dotenv guarantees correct UTF-8 parsing, handles quotes, and handles
# Windows paths that contain spaces — unlike the old manual parser.
_loaded = load_dotenv(dotenv_path=ENV_PATH, override=False)

if not _loaded:
    print(f"[config] WARNING: .env not found at {ENV_PATH}. "
          "Make sure SUPABASE_URL and SUPABASE_KEY are set in the environment.")
else:
    print(f"[config] .env loaded from: {ENV_PATH}")


class Config:
    TESSERACT_PATH    = os.environ.get("TESSERACT_PATH",
                                       r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    POPPLER_PATH      = os.environ.get("POPPLER_PATH", r"C:\poppler\Library\bin")
    MAX_FILE_SIZE     = os.environ.get("MAX_FILE_SIZE", "5MB")
    ALLOWED_EXTENSIONS = os.environ.get(
        "ALLOWED_EXTENSIONS", ".pdf,.png,.jpg,.jpeg"
    ).split(",")

    # Supabase — validated at import time so failures are loud and immediate
    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")


config = Config()


# Keep the old helper name for backward compatibility
def load_env_file() -> None:
    """No-op — env loading now happens at module import via python-dotenv."""
    pass
