# Extend docker/mcp-gateway with THG CA certificate
FROM docker/mcp-gateway:latest

# Download and install THG CA certificate for SSL interception proxy
# Uses wget (built into Alpine via busybox) with --no-check-certificate
USER root
RUN wget --no-check-certificate -O /usr/local/share/ca-certificates/thehutgroup.crt \
       https://thg-certificate.thgaccess.com/thehutgroup.pem \
    && update-ca-certificates

# Set environment variables for SSL
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
