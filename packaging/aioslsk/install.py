"""Install the source-reviewed aioslsk backports into this Python environment."""
import subprocess
import sys
import tempfile
from pathlib import Path

# Upstream's version-metadata commit for 1.7.2.
REVISION = "9db3f5d7597e7050f21ff062d92a6708a5572eb1"
PATCH_DIR = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)
        subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
        subprocess.run(["git", "fetch", "--quiet", "--depth=1",
                        "https://github.com/JurgenR/aioslsk.git", REVISION],
                       cwd=source, check=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "checkout", "--quiet",
                        "--detach", REVISION], cwd=source, check=True)
        subprocess.run(["git", "apply", str(PATCH_DIR / "transfer-files.patch"),
                        str(PATCH_DIR / "message-limits.patch")], cwd=source, check=True)
        metadata = source / "pyproject.toml"
        version = 'version = "v1.7.2"'
        contents = metadata.read_text(encoding="utf-8")
        if contents.count(version) != 1:
            raise ValueError("unexpected aioslsk version metadata")
        metadata.write_text(contents.replace(version, 'version = "1.7.2+slskreborn.1"'),
                            encoding="utf-8")
        subprocess.run([sys.executable, "-m", "pip", "install", str(source)], check=True)


if __name__ == "__main__":
    main()
