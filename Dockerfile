FROM python:3.13-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CAREER_SKILL_MCP_TRANSPORT=streamable-http \
    CAREER_SKILL_MCP_HOST=0.0.0.0 \
    CAREER_SKILL_MCP_PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    texlive-latex-extra \
    texlive-xetex \
    fonts-liberation \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-dejavu-core \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY templates/ ./templates/
RUN python -m pip install --no-cache-dir .

EXPOSE 8000
CMD ["python", "-m", "career_resume_skill.server"]