# IBM Block CSI Driver for NetApp SANtricity

This directory contains documentation and sample configurations for using the IBM Block CSI Driver with NetApp SANtricity storage arrays (E-Series). 

What **is** this thing? See [this blog post](https://scaleoutsean.github.io/2026/02/26/ibm-block-storage-cis-driver-santricity-fork.html). There are other ways to provision SANtricity to Kubernetes - please see this [Overview of E-Series CSI drivers](https://scaleoutsean.github.io/2026/01/20/kubernetes-netapp-eseries-santricity-csi.html) for more.

**WARNING:** this CSI driver uses a minimally changed `CSIDriver` object name in `./common/config.yaml` to avoid conflicts with upstream CSI driver name (if installed in the same Kuberntes cluster) and at the same time credit upstream authors (the link still points to ibm.com). This fork is **not associated with, or supported by, IBM**.

## Capabilities

The IBM Block Storage CSI driver documentation page [lists features and capabilities](https://www.ibm.com/docs/en/stg-block-csi-driver/1.13.0?topic=requirements-features-capabilities) in a more descriptive way.

As mentioned above, this *minimal* patch seeks to avoid adding features (and bugs) that upstream does not have. Our objective is simple - make IBM Block Storage CSI driver work with SANtricity and take advantage of the features upstream has and integration testing they do.

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
- Connectivity protocols - iscsi, fc, nvme_over_fc, and (addition in this patch) nvme_over_roce

If you use this driver, desire additional features already implemented in upstream driver and can assist with debugging (or development), create a feature request in Issues or ping me on X.

## Build Instructions

To build the driver with SANtricity support, you must vendor the `santricity-client` library. A helper target has been added to the main `Makefile`.

If you don't want to build your own, skip to **Installation**.

Previously we used to run "`make vendor-santricity`" to clone the latest client library from [scaleoutsean/santricity-client](https://github.com/scaleoutsean/santricity-client) into the local source tree, but because IBM Block Driver CSI runs on outdated Python 3.9, this has proven very brittle. This patch now includes manually integrated source code from SANtricity Client library.

1.  **Build the Controller image**:
    ```bash
    docker build -f Dockerfile-csi-controller -t ibm-block-csi-controller:latest .
    ```

2.  **Build the Node image**:
    ```bash
    docker build -f Dockerfile-csi-node -t ibm-block-csi-node:latest .
    ```

## Installation 

### Kubernetes distribution support

Please note that IBM Block Storage CSI supports only vanilla Kubernetes and OpenShift. Find the details in "supported orchestrators" list in the [official documentation](https://www.ibm.com/docs/en/stg-block-csi-driver).

Various thin distributions are not supported, so if you're looking for a SANtricity CSI driver for [MicroK8s](https://scaleoutsean.github.io/2026/05/12/microk8s-kubernetes-netapp-eseries-santricity-csi.html), k3s and similar, check out [SANtricity CSI](https://github.com/scaleoutsean/santricity-go) is recommended.

### Operator-based deployment

IBM Block Storage CSI Driver requires an "operator". You may use the pre-configured YAML file for the operator. **Note**: In this fork, the operator and driver are both isolated in the `santricity` namespace by default (unlike upstream which uses `default`).

**NOTE:** if you already have an earlier version of this patched IBM Block CSI that uses the `default` namespace (e.g. version 1.13.1 or early 1.13.2), un-install the CSI driver and operator first, and then install it as per below (which will deploy both the Operator and CSI to the `santricity` namespace).

```sh
# Create the namespace first!
kubectl create namespace santricity

# Deploy the operator and CRDs
kubectl apply -f ./deploy/santricity-solidfire/ibm-block-csi-operator.yaml

# Wait for CRDs to be registered by the API server before applying the custom resource
kubectl wait --for=condition=Established --timeout=120s crd/hostdefiners.csi.ibm.com
kubectl wait --for=condition=Established --timeout=120s crd/hostdefinitions.csi.ibm.com
kubectl wait --for=condition=Established --timeout=120s crd/ibmblockcsis.csi.ibm.com
```

If you used own images, change image locations in this file first. If you're using pre-built, run this step.

```sh
kubectl apply -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
```

You can test installation flow without an attached E-Series array. The operator, CRDs, and CSI workloads should deploy. Volume provisioning will fail until `secret-santricity.yaml` points to a reachable array:

```sh
vim ./deploy/santricity-solidfire/secret-santricity.yaml # edit TLS verify, credentials
# kubectl create -f ./deploy/santricity-solidfire/secret-santricity.yaml # create secret
```

## Storage Configuration

The driver supports two types of SANtricity storage entities: **Traditional Volume Groups** and **Dynamic Disk Pools (DDP)**:

- Traditional ("classic") disk groups: rigid capacity "islands" with very predictable behavior and granular (precise) capacity allocation. Suitable for many small (<32GB) volumes with specific requirements
- DDP: flexible "lakes" of capacity with dual volume RAID type (RAID 10 and RAID 6) capability. Has coarse allocation (~4GiB increments), otherwise recommended over classic disk groups

### 1. Traditional Volume Groups (RAID 1/5/6)

Traditional groups define the RAID level at the group level. Volumes created in these groups inherit the group's RAID properties. Do **not** specify `SpaceEfficiency` in the `StorageClass` with classic RAID.

**Sample StorageClass:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: santricity-traditional-vg
provisioner: santricity.block.csi.ibm.com
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
provisioner: santricity.block.csi.ibm.com
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
provisioner: santricity.block.csi.ibm.com
parameters:
  pool: "ddp_pool"
  SpaceEfficiency: "raid1"
```

## Snapshot Support

Upstream (IBM Block Driver CSI) does not implement Volume Group Snapshots as of v1.13.2. Therefore, only individual volume snapshots are currently available in this patch.

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
  name: demo-volumesnapshotclass-santricity
driver: santricity.block.csi.ibm.com # different from IBM's driver name
deletionPolicy: Delete
parameters:
  csi.storage.k8s.io/snapshotter-secret-name: santricity-secret
  csi.storage.k8s.io/snapshotter-secret-namespace: santricity

  # Optional: initial snapshot repository group size, as % of base volume.
  # Used only when no eligible snapshot group exists and the driver must create one.
  # Valid range: 1..100. Default when omitted: 20.
  initial_repo_group_size_pct: "25"
```

Notes:

- `initial_repo_group_size_pct` applies to SANtricity snapshot-group creation only.
- Existing snapshot groups are still preferred when eligible.
- If omitted, behavior remains unchanged from previous releases (`20%`).
- For a concise quick-reference note, see [Usage Details](../USAGE-DETAILS.md#santricity-snapshot-parameter).

You can then create snapshots by referencing this class:

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: demo-volumesnapshot-santricity
spec:
  volumeSnapshotClassName: demo-volumesnapshotclass-santricity
  source:
    persistentVolumeClaimName: demo-pvc-santricity
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

To avoid conflicting with the original upstream namespace (`ibm-block-csi`) and to provide standard isolation, this CSI driver defaults to the `santricity` namespace. You must create this namespace before deployment:

```sh
kubectl create namespace santricity
```

You may modify YAML files to use a different namespace if necessary.

Remember to update, and then apply the secret file:

```sh
kubectl apply -f ./deploy/santricity-solidfire/secret-santricity.yaml
```

### Kubernetes PVC Metadata tags

The IBM block CSI driver orchestrates Volume provisioning metadata by converting `csi.storage.k8s.io/*` keys (like `pvc_name` and `pvc_namespace`) into SANtricity volume Metadata tags. This drastically helps track K8s volume objects (like `csi_AdNDmArncUqCAG842z1H4Lj4xc`) to their native Kubernetes PVC names.

However, the `csi-provisioner` sidecar drops these PVC keys before passing the provisioning request to the CSI driver unless it runs with the `--extra-create-metadata=true` startup argument.

Because this driver is tightly managed by the IBM Block CSI Operator (`ibm-block-csi-operator.yaml`), the custom resource `csi.ibm.com_v1_ibmblockcsi_cr.yaml` strictly limits the configurable sidecar fields to only `imagePullPolicy`, `name`, `repository`, and `tag`. It does **not** support injecting custom `args` per the schema definition.

To enable natively visible PVC names on your SANtricity array, you must scale the operator down and manually patch the provisionser sidecar:

```sh
# 1. Stop the operator from reverting your manual changes
kubectl scale deployment ibm-block-csi-operator-controller-manager --replicas=0

# 2. Edit the deployed CSI controller StatefulSet
kubectl edit statefulset ibm-block-csi-controller
```

**3. Add \`--extra-create-metadata=true\` to the \`csi-provisioner\` container args array:**

Locate the `csi-provisioner` container in the open editor block and add the new argument:

```yaml
      - name: csi-provisioner
        image: registry.k8s.io/sig-storage/csi-provisioner:v4.0.1
        args:
        - --csi-address=$(ADDRESS)
        - --v=5
        - --timeout=120s
        - --retry-interval-start=500ms
        - --extra-create-metadata=true
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

Or re-install CSI Controller and Node:

```sh
kubectl delete -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
# wait until CSI Controller and Node pods terminate - roughly 60s
kubectl apply -f ./deploy/santricity-solidfire/csi.ibm.com_v1_ibmblockcsi_cr.yaml
```

When upgrading, you may want to make sure the images did get refreshed, especially if tags remained the same (e.g. `:latest`).

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

SANtricity snapshots must be deleted in strict order of creation, which means you can't delete the second oldest snapshot without deleting the oldest before it. Secondly, the API allows "yanking", so deleting a volume deletes without warnings all snapshots and linked clones that depend on it.

## SolidFire Support

There's a "stub" for a SolidFire (iSCSI) driver as well. I've been focused on SolidFire CSI (my "CSI from scratch done right" project), so SolidFire support in IBM Block Storage CSI will probably not be delivered unless someone needs it.

If anyone is interested (OpenShift users, etc.) in getting this done, let me know in Issues. Because SolidFire uses iSCSI, adopting it would be easier than it was for SANtricity.

## IBM Block Driver CSI Support

Obviously, don't contact IBM for support for things unrelated to IBM Block Driver CSI Support (which would be anything related to bugs or enhancement requests related to this fork).

