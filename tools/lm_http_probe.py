"""Hybrid approach: Go solver generates jspl + POST /js/ for cookie,
then curl_cffi (firefox135 JA3) handles /captcha/, /captcha/check, and stock endpoint.
100% browser-free."""
import re
import subprocess
from urllib.parse import quote, urlparse, parse_qs

from curl_cffi import requests

SOLVER = "/var/folders/pl/f9xl5jbj0gd_lcyhj64fkql80000gn/T/opencode/dds/DataDome-Solver/go/datadome"
KEY = "B4396EDF0B1699201D873B9700D966"
CDN = "https://bot.cdn.adeo.cloud"
PRODUCT_URL = "https://www.leroymerlin.fr/produits/climatiseur-split-mobile-reversible-portasplit-midea-par-optimea-93857579.html"
STOCK_URL = "https://www.leroymerlin.fr/store-header-module/services/contextlayer/store-search-result?latitude=48.85&longitude=2.35&productRef=93857579&storeSearchType=STOCK"
UA_FF = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0"

HEADERS = {
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}


def parse_dd(html):
    m = re.search(r"dd=\{([^}]+)\}", html)
    if not m:
        return {}
    block = m.group(1)
    dd = dict(re.findall(r"'(\w+)':'([^']*)'", block))
    dd.update(dict(re.findall(r"'(\w+)':(\d+)", block)))
    return dd


def parse_ddm(html):
    m = re.search(r"(?s)var ddm = \{(.*?)\n\};", html)
    if not m:
        return {}
    ddm = dict(re.findall(r"(\w+):\s*'([^']*)'", m.group(1)))
    return ddm


def first(pattern, text):
    m = re.search(pattern, text)
    return m.group(1) if m else ""


def gen_jspl(cid=""):
    args = [SOLVER, "-site", "https://www.leroymerlin.fr/", "-key", KEY, "-cdn", CDN, "-encrypt"]
    if cid:
        args += ["-cid", cid]
    return subprocess.check_output(args, text=True, timeout=10).strip()


