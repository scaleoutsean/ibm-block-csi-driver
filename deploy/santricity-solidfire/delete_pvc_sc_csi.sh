#!/usr/bin/env bash
#
kubectl delete -f ./demo-pvc-file-system-solidfire.yaml
kubectl delete -f ./demo-storageclass-solidfire.yaml
kubectl delete -f ./csi.ibm.com_v1_ibmblockcsi_cr.yaml
