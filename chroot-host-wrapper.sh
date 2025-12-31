#!/usr/bin/env bash

ME=`basename "$0"`

DIR="/host"   # The CSI node daemonset mount the / of the host into /host inside the container.
if [ ! -d "${DIR}" ]; then
    echo "Could not find docker engine host's filesystem at expected location: ${DIR}"
    exit 1
fi

# Prefer container binary (has sg3_utils/multipath deps). If missing, fall back to host binary via chroot.
for p in /usr/bin /usr/sbin /sbin /bin; do
    if [ -x "${p}/${ME}" ]; then
        exec "${p}/${ME}" "${@:1}"
    fi
done

if [ -x "${DIR}/usr/bin/${ME}" ] || [ -x "${DIR}/usr/sbin/${ME}" ] || [ -x "${DIR}/sbin/${ME}" ] || [ -x "${DIR}/bin/${ME}" ]; then
    exec chroot "$DIR" /usr/bin/env -i PATH="/sbin:/bin:/usr/bin:/usr/sbin" "${ME}" "${@:1}"
fi

echo "${ME} not found on host or in container"
exit 127

