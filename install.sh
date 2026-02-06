#!/usr/bin/env bash
# ============================================
# GRALPH Installer (macOS / Linux)
# Usage: curl -fsSL https://raw.githubusercontent.com/FacuVCanale/gralph/main/install.sh | bash
# ============================================

set -euo pipefail

REPO="https://github.com/FacuVCanale/gralph.git"
INSTALL_DIR="$HOME/.gralph"
BIN_DIR="$INSTALL_DIR/scripts/gralph"

echo ""
echo "  GRALPH Installer"
echo "  ================"
echo ""

# Check git
if ! command -v git &>/dev/null; then
    echo "  [ERROR] git is required. Install it first."
    exit 1
fi

# Clone or update
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

# Make executable
chmod +x "$BIN_DIR/gralph.sh"

# Create symlink so `gralph` works (not just `gralph.sh`)
mkdir -p "$HOME/.local/bin"
ln -sf "$BIN_DIR/gralph.sh" "$HOME/.local/bin/gralph"

# Detect shell and profile file
add_to_path() {
    local target_dir="$HOME/.local/bin"
    local shell_name profile_file

    shell_name="$(basename "${SHELL:-/bin/bash}")"
    case "$shell_name" in
        zsh)  profile_file="$HOME/.zshrc" ;;
        bash)
            if [[ -f "$HOME/.bash_profile" ]]; then
                profile_file="$HOME/.bash_profile"
            else
                profile_file="$HOME/.bashrc"
            fi
            ;;
        fish) profile_file="$HOME/.config/fish/config.fish" ;;
        *)    profile_file="$HOME/.profile" ;;
    esac

    # Check if already in PATH
    if echo "$PATH" | tr ':' '\n' | grep -qx "$target_dir"; then
        echo "  [OK] Already in PATH"
        return
    fi

    # Check if profile already has it
    if [[ -f "$profile_file" ]] && grep -q "$target_dir" "$profile_file" 2>/dev/null; then
        echo "  [OK] PATH entry already in $profile_file"
        return
    fi

    echo "  Adding to PATH in $profile_file ..."
    if [[ "$shell_name" == "fish" ]]; then
        echo "fish_add_path $target_dir" >> "$profile_file"
    else
        echo "" >> "$profile_file"
        echo "# gralph" >> "$profile_file"
        echo "export PATH=\"$target_dir:\$PATH\"" >> "$profile_file"
    fi
    echo "  [OK] Added $target_dir to PATH"
}

add_to_path

echo ""
echo "  Done! Restart your terminal (or source your profile), then run:"
echo ""
echo "    gralph --help           # show usage"
echo "    gralph --update         # update gralph"
echo "    gralph --init           # install skills in current repo"
echo ""
