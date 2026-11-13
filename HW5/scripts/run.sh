#!/bin/sh
set -eu
hw5_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo_dir=$(dirname "$hw5_dir")
cd "$repo_dir"
kube="$hw5_dir/scripts/kube.sh"
kind_bin=${KIND_BIN:-kind}
log_dir=${LOG_DIR:-$hw5_dir/.runtime/repeat-logs}
mkdir -p "$log_dir"
case "${1:-}" in
cluster)
    docker build -f HW5/Dockerfile -t hw5-job:local . > "$log_dir/image-build.log" 2>&1
    "$kind_bin" create cluster --name hw5 --config HW5/manifests/kind.yaml \
        --image kindest/node:v1.35.0 --kubeconfig "$hw5_dir/.runtime/kubeconfig" --wait 120s
    "$kind_bin" load docker-image hw5-job:local --name hw5
    "$kube" apply -f HW5/manifests/namespace.yaml -f HW5/manifests/s3-config.yaml
    "$kube" get nodes -o wide > "$log_dir/cluster.log"
    ;;
memory)
    "$kube" -n hw5 delete job pairs-oom pairs-profile pairs-calibrated --ignore-not-found
    "$kube" apply -f HW5/manifests/pairs-oom.yaml -f HW5/manifests/pairs-profile.yaml
    "$kube" -n hw5 wait --for=condition=failed job/pairs-oom --timeout=180s
    "$kube" -n hw5 describe pod -l app=pairs-oom > "$log_dir/oom.log"
    grep -q "Reason:.*OOMKilled" "$log_dir/oom.log"
    grep -q "Exit Code:.*137" "$log_dir/oom.log"
    "$kube" -n hw5 wait --for=condition=complete job/pairs-profile --timeout=240s
    "$kube" -n hw5 logs job/pairs-profile > "$log_dir/pairs-profile.log"
    python3 - "$log_dir" <<'PYMEM'
import json, math, sys
from pathlib import Path
logs = Path(sys.argv[1])
profile = json.loads((logs / 'pairs-profile.log').read_text())
peak = max(profile['peak_rss_mib'], profile.get('cgroup_memory_peak_mib', 0))
required = math.ceil(peak * 1.25 / 16) * 16
(logs / 'memory-limit.json').write_text(json.dumps(
    {'measured_peak_mib': peak, 'required_limit_mib': required,
     'configured_limit_mib': 80, 'reserve_factor': 1.25}, indent=2) + '\n')
assert required <= 80, 'New peak requires raising the calibrated manifest limit'
PYMEM
    "$kube" apply -f HW5/manifests/pairs-calibrated.yaml
    "$kube" -n hw5 wait --for=condition=complete job/pairs-calibrated --timeout=240s
    "$kube" -n hw5 logs job/pairs-calibrated > "$log_dir/pairs-calibrated.log"
    ;;
storage)
    docker pull rustfs/rustfs:1.0.1
    "$kind_bin" load docker-image rustfs/rustfs:1.0.1 --name hw5
    "$kube" apply -f HW5/manifests/rustfs.yaml
    "$kube" -n hw5 rollout status deployment/rustfs --timeout=120s
    ;;
migrate)
    docker run --rm --entrypoint python -v "$repo_dir:/workspace:ro" \
        hw5-job:local /workspace/HW5/scripts/migrate.py > "$log_dir/s3-migration.log"
    ;;
