#!/usr/bin/env python3
import logging
import sys

from config import HALOConfig
from halo.core.engine import HALOEngine
from halo.interface.cli import run_cli


def setup_logging(config: HALOConfig) -> None:
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    config = HALOConfig.load()
    setup_logging(config)
    engine = HALOEngine(config)
    run_cli(engine)


if __name__ == "__main__":
    main()
