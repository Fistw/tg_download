#!/usr/bin/env python3
"""
Configuration Update Checker
Compares config.example.yaml with local or remote config.yaml
to help safely update configurations without overwriting changes.
"""

import argparse
import yaml
import sys
from pathlib import Path
from typing import Dict, Any, Tuple


def load_yaml(file_path: Path) -> Dict[str, Any]:
    """Load YAML file safely"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"❌ Error loading {file_path}: {e}")
        sys.exit(1)


def compare_dicts(old: Dict[str, Any], new: Dict[str, Any], path: str = "") -> Dict[str, Any]:
    """Compare two dictionaries and find differences"""
    diff = {
        'added': [],
        'removed': [],
        'modified': [],
    }
    
    # Check for new/modified keys
    for key, value in new.items():
        current_path = f"{path}.{key}" if path else key
        
        if key not in old:
            diff['added'].append((current_path, value))
        else:
            if isinstance(value, dict) and isinstance(old[key], dict):
                nested_diff = compare_dicts(old[key], value, current_path)
                diff['added'].extend(nested_diff['added'])
                diff['removed'].extend(nested_diff['removed'])
                diff['modified'].extend(nested_diff['modified'])
            elif old[key] != value:
                diff['modified'].append((current_path, old[key], value))
    
    # Check for removed keys
    for key in old:
        if key not in new:
            current_path = f"{path}.{key}" if path else key
            diff['removed'].append((current_path, old[key]))
    
    return diff


def print_diff(diff: Dict[str, Any]) -> None:
    """Print differences in a user-friendly way"""
    if not any(diff.values()):
        print("✅ Configuration is up to date! No differences found.")
        return
    
    print("\n📊 Configuration Differences:")
    print("=" * 60)
    
    if diff['added']:
        print("\n🆕 New settings (will be ADDED if you update):")
        for path, value in diff['added']:
            print(f"  + {path}: {value}")
    
    if diff['removed']:
        print("\n⚠️  Removed settings (will be LOST if you update):")
        for path, value in diff['removed']:
            print(f"  - {path}: {value}")
    
    if diff['modified']:
        print("\n🔄 Modified settings (will be CHANGED if you update):")
        for path, old_val, new_val in diff['modified']:
            print(f"  ~ {path}: {old_val} -> {new_val}")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Compare config.example.yaml with your config.yaml"
    )
    parser.add_argument(
        '--local',
        action='store_true',
        help='Check local config.yaml'
    )
    parser.add_argument(
        '--remote',
        action='store_true',
        help='Check remote config.yaml (via SSH)'
    )
    parser.add_argument(
        '--remote-host',
        default='root@your.remote.host',
        help='Remote host (default: root@your.remote.host)'
    )
    parser.add_argument(
        '--remote-path',
        default='/root/workspace/tg_download',
        help='Remote path (default: /root/workspace/tg_download)'
    )
    
    args = parser.parse_args()
    
    # Load example config
    example_path = Path('config.example.yaml')
    if not example_path.exists():
        print("❌ config.example.yaml not found!")
        sys.exit(1)
    
    example_config = load_yaml(example_path)
    print(f"📄 Loaded example configuration from {example_path}")
    
    if args.local:
        config_path = Path('config.yaml')
        if not config_path.exists():
            print("❌ Local config.yaml not found!")
            sys.exit(1)
        
        local_config = load_yaml(config_path)
        print(f"📄 Comparing with local configuration from {config_path}")
        
        diff = compare_dicts(local_config, example_config)
        print_diff(diff)
    
    elif args.remote:
        import subprocess
        import tempfile
        
        # Download remote config
        remote_config_path = f"{args.remote_host}:{args.remote_path}/config.yaml"
        temp_file = tempfile.NamedTemporaryFile(mode='w+', suffix='.yaml', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            subprocess.run(
                ['scp', remote_config_path, temp_path],
                check=True,
                capture_output=True,
                text=True
            )
            
            remote_config = load_yaml(Path(temp_path))
            print(f"📄 Comparing with remote configuration from {remote_config_path}")
            
            diff = compare_dicts(remote_config, example_config)
            print_diff(diff)
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to fetch remote config: {e}")
            print(f"   Stderr: {e.stderr}")
        finally:
            import os
            os.unlink(temp_path)
    
    else:
        print("⚠️  Please specify --local or --remote")
        parser.print_help()


if __name__ == '__main__':
    main()
