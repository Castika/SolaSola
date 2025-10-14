import http.client
import sys

try:
    conn = http.client.HTTPConnection("localhost", 5656, timeout=5)
    conn.request("GET", "/health")
    response = conn.getresponse()
    if 200 <= response.status < 300:
        sys.exit(0)
    else:
        sys.exit(1)
except Exception:
    sys.exit(1)
finally:
    conn.close()