import logging
import signal
import threading

from tripweave.adapters.database import check_database, create_database_engine
from tripweave.adapters.worker_heartbeat import write_heartbeat
from tripweave.config import Settings, get_settings
from tripweave.logging import configure_logging

logger = logging.getLogger(__name__)


def run_worker(settings: Settings) -> None:
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    check_database(engine)

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    logger.info("worker started", extra={"service": "worker"})
    while not stop_event.is_set():
        write_heartbeat(settings.blob_dir)
        stop_event.wait(settings.worker_heartbeat_seconds)
    logger.info("worker stopped", extra={"service": "worker"})


def run() -> None:
    run_worker(get_settings())


if __name__ == "__main__":
    run()
