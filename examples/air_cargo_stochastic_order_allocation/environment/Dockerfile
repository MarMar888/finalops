FROM oragentbench-base:py311-scip

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ORCLAW_SOLVE_TIME_LIMIT_SECONDS=300
ENV ORCLAW_SCIP_GAP=0.0005

WORKDIR /app
COPY app/ /app/
COPY skills/ /skills/
RUN mkdir -p /app/submissions /logs/verifier /logs/agent
