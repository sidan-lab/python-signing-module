#!/usr/bin/env python3
"""
Python Signing Module Setup Script

This setup.py handles the complex multi-stage build process for the Python signing module:
1. Rust implementation compiled to static library
2. C++ bridge generated via cxx-build  
3. SWIG interface to generate Python bindings
4. Final Python extension module compilation

Prerequisites:
- Rust toolchain (cargo)
- SWIG 
- C++11 compatible compiler

Usage:
    python setup.py help_platforms       # Show platform-specific installation guide
    python setup.py check_prereq         # Check if prerequisites are installed
    pip install -e .                     # Development installation
    pip install .                        # Regular installation
"""

import os
import platform
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path
from setuptools import setup, Extension, Command
from setuptools.command.build_ext import build_ext
from setuptools.command.sdist import sdist
from setuptools.command.bdist_wheel import bdist_wheel


def read_requirements(filename):
    """Read requirements from a requirements file, filtering out comments and empty lines."""
    requirements_path = Path(__file__).parent / filename
    if not requirements_path.exists():
        return []
    
    with open(requirements_path, 'r', encoding='utf-8') as f:
        requirements = []
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith('#'):
                # Handle inline comments
                requirement = line.split('#')[0].strip()
                if requirement:
                    requirements.append(requirement)
        return requirements


def check_prerequisites(check_swig=True):
    """Check if all required build tools are installed.
    
    Args:
        check_swig (bool): Whether to check for SWIG. 
                          True for packaging/development, False for installation.
    """
    missing_tools = []
    
    # Always check for Rust/Cargo (needed for building static library)
    if not shutil.which('cargo'):
        missing_tools.append('cargo')
    else:
        # Check Rust version
        try:
            result = subprocess.run(['cargo', '--version'], capture_output=True, text=True, check=True)
            print(f"   ✓ Found {result.stdout.strip()}")
        except subprocess.CalledProcessError:
            missing_tools.append('cargo')
    
    # Conditionally check for SWIG
    if check_swig:
        if not shutil.which('swig'):
            missing_tools.append('swig')
        else:
            # Check SWIG version
            try:
                result = subprocess.run(['swig', '-version'], capture_output=True, text=True, check=True)
                version_line = [line for line in result.stdout.split('\n') if 'SWIG Version' in line][0]
                print(f"   ✓ Found {version_line.strip()}")
            except (subprocess.CalledProcessError, IndexError):
                print("   ✓ Found SWIG (version check failed)")
    else:
        print("   ⚪ Skipping SWIG check (using pre-generated files)")
    
    # Always check for C++ compiler (needed for compiling extension)
    compiler_result = check_cpp_compiler()
    if not compiler_result['found']:
        missing_tools.append('c++_compiler')
    else:
        print(f"   ✓ Found {compiler_result['name']} {compiler_result['version']}")
        print(f"     Command: {compiler_result['command']}")
        if compiler_result['cpp11_support']:
            print(f"   ✓ C++11 support confirmed")
        else:
            print(f"   ⚠️  C++11 support could not be verified")
        
        if compiler_result['warnings']:
            for warning in compiler_result['warnings']:
                print(f"   ⚠️  {warning}")
        else:
            print(f"   ✓ All compiler tests passed successfully")
    
    if missing_tools:
        print_installation_instructions(missing_tools)
        sys.exit(1)


def is_packaging_command():
    """Determine if we're running a packaging command that needs SWIG."""
    import sys
    
    # Commands that require SWIG for generating bindings
    packaging_commands = [
        'sdist', 'bdist', 'bdist_wheel', 'bdist_egg', 'bdist_rpm', 'bdist_wininst',
        'build_swig',  # Our custom command
        'egg_info',    # Sometimes run as part of packaging
    ]
    
    # Check command line arguments
    for arg in sys.argv:
        if arg in packaging_commands:
            return True
    
    return False


