#!/usr/bin/env python3
"""
build_submission.py — Automated Test Runner, Packager, and Zip Verifier
Adobe University Hackathon 2026 — Round 3: Agent Skill Marketplace

This script:
1. Cleans temporary files (__pycache__, *.pyc, .DS_Store).
2. Runs all smoke and unit test suites inside `brand-ai-readiness-audit/`.
3. Aborts packaging if any test suite fails.
4. Packages the CONTENTS of `brand-ai-readiness-audit/` into
   `brand-ai-readiness-audit-submission.zip` at the repo root.
5. Extracts and verifies the freshly built zip against requirements:
   - Ensures top-level marketplace.json and 5 skill folders.
   - Rejects leaked __pycache__, .pyc, .gitignore files.
   - Rejects known stale report files (e.g. tgbie_bot_block.json).
6. Outputs a PASS/FAIL summary including zip size and SHA-256 checksum.
"""

import os
import sys
import shutil
import hashlib
import zipfile
import tempfile
import subprocess

# Ensure UTF-8 output encoding for Windows command line environments
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

TEST_FILES = [
    "smoke_test_dv.py",
    "smoke_test_fs.py",
    "smoke_test_en.py",
    "smoke_test_ed.py",
    "smoke_test_orchestrator.py",
    "test_dv_checks_stdlib.py"
]

SKILL_FOLDERS = [
    "audit-orchestrator",
    "crawl-render-audit",
    "freshness-corroboration",
    "engagement-audit",
    "entity-disambiguation"
]

KNOWN_STALE_REPORTS = [
    "tgbie_bot_block.json"
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
    ".DS_Store",
    ".gitignore"
}

MAX_ZIP_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

def clean_directory(target_dir):
    """Recursively delete __pycache__, *.pyc, .DS_Store from target_dir."""
    cleaned_count = 0
    for root, dirs, files in os.walk(target_dir, topdown=False):
        for d in dirs:
            if d == '__pycache__':
                dir_path = os.path.join(root, d)
                shutil.rmtree(dir_path, ignore_errors=True)
                cleaned_count += 1
        for f in files:
            if f.endswith('.pyc') or f == '.DS_Store':
                file_path = os.path.join(root, f)
                try:
                    os.remove(file_path)
                    cleaned_count += 1
                except OSError:
                    pass
    return cleaned_count

def run_tests(marketplace_dir):
    """Run all smoke test suites and abort if any test fails."""
    print("=" * 60)
    print(" [TEST] Running test suites inside brand-ai-readiness-audit/...")
    print("=" * 60)

    passed_files = 0
    total_files = len(TEST_FILES)

    for test_file in TEST_FILES:
        test_path = os.path.join(marketplace_dir, test_file)
        if not os.path.isfile(test_path):
            print(f"  [FAIL] Missing test file: {test_file}")
            return False

        print(f"\n- Running {test_file}...")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        res = subprocess.run([sys.executable, test_file], cwd=marketplace_dir, env=env)
        if res.returncode != 0:
            print(f"\n  [FAIL] {test_file} failed with exit code {res.returncode}")
            return False
        else:
            print(f"  [PASS] {test_file}")
            passed_files += 1

    print("\n" + "=" * 60)
    print(f" [PASS] All {passed_files}/{total_files} test suites passed successfully.")
    print("=" * 60 + "\n")
    return True

