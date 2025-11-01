import os
import time
import requests
import plistlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import threading

cache_file = "MiHome-iOS.cache.txt"
all_file = "MiHome-iOS.all.txt"
latest_file = "MiHome-iOS.latest.txt"
plist_url_template = "https://cdn.cnbj1.fds.api.mi-img.com/mijia-ios-adhoc/AppStore/adhoc/plist/MiHome-ios-Feature-build{build_number}.plist"

thread_local = threading.local()


def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session


def get_all():
    results = []
    if os.path.exists(all_file):
        with open(all_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    results.append((parts[0], parts[1]))
    return results


def get_latest_build():
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            line = f.readline().strip()
            if line:
                return int(line)
    return 0


def safe_request(method, url, **kwargs):
    session = get_session()
    for attempt in range(3):
        try:
            return session.request(method, url, **kwargs)
        except requests.RequestException:
            if attempt < 2:
                time.sleep(1)
            else:
                return None
    return None


def fetch_version(build_number):
    plist_url = plist_url_template.format(build_number=build_number)
    plist_resp = safe_request("get", plist_url, timeout=10)
    if plist_resp is None or plist_resp.status_code != 200:
        return None, None
    plist_data = plistlib.loads(plist_resp.content)
    items = plist_data.get("items", [])
    bundle_version = ""
    package_url = ""
    for item in items:
        metadata = item.get("metadata", {})
        bundle_identifier = metadata.get("bundle-identifier", "")
        if bundle_identifier != "com.xiaomi.mihome.dailybuild":
            continue
        bundle_version = metadata.get("bundle-version", "")
        if bundle_version == "":
            continue
        assets = item.get("assets", [])

        package_url = ""
        for asset in assets:
            if asset.get("kind") == "software-package":
                package_url = asset.get("url", "")
                break
        if package_url != "":
            ipa_resp = safe_request("head", package_url, timeout=5)
            if ipa_resp is not None and ipa_resp.status_code != 200:
                package_url = ""
                continue
            break

    if bundle_version == "" or package_url == "":
        return None, None

    tqdm.write(f"{bundle_version} {package_url}")
    return bundle_version, package_url


def main():
    latest_build = get_latest_build()
    build_range = range(latest_build + 1, latest_build + 1000 + 1)
    results = get_all()
    latest_package_url = results[0][1] if results else ""
    build_numbers = []

    with ThreadPoolExecutor(max_workers=64) as executor:
        future_to_build = {executor.submit(fetch_version, i): i for i in build_range}
        for future in tqdm(as_completed(future_to_build), total=len(future_to_build), desc="Progress"):
            res = future.result()
            build_number = future_to_build[future]
            if res and all(res):
                results.append((res[0], res[1]))
                build_numbers.append(build_number)

    if build_numbers:
        results = list(set(results))

        # all
        results.sort(key=lambda x: [int(i) for i in x[0].split('.')], reverse=True)
        with open(all_file, "w") as f:
            for bundle_version, package_url in results:
                f.write(f"{bundle_version} {package_url}\n")

        if results[0][1] != latest_package_url:
            # cache
            with open(cache_file, "w") as f:
                f.write(str(max(build_numbers)))

            # latest
            latest_package_url = results[0][1]
            with open(latest_file, "w") as f:
                f.write(latest_package_url)


if __name__ == "__main__":
    main()
