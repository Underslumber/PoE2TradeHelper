import os
import sys
from pathlib import Path

os.environ["PUBLIC_CANONICAL_ORIGIN"] = "https://public.example.test:9443"
os.environ["PUBLIC_API_ORIGIN"] = "https://public.example.test"
os.environ.pop("PUBLIC_REDIRECT_HOSTS", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
