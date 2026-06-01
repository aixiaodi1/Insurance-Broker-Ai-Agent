"""
Pre-download and cache HuggingFace models for offline-safe production startup.

Usage:
    python scripts/download_models.py

Downloads both models to ~/.cache/huggingface/hub/.
Idempotent — re-running is a no-op if already cached.
"""

import sys

from huggingface_hub import snapshot_download

from app.config import Settings

MODELS = [
    Settings.model_fields["embedding_model"].default,
    Settings.model_fields["cross_encoder_model"].default,
]


def download_models() -> None:
    for repo_id in MODELS:
        print(f"[download]  {repo_id}  ...")
        try:
            snapshot_download(repo_id)
            print(f"[done]      {repo_id}")
        except Exception as exc:
            print(f"[error]     {repo_id}  ->  {exc}", file=sys.stderr)
            raise


if __name__ == "__main__":
    download_models()
