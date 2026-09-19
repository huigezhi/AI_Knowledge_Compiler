"""``python -m akc`` —— 启动本地服务。"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Knowledge Compiler local backend")
    parser.add_argument("--host", default=None, help="override AKC_HOST")
    parser.add_argument("--port", type=int, default=None, help="override AKC_PORT")
    parser.add_argument("--reload", action="store_true", help="enable auto reload (development)")
    args = parser.parse_args()

    from akc.config import get_settings

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    uvicorn.run(
        "akc.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
