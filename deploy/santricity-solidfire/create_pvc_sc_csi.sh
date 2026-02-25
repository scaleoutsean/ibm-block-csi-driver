#!/usr/bin/env bash
#
kubectl apply -f ./csi.ibm.com_v1_ibmblockcsi_cr.yaml
kubectl apply -f ./demo-storageclass-solidfire.yaml
kubectl apply -f ./demo-pvc-file-system-solidfire.yaml

