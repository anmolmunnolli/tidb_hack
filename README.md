# tidb_hack

Update server/.env:
Store your Huggingface key and Tidb credentials

Create venv:

```python -m venv venv```
```source venv/bin/activate```

install dependencies:

```pip install requirements.txt -r```

Update your ip in config.ts:

```
const API_BASE =
  Platform.select({
    ios: "http://<ip>:8000",      
    android: "http://<ip>:8000",   
    default: "http://<ip>:8000",  
  })!;
```

Note: Make sure you are connected to same network on testing device and computing device.

Run Backend:

```uvicorn app:app --reload --host 0.0.0.0 --port 8080```

Run frontend:

```npm expo start -c```

