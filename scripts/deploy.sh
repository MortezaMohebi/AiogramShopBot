#!/bin/sh
# Operate this checkout only; never install software or collect bot credentials.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

case "${1:-info}" in
  info)
    cat <<'HELP'
Registry deployment from this checkout:
  1. Copy .env.template to .env and .env.next-admin.example to .env.next-admin.
  2. Set unique database, Redis, bridge, session and Fernet encryption secrets.
     Use the same bridge secret in both files. Configure a private HTTPS
     NEXT_ADMIN_PUBLIC_ORIGIN; secure cookies remain enabled.
  3. scripts/deploy.sh check
  4. scripts/deploy.sh build
  5. For a wholly empty PostgreSQL database: scripts/deploy.sh initialize
     This creates the modern schema and zero bots without replaying history.
     For an existing versioned database, first back up its data and review the
     allowlisted table retirement in migration 20261107z001. Only then run:
       scripts/deploy.sh migrate --retire-original-schema
     Migration rejects unversioned databases; initialize rejects populated ones.
     The existing ./postgres_data mount is preserved during upgrades.
  6. Provision staff using scripts.manage_shop_staff inside the backend image.
  7. scripts/deploy.sh start
Register bots and credentials through Dashboard > Bots after login.
Shared workers start idle. Activate application services from Dashboard > Services.
Private fallback: docker compose exec bot python -m scripts.manage_shop_services list
No public ingress or provider webhook registration is performed here.
HELP
    ;;
  check) docker compose config --quiet ;;
  build) docker compose build bot runtime-worker broadcast-worker digital-delivery-worker customer-notifications-worker next-admin ;;
  initialize)
    docker compose up -d --wait postgres redis
    docker compose run --rm --no-deps bot python -m scripts.initialize_registry_database
    ;;
  migrate)
    if [ "${2:-}" != "--retire-original-schema" ] || [ "$#" -ne 2 ]; then
      echo "Back up the existing versioned database and review migration 20261107z001's retired-table allowlist." >&2
      echo "Then run: $0 migrate --retire-original-schema" >&2
      exit 2
    fi
    docker compose up -d --wait postgres redis
    docker compose run --rm --no-deps bot python -m scripts.migrate_registry_database --retire-original-schema
    ;;
  start) docker compose up -d --wait postgres redis bot runtime-worker broadcast-worker digital-delivery-worker customer-notifications-worker next-admin ;;
  status) docker compose ps -a ;;
  stop) docker compose down --remove-orphans ;;
  *) echo "Usage: $0 [info|check|build|initialize|migrate --retire-original-schema|start|status|stop]" >&2; exit 2 ;;
esac
