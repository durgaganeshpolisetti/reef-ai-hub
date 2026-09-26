import os

HUB_HOST = "127.0.0.1"
HUB_PORT = 8080
HUB_NAME = "Reef AI Hub"
HUB_VERSION = "0.1.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "reef_ai_hub.db")
