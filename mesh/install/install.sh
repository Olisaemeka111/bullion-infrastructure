#!/usr/bin/env bash
# Install Istio multi-primary across EKS + GKE + AKS so the three clusters form
# ONE active-active mesh. Run AFTER `terraform apply` and after you have a
# kubeconfig context for each cluster.
#
# Set these to your kube contexts (kubectl config get-contexts):
#   export CTX_EKS=... CTX_GKE=... CTX_AKS=...
#
# Prereqs: istioctl, kubectl, openssl, and the 3 contexts reachable.
set -euo pipefail
cd "$(dirname "$0")"

: "${CTX_EKS:?set CTX_EKS to your EKS kube context}"
: "${CTX_GKE:?set CTX_GKE to your GKE kube context}"
: "${CTX_AKS:?set CTX_AKS to your AKS kube context}"

declare -A CTX=( [eks]=$CTX_EKS [gke]=$CTX_GKE [aks]=$CTX_AKS )

echo "==> 1/5 generate shared root CA"
./gen-ca.sh

echo "==> 2/5 create istio-system + shared cacerts in each cluster"
for c in eks gke aks; do
  kubectl --context "${CTX[$c]}" create namespace istio-system --dry-run=client -o yaml \
    | kubectl --context "${CTX[$c]}" apply -f -
  kubectl --context "${CTX[$c]}" -n istio-system delete secret cacerts --ignore-not-found
  kubectl --context "${CTX[$c]}" -n istio-system create secret generic cacerts \
    --from-file=certs/$c/ca-cert.pem \
    --from-file=certs/$c/ca-key.pem \
    --from-file=certs/$c/root-cert.pem \
    --from-file=certs/$c/cert-chain.pem
done

echo "==> 3/5 install istiod + east-west gateway in each cluster"
istioctl install --context "$CTX_EKS" -y -f iop-eks.yaml
istioctl install --context "$CTX_GKE" -y -f iop-gke.yaml
istioctl install --context "$CTX_AKS" -y -f iop-aks.yaml

echo "==> 4/5 expose services across networks (east-west gateway)"
for c in eks gke aks; do
  kubectl --context "${CTX[$c]}" apply -n istio-system -f expose-services.yaml
done

echo "==> 5/5 exchange remote secrets (each istiod discovers the others' endpoints)"
for a in eks gke aks; do
  for b in eks gke aks; do
    [[ "$a" == "$b" ]] && continue
    istioctl create-remote-secret --context "${CTX[$a]}" --name "$a" \
      | kubectl --context "${CTX[$b]}" apply -f -
  done
done

echo "✓ multi-primary mesh ready. Verify:  istioctl --context $CTX_EKS remote-clusters"
