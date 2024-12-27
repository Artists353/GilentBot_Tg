import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level="DEBUG",
    format="%(levelname)s | %(name)s | %(asctime)s | %(lineno)d | %(message)s",
    datefmt="%I:%M:%S",
)

logger = logging.getLogger(__name__)
logger.info(f"Инициализирован логгер в модуле {__file__}")
