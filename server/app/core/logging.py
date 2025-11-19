from __future__ import annotations

import logging
import logging.config
from typing import Any, Dict

from pythonjsonlogger import jsonlogger

from app.core.context import get_request_id


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        record.request_id = request_id or "-"
        return True


def _build_logging_config() -> Dict[str, Any]:
    formatter = {
        "format": "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        "datefmt": "%Y-%m-%dT%H:%M:%S%z",
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": RequestContextFilter,
            }
        },
        "formatters": {
            "json": {
                "()": jsonlogger.JsonFormatter,
                "fmt": formatter["format"],
                "datefmt": formatter["datefmt"],
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["request_context"],
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "app": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["default"], "level": "INFO"},
    }


def configure_logging() -> None:
    logging.config.dictConfig(_build_logging_config())



