#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
export RUSTFS_ACCESS_KEY=hw2admin
export RUSTFS_SECRET_KEY=hw2-local-secret
export RUSTFS_STORAGE_CLASS_STANDARD=EC:2
export RUSTFS_ERASURE_SET_DRIVE_COUNT=4
export RUSTFS_UNSAFE_BYPASS_DISK_CHECK=true
exec ./bin/rustfs server --address 127.0.0.1:9000 --console-enable \
  --console-address 127.0.0.1:9001 "$PWD/volumes/disk1" "$PWD/volumes/disk2" \
  "$PWD/volumes/disk3" "$PWD/volumes/disk4"
