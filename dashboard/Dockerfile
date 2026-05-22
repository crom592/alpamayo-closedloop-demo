# Closed-loop dashboard image.
# Needs: docker CLI (to talk to the host daemon via mounted socket), nvidia-smi.
# Run with:
#   docker run -d --name alpamayo-dashboard -p 7860:8501 \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -v <RUN_DIR>:/run_dir:ro \
#     alpamayo-closedloop-dashboard
FROM python:3.12-slim

# docker CLI (no daemon, just client) + nvidia-smi shim via /usr/bin (provided by NVIDIA Container Toolkit at runtime if --gpus is used; otherwise script in dashboard falls back gracefully)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir streamlit>=1.36

COPY app_streamlit.py .

EXPOSE 8501

CMD ["streamlit", "run", "app_streamlit.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
