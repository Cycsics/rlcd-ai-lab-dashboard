# License scope

Source project `ljzqp/waveshare-esp32-s3-rlcd-4.2-ai-dashboard` did not declare a repository-level license when this independent repository was prepared. Its reused files and modifications to those files are NOT relicensed here. This is not a blanket MIT license for the entire repository. Obtain permission from the relevant authors for uses not otherwise authorized.

The MIT license below applies only to independently added `server/monitor_*.py`, `server/monitor.html`, `server/tests/test_monitor.py`, `agent/` (excluding copied modules), the new Windows scripts `dashboard_windows.ps1`, `run_server.ps1`, `firmware_windows.ps1`, `configure_windows.py`, and the new Windows monitoring documentation, under `work/rlcd_companion/` where applicable.

Vendor libraries retain their own licenses. Proprietary Codex pet sprites are not distributed.

The independent USB standby policy `firmware/rlcd_client/monitor_power.h` and its tests `server/tests/test_power_policy.py` and `server/tests/cpp/test_monitor_power.cpp` are also covered by the MIT license below (paths relative to `work/rlcd_companion/`).

The independent calendar tests in `server/tests/test_monitor_billing.py` are covered by the same MIT license.

The independent connection UI `server/monitor_connections.js` and connection tests `server/tests/test_monitor_connections.py` are covered by the same MIT license. Subscription protocol behavior was researched from MIT-licensed CC Switch (Copyright 2025 JasonYoung); this project independently implements the queries and does not bundle CC Switch code.

## MIT License — independent additions only

The independent ChatGPT bridge tests in `server/tests/test_monitor_chatgpt.py` are also included in this scope.

Copyright (c) 2026 Cycsics

Permission is hereby granted, free of charge, to any person obtaining a copy of the software covered by the scope above and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