parallel)
    "$kube" -n hw5 delete job split pairs-parallel pairs-reduce --ignore-not-found
    "$kube" apply -f HW5/manifests/split.yaml
    "$kube" -n hw5 wait --for=condition=complete job/split --timeout=300s
    "$kube" -n hw5 logs job/split > "$log_dir/split.log"
    "$kube" apply -f HW5/manifests/pairs-parallel.yaml
    "$kube" -n hw5 wait --for=condition=complete job/pairs-parallel --timeout=240s
    "$kube" -n hw5 get pods -l app=pairs-parallel -o name | while IFS= read -r hw5_pod; do
        "$kube" -n hw5 logs "$hw5_pod" --prefix=true
    done > "$log_dir/parallel.log"
    "$kube" apply -f HW5/manifests/pairs-reduce.yaml
    "$kube" -n hw5 wait --for=condition=complete job/pairs-reduce --timeout=180s
    "$kube" -n hw5 logs job/pairs-reduce > "$log_dir/reduce.log"
    "$kube" -n hw5 get jobs > "$log_dir/jobs-final.log"
    ;;
scheduling)
    "$kube" apply -f HW5/manifests/hw5-scheduling.yaml -f HW5/manifests/hw5-quota.yaml \
        -f HW5/manifests/priorities.yaml -f HW5/manifests/quota.yaml
    "$kube" -n hw5-scheduling delete pod cpu-holder cpu-waiter priority-low priority-high --ignore-not-found
    "$kube" -n hw5-quota delete pod quota-first quota-excess --ignore-not-found
    "$kube" apply -f HW5/manifests/cpu-holder.yaml
    "$kube" -n hw5-scheduling wait --for=condition=Ready pod/cpu-holder --timeout=60s
    "$kube" apply -f HW5/manifests/cpu-waiter.yaml
    "$kube" -n hw5-scheduling wait \
        --for='jsonpath={.status.conditions[?(@.type=="PodScheduled")].reason}=Unschedulable' \
        pod/cpu-waiter --timeout=60s
    "$kube" -n hw5-scheduling describe pod cpu-waiter > "$log_dir/cpu-pending.log"
    grep -q "Insufficient cpu" "$log_dir/cpu-pending.log"
    "$kube" -n hw5-scheduling delete pod cpu-holder
    "$kube" -n hw5-scheduling wait --for=condition=Ready pod/cpu-waiter --timeout=60s
    "$kube" -n hw5-scheduling describe pod cpu-waiter > "$log_dir/cpu-released.log"
    "$kube" -n hw5-scheduling delete pod cpu-waiter
    "$kube" apply -f HW5/manifests/priority-low.yaml
    "$kube" -n hw5-scheduling wait --for=condition=Ready pod/priority-low --timeout=60s
    "$kube" apply -f HW5/manifests/priority-high.yaml
    "$kube" -n hw5-scheduling wait --for=condition=Ready pod/priority-high --timeout=90s
    "$kube" -n hw5-scheduling get events --sort-by=.metadata.creationTimestamp > "$log_dir/preemption.log"
    grep -q "Preempted.*priority-low" "$log_dir/preemption.log"
    "$kube" -n hw5-scheduling describe pod priority-high >> "$log_dir/preemption.log"
    "$kube" -n hw5-scheduling delete pod priority-high
    "$kube" apply -f HW5/manifests/quota-first.yaml
    "$kube" -n hw5-quota wait --for=condition=Ready pod/quota-first --timeout=60s
    "$kube" -n hw5-quota describe resourcequota compute > "$log_dir/quota.log"
    if "$kube" create -f HW5/manifests/quota-excess.yaml >> "$log_dir/quota.log" 2>&1; then
        echo 'Expected quota rejection' >&2
        exit 1
    fi
    grep -q "exceeded quota" "$log_dir/quota.log"
    "$kube" -n hw5-quota delete pod quota-first
    ;;
collect)
    mkdir -p "$hw5_dir/.runtime/repeat-results"
    docker run --rm --entrypoint python -v "$repo_dir:/workspace" hw5-job:local \
        /workspace/HW5/scripts/collect.py --output-dir /workspace/HW5/.runtime/repeat-results \
        > "$log_dir/verification.log"
    ;;
*)
    echo 'Usage: run.sh cluster|memory|storage|migrate|parallel|scheduling|collect' >&2
    exit 2
    ;;
esac
