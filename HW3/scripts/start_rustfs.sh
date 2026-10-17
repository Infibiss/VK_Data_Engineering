#!/bin/zsh
set -eu
task_dir="$(cd "$(dirname "$0")/.." && pwd)"
binary="${RUSTFS_BINARY:-$task_dir/../HW2/bin/rustfs}"
mkdir -p "$task_dir/volumes/disk1" "$task_dir/volumes/disk2" "$task_dir/volumes/disk3" "$task_dir/volumes/disk4"
export RUSTFS_ACCESS_KEY=hw3admin
export RUSTFS_SECRET_KEY=hw3-local-secret
export RUSTFS_STORAGE_CLASS_STANDARD=EC:2
export RUSTFS_ERASURE_SET_DRIVE_COUNT=4
export RUSTFS_UNSAFE_BYPASS_DISK_CHECK=true
exec "$binary" server --address 127.0.0.1:9100 --console-enable \
  --console-address 127.0.0.1:9101 "$task_dir/volumes/disk1" "$task_dir/volumes/disk2" \
  "$task_dir/volumes/disk3" "$task_dir/volumes/disk4"
