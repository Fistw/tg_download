#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.webdav_server import MonitoringApp


def test_static_paths():
    print("Testing MonitoringApp static paths...")
    static_dir = Path(__file__).parent / "static"
    web_dist_dir = Path(__file__).parent / "web" / "dist"
    
    print(f"  static_dir: {static_dir} (exists: {static_dir.exists()})")
    print(f"  web_dist_dir: {web_dist_dir} (exists: {web_dist_dir.exists()})")
    
    app = MonitoringApp(static_dir, web_dist_dir, "", "")
    
    test_paths = [
        "/assets/index-C0ABudFn.css",
        "/assets/index-gqLiehQD.js",
        "/favicon.svg",
        "/icons.svg"
    ]
    
    print("\nTesting paths:")
    for path in test_paths:
        print(f"  {path:40}", end="")
        # Simulate handle_web_static
        if path.startswith("/static/"):
            relative_path = path[len("/static/"):]
        else:
            relative_path = path.lstrip("/")
        file_path = app.web_dist_dir / relative_path
        print(f" → {file_path} (exists: {file_path.exists()})")
        if file_path.exists():
            print(f"    Size: {file_path.stat().st_size} bytes")
            with open(file_path, "rb") as f:
                preview = f.read(100)
                print(f"    Preview: {preview[:50] if len(preview) > 50 else preview}")

    print("\nChecking files in web/dist/:")
    for item in web_dist_dir.iterdir():
        print(f"  {item.name:30} (dir: {item.is_dir()})")
    
    if (web_dist_dir / "assets").exists():
        print("\nChecking files in web/dist/assets/:")
        for item in (web_dist_dir / "assets").iterdir():
            print(f"  {item.name:40} (size: {item.stat().st_size})")


if __name__ == "__main__":
    test_static_paths()
