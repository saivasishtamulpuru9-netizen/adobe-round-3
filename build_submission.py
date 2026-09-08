#!/usr/bin/env python3
"""
build_submission.py — Automated Test Runner and Submission Packager
Adobe University Hackathon 2026 — Round 3: Agent Skill Marketplace

This script:
1. Runs all smoke and unit test suites inside `brand-ai-readiness-audit/`.
2. Aborts packaging if any test suite fails.
3. Packages `brand-ai-readiness-audit/` into `brand-ai-readiness-audit-submission.zip`
   excluding temporary files, caches, and git metadata.
4. Outputs verification summary including file size and SHA-256 checksum.
"""

import os
import sys
import hashlib
import zipfile
import subprocess

TEST_FILES = [
    "smoke_test_dv.py",
    "smoke_test_fs.py",
    "smoke_test_en.py",
    "smoke_test_ed.py",
    "smoke_test_orchestrator.py",
    "test_dv_checks_stdlib.py"
]

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".vscode",
    ".idea"
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".zip",
    ".DS_Store"
}

EXCLUDE_FILES = {
    ".DS_Store"
}

def run_tests(marketplace_dir):
    print("=" * 60)
    print(" 🧪 RUNNING TEST SUITES BEFORE PACKAGING")
    print("=" * 60)

    passed_files = 0
    total_files = len(TEST_FILES)

    for test_file in TEST_FILES:
        test_path = os.path.join(marketplace_dir, test_file)
        if not os.path.isfile(test_path):
            print(f"❌ [FAIL] Missing test file: {test_file}")
            return False

        print(f"\n▶ Running {test_file}...")
        res = subprocess.run([sys.executable, test_file], cwd=marketplace_dir)
        if res.returncode != 0:
            print(f"❌ [FAIL] {test_file} failed with exit code {res.returncode}")
            return False
        else:
            print(f"✅ [PASS] {test_file}")
            passed_files += 1

    print("\n" + "=" * 60)
    print(f" SUCCESS: {passed_files}/{total_files} Test Suites Passed")
    print("=" * 60 + "\n")
    return True

def package_submission(repo_root, marketplace_dir, zip_output_path):
    print("=" * 60)
    print(" 📦 PACKAGING BRAND-AI-READINESS-AUDIT SUBMISSION ZIP")
    print("=" * 60)

    count = 0
    with zipfile.ZipFile(zip_output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(marketplace_dir):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTENSIONS or file in EXCLUDE_FILES:
                    continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, marketplace_dir)
                
                # Normalize zip entry paths to forward slashes
                arcname = rel_path.replace(os.sep, '/')
                zf.write(full_path, arcname=arcname)
                count += 1

    print(f"✅ Successfully archived {count} files into '{os.path.basename(zip_output_path)}'.")

def compute_checksum_and_size(filepath):
    size_bytes = os.path.getsize(filepath)
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()
    return size_bytes, sha256_hash

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = script_dir
    marketplace_dir = os.path.join(repo_root, "brand-ai-readiness-audit")
    zip_output_path = os.path.join(repo_root, "brand-ai-readiness-audit-submission.zip")

    if not os.path.isdir(marketplace_dir):
        print(f"Error: Marketplace directory not found at {marketplace_dir}")
        sys.exit(1)

    # 1. Run tests
    if not run_tests(marketplace_dir):
        print("\n❌ BUILD ABORTED: One or more test suites failed.")
        sys.exit(1)

    # 2. Build zip
    package_submission(repo_root, marketplace_dir, zip_output_path)

    # 3. Report metrics
    size_bytes, sha256_hash = compute_checksum_and_size(zip_output_path)
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024

    print("\n" + "=" * 60)
    print(" 📊 SUBMISSION BUILD SUMMARY")
    print("=" * 60)
    print(f"  Status:         PASS (All 6 test suites passed)")
    print(f"  Output Archive: {zip_output_path}")
    print(f"  Archive Size:   {size_bytes:,} bytes ({size_kb:.2f} KB / {size_mb:.3f} MB)")
    print(f"  SHA-256:        {sha256_hash}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
