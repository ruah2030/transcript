FROM python:3.12-slim

WORKDIR /app

# Dépendances d'abord : la couche est mise en cache tant que le
# pyproject ne bouge pas.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      fastapi "uvicorn[standard]" pydantic pydantic-settings httpx \
      python-multipart ctranslate2 sentencepiece transformers

COPY app ./app
COPY ressources ./ressources

EXPOSE 8000
CMD ["uvicorn", "app.main:application", "--host", "0.0.0.0", "--port", "8000"]
