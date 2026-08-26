# GradeAI backend — FastAPI + the XeLaTeX typesetting pipeline.
#
# Why a Dockerfile instead of the previous nixpacks build: the paper generator
# now typesets with a real TeX engine, and the engine has to exist in the image.
#
# Size, measured, for the three ways of getting one:
#   * full TeX Live                                    ~5 GB
#   * apt texlive-xetex + latex-recommended
#     + fonts-recommended + science                    ~1.5-2 GB
#   * Tectonic binary + a pre-warmed resource cache     ~75 MB   <-- this
#
# Tectonic is the real XeTeX engine plus xdvipdfmx in one statically-linked
# executable; it fetches the individual .sty/.otf files a document needs from a
# signed bundle and caches them. The build below warms that cache with a document
# using every package the templates load, so the running container performs no
# network I/O to produce a paper — and the layer is baked in, which matters on
# Railway where the filesystem is ephemeral.
FROM python:3.12-slim

# ca-certificates is needed at BUILD time to fetch the engine and its bundle.
# The musl Tectonic build is statically linked, so nothing else is needed at run
# time; fontconfig is installed only so a licensed Century Gothic dropped into
# /usr/share/fonts is discoverable by the font resolver.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install the engine and pre-download every support file the templates need.
# TECTONIC_CACHE_DIR is set for both build and run so the warmed cache is the one
# the server reads.
ENV TECTONIC_CACHE_DIR=/opt/tectonic-cache
RUN python scripts/install_tectonic.py \
    && python -c "import sys; sys.path.insert(0, '.'); \
from utils.latex.engine import engine_status; s = engine_status(); \
print(s); sys.exit(0 if s['available'] else 1)"

# LaTeX typesetting is the default; GA_PDF_ENGINE=images reverts to the previous
# reportlab screenshot renderer without a redeploy.
ENV GA_PDF_ENGINE=latex \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