def check_cpp_compiler():
    """Comprehensive C++ compiler detection and capability testing."""
    
    # List of compilers to check (main commands only)
    compilers_to_test = [
        # GCC variants
        {'cmd': 'g++', 'name': 'GNU G++', 'type': 'gcc'},
        {'cmd': 'gcc', 'name': 'GNU GCC', 'type': 'gcc'},
        
        # Clang variants
        {'cmd': 'clang++', 'name': 'Clang++', 'type': 'clang'},
        {'cmd': 'clang', 'name': 'Clang', 'type': 'clang'},
        
        # MSVC variants
        {'cmd': 'cl', 'name': 'Microsoft Visual C++', 'type': 'msvc'},
        {'cmd': 'cl.exe', 'name': 'Microsoft Visual C++', 'type': 'msvc'},
        
        # Intel compiler
        {'cmd': 'icpc', 'name': 'Intel C++ Compiler', 'type': 'intel'},
        {'cmd': 'icc', 'name': 'Intel C Compiler', 'type': 'intel'},
        
        # Other compilers
        {'cmd': 'cc', 'name': 'System C Compiler', 'type': 'generic'},
        {'cmd': 'c++', 'name': 'System C++ Compiler', 'type': 'generic'},
    ]
    
    result = {
        'found': False,
        'name': '',
        'version': '',
        'command': '',
        'type': '',
        'cpp11_support': False,
        'warnings': []
    }
    
    # Test each compiler
    for compiler_info in compilers_to_test:
        compiler_cmd = compiler_info['cmd']
        
        if not shutil.which(compiler_cmd):
            continue
            
        # Found a compiler, now test it
        try:
            # Get version information
            version_info = get_compiler_version(compiler_cmd, compiler_info['type'])
            
            # Test C++11 compilation
            cpp11_works = test_cpp11_compilation(compiler_cmd, compiler_info['type'])
            
            # Test basic compilation with features we need
            additional_tests = test_compiler_features(compiler_cmd, compiler_info['type'])
            
            result.update({
                'found': True,
                'name': compiler_info['name'],
                'version': version_info,
                'command': compiler_cmd,
                'type': compiler_info['type'],
                'cpp11_support': cpp11_works,
                'warnings': additional_tests['warnings']
            })
            
            # If this compiler fully works, use it
            if cpp11_works and not additional_tests['critical_failures']:
                break
                
        except Exception as e:
            # This compiler doesn't work, try the next one
            continue
    
    return result


def get_compiler_version(compiler_cmd, compiler_type):
    """Get detailed version information for a compiler."""
    try:
        if compiler_type == 'msvc':
            # MSVC version detection is more complex
            result = subprocess.run([compiler_cmd], capture_output=True, text=True, timeout=10)
            if 'Microsoft' in result.stderr:
                lines = result.stderr.split('\n')
                for line in lines:
                    if 'Version' in line:
                        return line.strip()
                return "Microsoft Visual C++ (version unknown)"
            return "Microsoft Visual C++"
        else:
            # GCC, Clang, and most others support --version
            result = subprocess.run([compiler_cmd, '--version'], 
                                  capture_output=True, text=True, check=True, timeout=10)
            version_line = result.stdout.split('\n')[0].strip()
            return version_line
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return "(version unknown)"


def test_cpp11_compilation(compiler_cmd, compiler_type):
    """Test if the compiler can compile C++11 code."""
    cpp11_test_code = '''
#include <iostream>
#include <memory>
#include <vector>
#include <string>

// Test C++11 features
class TestClass {
public:
    TestClass() = default;
    TestClass(const TestClass&) = delete;
    TestClass& operator=(const TestClass&) = delete;
    
    void test_features() {
        // Auto keyword
        auto x = 42;
        
        // Range-based for loop
        std::vector<int> vec = {1, 2, 3, 4, 5};
        for (const auto& item : vec) {
            (void)item; // Suppress unused variable warning
        }
        
        // Smart pointers
        auto ptr = std::make_shared<int>(x);
        
        // Lambda expressions
        auto lambda = [](int a, int b) -> int { return a + b; };
        lambda(1, 2);
        
        // nullptr
        int* null_ptr = nullptr;
        (void)null_ptr;
    }
};

int main() {
    TestClass test;
    test.test_features();
    std::cout << "C++11 test successful" << std::endl;
    return 0;
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
        f.write(cpp11_test_code)
        source_file = f.name
    
    try:
        # Prepare compilation command
        if compiler_type == 'msvc':
            cmd = [compiler_cmd, '/std:c++11', '/EHsc', source_file, '/Fe:test_cpp11.exe']
        else:
            cmd = [compiler_cmd, '-std=c++11', '-o', 'test_cpp11', source_file]
        
        # Try to compile
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            # Compilation successful, try to run it
            if compiler_type == 'msvc':
                run_result = subprocess.run(['./test_cpp11.exe'], 
                                          capture_output=True, text=True, timeout=10)
            else:
                run_result = subprocess.run(['./test_cpp11'], 
                                          capture_output=True, text=True, timeout=10)
            
            # Clean up executable
            try:
                if compiler_type == 'msvc':
                    os.unlink('test_cpp11.exe')
                else:
                    os.unlink('test_cpp11')
            except OSError:
                pass
                
            return run_result.returncode == 0
        else:
            return False
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    finally:
        # Clean up source file
        try:
            os.unlink(source_file)
        except OSError:
            pass


def test_compiler_features(compiler_cmd, compiler_type):
    """Test additional compiler features and requirements."""
    warnings = []
    critical_failures = []
    
    # Test if compiler supports position independent code (needed for shared libraries)
    if compiler_type in ['gcc', 'clang']:
        try:
            result = subprocess.run([compiler_cmd, '-fPIC', '--help'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                warnings.append("Position Independent Code (-fPIC) support uncertain")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            warnings.append("Could not verify -fPIC support")
    
    # Test if we can find standard library headers
    header_test_code = '''
