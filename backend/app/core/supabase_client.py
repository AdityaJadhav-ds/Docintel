import os
from pathlib import Path
from dotenv import load_dotenv
from app.core.logger import logger

# ── Load .env using absolute path (safe in all subprocess contexts) ─────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)


class SupabaseClientManager:
    _instance = None

    @classmethod
    def get_client(cls):
        if cls._instance is None:
            supabase_url = os.environ.get("SUPABASE_URL", "").strip()
            supabase_key = os.environ.get("SUPABASE_KEY", "").strip()

            # ── Hard fail with a clear, actionable message ─────────────────────
            if not supabase_url:
                raise RuntimeError(
                    "[supabase_client] SUPABASE_URL is not set.\n"
                    f"  .env expected at: {ENV_PATH}\n"
                    "  Add:  SUPABASE_URL=https://xxxx.supabase.co\n"
                    "        SUPABASE_KEY=your-anon-or-service-role-key"
                )
            if not supabase_key:
                raise RuntimeError(
                    "[supabase_client] SUPABASE_KEY is not set.\n"
                    f"  .env expected at: {ENV_PATH}\n"
                    "  Add:  SUPABASE_KEY=your-anon-or-service-role-key"
                )

            # ── Log masked URL for startup diagnostics ─────────────────────────
            masked_url = supabase_url[:20] + "…" if len(supabase_url) > 20 else supabase_url
            logger.info(f"[supabase_client] Connecting to: {masked_url}")

            try:
                from supabase import create_client
                cls._instance = create_client(supabase_url, supabase_key)
                logger.info("[supabase_client] OK Supabase client initialized successfully.")
            except Exception as e:
                logger.error(f"[supabase_client] FAIL to initialize Supabase client: {e}")
                raise

        return cls._instance


def get_supabase():
    return SupabaseClientManager.get_client()
