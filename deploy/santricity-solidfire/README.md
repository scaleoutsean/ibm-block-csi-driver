# SANtricity & SolidFire CSI (Fork of IBM Block CSI)

This is a specialized fork of the IBM Block CSI driver, modified to support NetApp SANtricity (E-Series) and using the `santricity.block.csi.ibm.com` driver name. SolidFire storage systems can be supported as well.

## CRITICAL WARNING: Driver Name Conflict

**DO NOT** deploy this driver in a cluster that already has the official IBM Block CSI driver (`block.csi.ibm.com`) installed unless you have renamed the driver to avoid conflicts.

### Why this matters:

- **CSI Driver Object**: Kubernetes uses a cluster-scoped `CSIDriver` resource. If two drivers share the same name, they will conflict.
- **Node Registration**: Kubelet registers drivers by name on each node. Multiple drivers with the same name on the same node will fail to register correctly.
- **Sidecar Processing**: Sidecars like `external-provisioner` watch for `StorageClass` objects based on the `provisioner` name. If two namespaces run drivers with the same name, both will attempt to process the same PVCs, leading to race conditions and volume creation failures.

### Isolation Strategy:

1.  **Unique Name**: This fork has been updated to use `santricity.block.csi.ibm.com`.
2.  **Unique StorageClasses**: Use the provided demo StorageClasses in this directory, which reference the new provisioner name.
3.  **Namespace Separation**: Deploy this driver into its own namespace (e.g., `ibm-block-santricity-csi`).

## Supported Protocols

- **SANtricity**: iSCSI and NVMe over RoCE (with `nvmeoroce` protocol key).
- **SolidFire**: iSCSI.

## Support for "Port Sets"

While SANtricity does not have a native "port set" concept, this driver remains compatible with the IBM `HostDefiner` interface. `port_set` parameters provided in Kubernetes Secrets will be accepted but are currently ignored for SANtricity arrays.
