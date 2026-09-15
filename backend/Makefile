.PHONY: install install-nmt run modele-en-fr modele-fr-en lint

install:
	pip install -e .

install-nmt:
	pip install -e ".[nmt,conversion]"

install-transcription:
	pip install -e ".[transcription]"
	@echo "Pense à ffmpeg : sudo apt install ffmpeg"

run:
	uvicorn app.main:application --reload --port 8000

# Conversion des modèles Opus-MT. Une fois par paire.
#
# Les cibles « big » prennent les modèles tc-big, nettement meilleurs sur
# les phrases longues et les tournures idiomatiques. Ils sont trois à quatre
# fois plus lents. Sur un document qu'on garde, c'est le bon échange.
# Le fichier depot.txt indique au service quel tokenizer charger.

modele-en-fr-big:
	ct2-transformers-converter --model Helsinki-NLP/opus-mt-tc-big-en-fr \
		--output_dir modeles/opus-en-fr-ct2 --quantization int8
	@echo "Helsinki-NLP/opus-mt-tc-big-en-fr" > modeles/opus-en-fr-ct2/depot.txt

modele-fr-en-big:
	ct2-transformers-converter --model Helsinki-NLP/opus-mt-tc-big-fr-en \
		--output_dir modeles/opus-fr-en-ct2 --quantization int8
	@echo "Helsinki-NLP/opus-mt-tc-big-fr-en" > modeles/opus-fr-en-ct2/depot.txt

# Versions légères, pour un premier essai ou une machine contrainte.
modele-en-fr:
	ct2-transformers-converter --model Helsinki-NLP/opus-mt-en-fr \
		--output_dir modeles/opus-en-fr-ct2 --quantization int8
	@echo "Helsinki-NLP/opus-mt-en-fr" > modeles/opus-en-fr-ct2/depot.txt

modele-fr-en:
	ct2-transformers-converter --model Helsinki-NLP/opus-mt-fr-en \
		--output_dir modeles/opus-fr-en-ct2 --quantization int8
	@echo "Helsinki-NLP/opus-mt-fr-en" > modeles/opus-fr-en-ct2/depot.txt

lint:
	ruff check app
