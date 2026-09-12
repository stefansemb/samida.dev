#!/bin/bash
set -euo pipefail

SRC="/home/donste/services/samida"
DEST_DIR="/home/donste/services/samida-backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$DEST_DIR"
tar -czf "$DEST_DIR/samida-backup-$TIMESTAMP.tar.gz" -C "$SRC" .env data/samida.db data/attachments

# Keep only the 14 most recent backups.
cd "$DEST_DIR"
ls -1t samida-backup-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm --
