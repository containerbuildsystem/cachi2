#!/bin/bash
dnf -y install dnf-plugins-core openssl nginx nano procps-ng python python3-pip
pip install createrepo_c
cd /
mkdir CertificateAuthCA
chown root:nginx /CertificateAuthCA
chmod 770 /CertificateAuthCA
cd /CertificateAuthCA

echo "curl --insecure --cert /CertificateAuthCA/testuser.crt --key /CertificateAuthCA/testuser.key --output nano.rpm https://localhost/nano-7.2-7.fc40.x86_64.rpm" >> /root/example_command
