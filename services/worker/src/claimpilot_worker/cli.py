import sys

from arq.cli import cli


def main() -> None:
    sys.argv = ["arq", "claimpilot_worker.main.WorkerSettings", *sys.argv[1:]]
    cli()
