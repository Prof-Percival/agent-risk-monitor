import argparse
import logging
import signal
import sys
import time

from . import db
from .config import Config
from .engine import run_once

log = logging.getLogger("analyzer")
_stopping = False


def _stop(*_: object) -> None:
    global _stopping
    _stopping = True
    log.info("stopping after the current batch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyzer", description="Turns agent events into alerts.")
    parser.add_argument(
        "mode",
        nargs="?",
        default="once",
        choices=("once", "watch"),
        help="'once' drains what is pending and exits, 'watch' keeps polling",
    )
    parser.add_argument(
        "--interval", type=float, default=5.0, help="seconds between polls in watch mode"
    )
    arguments = parser.parse_args(argv)

    config = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    for received in (signal.SIGTERM, signal.SIGINT):
        signal.signal(received, _stop)

    with db.connect(config.database_url) as connection:
        if arguments.mode == "once":
            events, alerts = drain(connection, config)
            log.info("analyzed %d event(s), raised %d alert(s)", events, alerts)
            return 0

        log.info("watching for events every %.1fs", arguments.interval)

        while not _stopping:
            try:
                events, alerts = drain(connection, config)
                if events:
                    log.info("analyzed %d event(s), raised %d alert(s)", events, alerts)
            except Exception:
                log.exception("a batch failed, retrying after the interval")
                connection.rollback()

            time.sleep(arguments.interval)

    return 0


def drain(connection, config: Config) -> tuple[int, int]:
    """Keeps going while batches are full, so a backlog clears without waiting for the next poll."""
    events = alerts = 0

    while True:
        batch_events, batch_alerts = run_once(connection, config)
        events += batch_events
        alerts += batch_alerts

        if batch_events < config.batch_size:
            return events, alerts


if __name__ == "__main__":
    sys.exit(main())
