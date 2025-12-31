#!/usr/bin/env bash

ME=`basename "$0"`

DIR="/host"   # The CSI node daemonset mount the / of the host into /host inside the container.
if [ ! -d "${DIR}" ]; then
    echo "Could not find docker engine host's filesystem at expected location: ${DIR}"
    exit 1
fi

# Prefer host binary if present; otherwise fall back to container binary to avoid missing sg3_utils on the host.
if [ -x "${DIR}/usr/bin/${ME}" ] || [ -x "${DIR}/sbin/${ME}" ] || [ -x "${DIR}/bin/${ME}" ]; then
    exec chroot "$DIR" /usr/bin/env -i PATH="/sbin:/bin:/usr/bin:/usr/sbin" "${ME}" "${@:1}"
fi

if command -v "/usr/bin/${ME}" >/dev/null 2>&1; then
    exec "/usr/bin/${ME}" "${@:1}"
fi

echo "${ME} not found on host or in container"
exit 127

