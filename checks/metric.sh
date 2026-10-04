#!/usr/bin/env bash
# Juiz karpathy noturno — tempo (s) do ciclo completo de validação
# blackbr + lideriptv. Imprime EXATAMENTE 1 número; exit 0.
# Timings por passo ficam em /tmp/opencode/karpathy_cycle.log (stderr).
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1
venv/bin/python checks/cycle_runner.py \
  >/tmp/opencode/karpathy_cycle.out 2>/tmp/opencode/karpathy_cycle.log
rc=$?
if [ $rc -ne 0 ]; then
  tail -n 8 /tmp/opencode/karpathy_cycle.log >&2
  exit $rc
fi
OUT=$(tail -n 1 /tmp/opencode/karpathy_cycle.out)
echo "$OUT"
exit 0
