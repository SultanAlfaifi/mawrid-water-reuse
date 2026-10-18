#!/bin/sh
set -eu
MAWRID_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)

# The virtual plant, API and SQLite store use the Python standard library.
# A research environment is optional and is never created by this launcher.
if [ -n "${MAWRID_PYTHON:-}" ]; then
  MAWRID_PYTHON=$(command -v "$MAWRID_PYTHON") || {
    printf '%s\n' 'تعذر العثور على MAWRID_PYTHON. حدّد مسار ملف Python التنفيذي.' >&2
    exit 1
  }
elif [ -x "$MAWRID_DIR/../ml/gecco_baseline/.venv/bin/python" ]; then
  MAWRID_PYTHON="$MAWRID_DIR/../ml/gecco_baseline/.venv/bin/python"
else
  MAWRID_PYTHON=$(command -v python3) || {
    printf '%s\n' 'يتطلب مورد Python 3.10 أو أحدث. ثبّت Python ثم أعد التشغيل.' >&2
    exit 1
  }
fi
if ! "$MAWRID_PYTHON" -B -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  printf '%s\n' 'يتطلب مورد Python 3.10 أو أحدث. يمكنك تحديده عبر MAWRID_PYTHON.' >&2
  exit 1
fi
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
exec "$MAWRID_PYTHON" -B "$MAWRID_DIR/server/main.py" "$@"
