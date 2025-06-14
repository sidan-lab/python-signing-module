#!/usr/bin/env python3
"""
Script to build and publish source distributions for CardanoSigner
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a command and return success status"""
    print(f"Running: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, check=True, cwd=cwd, 
                              capture_output=True, text=True)
        print(f"✓ Success: {cmd}")
        if result.stdout.strip():
            print(result.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed: {cmd}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False

def check_tool_exists(tool):
    """Check if a tool exists in PATH"""
    return shutil.which(tool) is not None

def check_prerequisites():
    """Check if required tools are installed"""
    tools = ['python', 'twine']
    missing = []
    
    for tool in tools:
        if not check_tool_exists(tool):
            missing.append(tool)
    
    if missing:
        print(f"Missing tools: {', '.join(missing)}")
        print("Install with: pip install twine")
        return False
    
    # Check if build module is available
    try:
        import build
        print("✓ build module available")
    except ImportError:
        print("Warning: 'build' module not found. Install with: pip install build")
        print("Will use legacy setup.py method instead.")
    
    return True

def build_sdist():
    """Build source distribution"""
    setup_py = Path("setup.py")
    if not setup_py.exists():
        print("Error: setup.py not found in current directory")
        return False
    
    # Check if requirements files exist
    req_files = ["requirements.txt", "requirements-build.txt"]
    missing_req = []
    for req_file in req_files:
        if not Path(req_file).exists():
            missing_req.append(req_file)
    
    if missing_req:
        print(f"Warning: Missing requirements files: {', '.join(missing_req)}")
        print("These files should exist for a complete package distribution.")
    
    print("\n=== Building Source Distribution ===")
    
    # Try modern build method first
    try:
        import build
        success = run_command("python -m build --sdist")
    except ImportError:
        # Fall back to legacy method
        success = run_command("python setup.py sdist")
    
    if success:
        # List what was created
        dist_dir = Path("dist")
        if dist_dir.exists():
            print(f"\nCreated files in {dist_dir}:")
            sdist_files = list(dist_dir.glob("*.tar.gz"))
            for f in sdist_files:
                print(f"  - {f.name}")
                
            if sdist_files:
                # Show what's included in the package
                latest_sdist = sorted(sdist_files)[-1]
                print(f"\nContents of {latest_sdist.name}:")
                run_command(f"tar -tzf {latest_sdist}")
                
                # Check if requirements files are included
                print(f"\nChecking for requirements files in {latest_sdist.name}:")
                for req_file in req_files:
                    try:
                        result = subprocess.run(f"tar -tzf {latest_sdist}", 
                                              shell=True, capture_output=True, text=True)
                        if req_file in result.stdout:
                            print(f"  ✓ {req_file} included")
                        else:
                            print(f"  ✗ {req_file} missing")
                    except subprocess.CalledProcessError:
                        print(f"  ? Could not check {req_file}")
    
    return success

def upload_to_testpypi():
    """Upload to TestPyPI for testing"""
    print("\n=== Uploading to TestPyPI ===")
    return run_command("twine upload --repository testpypi dist/*.tar.gz")

def upload_to_pypi():
    """Upload to PyPI"""
    print("\n=== Uploading to PyPI ===")
    response = input("Are you sure you want to upload to PyPI? (y/N): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return False
    
    return run_command("twine upload dist/*.tar.gz")

def main():
    """Main function"""
    print("CardanoSigner Source Distribution Publisher")
    print("=" * 50)
    
    if not check_prerequisites():
        sys.exit(1)
    
    # Build
    if not build_sdist():
        print("Failed to build source distribution")
        sys.exit(1)
    
    # Ask what to do next
    print("\nOptions:")
    print("1. Upload to TestPyPI (recommended first)")
    print("2. Upload to PyPI")
    print("3. Exit")
    
    choice = input("Choice (1-3): ").strip()
    
    if choice == "1":
        if upload_to_testpypi():
            print("\n✓ Successfully uploaded to TestPyPI!")
            print("Test installation with:")
            print("pip install --index-url https://test.pypi.org/simple/ CardanoSigner")
    elif choice == "2":
        if upload_to_pypi():
            print("\n✓ Successfully uploaded to PyPI!")
            print("Install with: pip install CardanoSigner")
    else:
        print("Done.")

if __name__ == "__main__":
    main() 