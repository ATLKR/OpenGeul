"""Explicit diagnostic only; never an engine build or acceptance input."""
import sys
from pathlib import Path
try:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from dotnet_graph.runtime.controller import main
    result=main()
except BaseException:
    result=2
raise SystemExit(result)
