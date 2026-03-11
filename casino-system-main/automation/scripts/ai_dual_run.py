import subprocess
import sys
from pathlib import Path

if len(sys.argv) < 2:
    raise Exception("No command provided")

command = sys.argv[1]

SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_BIN = sys.executable or "python"

print("Running Agent 1...")
subprocess.Popen([PYTHON_BIN, str(SCRIPT_DIR / "ai_direct_pr.py"), command])

print("Running Agent 2...")
subprocess.Popen([PYTHON_BIN, str(SCRIPT_DIR / "ai_direct_pr_agent2.py"), command])
