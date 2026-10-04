#!/usr/bin/env bash
# Juiz Karpathy — tempo (segundos) do ciclo de testes dos painéis blackbr + newmais.
# Imprime EXATAMENTE 1 número (s, 2 decimais) no stdout; exit 0.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1
START=$(date +%s.%N)
venv/bin/python -m pytest \
  tests/test_blackbr_crud.py tests/test_blackbr_scraper.py \
  tests/test_newmais_crud.py tests/test_newmais_scraper.py \
  -q -p no:cacheprovider >/dev/null 2>&1 || exit 1
END=$(date +%s.%N)
echo "$(bc <<< "$END - $START")"
exit 0
