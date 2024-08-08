#!/bin/bash

# verify server and certs are configured correctly.

curl \
  --cacert /CertificateAuthCA/myCA.crt \
  --key /CertificateAuthCA/testuser.key \
  --cert /CertificateAuthCA/testuser.crt \
  https://localhost