# Open Policy Agent serving the VCL policies. [spec §5.3]
FROM openpolicyagent/opa:0.68.0

COPY policies /policies

# Serve OPA's REST API on :8181 with the bundled policies loaded.
ENTRYPOINT ["/opa"]
CMD ["run", "--server", "--addr", "0.0.0.0:8181", "--log-level", "info", "/policies"]
