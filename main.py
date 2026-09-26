import logging
import uvicorn
from config import HUB_HOST, HUB_PORT
from api.app import app

logger = logging.getLogger("reef_ai_hub")


def run():
    uvicorn.run(
        app,
        host=HUB_HOST,
        port=HUB_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    run()
