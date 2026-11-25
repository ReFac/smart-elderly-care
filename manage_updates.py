"""Start the managed institution service or build an offline signed release."""

import argparse
import os
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from platform_core import updates
from platform_core.update_deploy import Launcher, app_file


ROOT = Path(__file__).resolve().parent


def build(version, output, keyfile, notes):
    updates.parse_version(version)
    if len(notes) > 1400:
        raise ValueError("发布说明最长 1400 字")
    key = load_pem_private_key(keyfile.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("发布私钥须为 Ed25519")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    archive = output / ("elderly-care-" + version + ".zip")
    with ZipFile(archive, "x", ZIP_DEFLATED, compresslevel=6) as package:
        package.write(ROOT / "server.py", "server.py")
        # Bundle Markdown and connector metadata below the application prefix accepted by older launchers.
        resources = "platform_core/agents/bundled/"
        package.write(ROOT / "docs/examples/workspace-mcp.json", resources + "workspace-mcp.json")
        for manifest in sorted(ROOT.glob("requirements-*.txt")):
            package.write(manifest, resources + manifest.name)
        for path in sorted((ROOT / "skills").rglob("*")):
            if path.is_file() and not path.is_symlink() and (path.suffix == ".md" or path.name == "LICENSE.txt"):
                package.write(path, resources + path.relative_to(ROOT).as_posix())
        for entry in ("platform_core", "web"):
            for path in sorted((ROOT / entry).rglob("*")):
                name = path.relative_to(ROOT).as_posix()
                if not path.is_symlink() and path.is_file() and app_file(name):
                    package.write(path, name)
    digest = sha256()
    with archive.open("rb") as stream:
        while block := stream.read(updates.CHUNK):
            digest.update(block)
    size = archive.stat().st_size
    if size > updates.MAX_ARCHIVE:
        raise ValueError("发布包超出最大安装体积")
    release = {
        "product": "ankang-platform", "format": 1, "version": version,
        "artifact": archive.name, "size": size, "sha256": digest.hexdigest(), "notes": notes,
    }
    signature = b64encode(key.sign(updates.canonical(release))).decode()
    updates.atomic_json(output / "latest.json", {"release": release, "signature": signature})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("run", help="托管机构服务，并在备份后安装经签名的新版")
    serve.add_argument("--db", type=Path, default=ROOT / ".local" / "workspace.sqlite3")
    serve.add_argument("--port", type=int, help="固定端口，省略时读取部署设置")
    serve.add_argument("--public-origin")
    serve.add_argument("--demo-public-tour", action="store_true")
    serve.add_argument("--initial-data", choices=("demo", "empty"), default="demo")
    release = commands.add_parser("build", help="在发布主机生成签名发布清单和程序包")
    release.add_argument("--version", required=True)
    release.add_argument("--output", type=Path, required=True)
    release.add_argument("--key-file", type=Path, required=True)
    release.add_argument("--notes", default="")
    args = parser.parse_args()
    try:
        if args.command == "build":
            if not re.fullmatch(r"[0-9.]{5,20}", args.version):
                parser.error("请提供正式数字版本号")
            build(args.version, args.output.resolve(), args.key_file, args.notes)
        else:
            from platform_core.deployment_console import start_options
            _, port, _ = start_options(args.db, args.port, args.public_origin)
            if args.port is None:
                os.environ["NH_DEPLOY_PORT_INHERITED"] = "1"
            else:
                os.environ.pop("NH_DEPLOY_PORT_INHERITED", None)
            launcher = Launcher(
                ROOT, args.db.resolve(), port, public_origin=args.public_origin,
                demo=args.demo_public_tour, initial_data=args.initial_data,
            )
            launcher.run()
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