#include <iostream>
#include <string>
#include <vector>
#include <memory>
int main() { return 0; }
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
        f.write(header_test_code)
        header_test_file = f.name
    
    try:
        if compiler_type == 'msvc':
            cmd = [compiler_cmd, '/EHsc', header_test_file, '/Fe:test_headers.exe']
        else:
            cmd = [compiler_cmd, '-o', 'test_headers', header_test_file]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode != 0:
            critical_failures.append("Cannot compile basic C++ headers")
            warnings.append("Standard library headers may be missing or incompatible")
        
        # Clean up
        try:
            if compiler_type == 'msvc':
                os.unlink('test_headers.exe')
            else:
                os.unlink('test_headers')
        except OSError:
            pass
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        warnings.append("Could not verify standard library availability")
    finally:
        try:
            os.unlink(header_test_file)
        except OSError:
            pass
    
    # Check for known problematic compiler versions
    if compiler_type == 'gcc':
        try:
            result = subprocess.run([compiler_cmd, '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version_output = result.stdout
                # Extract GCC version
                import re
                match = re.search(r'gcc.*?(\d+)\.(\d+)\.(\d+)', version_output.lower())
                if match:
                    major, minor, patch = map(int, match.groups())
                    if major < 4 or (major == 4 and minor < 7):
                        warnings.append(f"GCC {major}.{minor}.{patch} is quite old, consider upgrading")
                    elif major >= 11:
                        # Very recent versions might have compatibility issues
                        pass  # Generally good
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    
    elif compiler_type == 'clang':
        try:
            result = subprocess.run([compiler_cmd, '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version_output = result.stdout
                import re
                match = re.search(r'clang.*?(\d+)\.(\d+)\.(\d+)', version_output.lower())
                if match:
                    major, minor, patch = map(int, match.groups())
                    if major < 3 or (major == 3 and minor < 3):
                        warnings.append(f"Clang {major}.{minor}.{patch} may not fully support C++11")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    
    # Test specific features that might be needed by the Rust/C++ bridge
    rust_bridge_test_code = '''
#include <iostream>
#include <stdexcept>
#include <cstdint>

// Test features commonly used in Rust-C++ bridges
extern "C" {
    // Test extern C linkage
    void test_extern_c() {
        // Empty function to test extern C
    }
}

// Test exception handling (often used in SWIG bindings)
class TestException : public std::exception {
public:
    const char* what() const noexcept override {
        return "Test exception";
    }
};

// Test fixed-width integer types (common in Rust interop)
int main() {
    uint8_t u8 = 255;
    uint16_t u16 = 65535;
    uint32_t u32 = 4294967295U;
    uint64_t u64 = 18446744073709551615ULL;
    
    int8_t i8 = -128;
    int16_t i16 = -32768;
    int32_t i32 = -2147483648;
    int64_t i64 = -9223372036854775807LL - 1;
    
    try {
        throw TestException();
    } catch (const std::exception& e) {
        // Exception handling works
    }
    
    return 0;
}
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
        f.write(rust_bridge_test_code)
        bridge_test_file = f.name
    
    try:
        if compiler_type == 'msvc':
            cmd = [compiler_cmd, '/EHsc', bridge_test_file, '/Fe:test_bridge.exe']
        else:
            cmd = [compiler_cmd, '-std=c++11', '-o', 'test_bridge', bridge_test_file]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode != 0:
            warnings.append("May have issues with Rust-C++ bridge features")
        else:
            # Try to run it
            try:
                if compiler_type == 'msvc':
                    run_result = subprocess.run(['./test_bridge.exe'], 
                                              capture_output=True, text=True, timeout=5)
                else:
                    run_result = subprocess.run(['./test_bridge'], 
                                              capture_output=True, text=True, timeout=5)
                
                if run_result.returncode != 0:
                    warnings.append("Rust-C++ bridge compatibility test failed at runtime")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                warnings.append("Could not verify Rust-C++ bridge runtime compatibility")
        
        # Clean up
        try:
            if compiler_type == 'msvc':
                os.unlink('test_bridge.exe')
            else:
                os.unlink('test_bridge')
        except OSError:
            pass
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        warnings.append("Could not verify Rust-C++ bridge compatibility")
    finally:
        try:
            os.unlink(bridge_test_file)
        except OSError:
            pass
    
    # Test threading support (may be needed by Rust libraries)
    if compiler_type in ['gcc', 'clang']:
        threading_test_code = '''
#include <thread>
#include <mutex>
#include <atomic>

std::mutex test_mutex;
std::atomic<int> test_atomic{0};

void test_thread_func() {
    std::lock_guard<std::mutex> lock(test_mutex);
    test_atomic++;
}

int main() {
    std::thread t(test_thread_func);
    t.join();
    return 0;
}
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
            f.write(threading_test_code)
            thread_test_file = f.name
        
        try:
            cmd = [compiler_cmd, '-std=c++11', '-pthread', '-o', 'test_threading', thread_test_file]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                warnings.append("Threading support may be limited (missing -pthread or thread library)")
            else:
                try:
                    os.unlink('test_threading')
                except OSError:
                    pass
                    
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            warnings.append("Could not verify threading support")
        finally:
            try:
                os.unlink(thread_test_file)
            except OSError:
                pass
    
    return {
        'warnings': warnings,
        'critical_failures': critical_failures
    }


def print_installation_instructions(missing_tools):
    """Print platform-specific installation instructions for missing tools."""
    system = platform.system().lower()
    
    print("\n" + "="*60)
    print("ERROR: Missing required build tools!")
    print("="*60)
    
    for tool in missing_tools:
        print(f"\n❌ {tool.upper()} not found")
        
        if tool == 'cargo':
            print("   Rust toolchain is required to build this package.")
            if system == 'darwin':  # macOS
                print("   Install with: brew install rust")
                print("   Or visit: https://rustup.rs/")
            elif system == 'linux':
                print("   Install with: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
                print("   Or use your package manager:")
                print("     - Ubuntu/Debian: sudo apt install rustc cargo")
                print("     - Fedora: sudo dnf install rust cargo")
                print("     - Arch: sudo pacman -S rust")
            elif system == 'windows':
                print("   Download and install from: https://rustup.rs/")
                print("   Or use: winget install Rustlang.Rustup")
            else:
                print("   Visit: https://rustup.rs/ for installation instructions")
        
        elif tool == 'swig':
            print("   SWIG is required to generate Python bindings.")
            if system == 'darwin':  # macOS
                print("   Install with: brew install swig")
            elif system == 'linux':
                print("   Install with your package manager:")
                print("     - Ubuntu/Debian: sudo apt install swig")
                print("     - Fedora: sudo dnf install swig")
                print("     - Arch: sudo pacman -S swig")
            elif system == 'windows':
                print("   Download from: http://www.swig.org/download.html")
                print("   Or use: winget install SWIG.SWIG")
                print("   Or with Chocolatey: choco install swig")
            else:
                print("   Visit: http://www.swig.org/ for installation instructions")
        
        elif tool == 'c++_compiler':
            print("   C++11 compatible compiler is required.")
            print("   Supported compilers: GCC, Clang, MSVC")
            
            if system == 'darwin':  # macOS
                print("   📦 RECOMMENDED: Install Xcode Command Line Tools")
                print("     xcode-select --install")
                print("   ")
                print("   🍺 ALTERNATIVE: Install via Homebrew")
                print("     brew install gcc          # Latest GCC")
                print("     brew install llvm         # Latest Clang")
                print("   ")
                print("   ✅ VERIFY: gcc --version or clang++ --version")
                
            elif system == 'linux':
                print("   📦 Install with your package manager:")
                print("   ")
                print("   🐧 Ubuntu/Debian:")
                print("     sudo apt update")
                print("     sudo apt install build-essential  # GCC + essential tools")
                print("     # OR for specific versions:")
                print("     sudo apt install gcc-11 g++-11")
                print("   ")
                print("   🎩 Fedora/RHEL/CentOS:")
                print("     sudo dnf groupinstall 'Development Tools'")
                print("     # OR specific packages:")
                print("     sudo dnf install gcc gcc-c++ make")
                print("   ")
                print("   🏹 Arch Linux:")
                print("     sudo pacman -S base-devel  # Includes GCC")
                print("     sudo pacman -S clang      # Alternative: Clang")
                print("   ")
                print("   ✅ VERIFY: g++ --version or clang++ --version")
                
            elif system == 'windows':
                print("   🏢 OPTION 1: Visual Studio (Recommended)")
                print("     Download Visual Studio Community (free):")
                print("     https://visualstudio.microsoft.com/downloads/")
                print("     ✓ Select 'Desktop development with C++' workload")
                print("     ✓ Includes MSVC compiler, Windows SDK, CMake")
                print("   ")
                print("   🔧 OPTION 2: Build Tools Only")
                print("     Download 'Build Tools for Visual Studio':")
                print("     https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022")
                print("     winget install Microsoft.VisualStudio.2022.BuildTools")
                print("   ")
                print("   🐧 OPTION 3: MinGW-w64 (Unix-like)")
                print("     Install MSYS2: https://www.msys2.org/")
                print("     pacman -S mingw-w64-x86_64-toolchain")
                print("     # Add C:\\msys64\\mingw64\\bin to PATH")
                print("   ")
                print("   📦 OPTION 4: Package Managers")
                print("     winget install LLVM.LLVM          # Clang")
                print("     choco install mingw               # MinGW")
                print("   ")
                print("   ✅ VERIFY: cl (MSVC) or g++ --version (MinGW) or clang++ --version")
                print("   💡 TIP: Use 'Developer Command Prompt' for MSVC")
                
            else:
                print("   Install a C++11 compatible compiler for your platform")
                print("   Minimum versions: GCC 4.7, Clang 3.3, MSVC 2013")
            
            print("   ")
            print("   🧪 TEST YOUR COMPILER:")
            print("     Create test.cpp with: #include <iostream>")
            print("                          int main() { std::cout << \"Hello C++11\\n\"; }")
            print("     Compile: g++ -std=c++11 test.cpp -o test")
            print("     Run: ./test")
    
    print("\n" + "="*60)
    print("After installing the missing tools, run the setup again.")
    print("="*60 + "\n")


class CustomBuildExt(build_ext):
    """Custom build extension to handle Rust -> C++ -> Python build pipeline."""
    
    def run(self):
        """Execute the custom build process."""
        print("Checking prerequisites for installation...")
        check_prerequisites(check_swig=False)  # Installation doesn't need SWIG
        print("✅ All prerequisites are available!")
        
        self.run_rust_build()
        
        # Verify SWIG files exist (they should be pre-generated during packaging)
        print("🐍 Using pre-generated SWIG files")
        self.verify_swig_files()
        
        super().run()
        
        print("\n🎉 Build completed successfully!")
        print("   The CardanoSigner module is ready to use.")
    
    def verify_swig_files(self):
        """Verify that required SWIG-generated files exist."""
        required_files = [
            ('src/signer_wrap.cxx', 'SWIG-generated C++ wrapper'),
            ('src/CardanoSigner.py', 'SWIG-generated Python module')
        ]
        
        missing_files = []
        for file_path, description in required_files:
            if not Path(file_path).exists():
                missing_files.append((file_path, description))
            else:
                print(f"   ✓ Found {description}: {file_path}")
        
        if missing_files:
            print("   ❌ Missing SWIG-generated files:")
            for file_path, description in missing_files:
                print(f"      - {file_path} ({description})")
            print("   💡 These files should be pre-generated during package creation")
            print("   💡 Try: python setup.py build_swig")
            raise FileNotFoundError("Required SWIG-generated files are missing")
    
    def run_rust_build(self):
        """Build the Rust library and copy necessary files."""
        print("🔨 Building Rust library...")
        
        try:
            # Build Rust library
            subprocess.check_call(['cargo', 'build'], cwd='.')
            print("   ✓ Rust library built successfully")
        except subprocess.CalledProcessError as e:
            print(f"   ❌ Failed to build Rust library: {e}")
            raise
        
        # Copy files as per build.sh
        src_dir = Path('src')
        target_dir = Path('target/debug')
        cxxbridge_dir = Path('target/cxxbridge')
        
        try:
            # Find the static library (platform-dependent naming)
            lib_src, lib_dst = self.find_static_library(target_dir, src_dir)
            
            if not lib_src.exists():
                raise FileNotFoundError(f"Static library not found: {lib_src}")
            
            if platform.system().lower() == 'windows':
                # Use Python's shutil.copy2 on Windows instead of cp
                shutil.copy2(str(lib_src), str(lib_dst))
            else:
                subprocess.check_call(['cp', '-f', str(lib_src), str(lib_dst)])
            
            print(f"   ✓ Static library copied: {lib_dst.name}")
            
            # Copy bridge headers
            lib_rs_h = cxxbridge_dir / 'signer/src/lib.rs.h'
            cxx_h = cxxbridge_dir / 'rust/cxx.h'
            
            if lib_rs_h.exists():
                if platform.system().lower() == 'windows':
                    shutil.copy2(str(lib_rs_h.resolve()), str(src_dir / 'lib.rs.h'))
                else:
                    subprocess.check_call([
                        'cp', '-f', str(lib_rs_h.resolve()), str(src_dir / 'lib.rs.h')
                    ])
                print("   ✓ lib.rs.h header copied")
            
            if cxx_h.exists():
                if platform.system().lower() == 'windows':
                    shutil.copy2(str(cxx_h.resolve()), str(src_dir / 'cxx.h'))
                else:
                    subprocess.check_call([
                        'cp', '-f', str(cxx_h.resolve()), str(src_dir / 'cxx.h')
                    ])
                print("   ✓ cxx.h header copied")
                
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            print(f"   ❌ Failed to copy build artifacts: {e}")
            raise
    
    def find_static_library(self, target_dir, src_dir):
        """Find the static library with platform-appropriate naming."""
        possible_names = get_possible_library_names()
        
        # Try to find the library
        for lib_name in possible_names:
            lib_src = target_dir / lib_name
            if lib_src.exists():
                # Use the same name in src directory
                lib_dst = src_dir / lib_name
                print(f"   ✓ Found static library: {lib_name}")
                return lib_src, lib_dst
        
        # If none found, default to the first option and let the error be handled upstream
        lib_name = possible_names[0]
        return target_dir / lib_name, src_dir / lib_name
    



class PlatformHelpCommand(Command):
    """Custom command to show platform-specific installation instructions."""
    description = 'Show platform-specific installation instructions'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.show_help()
    
    def show_help(self):
        print("\n" + "="*70)
        print("PYTHON SIGNING MODULE - PLATFORM INSTALLATION GUIDE")
        print("="*70)
        
        print("\n📋 PREREQUISITES:")
        print("   1. Rust toolchain (cargo)")
        print("   2. SWIG (Simplified Wrapper and Interface Generator)")
        print("   3. C++11 compatible compiler")
        
        print("\n🍎 MACOS:")
        print("   # Install Homebrew if not already installed")
        print("   /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        print("   ")
        print("   # Install prerequisites")
        print("   brew install rust swig")
        print("   xcode-select --install  # For C++ compiler")
        
        print("\n🐧 LINUX:")
        print("   # Ubuntu/Debian:")
        print("   sudo apt update")
        print("   sudo apt install build-essential swig")
        print("   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
        print("   ")
        print("   # Fedora:")
        print("   sudo dnf groupinstall 'Development Tools'")
        print("   sudo dnf install rust cargo swig")
        print("   ")
        print("   # Arch Linux:")
        print("   sudo pacman -S base-devel rust swig")
        
        print("\n🪟 WINDOWS:")
        print("   # Option 1: Using winget (Windows Package Manager)")
        print("   winget install Rustlang.Rustup")
        print("   winget install SWIG.SWIG")
        print("   # Install Visual Studio Build Tools from Microsoft")
        print("   ")
        print("   # Option 2: Using Chocolatey")
        print("   choco install rust swig visualstudio2022buildtools")
        print("   ")
        print("   # Option 3: Manual installation")
        print("   # Download Rust from: https://rustup.rs/")
        print("   # Download SWIG from: http://www.swig.org/download.html")
        print("   # Install Visual Studio Community or Build Tools")
        
        print("\n🔧 BUILD COMMANDS:")
        print("   # Check prerequisites")
        print("   python setup.py check_prereq")
        print("   python setup.py --check-prereq        # Alternative")
        print("   ")
        print("   # Show this help")
        print("   python setup.py help_platforms")
        print("   python setup.py --help-platforms      # Alternative")
        print("   ")
        print("   # Generate SWIG bindings (for development)")
        print("   python setup.py build_swig")
        print("   ")
        print("   # Create packages (includes SWIG generation)")
        print("   python setup.py sdist                 # Source package")
        print("   python setup.py bdist_wheel           # Binary wheel")
        print("   ")
        print("   # Development installation")
        print("   pip install -e .                      # Uses existing SWIG files")
        print("   ")
        print("   # Regular installation")
        print("   pip install .                         # Uses existing SWIG files")
        print("   ")
        print("   # Build only")
        print("   python setup.py build                 # Uses existing SWIG files")
        print("   ")
        print("   📝 NOTE: SWIG Workflow:")
        print("      • SWIG runs automatically during packaging (sdist/bdist_wheel)")
        print("      • Installation uses pre-generated SWIG files")
        print("      • Use 'build_swig' command to regenerate manually")
        print("   ")
        print("   📝 NOTE: Static library naming is platform-dependent:")
        print("      • Linux/macOS: libsigner.a")
        print("      • Windows MSVC: signer.lib")
        print("      • Windows MinGW: libsigner.a")
        
        print("\n🆘 TROUBLESHOOTING:")
        print("   • If cargo is not found: source ~/.cargo/env (Linux/macOS)")
        print("   • If build fails: ensure all prerequisites are in PATH")
        print("   • For Windows: use 'Developer Command Prompt' or 'x64 Native Tools'")
        print("   • Check tool versions with: cargo --version, swig -version")
        print("   • Compiler issues: python setup.py check_prereq (runs extensive tests)")
        print("   • Our setup tests C++11 features: auto, lambdas, smart pointers, etc.")
        print("   • If compiler test fails, try a different compiler or update existing one")
        
        print("\n" + "="*70)
        print("For more help, visit: https://github.com/sidan-lab/python-signing-module")
        print("="*70 + "\n")


class CheckPrereqCommand(Command):
    """Custom command to check prerequisites."""
    description = 'Check if all prerequisites are installed'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Automatically determine if SWIG check is needed based on context
        need_swig = is_packaging_command()
        
        if need_swig:
            print("Checking prerequisites for packaging/development...")
        else:
            print("Checking prerequisites for installation...")
            
        try:
            check_prerequisites(check_swig=need_swig)
            print("✅ All prerequisites are available!")
        except SystemExit:
            pass  # Error already printed by check_prerequisites


class BuildSwigCommand(Command):
    """Custom command to generate SWIG bindings."""
    description = 'Generate SWIG Python bindings'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        print("Checking prerequisites for SWIG generation...")
        check_prerequisites(check_swig=True)
        print("✅ All prerequisites are available!")
        
        generate_swig_bindings()


def generate_swig_bindings():
    """Generate SWIG bindings (shared function)."""
    print("🐍 Generating SWIG Python bindings...")
    
    try:
        swig_file = Path('src/signer.i')
        if not swig_file.exists():
            raise FileNotFoundError(f"SWIG interface file not found: {swig_file}")
        
        subprocess.check_call(['swig', '-c++', '-python', 'src/signer.i'])
        print("   ✓ Python bindings generated successfully")
        
        # Verify the generated files exist
        expected_files = ['src/signer_wrap.cxx', 'src/CardanoSigner.py']
        for file_path in expected_files:
            if not Path(file_path).exists():
                print(f"   ⚠️  Warning: Expected file {file_path} was not generated")
            else:
                print(f"   ✓ Generated {file_path}")
                
    except subprocess.CalledProcessError as e:
        print(f"   ❌ Failed to generate Python bindings: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"   ❌ {e}")
        sys.exit(1)


class CustomSdist(sdist):
    """Custom sdist that generates SWIG bindings before creating source distribution."""
    
    def run(self):
        """Generate SWIG bindings then create source distribution."""
        print("📦 Creating source distribution...")
        
        # Check prerequisites for packaging (including SWIG)
        print("Checking prerequisites for packaging...")
        check_prerequisites(check_swig=True)
        print("✅ All prerequisites are available!")
        
        # Generate SWIG bindings before packaging
        generate_swig_bindings()
        
        # Run the standard sdist
        super().run()
        
        print("✅ Source distribution created with pre-generated SWIG files")


class CustomBdistWheel(bdist_wheel):
    """Custom bdist_wheel that generates SWIG bindings before creating wheel."""
    
    def run(self):
        """Generate SWIG bindings then create wheel."""
        print("🎡 Creating wheel distribution...")
        
        # Check prerequisites for packaging (including SWIG)
        print("Checking prerequisites for packaging...")
        check_prerequisites(check_swig=True)
        print("✅ All prerequisites are available!")
        
        # Generate SWIG bindings before packaging
        generate_swig_bindings()
        
        # Run the standard bdist_wheel
        super().run()
        
        print("✅ Wheel created with pre-generated SWIG files")


def get_possible_library_names():
    """Get possible static library names for the current platform."""
    system = platform.system().lower()
    
    if system == 'windows':
        # Windows can have different naming depending on toolchain
        return [
            'signer.lib',        # MSVC style
            'libsigner.a',       # MinGW style
            'libsigner.lib',     # Alternative naming
        ]
    else:
        # Unix-like systems (Linux, macOS, etc.)
        return ['libsigner.a']


def get_static_library_name():
    """Get the expected static library name for the current platform."""
    system = platform.system().lower()
    
    if system == 'windows':
        # Try to detect toolchain (simplified detection)
        if shutil.which('cl') and not shutil.which('gcc'):
            return 'signer.lib'       # Pure MSVC environment
        else:
            return 'libsigner.a'      # MinGW or mixed environment
    else:
        return 'libsigner.a'          # Unix-like systems


# Define the extension module with platform-appropriate library
signer_extension = Extension(
    '_CardanoSigner',
    sources=[
        'src/signer_wrap.cxx', 
        'src/signer.cpp'
    ],
    extra_objects=[f'src/{get_static_library_name()}'],
    include_dirs=['src'],
    language='c++',
    extra_compile_args=['-std=c++11']
)

# Handle special help commands before setuptools processes arguments
if __name__ == '__main__' and len(sys.argv) > 1:
    if '--help-platforms' in sys.argv:
        PlatformHelpCommand().show_help()
        sys.exit(0)
    elif '--check-prereq' in sys.argv:
        # For --check-prereq flag, default to checking for installation context
        print("Checking prerequisites for installation...")
        try:
            check_prerequisites(check_swig=False)
            print("✅ All prerequisites are available!")
        except SystemExit:
            pass  # Error already printed by check_prerequisites
        sys.exit(0)

# Read README for long description
readme_path = Path(__file__).parent / 'README.md'
if readme_path.exists():
    with open(readme_path, 'r', encoding='utf-8') as f:
        long_description = f.read()
else:
    long_description = 'Python signing module, implementation in Rust, ported over to C++, then to Python.'

setup(
    name='python-signing-module',
    version='0.1.0',
    author='Your Name',
    author_email='your.email@example.com',
    description='Python signing module for Cardano transactions',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/sidan-lab/python-signing-module',
    packages=[],  # No packages, just extension modules
    package_dir={'': 'src'},  # Tell setup.py to look for modules in src/
    py_modules=['CardanoSigner'],
    ext_modules=[signer_extension],
    cmdclass={
        'build_ext': CustomBuildExt,
        'help_platforms': PlatformHelpCommand,
        'check_prereq': CheckPrereqCommand,
        'build_swig': BuildSwigCommand,
        'sdist': CustomSdist,
        'bdist_wheel': CustomBdistWheel,
    },
    python_requires='>=3.7',
    install_requires=read_requirements('requirements.txt'),
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Rust',
        'Programming Language :: C++',
        'Topic :: Security :: Cryptography',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    keywords='cardano signing cryptocurrency blockchain',
    include_package_data=True,
    zip_safe=False,
) 