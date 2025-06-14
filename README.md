# python-signing-module
Python signing module, implementation in Rust, ported over to C++, then to Python.

# Requirements

## Files

- **`requirements.txt`** - Runtime dependencies (currently empty - uses only standard library)
- **`requirements-build.txt`** - Dependencies needed to build from source

## Building from Source
1. Install system dependencies:
   ```bash
   # Rust
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   
   # SWIG and C++ compiler
   # macOS: brew install swig && xcode-select --install
   # Ubuntu: sudo apt-get install swig build-essential
   # CentOS: sudo yum install swig && sudo yum groupinstall "Development Tools"
   ```

2. Install Python build dependencies:
   ```bash
   pip install -r requirements-build.txt
   ```

3. Build:
   ```bash
   cd src/
   python setup.py build
   ```

### Publishing
```bash
pip install -r requirements-build.txt
python publish_sdist.py
