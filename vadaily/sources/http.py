import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Trust the OS certificate store so HTTPS works behind the VA's TLS-inspecting proxy.
truststore.inject_into_ssl()


def make_session(contact_email=""):
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    agent = "vadaily/0.1"
    if contact_email:
        agent += f" (mailto:{contact_email})"
    s.headers["User-Agent"] = agent
    return s
