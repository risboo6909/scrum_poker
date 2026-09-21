FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD python -c "import os, urllib.request; prefix=os.getenv('BASE_PATH', '').strip('/'); url='http://127.0.0.1:' + os.getenv('PORT', '8000') + ('/' + prefix if prefix else '') + '/health'; urllib.request.urlopen(url, timeout=3)"

CMD ["python", "-m", "src.app"]
