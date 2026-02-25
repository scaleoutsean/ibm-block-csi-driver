#!/usr/bin/env bash
#
kubectl delete -f ./demo-pvc-santricity.yaml
kubectl delete -f ./demo-storageclass-santricity.yaml
kubectl delete -f ./csi.ibm.com_v1_ibmblockcsi_cr.yaml
