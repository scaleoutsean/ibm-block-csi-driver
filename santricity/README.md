# IBM Block CSI Driver for NetApp SANtricity

This directory contains documentation and sample configurations for using the IBM Block CSI Driver with NetApp SANtricity storage arrays (E-Series). 

What **is** this thing? See [this blog post](https://scaleoutsean.github.io/2026/02/26/ibm-block-storage-cis-driver-santricity-fork.html).

**WARNING:** this CSI driver uses a minimally changed `CSIDriver` object name in `./common/config.yaml` to avoid conflicts with upstream CSI driver name (if installed in the same Kuberntes cluster) and at the same time credit upstream authors (the link still points to ibm.com). This fork is **not associated with, or supported by, IBM**.

## Capabilities

The IBM Block Storage CSI driver documentation page [lists features and capabilities](https://www.ibm.com/docs/en/stg-block-csi-driver/1.13.0?topic=requirements-features-capabilities) in a more descriptive way.

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
# Wait for CRDs to be registered by the API server before applying the custom resource
kubectl wait --for=condition=Established --timeout=120s crd/hostdefiners.csi.ibm.com
kubectl wait --for=condition=Established --timeout=120s crd/hostdefinitions.csi.ibm.com
kubectl wait --for=condition=Established --timeout=120s crd/ibmblockcsis.csi.ibm.com
kubectl apply -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
```

You can test installation flow without an attached E-Series array. The operator, CRDs, and CSI workloads should deploy. Volume provisioning will fail until `secret-santricity.yaml` points to a reachable array.

### Snapshot Support

For snapshot provisioning and deletion to work, make sure that Kubernetes external snapshotter CRDs, Snapshot Controller, and an appropriate `VolumeSnapshotClass` are installed in your cluster.

Download "external snapshotter" and install the CRDs and controller:

```sh
kubectl apply -k ./external-snapshotter/client/config/crd/
kubectl apply -k ./external-snapshotter/deploy/kubernetes/snapshot-controller
```

A minimal `VolumeSnapshotClass` for SANtricity arrays should look like this:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: demo-volumesnapshotclass
driver: santricity.block.csi.ibm.com # different from IBM's driver name
deletionPolicy: Delete
parameters:
  csi.storage.k8s.io/snapshotter-secret-name: demo-secret
  csi.storage.k8s.io/snapshotter-secret-namespace: default
```

You can then create snapshots by referencing this class:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: demo-volumesnapshot
spec:
  volumeSnapshotClassName: demo-volumesnapshotclass
  source:
    persistentVolumeClaimName: demo-pvc-file-system
```

## Call Home and Privacy

For this SANtricity fork, call-home registration to storage arrays is **not** sent.

- The generic call-home registration path exists in the upstream code for SVC-family arrays.
- In the SANtricity mediator, `register_plugin()` is a no-op (`pass`), so no `registerplugin` command is executed.
- Default call-home metadata is still generated in process startup code, and logged by the controller.

If you want explicit privacy/compliance posture, set the custom resource field below:

```yaml
spec:
  enableCallHome: "false"
```

This prevents call-home registration attempts in environments where that path is implemented.

For SANtricity specifically, this is also a clear and auditable policy setting.

This uses pre-built images from Github Container Registry:
- ghcr.io/scaleoutsean/ibm-block-csi-driver-controller:latest
- ghcr.io/scaleoutsean/ibm-block-csi-driver-node:latest

To avoid conflicting with the usual namespace (`ibm-block-csi`), this CSI driver by default installs in the default namespace. You may modify YAML files as necessary.

Remember to update, and then apply the secret file:

```sh
kubectl apply -f ./deploy/santricity-solidfire/secret-santricity.yaml
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

SANtricity DDP allocates storage in 4 GiB chunks, so on small PVCs (less than 20 GB) you may see allocated more than you think or expect. It is recommended to use 4 GiB "units" and over 10 GiB sizes on DDP. Traditional disk groups (RAID 1/5/6) allocate precisely.

There are no quotas or other fancy features. Try [santricity-go](https://github.com/scaleoutsean/santricity-go/csi/) for status reporting, or watch your array performance and capacity in a monitoring system such as [EPA](https://github.com/scaleoutsean/eseries-perf-analyzer).

IBM Block Storage CSI drivers creates (too?) unique volume names that aren't supposed to be readable by humans. And that's fine, PVC names are readable but impossible to memorize anyway. This fork attaches Kubernetes PVC metadata tags to SANtricity volumes, so if you use ESC (mentioned above) you can track them in InfluxDB and watch them in Grafana. What's injected in SANtricity volume metadata:

- pvc_name - from csi.storage.k8s.io/pvc/name  
- pvc_namespace - from csi.storage.k8s.io/pvc/namespace
- pv_name - from csi.storage.k8s.io/pv/name
- fstype - from csi.storage.k8s.io/fstype

## SolidFire Support

There's a "stub" for a SolidFire (iSCSI) driver as well. I've been focused on SolidFire CSI (my "CSI from scratch done right" project), so SolidFire support in IBM Block Storage CSI will probably not be delivered unless someone needs it.

If anyone is interested (OpenShift users, etc.) in getting this done, let me know in Issues. Because SolidFire uses iSCSI, adopting it would be easier than it was for SANtricity.

## IBM Block Driver CSI Support

Obviously, don't contact IBM for support for things unrelated to IBM Block Driver CSI Support (which would be anything related to bugs or enhancement requests related to this fork).

