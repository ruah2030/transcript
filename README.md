# Atelier de transcription — v5

Chaîne locale : d'une vidéo à un document composé, sans qu'un octet sorte de
ta machine. Backend FastAPI, interface React.

Huit passes, de la récupération du texte parlé jusqu'à la mise en page.

## Ce qui a changé

**v5** — qualité de traduction reprise : recherche en faisceau au lieu du
décodage glouton, pénalités de longueur et de répétition, modèles `tc-big`,
et découpage en phrases qui ne coupe plus sur les abréviations. Progression
indéterminée pour les étapes sans avancement mesurable.

**v4** — deuxième voie d'accès aux sous-titres YouTube, par les endpoints
`timedtext`, indépendante de yt-dlp et essayée en premier. Diagnostic des
réglages effectifs, repli automatique sur plusieurs clients, contrôle des
valeurs placées dans le mauvais champ.

**v3** — récupération du texte parlé depuis une vidéo, sous-titres d'abord et
transcription Whisper sinon. Interface refondue autour du rail de passes,
avec historique annulable. Sélection du modèle par tâche.

**v2** — moteurs NMT (Opus-MT, Argos) à côté du modèle de langue, mode
hybride qui combine les deux, réparation ciblée. Backend et interface
séparés.

**v1** — scripts Python enchaînés à la main, interface HTML statique.

---

## Le point à comprendre avant tout le reste

Les moteurs ne sont pas interchangeables.

Un modèle NMT — Opus-MT, Argos — est un **seq2seq bilingue** : il prend
une langue en entrée, il en produit une autre. Il ne sait pas réécrire un
mauvais français en bon français, parce que cette tâche est monolingue et
n'a aucune représentation dans son espace d'entraînement. Ce n'est pas une
limite d'implémentation, c'est structurel.

D'où la répartition :

| Tâche | Direction | Moteurs possibles | 80 000 mots |
|---|---|---|---|
| Traduire | en → fr | Opus-MT, Argos, LLM, hybride | 5-15 min en NMT |
| Réparer | fr → fr | LLM seul | plusieurs heures |
| Réviser | fr → fr | LLM seul | plusieurs heures |

Le backend refuse une combinaison impossible **avant** d'ouvrir le travail,
avec un message qui nomme les moteurs capables. Tu es arrêté en une seconde
plutôt qu'après dix minutes de calcul.

### Le mode hybride

C'est celui qui compte sur une machine sans GPU.

Un LLM traite environ 4 mots/seconde sur CPU, un NMT environ 200. Mais la
sortie NMT est produite phrase par phrase : pronoms flottants, terminologie
qui dérive, idiomes rendus mot à mot.

Ces défauts ne sont pas répartis uniformément. Ils se concentrent sur une
minorité de segments, et ces segments sont repérables mécaniquement. Le mode
hybride fait donc la passe NMT sur l'intégralité, note chaque segment sur
cinq signaux, puis ne repasse au LLM que ceux qui dépassent le seuil.

Les cinq signaux, dans `services/traduction/hybride.py` :

| Signal | Ce qu'il détecte | Poids |
|---|---|---|
| Ratio de longueur | Volume perdu ou doublé — texte mangé ou inventé | 1,0 |
| Répétitions en boucle | Le décodeur a décroché et tourne en rond | 1,2 |
| Mots non traduits | De l'anglais resté tel quel dans la sortie | 1,5 |
| Phrases trop longues | Calque non restructuré — le NMT ne coupe jamais | 0,6 |
| Terminologie ignorée | Un terme du glossaire présent à la source, absent de la sortie | 1,4 |

Le dernier est le plus utile : le NMT ne connaît pas ton glossaire, donc
c'est exactement là qu'il faut le LLM. Un plafond à 30 % de segments repris
évite de basculer insensiblement vers un traitement LLM complet — au-delà,
autant le lancer franchement et l'assumer.

---

## Installation

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[nmt,conversion]"
cp .env.exemple .env
python -m uvicorn app.main:application --reload --port 8000
```

`python -m uvicorn` plutôt que `uvicorn` seul : si le venv n'est pas
correctement dans le `PATH`, la seconde forme échoue avec « commande non
trouvée » alors que le paquet est bien installé.

L'installation en mode éditable n'est pas obligatoire. Le service se lance
depuis son dossier sans être installé du tout :

```bash
pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-multipart
python -m uvicorn app.main:application --reload --port 8000
```

Au démarrage, le journal indique l'état de chaque moteur :

```
  ✓ opusmt     2 paire(s) disponible(s)
  · argos      aucun modèle installé
  ✓ llm        hy-mt-1.8b prêt
  ✓ hybride    2 paire(s) disponible(s), reprise par hy-mt-1.8b prêt
