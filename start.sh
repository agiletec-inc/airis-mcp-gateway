#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
ARM_EMU_FILE="${SCRIPT_DIR}/docker-compose.arm-emu.yml"

COMPOSE_FILES="-f ${COMPOSE_FILE}"
case "$(uname -m)" in
  x86_64|amd64)
    COMPOSE_FILES="${COMPOSE_FILES} -f ${ARM_EMU_FILE}"
    # Register QEMU binfmt handlers for ARM64 emulation (idempotent)
    if [ ! -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
      echo "Registering QEMU binfmt handlers for ARM64 emulation..."
      docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
    fi
    ;;
esac

docker compose ${COMPOSE_FILES} up -d "$@"
