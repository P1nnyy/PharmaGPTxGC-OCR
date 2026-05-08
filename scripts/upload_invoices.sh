#!/bin/bash
# -----------------------------------------------------------------------------
# GCP-Optimized Invoice Upload Script
# Runs locally on Mac to batch upload invoices to GCP VM for OCR benchmarking.
# -----------------------------------------------------------------------------

set -euo pipefail

# Default Configuration
DRY_RUN=false
VERBOSE=false
SSH_KEY=""
DEFAULT_GCP_KEY="${HOME}/.ssh/google_compute_engine"
REMOTE_DIR="~/PharmaGPTxGC-OCR/test_images"

# Help / Usage Function
usage() {
    echo "====================================================================="
    echo " GCP Invoice Upload Tool"
    echo "====================================================================="
    echo "Usage: $0 [OPTIONS] <USER@VM_IP> [SSH_KEY_PATH]"
    echo ""
    echo "Options:"
    echo "  -d, --dry-run      Dry run: Show files to upload without performing it"
    echo "  -v, --verbose      Enable verbose SSH/SCP debugging outputs"
    echo "  -h, --help         Show this help menu"
    echo ""
    echo "Examples:"
    echo "  $0 pranavgupta1638@34.93.46.50"
    echo "  $0 pranavgupta1638@34.93.46.50 ~/.ssh/google_compute_engine"
    echo "  $0 --dry-run pranavgupta1638@34.93.46.50"
    echo "====================================================================="
    exit 1
}

# Parse Arguments
PARAMS=""
while (( "$#" )); do
    case "$1" in
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*|--*)
            echo "❌ Error: Unsupported option '$1'" >&2
            usage
            ;;
        *)
            PARAMS="$PARAMS $1"
            shift
            ;;
    esac
done

# Reset Positional Parameters
eval set -- "$PARAMS"

# Validate required positional parameters
if [ $# -lt 1 ]; then
    echo "❌ Error: Missing required target argument (USER@VM_IP)." >&2
    usage
fi

VM_TARGET=$1

# Handle custom key parameter if supplied
if [ $# -ge 2 ]; then
    SSH_KEY=$2
fi

echo "🔍 Starting GCP upload workflow..."

# Auto-detect default GCP key if none is provided
if [ -z "$SSH_KEY" ]; then
    if [ -f "$DEFAULT_GCP_KEY" ]; then
        SSH_KEY="$DEFAULT_GCP_KEY"
        echo "ℹ️ Auto-detected default GCP key: $SSH_KEY"
    else
        echo "ℹ️ No explicit key provided, and default '$DEFAULT_GCP_KEY' is missing."
        echo "ℹ️ Attempting to use default system keys/active ssh-agent."
    fi
fi

# Explicit validation of key path if specified or auto-detected
if [ -n "$SSH_KEY" ]; then
    if [ ! -f "$SSH_KEY" ]; then
        echo "❌ Error: Specified SSH key file does not exist: $SSH_KEY" >&2
        echo "💡 Tip: If you haven't yet, run 'gcloud compute ssh $VM_TARGET' on your Mac"
        echo "   to automatically generate GCP keys at '$DEFAULT_GCP_KEY'."
        exit 1
    fi
fi

# Build SSH and SCP connection options
SSH_OPTS="-o ConnectTimeout=10"
SCP_OPTS="-o ConnectTimeout=10"

if [ "$VERBOSE" = true ]; then
    echo "⚙️ Verbose logging enabled."
    SSH_OPTS="$SSH_OPTS -v"
    SCP_OPTS="$SCP_OPTS -v"
fi

if [ -n "$SSH_KEY" ]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
    SCP_OPTS="$SCP_OPTS -i $SSH_KEY"
fi

# Locate and gather images
shopt -s nullglob nocaseglob
files=(${HOME}/Desktop/invoices/*.jpg ${HOME}/Desktop/invoices/*.jpeg ${HOME}/Desktop/invoices/*.png)

if [ ${#files[@]} -eq 0 ]; then
    echo "❌ Error: No invoice images (.jpg, .jpeg, .png) found in ~/Desktop/invoices!" >&2
    exit 1
fi

echo "📂 Found ${#files[@]} images in ~/Desktop/invoices:"
for f in "${files[@]}"; do
    echo "   • $(basename "$f")"
done

# Execute Dry-Run Mode
if [ "$DRY_RUN" = true ]; then
    echo "🐪 [DRY RUN] Would test SSH connection and create remote folder: $REMOTE_DIR"
    echo "🐪 [DRY RUN] Would batch-upload ${#files[@]} images using SCP."
    echo "🚀 Dry run complete. No actions were performed."
    exit 0
fi

# Test SSH connection & prepare directory
echo "🌐 Connecting to $VM_TARGET and creating remote folder..."
set +e
ssh $SSH_OPTS "$VM_TARGET" "mkdir -p $REMOTE_DIR"
SSH_STATUS=$?
set -e

if [ $SSH_STATUS -ne 0 ]; then
    echo "❌ Error: SSH connection to $VM_TARGET failed (Exit Code: $SSH_STATUS)." >&2
    echo "💡 Recommendations:"
    echo "   1. Ensure the VM IP is correct and active."
    echo "   2. Ensure the VM user matches your GCP user."
    echo "   3. If your keys are managed by gcloud, run 'gcloud compute ssh $VM_TARGET' first"
    echo "      to populate your local ssh credentials."
    exit 1
fi

# Upload the images
echo "📤 Transferring ${#files[@]} images via SCP..."
set +e
scp $SCP_OPTS "${files[@]}" "$VM_TARGET:$REMOTE_DIR/"
SCP_STATUS=$?
set -e

if [ $SCP_STATUS -ne 0 ]; then
    echo "❌ Error: SCP transfer failed (Exit Code: $SCP_STATUS)." >&2
    exit 1
fi

echo "====================================================================="
echo "🎉 Success! All ${#files[@]} images uploaded to $VM_TARGET:$REMOTE_DIR/"
echo "====================================================================="
