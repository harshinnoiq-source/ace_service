FROM python:3.12-slim

WORKDIR /app

# Client only — needed for pg_isready in entrypoint.sh. No more full Postgres server here.
RUN apt-get update && \
    apt-get install -y postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements first — this layer only rebuilds if requirements.txt changes
COPY requirements.txt /app/

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the rest of the code (overridden at runtime by the bind mount in docker-compose)
COPY . /app/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8090

ENTRYPOINT ["/entrypoint.sh"]