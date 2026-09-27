from __future__ import annotations

import sys
import os
os.environ['RLCD_MONITOR_ENABLED'] = '0'
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

