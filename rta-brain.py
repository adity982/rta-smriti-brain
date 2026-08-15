import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    if sys.argv[1:2] == ["mcp-server"]:
        from rta_brain.mcp_server import main

        raise SystemExit(main(sys.argv[2:]))
    from rta_brain.cli import main

    raise SystemExit(main())
