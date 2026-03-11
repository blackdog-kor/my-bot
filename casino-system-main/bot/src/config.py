import logging
import json
import sys

def setup_logger(name="bot"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)

    return logger


def log_event(logger, event, **fields):
    payload = {
        "event": event,
        **fields
    }
    logger.info(json.dumps(payload))
