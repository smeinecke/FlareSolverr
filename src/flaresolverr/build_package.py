import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

import requests

# Script moved from src/ to src/flaresolverr/; compute repo root once.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def clean_files():
    for folder in ("build", "dist", "dist_chrome"):
        try:
            shutil.rmtree(os.path.join(REPO_ROOT, folder))
        except OSError:
            pass


def download_custom_chromium():
    """Extract the custom stealth Chromium from the chromium-stealth image.

    Linux packages ship the same patched binary the Docker image uses so the
    stealth patches (native UA, webdriver-false, ...) and the SwANGLE WebGL
    runtime files (libvulkan.so.1, vk_swiftshader_icd.json) are present.
    Set PACKAGE_STOCK_CHROMIUM=1 to force the stock snapshot instead.
    """
    image = os.environ.get("CHROMIUM_STEALTH_IMAGE", "ghcr.io/smeinecke/chromium-stealth:latest")
    dl_path = os.path.join(REPO_ROOT, "dist_chrome")
    chrome_path = os.path.join(dl_path, "chrome")
    print(f"Extracting custom Chromium from image: {image}")

    if shutil.which("docker") is None:
        print("WARNING: docker not found, falling back to stock Chromium snapshot")
        return download_stock_chromium()

    os.mkdir(dl_path)
    cid = subprocess.run(["docker", "create", image], capture_output=True, text=True, check=True).stdout.strip()
    try:
        subprocess.run(["docker", "cp", f"{cid}:/opt/chromium", chrome_path], check=True)
    finally:
        subprocess.run(["docker", "rm", cid], check=True)

    marker = os.path.join(chrome_path, ".stealth-patched")
    if not os.path.exists(marker):
        raise RuntimeError(f"Image {image} does not contain a stealth-patched Chromium ({marker} missing)")

    # Give executable permissions for *nix
    print("Giving executable permissions...")
    for exec_file in ("chrome", "chrome_crashpad_handler", "chrome_sandbox", "chrome-wrapper", "chromedriver"):
        exec_path = os.path.join(chrome_path, exec_file)
        if os.path.exists(exec_path):
            os.chmod(exec_path, 0o755)
    print("Extracted in: " + chrome_path)


def download_stock_chromium():
    # https://commondatastorage.googleapis.com/chromium-browser-snapshots/index.html?prefix=Linux_x64/
    revision = "1681099" if os.name == "nt" else "1681097"
    arch = "Win_x64" if os.name == "nt" else "Linux_x64"
    dl_file = "chrome-win" if os.name == "nt" else "chrome-linux"
    dl_path = os.path.join(REPO_ROOT, "dist_chrome")
    dl_path_folder = os.path.join(dl_path, dl_file)
    dl_path_zip = dl_path_folder + ".zip"

    # response = requests.get(
    #     f'https://commondatastorage.googleapis.com/chromium-browser-snapshots/{arch}/LAST_CHANGE',
    #     timeout=30)
    # revision = response.text.strip()
    print("Downloading revision: " + revision)

    os.mkdir(dl_path)
    with requests.get(f"https://commondatastorage.googleapis.com/chromium-browser-snapshots/{arch}/{revision}/{dl_file}.zip", stream=True) as r:
        r.raise_for_status()
        with open(dl_path_zip, "wb") as f:
            f.writelines(r.iter_content(chunk_size=8192))
    print("File downloaded: " + dl_path_zip)
    with zipfile.ZipFile(dl_path_zip, "r") as zip_ref:
        zip_ref.extractall(dl_path)
    os.remove(dl_path_zip)

    chrome_path = os.path.join(dl_path, "chrome")
    shutil.move(dl_path_folder, chrome_path)
    print("Extracted in: " + chrome_path)

    if os.name != "nt":
        # Give executable permissions for *nix
        # file * | grep executable | cut -d: -f1
        print("Giving executable permissions...")
        execs = ["chrome", "chrome_crashpad_handler", "chrome_sandbox", "chrome-wrapper"]
        for exec_file in execs:
            exec_path = os.path.join(chrome_path, exec_file)
            os.chmod(exec_path, 0o755)


def download_chromium():
    # There is no Windows build of the custom Chromium — the Windows package
    # always ships a stock snapshot. Linux defaults to the stealth build;
    # PACKAGE_STOCK_CHROMIUM=1 forces the stock snapshot path.
    if os.name != "nt" and os.environ.get("PACKAGE_STOCK_CHROMIUM", "") not in ("1", "true"):
        download_custom_chromium()
    else:
        download_stock_chromium()


def run_pyinstaller():
    sep = ";" if os.name == "nt" else ":"
    # Bundled resources must land under _internal/flaresolverr/ because the
    # frozen package resolves files relative to flaresolverr/utils.py
    # (sys._MEIPASS/flaresolverr/). The chrome dir additionally carries
    # .stealth-patched/.stealth-manifest.json so the runtime auto-detects the
    # custom build when the stealth image was used.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--icon",
            os.path.join("resources", "flaresolverr_logo.ico"),
            "--add-data",
            f"pyproject.toml{sep}.",
            "--add-data",
            f"{os.path.join('dist_chrome', 'chrome')}{sep}flaresolverr/chrome",
            "--add-data",
            f"{os.path.join('src', 'flaresolverr', 'stealth.js')}{sep}flaresolverr",
            "--add-data",
            f"{os.path.join('src', 'flaresolverr', 'stealth_fallback.js')}{sep}flaresolverr",
            "--add-data",
            f"{os.path.join('src', 'flaresolverr', 'proxy_extension')}{sep}flaresolverr/proxy_extension",
            os.path.join("src", "flaresolverr", "flaresolverr.py"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.decode("utf-8"))
        raise RuntimeError("Error running pyInstaller")


def compress_package():
    dist_folder = os.path.join(REPO_ROOT, "dist")
    package_folder = os.path.join(dist_folder, "package")
    shutil.move(os.path.join(dist_folder, "flaresolverr"), os.path.join(package_folder, "flaresolverr"))
    print("Package folder: " + package_folder)

    compr_format = "zip" if os.name == "nt" else "gztar"
    compr_file_name = "flaresolverr_windows_x64" if os.name == "nt" else "flaresolverr_linux_x64"
    compr_file_path = os.path.join(dist_folder, compr_file_name)

    if compr_format == "zip":
        shutil.make_archive(compr_file_path, compr_format, package_folder)
        print("Compressed file path: " + compr_file_path)
    else:

        def _reset_tarinfo(tarinfo):
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.uname = ""
            tarinfo.gname = ""
            return tarinfo

        tar_path = compr_file_path + ".tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for entry in os.listdir(package_folder):
                fullpath = os.path.join(package_folder, entry)
                tar.add(fullpath, arcname=entry, filter=_reset_tarinfo)
        print("Compressed file path: " + tar_path)


if __name__ == "__main__":
    print("Building package...")
    print("Platform: " + platform.platform())

    print("Cleaning previous build...")
    clean_files()

    print("Downloading Chromium...")
    download_chromium()

    print("Building pyinstaller executable... ")
    run_pyinstaller()

    print("Compressing package... ")
    compress_package()

# NOTE: python -m pip install pyinstaller
