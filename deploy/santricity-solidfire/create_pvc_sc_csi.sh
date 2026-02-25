#!/usr/bin/env bash
#
kubectl apply -f ./csi.ibm.com_v1_ibmblockcsi_cr.yaml
kubectl apply -f ./demo-storageclass-santricity.yaml
kubectl apply -f ./demo-pvc-santricity.yaml

