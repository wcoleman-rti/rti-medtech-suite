#!/bin/bash
cd /mnt/c/Users/wcoleman/Documents/repos/rti-medtech-suite
source install/setup.bash 2>/dev/null
python -m pytest tests/integration/test_operational_service_host.py -x -v --tb=short 2>&1
echo "DONE_EXIT=$?"
