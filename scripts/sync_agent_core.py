"""Vendor the tested AutoLab core into each Agent Engine workspace before `agentengine build`.

Each workspace builds in isolation, so the shared packages are copied into its src/.
Run after any core change:  .venv/bin/python scripts/sync_agent_core.py
"""
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ["shared", "harness", "evaluation", "simulation", "robot_gateway", "agents", "orchestrator"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

for ws in ["autolab-operator", "autolab-scientist"]:
    src = ROOT / "agentengine" / ws / "src"
    for pkg in CORE:
        dst = src / pkg
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(ROOT / pkg, dst, ignore=IGNORE)
    fx = src / "fixtures"
    if fx.exists():
        shutil.rmtree(fx)
    shutil.copytree(ROOT / "fixtures", fx)
    (fx / "__init__.py").touch()
    print(f"synced core -> {src}")
