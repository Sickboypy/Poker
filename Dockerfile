# Swarm Descent: servidor de juego (archivos + WebSocket) para Cloud Run.
# Solo usa la biblioteca estándar de Python: no hay dependencias que instalar.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app
COPY servidor_vr.py *.html ./
RUN useradd --no-create-home --uid 10001 juego
USER juego
EXPOSE 8080
CMD ["python", "servidor_vr.py"]