def run():
    s = requests.Session(impersonate="firefox135", timeout=30)
    base = {**HEADERS, "user-agent": UA_FF}

    # 1. GET product → challenge
    print("=== 1. GET product ===")
    r1 = s.get(PRODUCT_URL, headers={**base, "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    dd = parse_dd(r1.text)
    print(f"HTTP {r1.status_code} dd: rt={dd.get('rt')} cid={dd.get('cid','')[:40]} s={dd.get('s')}")
    if not dd:
        print("no challenge — product accessible")
        dd = {"cookie": ""}

    # 2. Generate jspl via Go solver
    print("\n=== 2. Generate jspl (Go solver) ===")
    jspl = gen_jspl(cid=dd.get("cookie", ""))
    print(f"jspl: {len(jspl)} chars")

    # 3. POST jspl to bot.cdn.adeo.cloud/js/ via curl_cffi firefox135
    print("\n=== 3. POST /js/ (curl_cffi firefox135) ===")
    form = {
        "jspl": jspl,
        "eventCounters": "[]",
        "jsType": "ch",
        "cid": dd.get("cookie", ""),
        "ddk": KEY,
        "Referer": "https://www.leroymerlin.fr/",
        "request": "%2F",
        "responsePage": "origin",
        "ddv": "5.6.6",
    }
    r2 = s.post(CDN + "/js/", data=form, headers={
        **base,
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.leroymerlin.fr",
        "referer": "https://www.leroymerlin.fr/",
    })
    print(f"HTTP {r2.status_code} body: {r2.text[:160]}")
    m = re.search(r'"cookie":"(datadome=[^"\\]+)', r2.text)
    if not m:
        print("no cookie from /js/")
        return False
    solver_cookie = m.group(1)
    print(f"solver cookie: {solver_cookie[:80]}...")

    # 4. GET /captcha/ iframe
    if dd.get("cid"):
        print("\n=== 4. GET /captcha/ iframe ===")
        low_cookie = "datadome=" + dd["cookie"]
        captcha_url = (
            f"https://{dd['host']}/captcha/?initialCid={quote(dd['cid'])}"
            f"&hash={quote(dd['hsh'])}&cid={quote(dd['cookie'])}&t={quote(dd.get('t','fe'))}"
            f"&referer={quote(PRODUCT_URL)}"
            + (f"&s={quote(dd['s'])}" if dd.get('s') else "")
            + f"&e={quote(dd['e'])}&dm=cd"
        )
        r3 = s.get(captcha_url, headers={**base, "accept": "text/html", "referer": PRODUCT_URL, "cookie": low_cookie})
        print(f"HTTP {r3.status_code} body {len(r3.text)} bytes")
        ddm = parse_ddm(r3.text)
        ch = first(r"ddCaptchaChallenge='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r3.text)
        env = first(r"ddCaptchaEnv='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r3.text)
        audio = first(r"ddCaptchaAudioChallenge='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r3.text)

        if ch and env and audio and ddm.get("cid"):
            # 5. GET /captcha/check
            print("\n=== 5. GET /captcha/check ===")
            s_val = ddm.get("s") or dd.get("s") or "38863"
            check_url = (
                f"https://{dd['host']}/captcha/check?"
                f"cid={quote(ddm['cid'])}&icid={quote(dd['cid'])}&ccid="
                f"&userEnv={quote(ddm['userEnv'])}&dm=cd"
                f"&ddCaptchaChallenge={quote(ch)}&ddCaptchaEnv={quote(env)}&ddCaptchaAudioChallenge={quote(audio)}"
                f"&hash={quote(ddm['hash'])}&ua={quote(ddm['ua'])}&referer={quote(PRODUCT_URL)}"
                f"&parent_url={quote(PRODUCT_URL)}&s={quote(s_val)}&ir="
            )
            r4 = s.get(check_url, headers={
                **base,
                "accept": "*/*",
                "referer": captcha_url,
                "cookie": low_cookie,
                "x-requested-with": "XMLHttpRequest",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })
            print(f"HTTP {r4.status_code} body: {r4.text[:200]}")
            m = re.search(r'"cookie":"(datadome=[^"\\]+)', r4.text)
            if m:
                trusted_cookie = m.group(1)
                print(f"trusted cookie: {trusted_cookie[:80]}...")
    # 6. Test stock endpoint with iterative challenge solving
    print("\n=== 6. GET stock (iterative solve) ===")
    cookie = trusted_cookie
    for attempt in range(1, 6):
        r5 = s.get(STOCK_URL, headers={
            **base,
            "accept": "application/json, text/plain, */*",
            "referer": PRODUCT_URL,
            "cookie": cookie,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        })
        print(f"  attempt {attempt}: HTTP {r5.status_code} body {len(r5.text)} bytes")
        if r5.status_code == 200:
            print("✅ STOCK ACCESSIBLE EN HTTP PUR!")
            print(r5.text[:300].replace("\n", " "))
            return True
        # Parse JSON challenge
        try:
            data = r5.json()
            cap_url = data.get("url", "")
        except:
            dd5 = parse_dd(r5.text)
            if dd5.get("rt"):
                cap_url = None
            else:
                break
        if not cap_url:
            print(f"  no url in response: {r5.text[:200]}")
            break
        # Parse the captcha URL
        qs = parse_qs(urlparse(cap_url).query)
        # GET the captcha iframe
        r_cap = s.get(cap_url, headers={**base, "accept": "text/html", "referer": STOCK_URL, "cookie": cookie})
        ddm2 = parse_ddm(r_cap.text)
        ch2 = first(r"ddCaptchaChallenge='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r_cap.text)
        env2 = first(r"ddCaptchaEnv='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r_cap.text)
        audio2 = first(r"ddCaptchaAudioChallenge='\s*\+\s*encodeURIComponent\(\s*'([a-f0-9]+)'", r_cap.text)
        if not (ch2 and env2 and audio2 and ddm2.get("cid")):
            print(f"  can't parse captcha iframe: ch={bool(ch2)} env={bool(env2)} audio={bool(audio2)}")
            break
        s_val2 = qs.get("s", [""])[0] or ddm2.get("s") or "38863"
        initial_cid = qs.get("initialCid", [""])[0]
        check_url2 = (
            f"https://geo.captcha-delivery.com/captcha/check?"
            f"cid={quote(ddm2['cid'])}&icid={quote(initial_cid)}&ccid="
            f"&userEnv={quote(ddm2['userEnv'])}&dm=cd"
            f"&ddCaptchaChallenge={quote(ch2)}&ddCaptchaEnv={quote(env2)}&ddCaptchaAudioChallenge={quote(audio2)}"
            f"&hash={quote(ddm2['hash'])}&ua={quote(ddm2['ua'])}&referer={quote(STOCK_URL)}"
            f"&parent_url={quote(STOCK_URL)}&s={quote(s_val2)}&ir="
        )
        r_chk = s.get(check_url2, headers={
            **base,
            "accept": "*/*",
            "referer": cap_url,
            "cookie": cookie,
            "x-requested-with": "XMLHttpRequest",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        })
        print(f"  /check: HTTP {r_chk.status_code} body {r_chk.text[:100]}")
        m = re.search(r'"cookie":"(datadome=[^"\\]+)', r_chk.text)
        if m:
            cookie = m.group(1)
            print(f"  new cookie: {cookie[:60]}...")
        else:
            print("  no cookie from /check")
            break
    return False


if __name__ == "__main__":
    ok = 0
    for i in range(5):
        print(f"\n{'='*60}")
        print(f"RUN {i+1}/5")
        print(f"{'='*60}")
        try:
            if run():
                ok += 1
        except Exception as e:
            print(f"ERR: {e}")
    print(f"\n{'='*60}")
    print(f"Success: {ok}/5")
