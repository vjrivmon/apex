#!/usr/bin/env sh
# Variante fuente del hook pre-commit con gitleaks (Sprint 19, Gap F).
#
# Es el MISMO chequeo que templates/devops/.husky/pre-commit, pero escrito
# para poder usarse como hook git "plano" (sin husky):
#
#   cp templates/devops/husky-pre-commit.sh <proyecto>/.git/hooks/pre-commit
#   chmod +x <proyecto>/.git/hooks/pre-commit
#
# apex_scaffold_devops instala la variante de husky en <proyecto>/.husky/.
# Mantener los dos scripts con la misma logica: si divergen, el gate de
# fase 10.5 dejaria de reflejar lo que realmente se ejecuta.
#
# Detalle de los hallazgos:
#   gitleaks detect --staged -v

set -eu

if ! command -v gitleaks >/dev/null 2>&1; then
    echo "gitleaks no esta instalado: el hook NO puede comprobar secretos." >&2
    echo "Instalalo con uno de estos comandos:" >&2
    echo "  brew install gitleaks                                   # macOS / Linuxbrew" >&2
    echo "  sudo apt install gitleaks                               # Debian / Ubuntu" >&2
    echo "  go install github.com/gitleaks/gitleaks/v8@latest       # Go" >&2
    exit 1
fi

if ! gitleaks protect --staged --redact; then
    echo "" >&2
    echo "gitleaks ha detectado secretos en lo staged: el commit NO se ha hecho." >&2
    echo "  - Ver el detalle:  gitleaks detect --staged -v" >&2
    echo "  - Falso positivo:  anade 'gitleaks:allow' a la linea, o amplia" >&2
    echo "                     la configuracion en .gitleaks.toml" >&2
    echo "  - Deshacer staged:  git reset" >&2
    exit 1
fi

exit 0
