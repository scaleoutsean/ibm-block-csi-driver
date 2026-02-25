# IBM Block CSI Driver for NetApp SANtricity

This directory contains documentation and sample configurations for using the IBM Block CSI Driver with NetApp SANtricity storage arrays (E-Series).

**WARNING:** this CSI driver uses a minimally changed `CSIDriver` object name in `./common/config.yaml` to avoid conflict with upstream CSI driver name (if installed in the same Kuberntes cluster) and at the same time credit upstream auhors. This fork is **not associated with, or suppored by, IBM**.

## Capabilities

### CSI RPC Capabilities

These are the capabilities the driver explicitly reports to Kubernetes during the CSI GetCapabilities calls.

- Controller Capabilities: Reported in `csi_controller_server.py`
  - CREATE_DELETE_VOLUME (Dynamic Provisioning)
  - CREATE_DELETE_SNAPSHOT (Snapshots)
  - PUBLISH_UNPUBLISH_VOLUME (Attach/Detach)
  - CLONE_VOLUME (Volume Cloning)
  - EXPAND_VOLUME (Offline/Online Resizing)
- Node Capabilities: Hardcoded in node.go:37.
  - STAGE_UNSTAGE_VOLUME (Mount/Unmount)
  - EXPAND_VOLUME (Node-side resizing)
  - GET_VOLUME_STATS (Volume metrics)
- Access Modes (RWO/RWX): Defined in node.go:46.
  - SINGLE_NODE_WRITER (RWO)
  - MULTI_NODE_MULTI_WRITER (RWX)
- Driver Identity & Plug-in Capabilities
  - The driver's global identity and high-level service capabilities are defined in the central configuration file:
    - CONTROLLER_SERVICE
    - VolumeExpansion: ONLINE
- Supported Connectivity Protocols
The protocols supported by the driver (iSCSI, FC, NVMe) are defined in the configuration and implemented via the storage mediators:
- Connectivity protocols - iscsi, fc, nvme_over_fc, and our new nvme_over_roce

If you use this driver, desire additional features already implemented in upstream driver and can assist with debugging (or development), create a feature request in Issues or ping me on X.

## Build Instructions

To build the driver with SANtricity support, you must vendor the `santricity-client` library. A helper target has been added to the main `Makefile`.

If you don't want to build your own, skip to **Installation**.

1.  **Vendor the library**:
    ```bash
    make vendor-santricity
    ```
    This clones the latest client library from [scaleoutsean/santricity-client](https://github.com/scaleoutsean/santricity-client) into the local source tree.

2.  **Build the Controller image**:
    ```bash
    docker build -f Dockerfile-csi-controller -t ibm-block-csi-controller:latest .
    ```

3.  **Build the Node image**:
    ```bash
    docker build -f Dockerfile-csi-node -t ibm-block-csi-node:latest .
    ```

## Installation 

IBM Block Storage CSI Driver requires an "operator". You may use pre-configured YAML files.

```sh
kubectl apply -f ./deploy/santricity-solidfire/ibm-block-csi-operator.yaml
kubectl apply -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
```

This uses pre-built images from Github Container Registry:
- ghcr.io/scaleoutsean/ibm-block-csi-driver-controller:santricity
- ghcr.io/scaleoutsean/ibm-block-csi-driver-node:santricity

To avoid conflicting with the usual namespace (`ibm-block-csi`), this CSI driver by default installs in the default namespace. You may modify YAML files as necessary.

Remember to update, and then apply the secret file:
```sh
kubectl apply -f ./deploy/secret-santricity.yaml`
```

## Storage Configuration

The driver supports two types of SANtricity storage entities: **Traditional Volume Groups** and **Dynamic Disk Pools (DDP)**.

### 1. Traditional Volume Groups (RAID 1/5/6)
Traditional groups define the RAID level at the group level. Volumes created in these groups inherit the group's RAID properties. Do **not** specify `SpaceEfficiency` in the `StorageClass`.

**Sample StorageClass:**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: santricity-traditional-vg
provisioner: block.csi.ibm.com
parameters:
  pool: "vg_r5"  # Name or ID of the Traditional Volume Group on the array
```

### 2. Dynamic Disk Pools (DDP)

DDP pools are modern distributed parity pools. While they handle redundancy automatically, the `SpaceEfficiency` parameter can be used to set the preferred redundancy level (defaults to `raid6`).

**Sample StorageClass (with RAID 6 default):**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: santricity-ddp-pool
provisioner: block.csi.ibm.com
parameters:
  pool: "ddp_pool"  # Name or ID of the DDP Pool on the array
  SpaceEfficiency: "raid6"
```

**Sample StorageClass (with RAID 1 override):**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: santricity-ddp-raid1
provisioner: block.csi.ibm.com
parameters:
  pool: "ddp_pool"
  SpaceEfficiency: "raid1"
```

## Update

Update the Controller (StatefulSet):

```sh
kubectl rollout restart statefulset ibm-block-csi-controller
```

Update the Node Agents (DaemonSet)
```sh
kubectl rollout restart daemonset ibm-block-csi-node
```

Or just one command that does two things at once.

```sh
kubectl apply -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
```

## Testing

You can use the following YAML to test your installation:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: santricity-test-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: santricity-ddp-pool
---
apiVersion: v1
kind: Pod
metadata:
  name: santricity-test-pod
spec:
  containers:
  - name: test-container
    image: busybox
    command: [ "sh", "-c", "while true; do date >> /mnt/test/data; sleep 10; done" ]
    volumeMounts:
    - name: test-volume
      mountPath: /mnt/test
  volumes:
  - name: test-volume
    persistentVolumeClaim:
      claimName: santricity-test-pvc
```

## Limitations

There are no quotas or other fancy features. Try [santricity-go](https://github.com/scaleoutsean/santricity-go/csi/) or watch your array performance and capacity in a monitoring system such as these.

- [EPA](https://github.com/scaleoutsean/eseries-perf-analyzer) - easy setup
- [ESC](https://github.com/scaleoutsean/eseries-santricity-collector) - hard (for power users)

IBM Block Driver CSI creates (too) unique volume names that aren't supposed to be readable by humans. And that's fine, PVC names are readable but impossible to memorize anyway. This fork attaches metadatta tags to volumes, so if you use ESC mentioned above, you can track them in Grafana. What's injected:
- pvc_name - from csi.storage.k8s.io/pvc/name  
- pvc_namespace - from csi.storage.k8s.io/pvc/namespace
- pv_name - from csi.storage.k8s.io/pv/name


## SolidFire Support

There's a "stub" for a SolidFire (iSCSI) driver as well. I've been focused on SolidFire CSI (my "CSI from scratch done right" project), so SolidFire support in IBM Block Storage CSI probably not be delivered.

But if anyone is interested (OpenShift users, etc.) in getting this done, let me know in Issues!

## IBM Block Driver CSI Support

Obviously, don't contact IBM for support for things unrelated to IBM Block Driver CSI Support (which would be anything related to bugs or enhancement requests related to this fork).

