# decoding key
O7jNwhi5HptRZAX09Q5JklD9mnn5MWdjED5QFMRZNh9mdRIyLu2uaGBrzlclK001lfyssLTie5orFL+pKS5ogQ==

# excute
uvicorn app.main:app --reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# background excute
cd /home/ubuntu/AuraView/backend
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &

# server ip
ec2-16-171-133-228.eu-north-1.compute.amazonaws.com

37.582528
127.047978

# address
http://13.48.70.193:8000/ui


```bash
cd /home/ubuntu/AuraView/backend
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
```

확인:

```bash
ps -ef | grep uvicorn
tail -f /home/ubuntu/AuraView/backend/uvicorn.log
```

종료:

```bash
pkill -f "uvicorn app.main:app"
```

재실행 한 줄:

```bash
cd /home/ubuntu/AuraView/backend && pkill -f "uvicorn app.main:app" ; nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
```

CI/CD 배포 스크립트용으로는 이 한 줄 쓰면 된다:

```bash
cd /home/ubuntu/AuraView/backend && git pull && pkill -f "uvicorn app.main:app" ; nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
```
