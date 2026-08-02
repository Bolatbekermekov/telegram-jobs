#!/usr/bin/env bash
# Собирает резюме под каждую роль из sender/cv/<роль>/cv.tex и проверяет
# главное: КАЖДОЕ должно остаться на одной странице. Двухстраничное резюме на
# Junior/Middle читают хуже одностраничного, а переполнение происходит молча —
# LaTeX просто переносит хвост и ничего не говорит.
#
# Сами резюме в git не попадают (sender/cv/* в .gitignore, репозиторий
# публичный, в .tex телефон и почта). Версионируется только этот скрипт.
#
# Требуется tectonic: brew install tectonic
set -uo pipefail

CV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cv"
PYTHON="$(dirname "$CV_DIR")/.venv/bin/python"

# Роль -> имя PDF, которое увидит рекрутёр. Имя файла читают до содержимого,
# поэтому оно называет роль, а не «(FD)».
declare -a ROLES=(
  "ai:Bolatbek_Yermekov_AI_Engineer"
  "backend-node:Bolatbek_Yermekov_Backend_NodeJS"
  "backend-go:Bolatbek_Yermekov_Backend_Go"
  "backend-python:Bolatbek_Yermekov_Backend_Python"
  "frontend:Bolatbek_Yermekov_Frontend"
  "mobile:Bolatbek_Yermekov_React_Native"
  "qa:Bolatbek_Yermekov_QA_Engineer"
  "fullstack:Bolatbek_Yermekov_Fullstack"
)

command -v tectonic >/dev/null || { echo "нет tectonic: brew install tectonic"; exit 1; }

failed=0
for entry in "${ROLES[@]}"; do
  role="${entry%%:*}"
  name="${entry#*:}"
  src="$CV_DIR/$role/cv.tex"

  if [[ ! -f "$src" ]]; then
    printf '%-16s ПРОПУЩЕН (нет cv.tex)\n' "$role"
    continue
  fi

  if ! (cd "$CV_DIR/$role" && tectonic cv.tex >/dev/null 2>&1); then
    printf '%-16s ❌ не собирается\n' "$role"
    failed=1
    continue
  fi

  mv "$CV_DIR/$role/cv.pdf" "$CV_DIR/$role/$name.pdf"
  pages=$("$PYTHON" -c "
from pypdf import PdfReader
print(len(PdfReader('$CV_DIR/$role/$name.pdf').pages))")

  if [[ "$pages" == "1" ]]; then
    printf '%-16s ✅ 1 стр.  %s.pdf\n' "$role" "$name"
  else
    printf '%-16s ⚠️  %s стр. — НЕ ВЛЕЗЛО, режь наименее релевантное\n' "$role" "$pages"
    failed=1
  fi
done

exit "$failed"
