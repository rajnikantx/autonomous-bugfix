from __future__ import annotations
import os


def read_file(file_path: str) -> str:
    """
    Read a file and return its full content with line numbers.

    Use when:
      - Config files (always small, always read fully)
      - Small files under ~100 lines
      - Agent explicitly needs the whole file

    For large files: prefer extract_snippet to avoid flooding context.

    Returns error string if not found — never raises.
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if not lines:
            return f"(empty file: {file_path})"

        numbered = [f"{i + 1:4d} | {line}" for i, line in enumerate(lines)]
        header   = f"# {file_path}  ({len(lines)} lines)\n"
        return header + "".join(numbered)

    except Exception as e:
        return f"ERROR reading {file_path}: {e}"


def apply_patch(
    file_path: str,
    old_code: str,
    new_code: str,
) -> bool:
    """
    Replace old_code with new_code in file_path.

    Returns True on success, False on failure.
    Validates syntax of new_code before writing.
    old_code must appear EXACTLY ONCE — prevents silent multi-replacement.

    Called by Fixer node — always pass absolute path inside sandbox.
    """
    if not os.path.exists(file_path):
        print(f"[apply_patch] ERROR: file not found: {file_path}")
        return False

    # Read current content
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[apply_patch] ERROR reading {file_path}: {e}")
        return False

    # Validate old_code exists exactly once
    count = content.count(old_code)
    if count == 0:
        print(
            f"[apply_patch] ERROR: old_code not found in {file_path}.\n"
            "Ensure old_code is copied exactly from read_file/extract_snippet output\n"
            "(including indentation, spaces, and newlines)."
        )
        return False
    if count > 1:
        print(
            f"[apply_patch] ERROR: old_code appears {count} times in {file_path}.\n"
            "Add more surrounding lines to make old_code unique."
        )
        return False

    new_content = content.replace(old_code, new_code, 1)

    # Validate syntax of the entire new file before writing
    syntax_error = _validate_syntax(new_content, file_path)
    if syntax_error:
        print(f"[apply_patch] ERROR: new_code produces invalid Python syntax:\n{syntax_error}")
        return False

    # Write to disk
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"[apply_patch] ERROR writing {file_path}: {e}")
        return False


def write_file(file_path: str, content: str) -> None:
    """
    Internal helper — write content to a file.
    Not exposed to LLM. Called by apply_patch only.
    """
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def _validate_syntax(code: str, filename: str = "<string>") -> str:
    """
    Compile code and return error message if syntax is invalid.
    Returns empty string if syntax is valid.
    Internal — called by apply_patch before writing.
    """
    try:
        compile(code, filename, "exec")
        return ""
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return str(e)