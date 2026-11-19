import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LLM_ENABLED"] = "0"
os.environ["READING_STRATEGY"] = "accuracy"      # the tests written for the two-reader path keep exercising it; reading-plan tests choose their own
