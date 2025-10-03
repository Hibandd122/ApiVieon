from flask import Flask, request, Response, jsonify
import requests, random, string, time, re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

# ---------- Helpers ----------
def rand_str(chars, n):
    return ''.join(random.choices(chars, k=n))

def get_mail_domain():
    url = "https://api.mail.tm/domains"
    for _ in range(6):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            domains = r.json().get("hydra:member", [])
            if domains:
                return random.choice(domains)["domain"]
        except Exception:
            time.sleep(1)
    raise RuntimeError("Không lấy được domain mail.tm")

def create_mail_account(email, password):
    r = requests.post("https://api.mail.tm/accounts", json={"address": email, "password": password}, timeout=10)
    if r.status_code != 201:
        raise RuntimeError(f"Tạo account thất bại: {r.status_code} {r.text}")
    t = requests.post("https://api.mail.tm/token", json={"address": email, "password": password}, timeout=10)
    if t.status_code != 200:
        raise RuntimeError(f"Lấy token thất bại: {t.status_code} {t.text}")
    return t.json().get("token")

def update_vieon_email(auth_token, email):
    url = "https://api.vieon.vn/backend/user/profile/update_email?platform=web&ui=012021"
    headers = {"authorization": auth_token, "content-type": "application/x-www-form-urlencoded"}
    payload = {
        "email": email,
        "model": "Windows 10",
        "device_name": "Chrome/140",
        "device_type": "desktop",
        "platform": "web",
        "ui": "012021"
    }
    r = requests.post(url, headers=headers, data=payload, timeout=15)
    return r.status_code, r.text

def extract_vieon_link(html_content, text_content):
    if html_content:
        html = "".join(html_content) if isinstance(html_content, list) else html_content
        soup = BeautifulSoup(html, "html.parser")
        a = soup.find("a", href=True)
        if a and "vieon.vn" in a["href"]:
            return a["href"]
    if text_content:
        m = re.search(r"https://[^\s\]]+", text_content)
        if m and "vieon.vn" in m.group(0):
            return m.group(0)
    return None

def confirm_vieon_email(auth_token, mail_token, wait_seconds=120, poll_interval=2):
    headers = {"Authorization": f"Bearer {mail_token}"}
    url = "https://api.mail.tm/messages"
    deadline = time.time() + wait_seconds

    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        members = r.json().get("hydra:member", [])
        if members:
            mid = members[0]["id"]
            detail = requests.get(f"{url}/{mid}", headers=headers, timeout=10).json()
            link = extract_vieon_link(detail.get("html", []), detail.get("text", ""))

            if link:
                try:
                    resp = requests.get(link, timeout=15, allow_redirects=True)
                    final_url = resp.url
                    parsed = urlparse(final_url)
                    qs = parse_qs(parsed.query)
                    reg_id = qs.get("register_session_id", [None])[0]
                    otp_code = qs.get("otp", [None])[0]

                    if reg_id and otp_code:
                        confirm_url = "https://api.vieon.vn/backend/user/profile/update_email/confirm_otp?platform=web&ui=012021"
                        payload = {
                            "register_session_id": reg_id,
                            "otp_code": otp_code,
                            "platform": "web",
                            "ui": "012021"
                        }
                        headers2 = {
                            "authorization": auth_token,
                            "content-type": "application/x-www-form-urlencoded"
                        }
                        r2 = requests.post(confirm_url, headers=headers2, data=payload, timeout=15)
                        return {
                            "status": "confirmed",
                            "resp_status": r2.status_code,
                            "resp_text": r2.text,
                            "email": qs.get("email", [""])[0]
                        }
                    return {"status": "link_but_no_params", "url": final_url}

                except Exception as e:
                    return {"status": "confirm_error", "error": str(e)}

        time.sleep(poll_interval)

    return {"status": "timeout"}

# ---------- Route ----------
@app.route("/create", methods=["POST"])
def create_random_email_pass():
    data = request.get_json(force=True, silent=True) or {}
    auth_token = data.get("auth_token") or data.get("AUTH_TOKEN")
    if not auth_token:
        return jsonify({"error": "auth_token is required"}), 400

    try:
        username = rand_str(string.ascii_lowercase + string.digits, 10)
        domain = get_mail_domain()
        email = f"{username}@{domain}"
        password = rand_str(string.ascii_letters + string.digits, 12)

        # tạo account mail.tm
        mail_token = create_mail_account(email, password)

        # update email lên VieON
        vieon_status, vieon_text = update_vieon_email(auth_token, email)

        # check inbox & auto confirm
        confirm_info = confirm_vieon_email(auth_token, mail_token, wait_seconds=120)

        body = f"{email}:{password}"
        return Response(body, status=200, mimetype="text/plain")

    except Exception as e:
        return jsonify({"error": str(e)}), 500
