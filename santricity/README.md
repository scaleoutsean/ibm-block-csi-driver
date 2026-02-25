# IBM Block CSI Driver for NetApp SANtricity

This directory contains documentation and sample configurations for using the IBM Block CSI Driver with NetApp SANtricity storage arrays (E-Series).

## Build Instructions

To build the driver with SANtricity support, you must vendor the `santricity-client` library. A helper target has been added to the main `Makefile`.

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