```

Documentation interactive de l'API : http://localhost:8000/docs

Si `pip install -e .` échoue sur *Multiple top-level packages discovered in
a flat-layout*, c'est que `pyproject.toml` ne déclare pas `[tool.setuptools]
packages = ["app"]`. Setuptools voit alors `app`, `ressources` et `modeles`
côte à côte et refuse de deviner lequel est le code.

### Interface

```bash
cd frontend
npm install
npm run dev
```

Sur http://localhost:5173. Détails et cas particuliers dans la section
« Prérequis » ci-dessous.

---

## Prérequis, module par module

Le service démarre toujours, même sans aucune dépendance optionnelle. Les
imports lourds — `ctranslate2`, `transformers`, `sentencepiece` — sont faits
**à l'intérieur des fonctions**, pas en tête de fichier. Un moteur dont les
dépendances manquent apparaît simplement comme indisponible dans le
diagnostic, sans empêcher le reste de fonctionner.

Vérifie l'état réel à tout moment :

```bash
curl -s localhost:8000/api/v1/moteurs | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    print(f\"{'OK' if m['disponible'] else '--'}  {m['nom']:<18} {m['detail']}\")
"
```

Chaque moteur indisponible porte un champ `remede` : la commande exacte à
lancer pour le débloquer. L'interface l'affiche derrière un lien
« Comment l'activer ? » sous le moteur grisé.

**Un moteur reste grisé après installation ?** L'interface ne charge l'état
des moteurs qu'à l'ouverture. Clique **Revérifier** à côté du titre
« Moteur » — ou vérifie le nom du dossier, qui est la cause la plus
fréquente : le registre cherche exactement `opus-<source>-<cible>-ct2`
contenant un `model.bin`. `opus-mt-en-fr` ou `en-fr` ne sont pas reconnus.

### Vue d'ensemble

| Module | Route | Paquets Python | Service externe | Fichiers requis |
|---|---|---|---|---|
| **Source vidéo** | `POST /source/inspecter` | `yt-dlp` | — | — |
| **Transcription** | `POST /travaux/transcription` | `faster-whisper`, `yt-dlp` | **ffmpeg** | — |
| Nettoyage | `POST /nettoyage` | base | — | — |
| Correction | `POST /correction` | base | — | `ressources/dictionnaire*.json` |
| Grammaire | `POST /correction` (`grammaire: true`) | base | **LanguageTool** | — |
| Analyse | `POST /analyse` | base | — | — |
| Import | `POST /documents/import` | base | — | — |
| Glossaire | `GET·PUT /glossaires` | base | — | `ressources/glossaire.json` |
| Structure | `POST /structure` | base | — | — |
| Mise en page | `POST /mise-en-page` | base | — | — |
| Travaux | `GET /travaux/…` | base | — | — |
| **Opus-MT** | moteur `opusmt` | `ctranslate2`, `transformers`, `sentencepiece` | — | `modeles/opus-<src>-<cbl>-ct2/` |
| **Argos** | moteur `argos` | `ctranslate2`, `sentencepiece` | — | paquets Argos installés |
| **LLM** | moteur `llm` | base | **Ollama** ou API OpenAI | `ressources/glossaire.json` |
| **Hybride** | moteur `hybride` | Opus-MT + LLM | **Ollama** | les deux |
| **Réparation ciblée** | moteur `reparation_ciblee` | base | **Ollama** | `dictionnaire-calques.json`, `glossaire.json` |
| Vérification | `POST /travaux/verification` | base | **Ollama** | — |

« base » signifie les dépendances installées par `pip install -e .` :
`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`,
`python-multipart`. Rien d'autre.

---

### Ce qui marche sans rien installer de plus

Sept modules sur quinze ne demandent aucun modèle ni aucun serveur : le
nettoyage, la correction par dictionnaires, l'analyse, l'import, le
glossaire, la détection de structure et la mise en page.

C'est de quoi valider toute la préparation d'un document avant de
télécharger le moindre gigaoctet. Fais-le d'abord.

**L'import de documents** lit `.txt`, `.md` et `.docx` sans aucune
dépendance — le `.docx` est dézippé et son XML nettoyé à la main. Les
autres formats renvoient la commande de conversion à lancer :

```bash
pdftotext -layout doc.pdf doc.txt        # PDF
pandoc doc.odt -t plain -o doc.txt       # ODT, RTF, EPUB, HTML
```

**La correction** cherche `ressources/dictionnaire*.json` — le motif est un
glob, tu peux en ajouter autant que tu veux, ils apparaîtront dans
`GET /dictionnaires`. Un dictionnaire absent lève une erreur explicite plutôt
que d'être ignoré silencieusement.

**La mise en page** a une dépendance non évidente : elle suppose **un
paragraphe par ligne**. La détection d'intertitres teste que la ligne
suivante dépasse 80 caractères ; sur un texte replié à 72 colonnes, tous les
intertitres sont pris pour du corps de texte. Lance donc le nettoyage avec
fusion des paragraphes avant. `POST /structure` détecte le cas et te
prévient dans le champ `avertissement`.

---

### Source vidéo et transcription

```bash
pip install -e ".[transcription]"
sudo apt install ffmpeg
```

`faster-whisper` s'appuie sur **CTranslate2**, le même moteur d'inférence que
les traducteurs Opus-MT et Argos. Si tu as déjà installé l'extra `nmt`, il
n'y a pas de seconde pile à mettre en place. `ffmpeg` sert à décoder et
rééchantillonner l'audio ; sans lui, seuls les sous-titres fonctionnent.

**Deux voies vers les sous-titres, essayées dans l'ordre.**

`youtube-transcript-api` lit les endpoints `timedtext` de YouTube — la même
source que le panneau de transcription affiché sur youtube.com. Ni clé
d'API, ni OAuth, ni navigateur piloté.

yt-dlp, lui, interroge l'API du lecteur, que YouTube protège bien plus
sévèrement. C'est de là que viennent les blocages « Sign in to confirm
you're not a bot ».

Les deux chemins étant distincts, **le premier passe souvent quand le second
est refusé**. Le service essaie donc timedtext d'abord, puis yt-dlp, puis
Whisper. Si yt-dlp est bloqué mais que les sous-titres restent lisibles,
l'inspection répond quand même avec ce qu'elle a.

yt-dlp reste indispensable pour les autres plateformes et pour l'extraction
audio.

**Les sous-titres passent avant Whisper.** Beaucoup de vidéos en ont déjà,
humains ou générés. Les récupérer prend quelques secondes contre des minutes
de calcul, et c'est vrai même quand ils sont automatiques. Le service tente
donc toujours cette voie en premier, sauf si tu coches « transcrire l'audio
même si des sous-titres existent ».

`POST /source/inspecter` ne télécharge rien et répond en quelques secondes.
Il annonce le titre, la durée, les pistes disponibles et la voie qui sera
prise. C'est ce qui évite de lancer vingt minutes de transcription sur une
vidéo qui avait déjà ses sous-titres.

Modèles Whisper, sur CPU sans GPU :

| Modèle | Poids | Vitesse | 1 h d'audio | Pour quoi |
|---|---|---|---|---|
| `tiny` | 75 Mo | ~20× | ~3 min | Repérage seulement, trop d'erreurs |
| `base` | 145 Mo | ~12× | ~5 min | Prise de son nette, sans accent marqué |
| `small` | 484 Mo | ~6× | ~10 min | **Le bon compromis. Défaut.** |
| `medium` | 1,5 Go | ~2,5× | ~24 min | Meilleur sur les accents et le bruit |
| `large-v3` | 3,1 Go | ~1× | ~60 min | Le meilleur, mais lent sans GPU |

Les vitesses sont des ordres de grandeur, très dépendants du nombre de
cœurs. `/source/inspecter` renvoie une estimation par modèle pour la durée
réelle de ta vidéo.

Deux réglages qui comptent, appliqués par défaut :

- **filtre VAD** — les silences sont sautés, ce qui accélère beaucoup les
  enregistrements avec des pauses ;
- **`condition_on_previous_text=False`** — sans ça, Whisper part parfois en
  boucle et répète la même phrase pendant plusieurs minutes.

Précise la langue plutôt que de laisser détecter. Sur un français parsemé de
citations anglaises, la détection automatique bascule parfois d'une langue à
l'autre en cours de route.

Tu peux aussi déposer un fichier audio ou vidéo directement, via
`POST /travaux/transcription-fichier`, quand la source n'est pas une URL
publique.

#### Quand l'extraction échoue

`Precondition check failed`, `HTTP Error 400`, `Unable to extract` : dans la
quasi-totalité des cas, **yt-dlp est périmé**. YouTube change son API
régulièrement et seules les versions récentes suivent.

```bash
python -m pip install -U --pre yt-dlp
yt-dlp --version
```

Vérifie d'abord quel binaire répond :

```bash
which yt-dlp
```

S'il pointe vers `/usr/bin/yt-dlp`, c'est la version d'apt. Les paquets
système accusent souvent un retard considérable et refusent de se mettre à
jour seuls, en renvoyant vers le gestionnaire de paquets. Retire-la pour que
celle du venv reprenne la main :

```bash
sudo apt remove yt-dlp
```

`GET /transcription/modeles` affiche la version détectée et signale le cas
où le binaire vient du système. Les erreurs d'extraction portent désormais
la marche à suivre plutôt que la pile de warnings brute.

#### Quand YouTube demande une authentification

`Sign in to confirm you're not a bot` est un problème distinct du précédent :
mettre yt-dlp à jour n'y change rien. Trois remèdes, du moins engageant au
plus. Redémarre le service après chaque modification de `.env` — la
configuration est lue au démarrage.

**0. Vérifie d'abord que ton réglage est bien chargé.**

```bash
curl -s localhost:8000/api/v1/transcription/config | python3 -m json.tool
```

`arguments_passes` montre exactement ce qui part vers yt-dlp. Si tu ne
retrouves pas ton réglage, c'est qu'il n'a jamais été lu : **uvicorn
`--reload` ne surveille que les fichiers Python**, donc modifier `.env` ne
redémarre rien. Il faut arrêter le serveur avec Ctrl+C et le relancer.

C'est la cause la plus fréquente d'un réglage « qui ne marche pas ».

**1. Changer de client.** YouTube n'applique pas les mêmes contrôles à tous
ses clients, et en imiter un autre suffit souvent. Aucun compte n'est
impliqué, c'est donc à essayer en premier.

Sans `ATELIER_YTDLP_CLIENT`, le service essaie automatiquement `tv`, `mweb`,
`android`, `web_safari` puis `ios` avant d'abandonner, et l'erreur indique
lesquels ont été tentés. Ne renseigne le réglage que pour en imposer un.

```
ATELIER_YTDLP_CLIENT=tv
```

Puis, si besoin : `mweb`, `android`, `web_safari`. Teste en ligne de commande
plutôt que par l'interface, c'est plus rapide :

```bash
yt-dlp --extractor-args "youtube:player_client=tv" \
       --dump-json --skip-download "URL" | head -c 300
```

**2. Un fichier de cookies exporté.** Le plus fiable : il ne dépend ni du
trousseau système ni de l'état du navigateur, ce qui compte pour un service
qui tourne en fond. Exporte un `cookies.txt` au format Netscape depuis une
extension de ton navigateur, puis :

```
ATELIER_YTDLP_COOKIES_FICHIER=~/cookies.txt
```

**3. Les cookies lus directement dans le navigateur.** Plus simple mais plus
fragile sous Linux. Ferme le navigateur avant d'essayer : il verrouille sa
base de cookies, et l'extraction échoue tant qu'il tourne.

Les deux familles ne désignent pas leur profil de la même façon. Firefox
utilise un chemin, Chrome et Chromium un nom :

```
ATELIER_YTDLP_COOKIES=chrome:Default
ATELIER_YTDLP_COOKIES=chromium:Profile 1
```

Chrome et Chromium chiffrent en outre leurs cookies avec le trousseau
système, ce qui échoue souvent hors session interactive. Un suffixe permet
d'imposer le mécanisme — `gnomekeyring`, `kwallet` ou `basictext`, ce
dernier quand aucun trousseau ne tourne :

```
ATELIER_YTDLP_COOKIES=chrome+basictext:Default
``` Firefox
en snap ou flatpak range son profil ailleurs que là où yt-dlp le cherche —
il faut alors le désigner :

```bash
ls -d ~/snap/firefox/common/.mozilla/firefox/*.default* \
      ~/.mozilla/firefox/*.default* 2>/dev/null
```

Firefox nomme ses profils avec un identifiant aléatoire — recopie le nom
complet du dossier obtenu, pas un exemple :

```
ATELIER_YTDLP_COOKIES=firefox:~/snap/firefox/common/.mozilla/firefox/k7m3p2q9.default-release
```

Le `~` est développé par le service, et un profil introuvable est refusé au
démarrage de la requête plutôt que de laisser yt-dlp retomber silencieusement
sur un accès anonyme — c'est ce qui rendait la panne trompeuse, l'erreur
parlant d'authentification sans jamais mentionner le chemin fautif.

Un mot d'avertissement : utiliser ton compte principal pour du
téléchargement automatisé peut le faire signaler par YouTube.

Ce que tu récupères d'une vidéo dépend de ce que la plateforme et l'auteur
autorisent — vérifie de ton côté ce que tu as le droit de télécharger.

### Grammaire — LanguageTool

```bash
docker run -d -p 8081:8010 silviof/docker-languagetool
```

Configuration : `ATELIER_LANGUAGETOOL_URL=http://localhost:8081`.

Sur une machine à 14 Go, borne la JVM, sinon elle prend ce qu'elle trouve :

```bash
docker run -d -p 8081:8010 \
  -e Java_Xms=256m -e Java_Xmx=1g \
  silviof/docker-languagetool
```

Le service ne retient que les corrections à **remplacement unique** et
ignore les catégories `TYPOGRAPHY`, `STYLE`, `REDUNDANCY` et `CASING` —
elles entrent en conflit avec la passe typographique, qui est déterministe
et dépend de la langue d'arrivée. Les cas ambigus sont laissés à l'humain.

---

### Opus-MT — le moteur rapide

**Paquets.** `torch` ne sert qu'à la conversion, jamais à l'inférence. Tu
peux le désinstaller une fois tes modèles convertis.

```bash
pip install ctranslate2 sentencepiece transformers
pip install torch --index-url https://download.pytorch.org/whl/cpu   # conversion seule
```

**Modèles.** Une conversion par paire, une fois pour toutes. Prends la
version « big » si tu tiens à la qualité :

```bash
make modele-en-fr-big    # opus-mt-tc-big-en-fr, recommandé
make modele-en-fr        # opus-mt-en-fr, léger et nettement moins bon
```

Les modèles `tc-big` sont trois à quatre fois plus lents et bien meilleurs
sur les phrases longues et les tournures idiomatiques. Sur un document que
tu comptes garder, l'échange est favorable : quinze minutes deviennent une
heure, mais la relecture derrière est bien plus courte.

La conversion écrit un fichier `depot.txt` dans le dossier du modèle, qui
indique au service quel tokenizer charger — les deux familles ne suivent pas
la même convention de nommage sur HuggingFace.

**Qualité du décodage.** Quatre réglages pèsent lourd, et leurs défauts ont
changé en v4 :

| Réglage | Défaut | Effet |
|---|---|---|
| `ATELIER_CT2_FAISCEAU` | `4` | Recherche en faisceau. `1` est glouton : deux à trois fois plus rapide et nettement plus mauvais |
| `ATELIER_CT2_PENALITE_LONGUEUR` | `1.1` | En dessous de `1`, le décodeur tronque les phrases complexes |
| `ATELIER_CT2_PENALITE_REPETITION` | `1.05` | Freine les boucles de répétition |
| `ATELIER_CT2_RECOPIER_INCONNUS` | `false` | À `true`, recopie le mot anglais quand le modèle sèche |

Le dernier mérite une explication. Recopier le mot source produit des
anglicismes qui se fondent dans le texte et échappent à la relecture. Un
passage manifestement raté se repère ; « the purpose » glissé au milieu
d'une phrase française, beaucoup moins.

**Le nom du dossier est contractuel** : le registre scanne `modeles/` en
cherchant le motif `opus-<source>-<cible>-ct2` contenant un `model.bin`. Un
dossier renommé n'est pas vu. Les modèles ajoutés apparaissent au
**redémarrage** du service, pas à chaud.

**Réseau au premier appel.** Les poids viennent du dossier converti, mais le
tokenizer est chargé depuis Hugging Face (`Helsinki-NLP/opus-mt-<src>-<cbl>`)
— c'est le pattern documenté par CTranslate2 pour les modèles Marian. Il est
mis en cache dans `~/.cache/huggingface`, ensuite tu es hors-ligne. Prévois
donc une connexion au tout premier essai de chaque paire.

**Le pivot.** Si la paire directe manque, le moteur se rabat sur
`source → en → cible`, ce qui double le temps. `en→fr` et `fr→en` sont
toujours en une seule passe.

---

### Argos

```bash
pip install ctranslate2 sentencepiece argostranslate
```

Détail utile : **`argostranslate` n'est jamais importé par le service**. Il
ne sert qu'à installer les paquets ; à l'exécution, le moteur lit
directement le dossier de paquets avec CTranslate2 et SentencePiece. Tu peux
l'installer dans un autre environnement si tu veux garder celui-ci léger.

Emplacement scanné, dans l'ordre :

1. la variable `ARGOS_PACKAGES_DIR` si elle est définie ;
2. sinon `~/.local/share/argos-translate/packages/`.

Le moteur cherche des dossiers commençant par `translate-<src>_<cbl>`.
Chacun doit contenir un sous-dossier `model/` et un fichier
`sentencepiece.model`.

Argos **pivote systématiquement par l'anglais** : `fr→es` coûte deux passes.
C'est sa différence principale avec Opus-MT, qui existe en paires directes.

---

### LLM — Ollama ou API compatible OpenAI

Aucun paquet supplémentaire : le service parle HTTP via `httpx`, déjà dans
les dépendances de base.

```bash
# Modèle de traduction spécialisé, léger
cat > Modelfile <<'EOF'
FROM hf.co/tencent/HY-MT1.5-1.8B-GGUF:Q8_0
TEMPLATE """<｜hy_begin▁of▁sentence｜>{{ if .System }}{{ .System }}<｜hy_place▁holder▁no▁3｜>{{ end }}{{ if .Prompt }}<｜hy_User｜>{{ .Prompt }}{{ end }}<｜hy_Assistant｜>"""
PARAMETER num_ctx 2048
EOF
ollama create hy-mt-1.8b -f Modelfile
```

Configuration :

```
ATELIER_LLM_URL=http://localhost:11434
ATELIER_LLM_API=ollama          # ou « openai » pour LM Studio, llama.cpp, vLLM
ATELIER_LLM_MODELE=hy-mt-1.8b
ATELIER_LLM_CONTEXTE=2048
```

Pour une API compatible OpenAI, la clé se passe par `OPENAI_API_KEY` dans
l'environnement — elle n'est jamais écrite dans la configuration.

**Deux modèles, un par famille de tâche.** Traduire d'une langue à une
autre et réécrire dans une seule langue sont deux compétences distinctes.
Un spécialisé traduction comme HY-MT est excellent sur la première et
médiocre sur la seconde : il n'a jamais vu de consigne de réécriture
monolingue, et ne produit pas le JSON attendu par la vérification.

Le service route donc selon la capacité demandée :

| Capacité | Modèle utilisé |
|---|---|
| `traduction` | `ATELIER_LLM_MODELE` |
| `reparation`, `revision` | `ATELIER_LLM_MODELE_REECRITURE` |
| vérification de fidélité | `ATELIER_LLM_MODELE_REECRITURE` |

```
ATELIER_LLM_MODELE=hy-mt-1.8b               # spécialisé traduction
ATELIER_LLM_MODELE_REECRITURE=mistral-nemo:12b   # généraliste
```

Le second est facultatif : vide, le premier sert à tout. Les deux sont
vérifiés au démarrage, et un modèle manquant est nommé dans le remède.

Le modèle fait partie de l'empreinte de cache : en changer invalide
naturellement les segments concernés, sans purge manuelle.

**Comparer deux modèles sans redémarrer.** L'interface propose un sélecteur
de modèle dès qu'un moteur à LLM est choisi, alimenté par
`GET /api/v1/modeles`. Le choix ne vaut que pour l'appel en cours et ne
touche pas à `.env`. En ligne de commande, c'est le champ `modele` :

```bash
for m in gemma3:4b qwen3:8b mistral-nemo:12b; do
  echo "=== $m ==="
  curl -s -X POST localhost:8000/api/v1/traduction \
    -H 'Content-Type: application/json' \
    -d "{\"texte\":\"<un segment vraiment mauvais>\",\"moteur\":\"llm\",
         \"capacite\":\"reparation\",\"source\":\"fr\",\"cible\":\"fr\",
         \"modele\":\"$m\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["texte"])'
done
```

Les caches sont séparés par modèle, donc relancer la comparaison est
instantané.

Candidats pour la réécriture, sur 14 Go sans GPU :

| Modèle | Poids Q4 | Débit CPU | Plafond auto |
|---|---|---|---|
| `gemma3:4b` | ~2,5 Go | 8-12 tok/s | 30 % |
| `qwen3:8b` | ~5 Go | 4-6 tok/s | 20 % |
| `mistral-nemo:12b` | 7,1 Go | 2-3 tok/s | 15 % |
| `gemma3:12b` | 8,1 Go | 2-3 tok/s | 15 % |

La colonne « plafond auto » est la part maximale de segments que la
réparation ciblée accepte de réécrire. Elle se déduit de la taille lue dans
le nom du modèle, parce que le coût par segment varie d'un facteur six entre
un 4B et un 12B : un plafond fixe ferait passer le même document de vingt
minutes à deux heures selon le modèle, sans que rien ne le signale. Tu peux
la forcer en passant `part_maximale` au constructeur.

**Réglages mémoire, indispensables sur 14 Go.** Par défaut Ollama alloue le
cache KV pour quatre requêtes parallèles et peut garder plusieurs modèles
chargés :

```bash
export OLLAMA_NUM_PARALLEL=1        # 8 si tu veux du débit sur un petit modèle
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=10m
```

Le parallélisme multiplie la mémoire du cache KV. Batch 8 sur un 4B passe
largement ; batch 8 sur un 12B avec un grand contexte fait partir la machine
en swap.

---

### Hybride

Cumule les prérequis d'Opus-MT et du LLM. Si l'un des deux manque, le
diagnostic le dit précisément :

```
· hybride   NMT prêt mais LLM indisponible — serveur injoignable sur …
```

Réglages dans `services/traduction/hybride.py` :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `seuil` | `1.0` | Score minimal pour qu'un segment soit repris par le LLM |
| `part_maximale` | `0.30` | Plafond de segments repris. Baisse-le à `0.15` avec un modèle de 12B sur CPU |

Le signal le plus utile est « terminologie ignorée » : il compare les termes
de ton `glossaire.json` présents à la source et absents de la sortie. **Sans
glossaire, ce signal est neutralisé** et la détection perd son meilleur
indicateur. Enrichir le glossaire améliore donc à la fois la qualité de la
reprise et sa précision de ciblage.

---

### Réparation ciblée

Prérequis : un LLM, plus deux fichiers de ressources qui servent de
détecteurs.

| Fichier | Section lue | Effet si absent |
|---|---|---|
| `dictionnaire-calques.json` | `signalements` | Le signal correspondant vaut zéro |
| `glossaire.json` | `calques_a_bannir` | Le signal correspondant vaut zéro |

Les six autres signaux — phrases interminables, densité passive,
connecteurs répétés, résidus anglais, pronoms flottants — sont
morphosyntaxiques et ne dépendent d'aucun fichier.

Ces deux fichiers sont donc le point de réglage principal : **enrichir les
`signalements` améliore la détection sans toucher au code**. C'est le même
geste que celui que tu fais déjà en relecture.

Règle le seuil avant d'engager du temps de calcul, avec un endpoint qui
n'appelle aucun modèle :

```bash
curl -X POST localhost:8000/api/v1/diagnostic-reparation \
  -H 'Content-Type: application/json' \
  -d '{"texte":"…","capacite":"reparation"}'
```

Il rend le nombre de segments au-dessus du seuil, les motifs de chacun, le
volume de mots à réécrire et une estimation de durée par taille de modèle.

Le paramètre `taille_segment` vaut 1200 par défaut, contre 3500 en
traduction. C'est délibéré : la granularité de découpe borne la précision du
ciblage — dans un bloc de 3500 caractères, bon et mauvais français
cohabitent et on réécrit du texte correct pour rien. Descendre plus bas que
1200 n'aide pas : plus les segments sont petits, plus il y en a qui
franchissent le seuil.

---

### Vérification de fidélité

Un LLM, rien d'autre. Prends un **modèle généraliste**, pas un spécialisé
traduction : la tâche demande de produire du JSON structuré et de raisonner
sur deux textes, ce que HY-MT ne fait pas.

Limite structurelle à garder en tête : aucun modèle ne retrouve un sens
absent des deux versions comparées. Compare contre le texte d'origine quand
tu l'as, pas contre une version déjà dégradée.

---

### Interface

`node` 18 ou plus, et `npm`.

```bash
cd frontend
npm install
npm run dev
```

Le proxy Vite renvoie `/api` vers `http://localhost:8000` — c'est le **seul
endroit** où le port du backend est écrit côté front, le client API
n'utilise que des chemins relatifs. Si tu changes de port, corrige
`vite.config.ts` et rien d'autre.

Ce proxy évite tout CORS en développement, flux SSE compris. Le navigateur
ne parle jamais directement à Ollama : contrairement à la v1, `OLLAMA_ORIGINS`
n'est plus nécessaire.

En production, sers le `dist/` par un serveur statique et ajoute son origine
à `ATELIER_ORIGINES_AUTORISEES`.

---

### Récapitulatif d'installation par ambition

**Préparer des documents, sans aucun modèle**

```bash
pip install -e .
```

Nettoyage, correction, analyse, structure, mise en page, diagnostic de
réparation. Suffisant pour valider toute la chaîne.

**Y ajouter la grammaire**

```bash
docker run -d -p 8081:8010 -e Java_Xmx=1g silviof/docker-languagetool
```

**Traduire vite**

```bash
pip install -e ".[nmt,conversion]"
make modele-en-fr
```

**Tout, y compris réparation et révision**

Les deux précédents, plus Ollama avec un modèle généraliste et un modèle
spécialisé traduction.

---

## L'ordre des passes

L'enchaînement n'est pas arbitraire — il y a des dépendances réelles.

```
0. Source      sous-titres d'une vidéo, ou transcription de son audio
1. Nettoyage   marqueurs temporels, fusion en paragraphes
2. Correction  typographie, doublons, dictionnaires, références
3. Grammaire   LanguageTool (optionnel)
4. Analyse     profil, alertes, estimation de durée par moteur
5. Traduction  moteur choisi, avec suivi si le texte est long
6. Mise en page HTML imprimable ou Markdown
7. Vérification contrôle de fidélité (optionnel)
```

**La fusion des paragraphes de l'étape 1 est requise par l'étape 6.** La
détection d'intertitres suppose un paragraphe par ligne : sur un texte
replié, les intertitres sont pris pour du corps de texte. L'endpoint
`/structure` le détecte et l'annonce, mais mieux vaut ne pas y arriver.

---

## Architecture

```
backend/app/
├── core/          config, erreurs métier
├── domain/        découpage, typographie, langues — logique pure
├── services/
│   ├── correction.py      passes 1 à 4
│   ├── mise_en_page.py    passe 6
│   ├── verification.py    passe 7
│   ├── transcription/
│   │   ├── sources.py     yt-dlp — inspection, sous-titres, audio
│   │   └── whisper.py     faster-whisper (CTranslate2)
│   └── traduction/
│       ├── base.py        contrat + capacités
│       ├── nmt.py         Opus-MT et Argos (CTranslate2)
│       ├── llm.py         Ollama / OpenAI
│       ├── hybride.py     NMT + reprise ciblée
│       └── registre.py    résolution et diagnostic
├── infra/         cache disque, gestionnaire de travaux
├── schemas/       contrat d'API
└── api/v1/        routes
```

Trois principes tenus :

**Le domaine ne dépend de rien.** `domain/` n'importe ni FastAPI, ni httpx,
ni CTranslate2. Le découpage et la typographie sont testables sans rien
démarrer.

**Les moteurs déclarent leurs capacités.** Ajouter un moteur, c'est écrire
une classe qui remplit `MoteurTraduction` et l'inscrire au registre. Aucune
route ne change.

**Les traitements longs sont des travaux.** POST ouvre et rend un
identifiant, le client s'abonne en SSE. Un onglet rouvert retrouve l'état
courant sans avoir manqué la fin.

---

## Ce qui est vérifié, et ce qui ne l'est pas

Testé de bout en bout : la chaîne de correction sur des données réelles
(dictionnaires, signalements, références), le garde-fou de capacité, le
cycle travail + SSE, la détection de structure, la génération HTML et
Markdown, la compilation TypeScript et le build de production.

**Non exécuté : le chemin CTranslate2.** Le code des moteurs NMT est écrit
mais n'a jamais tourné avec de vrais poids. Attends-toi à devoir ajuster au
premier lancement, en particulier la tokenisation Marian. Commence par un
paragraphe avant de lancer un livre.

Non exécuté non plus : le chemin LLM contre un vrai Ollama, et le contrôle
de fidélité.

---

## Ce que la chaîne ne fait pas

Les passes 1 à 4 réparent des erreurs de surface. Elles ne touchent pas à
la syntaxe. Un texte issu de traduction automatique reste bâti sur une
grammaire étrangère, et aucune règle mécanique ne corrige ça.

Le mode hybride produit un brouillon exploitable, pas un texte publiable.
Une relecture humaine reste nécessaire, en particulier sur les citations
bibliques, qu'il vaut mieux recopier depuis une version française établie
que de laisser réécrire.

Enfin, ces outils servent à rendre lisible un texte que tu possèdes, pour
ton usage. Pour un ouvrage publié, l'édition française officielle reste la
référence citable.
# transcript
