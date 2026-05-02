import os
import sys

# backend/ 를 sys.path 에 추가해 `from app.main import app` 가능하게
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
