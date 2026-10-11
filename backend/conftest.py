import os
import sys

# Ensure TESTING environment flag is set before any app modules are loaded
os.environ["TESTING"] = "true"

backend_dir = os.path.abspath(os.path.dirname(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
