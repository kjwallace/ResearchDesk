import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # so tests can `from fakes import ...`
