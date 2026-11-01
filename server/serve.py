import os
import sys

import uvicorn


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "start"
    if mode not in {"dev", "start"}:
        raise SystemExit("Usage: python serve.py [dev|start]")

    try:
        port = int(os.getenv("PORT", "4000"))
    except ValueError as exc:
        raise SystemExit("PORT must be a valid TCP port.") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be a valid TCP port.")

    host = os.getenv("HOST", "127.0.0.1" if mode == "dev" else "0.0.0.0")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=mode == "dev",
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
