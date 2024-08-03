# FROM ubi9
FROM registry.fedoraproject.org/fedora:40

COPY setup.sh .
RUN ./setup.sh

WORKDIR /CertificateAuthCA
COPY mtls.sh .
RUN ./mtls.sh

WORKDIR /root
COPY setup-dnfrepo.sh .
RUN  ./setup-dnfrepo.sh

EXPOSE 443 8081

# server the cert dir on port 80 so the test client can get the files it needs
RUN ln -s /CertificateAuthCA /usr/share/nginx/html/CertificateAuthCA

COPY nginx.conf /etc/nginx/conf.d/
CMD ["nginx", "-g", "daemon off;"]
