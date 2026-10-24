"""Small command line entry point for running the API."""

import argparse
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the disaster response API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("disaster_response.api:app", host=args.host, port=args.port, reload=False,
                env_file=".env" if Path(".env").exists() else None)


if __name__ == "__main__":
    main()

