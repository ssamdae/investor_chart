#!/usr/bin/env bash
# Read-only 1st-stage support snapshot -> 2nd-stage Kiwoom precursor pilot.
# Execute inside a separate worktree/venv; never modify production services.
set -euo pipefail

if [[ "$#" -lt 1 || "$#" -gt 3 ]]; then
  echo "사용법: $0 /path/to/선취매_지지수급_YYYYMMDD.xlsx [조회종목수:5] [시장:KRX]" >&2
  echo "API 조회 없이 구조 검증만 하려면: VALIDATE_ONLY=1 $0 <path>" >&2
  exit 2
fi
POOL="$1"
LIMIT="${2:-5}"
MARKET="${3:-KRX}"
if [[ ! -f "$POOL" ]]; then
  echo "입력 파일을 찾지 못했습니다: $POOL" >&2
  exit 2
fi
if [[ ! "$LIMIT" =~ ^[0-9]+$ || "$LIMIT" -lt 1 ]]; then
  echo "조회종목수는 양의 정수여야 합니다." >&2
  exit 2
fi
if [[ "$MARKET" != "KRX" && "$MARKET" != "통합" && "$MARKET" != "NXT" ]]; then
  echo "시장: KRX, 통합, NXT 중 하나를 선택하세요." >&2
  exit 2
fi

FILE_NAME="$(basename "$POOL")"
if [[ "$FILE_NAME" =~ ^선취매_지지수급_(20[0-9]{6})\.xlsx$ ]]; then
  ASOF="${BASH_REMATCH[1]}"
else
  echo "날짜가 포함된 스냅샷 파일만 사용합니다: 선취매_지지수급_YYYYMMDD.xlsx" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "[1/2] 일자·지지선·우선검토40 입력 검증 (키움 미호출)"
"$PYTHON_BIN" -m research.support_pool --pool "$POOL" --asof "$ASOF" --validate-only

if [[ "${VALIDATE_ONLY:-0}" == "1" ]]; then
  echo "완료: 검증 모드로 키움 API를 호출하지 않았습니다."
  exit 0
fi
if [[ ! -f .env && -z "${KIWOOM_APP_KEY:-}" ]]; then
  echo "연구 작업 디렉터리에 .env를 읽기 전용 링크로 연결하거나 환경변수를 설정하세요." >&2
  exit 2
fi

OUT="output/pre500_trial/${ASOF}_${MARKET}_first${LIMIT}.csv"
echo "[2/2] 키움 일봉·투자주체 순매수 분석: 날짜=$ASOF, 시장=$MARKET, 종목수=$LIMIT"
"$PYTHON_BIN" -m research.support_pool --pool "$POOL" --asof "$ASOF" \
  --market "$MARKET" --limit "$LIMIT" --output "$OUT"
echo "완료: $ROOT/$OUT"
