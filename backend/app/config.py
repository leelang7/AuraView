import os
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = os.getenv("SERVICE_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://apis.data.go.kr/B551982/rti")