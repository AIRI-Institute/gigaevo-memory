#!/usr/bin/env bash
# Postgres backup for gigaevo-memory (P2 §7, iter #38).
#
# Dumps the docker-compose `postgres` service to a gzip'd SQL file in
# $BACKUP_DIR (default: ./backups). When $S3_BUCKET is set, the dump is
# additionally uploaded to s3://$S3_BUCKET/$S3_PREFIX/<filename>.
#
# Usage:
#   deploy/scripts/backup.sh [--dry-run] [--help]
#
# Environment variables (all have safe defaults):
#   BACKUP_DIR     Local output directory   (default: ./backups)
#   POSTGRES_USER  DB user for pg_dump      (default: memory)
#   POSTGRES_DB    DB name for pg_dump      (default: memory)
#   COMPOSE_FILE   Path to docker-compose   (default: deploy/docker-compose.yml)
#   COMPOSE_PROJECT
#                  Compose project name     (default: gigaevo-memory)
#   S3_BUCKET      S3 bucket (optional — skips upload when unset)
#   S3_PREFIX      Key prefix inside bucket (default: gigaevo-memory/backups)
#
# Exit codes:
#   0  success
#   2  bad CLI usage
#   1  pg_dump or upload failure
#
# Designed to be re-runnable on a schedule (cron / systemd timer). The
# dump filename includes a UTC timestamp so concurrent runs never
# collide on filesystem nor S3 keys.

set -euo pipefail

DRY_RUN=0

print_usage() {
  sed -n '2,30p' "$0"  # echoes the leading comment block as usage
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1; shift ;;
    --help|-h)
      print_usage; exit 0 ;;
    *)
      echo "error: unknown flag $1" >&2
      print_usage >&2
      exit 2 ;;
  esac
done

# Defaults — overridable from the environment.
BACKUP_DIR="${BACKUP_DIR:-./backups}"
POSTGRES_USER="${POSTGRES_USER:-memory}"
POSTGRES_DB="${POSTGRES_DB:-memory}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-gigaevo-memory}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-gigaevo-memory/backups}"

TIMESTAMP="$(date -u +%Y%m%d-%H%M%SZ)"
FILENAME="gigaevo-memory-${TIMESTAMP}.sql.gz"
OUTPUT_PATH="${BACKUP_DIR}/${FILENAME}"

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "would run: $*"
  else
    eval "$*"
  fi
}

ensure_dir() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "would mkdir -p ${BACKUP_DIR}"
  else
    mkdir -p "${BACKUP_DIR}"
  fi
}

echo "==> gigaevo-memory backup: ${OUTPUT_PATH}"
ensure_dir

# pg_dump runs inside the postgres container so we don't need
# Postgres client tools installed on the host. The dump is piped
# through host-side gzip and written to BACKUP_DIR.
DUMP_CMD="docker compose -p ${COMPOSE_PROJECT} -f ${COMPOSE_FILE} exec -T postgres pg_dump -U ${POSTGRES_USER} -d ${POSTGRES_DB} | gzip > ${OUTPUT_PATH}"
run "${DUMP_CMD}"

if [[ -n "${S3_BUCKET}" ]]; then
  S3_KEY="s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}"
  echo "==> uploading to ${S3_KEY}"
  UPLOAD_CMD="aws s3 cp ${OUTPUT_PATH} ${S3_KEY}"
  run "${UPLOAD_CMD}"
else
  echo "==> skipping S3 upload (S3_BUCKET unset)"
fi

if [[ $DRY_RUN -eq 0 ]]; then
  echo "==> backup complete: ${OUTPUT_PATH}"
fi
