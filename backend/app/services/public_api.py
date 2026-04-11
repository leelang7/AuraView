import requests
from ..config import SERVICE_KEY, BASE_URL


def fetch_intersections(page_no=1, num_of_rows=100):
    url = "{}/crsrd_map_info".format(BASE_URL)
    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "dataType": "JSON"
    }

    try:
        res = requests.get(url, timeout=3)   # 🔥 15 → 3초로 줄임
        res.raise_for_status()
        return res.json()

    except Exception as e:
        print("⚠️ SIGNAL API FAIL:", e)

        # 🔥 fallback (시연용 강제값)
        return {
            "body": {
                "items": {
                    "item": {
                        "stPdsgSttsNm": "stop-And-Remain",
                        "stPdsgRmndCs": "10"
                    }
                }
            }
        }

import requests

def fetch_signal_info(intersection_id):
    url = "https://apis.data.go.kr/B551982/rti/getSignalLightInfo"  # 너 쓰던 엔드포인트

    params = {
        "serviceKey": "너 API 키",
        "pageNo": "1",
        "numOfRows": "1",
        "crsrdId": intersection_id,
        "_type": "json"
    }

    try:
        res = requests.get(url, params=params, timeout=3)
        res.raise_for_status()
        return res.json()

    except Exception as e:
        print("⚠️ SIGNAL API FAIL:", e)

        # 🔥 fallback
        return {
            "body": {
                "items": {
                    "item": {
                        "stPdsgSttsNm": "stop-And-Remain",
                        "stPdsgRmndCs": "10"
                    }
                }
            }
        }