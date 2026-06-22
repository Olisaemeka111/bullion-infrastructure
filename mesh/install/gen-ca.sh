#!/usr/bin/env bash
# Generate ONE shared root CA + a per-cluster intermediate CA, and emit the
# `cacerts` secret for each cluster. A common root is what lets workloads in EKS,
# GKE and AKS trust each other's mTLS identities — i.e. behave as one mesh.
#
# Usage:  ./gen-ca.sh        (writes certs/ to the current dir)
# Then install.sh creates the `cacerts` secret in each cluster BEFORE installing
# istiod (istiod picks it up instead of self-signing).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p certs && cd certs
CLUSTERS=("eks" "gke" "aks")

# ---- root CA ----------------------------------------------------------------
if [[ ! -f root-key.pem ]]; then
  openssl genrsa -out root-key.pem 4096
  openssl req -x509 -new -nodes -key root-key.pem -sha256 -days 3650 \
    -subj "/O=fleet-mesh/CN=Root CA" -out root-cert.pem
fi

# ---- per-cluster intermediate CA -------------------------------------------
for c in "${CLUSTERS[@]}"; do
  mkdir -p "$c"
  openssl genrsa -out "$c/ca-key.pem" 4096
  openssl req -new -key "$c/ca-key.pem" \
    -subj "/O=fleet-mesh/CN=Intermediate CA/L=$c" -out "$c/ca.csr"
  openssl x509 -req -in "$c/ca.csr" -CA root-cert.pem -CAkey root-key.pem \
    -CAcreateserial -days 1825 -sha256 \
    -extfile <(printf "basicConstraints=critical,CA:true\nkeyUsage=critical,digitalSignature,keyCertSign,cRLSign\nsubjectAltName=DNS:istiod.istio-system.svc") \
    -out "$c/ca-cert.pem"
  cat "$c/ca-cert.pem" root-cert.pem > "$c/cert-chain.pem"
  cp root-cert.pem "$c/root-cert.pem"
  echo "  generated cacerts for $c"
done
echo "Done. certs/<cluster>/{ca-cert.pem,ca-key.pem,root-cert.pem,cert-chain.pem}"
