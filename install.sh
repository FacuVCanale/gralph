#!/usr/bin/env bash
# ============================================
# GRALPH Installer (macOS / Linux)
# Usage: curl -fsSL https://raw.githubusercontent.com/FacuVCanale/gralph/main/install.sh | bash
# ============================================

set -euo pipefail

REPO="https://github.com/FacuVCanale/gralph.git"
INSTALL_DIR="$HOME/.gralph"
MIN_PYTHON="3.10"

echo ""
echo "  GRALPH Installer"
echo "  ================"
echo ""

# ── Check git ───────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "  [ERROR] git is required. Install it first."
    exit 1
fi

# ── Check Python 3.10+ ─────────────────────────────────────────────
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        py_version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [[ -n "$py_version" ]]; then
            major="${py_version%%.*}"
            minor="${py_version#*.}"
            if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
                PYTHON="$candidate"
                break
            fi
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "  [ERROR] Python $MIN_PYTHON+ is required."
    echo "  Install from https://www.python.org/downloads/"
    exit 1
fi
echo "  [OK] Found $PYTHON ($py_version)"

# ── Ensure pipx ────────────────────────────────────────────────────
if ! command -v pipx &>/dev/null; then
    echo "  Installing pipx..."
    "$PYTHON" -m pip install --user pipx 2>/dev/null || {
        echo "  [ERROR] Could not install pipx. Install manually:"
        echo "    $PYTHON -m pip install --user pipx"
        exit 1
    }
    "$PYTHON" -m pipx ensurepath 2>/dev/null || true
    # Try to find pipx after install
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v pipx &>/dev/null; then
        echo "  [WARN] pipx installed but not in PATH yet."
        echo "  Restart your terminal and run this installer again."
        exit 1
    fi
fi
echo "  [OK] Found pipx"

# ── Clone or update repo ──────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "  Updating existing installation..."
    git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || {
        echo "  [WARN] git pull failed, resetting..."
        git -C "$INSTALL_DIR" fetch origin 2>/dev/null
        git -C "$INSTALL_DIR" reset --hard origin/main 2>/dev/null
    }
    echo "  [OK] Updated"
else
    rm -rf "$INSTALL_DIR"
    echo "  Cloning gralph to $INSTALL_DIR ..."
    git clone --depth 1 "$REPO" "$INSTALL_DIR" 2>/dev/null
    echo "  [OK] Cloned"
fi

# ── Install Python package via pipx ───────────────────────────────
echo "  Installing gralph CLI via pipx..."
pipx install "$INSTALL_DIR" --force 2>/dev/null || {
    echo "  [ERROR] pipx install failed."
    echo "  Try manually: pipx install $INSTALL_DIR"
    exit 1
}
echo "  [OK] Installed"

echo ""
echo "  Done! Restart your terminal, then run:"
echo ""
echo "    gralph --help           # show usage"
echo "    gralph --update         # update gralph"
echo "    gralph --init           # install skills in current repo"
echo ""