def package_submission(marketplace_dir, zip_output_path):
    """Zip the contents of brand-ai-readiness-audit/ (without wrapper folder)."""
    print("=" * 60)
    print(" [BUILD] Packaging brand-ai-readiness-audit-submission.zip...")
    print("=" * 60)

    count = 0
    with zipfile.ZipFile(zip_output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(marketplace_dir):
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

    print(f" [OK] Archived {count} files into '{os.path.basename(zip_output_path)}'.\n")

def verify_submission_zip(zip_output_path):
    """Extract zip to temp directory and run verification checks."""
    print("=" * 60)
    print(" [VERIFY] Verifying generated submission zip archive...")
    print("=" * 60)

    # 1. Size check
    size_bytes = os.path.getsize(zip_output_path)
    if size_bytes > MAX_ZIP_SIZE_BYTES:
        print(f"  [FAIL] Zip size exceeds 50MB limit: {size_bytes / (1024*1024):.2f} MB")
        return False
    print(f"  [PASS] Zip size is within limits: {size_bytes / 1024:.2f} KB (< 50 MB)")

    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_output_path, 'r') as zf:
            zf.extractall(temp_dir)

        # 2. Check marketplace.json at top level
        marketplace_json_path = os.path.join(temp_dir, "marketplace.json")
        if not os.path.isfile(marketplace_json_path):
            print("  [FAIL] marketplace.json is NOT at the top level of the zip archive.")
            return False
        print("  [PASS] marketplace.json found at zip top level.")

        # 3. Check all 5 skill folders present in skills/
        skills_dir = os.path.join(temp_dir, "skills")
        if not os.path.isdir(skills_dir):
            print("  [FAIL] 'skills/' directory missing in extracted zip.")
            return False

        for skill in SKILL_FOLDERS:
            skill_path = os.path.join(skills_dir, skill)
            if not os.path.isdir(skill_path):
                print(f"  [FAIL] Missing skill directory: skills/{skill}")
                return False
        print(f"  [PASS] All {len(SKILL_FOLDERS)} skill directories present under skills/.")

        # 4. Check no __pycache__, *.pyc, .gitignore leaked in
        leaked = []
        for root, dirs, files in os.walk(temp_dir):
            for d in dirs:
                if d == "__pycache__":
                    leaked.append(os.path.join(root, d))
            for f in files:
                if f == ".gitignore" or f.endswith(".pyc") or f == ".DS_Store":
                    leaked.append(os.path.join(root, f))

        if leaked:
            print(f"  [FAIL] Leaked files/folders detected in zip: {leaked}")
            return False
        print("  [PASS] No __pycache__, .gitignore, *.pyc, or .DS_Store files leaked in.")

        # 5. Check reports/ does not contain known-stale filenames
        reports_dir = os.path.join(temp_dir, "reports")
        if os.path.isdir(reports_dir):
            for stale_file in KNOWN_STALE_REPORTS:
                stale_path = os.path.join(reports_dir, stale_file)
                if os.path.exists(stale_path):
                    print(f"  [FAIL] Known stale report file found: reports/{stale_file}")
                    return False
        print("  [PASS] No known-stale report files found in reports/.")

    print("=" * 60)
    print(" [PASS] All submission zip verification checks passed successfully.")
    print("=" * 60 + "\n")
    return True

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
        print(f"[ERROR] Marketplace directory not found at {marketplace_dir}")
        sys.exit(1)

    # Step a & b: Clean temporary files from brand-ai-readiness-audit/
    cleaned = clean_directory(marketplace_dir)
    if cleaned > 0:
        print(f"[CLEAN] Cleaned {cleaned} temporary files/directories from brand-ai-readiness-audit/.")

    # Step c: Run tests inside brand-ai-readiness-audit/
    if not run_tests(marketplace_dir):
        if os.path.exists(zip_output_path):
            try:
                os.remove(zip_output_path)
            except OSError:
                pass
        print("\n❌ BUILD ABORTED: One or more test suites failed. No submission zip produced.")
        sys.exit(1)

    # Step d: Package submission zip
    package_submission(marketplace_dir, zip_output_path)

    # Step e: Verify zip contents
    if not verify_submission_zip(zip_output_path):
        if os.path.exists(zip_output_path):
            try:
                os.remove(zip_output_path)
            except OSError:
                pass
        print("\n❌ BUILD ABORTED: Verification checks failed. Removed submission zip.")
        sys.exit(1)

    # Step f: Report PASS/FAIL summary, size, and SHA-256 checksum
    size_bytes, sha256_hash = compute_checksum_and_size(zip_output_path)
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024

    print("=" * 60)
    print(" 📊 SUBMISSION BUILD SUMMARY")
    print("=" * 60)
    print(f"  Status:         PASS (All test suites & verification checks passed)")
    print(f"  Output Archive: {os.path.basename(zip_output_path)}")
    print(f"  Archive Path:   {zip_output_path}")
    print(f"  Archive Size:   {size_bytes:,} bytes ({size_kb:.2f} KB / {size_mb:.3f} MB)")
    print(f"  SHA-256:        {sha256_hash}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()

