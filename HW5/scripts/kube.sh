#!/bin/sh
set -eu
hw5_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export KUBECONFIG="$hw5_dir/.runtime/kubeconfig"
exec kubectl "$@"
