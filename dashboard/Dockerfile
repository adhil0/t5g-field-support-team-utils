FROM registry.fedoraproject.org/fedora:41
LABEL org.opencontainers.image.authors="Telco5G Field Engineering Team"
RUN dnf -y install python3-pip gcc redhat-rpm-config python3-devel npm libxml2-devel xmlsec1-devel xmlsec1-openssl-devel libtool-ltdl-devel python3-xmlsec; dnf clean all
COPY src/ /srv/
WORKDIR /srv 
RUN pip3 install --no-cache-dir .
RUN npm ci --prefix t5gweb/static --ignore-scripts
RUN groupadd dashboard
RUN useradd -g dashboard dashboard
USER dashboard
EXPOSE 8080
