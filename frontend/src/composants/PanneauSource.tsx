import { useState } from "react";

import { ErreurAtelier, api } from "@/api/client";
import type { InstantaneTravail, ReponseSource } from "@/api/types";
import { Progression } from "@/composants/Progression";

const MODELES = [
  { nom: "tiny", libelle: "tiny · 75 Mo" },
  { nom: "base", libelle: "base · 145 Mo" },
  { nom: "small", libelle: "small · 484 Mo" },
  { nom: "medium", libelle: "medium · 1,5 Go" },
  { nom: "large-v3", libelle: "large-v3 · 3,1 Go" },
];

function duree(secondes: number): string {
  if (!secondes) return "—";
  const h = Math.floor(secondes / 3600);
  const m = Math.round((secondes % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
}

interface Props {
  desactive?: boolean;
  travail: InstantaneTravail | null;
  onErreur: (e: ErreurAtelier) => void;
  onLancer: (corps: {
    url: string; langue: string; modele: string; forcer_audio: boolean;
  }) => void;
  onAnnuler: () => void;
}

/**
 * Passe 0 — obtenir le texte parlé.
 *
 * L'inspection précède toujours le lancement. Elle ne télécharge rien et
 * répond en quelques secondes, mais elle change la décision : une vidéo qui
 * a des sous-titres se récupère instantanément, là où une transcription
 * audio de la même vidéo prendrait vingt minutes.
 */
export function PanneauSource({
  desactive, travail, onErreur, onLancer, onAnnuler,
}: Props) {
  const [url, setUrl] = useState("");
  const [langue, setLangue] = useState("fr");
  const [modele, setModele] = useState("small");
  const [forcerAudio, setForcerAudio] = useState(false);
  const [media, setMedia] = useState<ReponseSource | null>(null);
  const [inspection, setInspection] = useState(false);

  const inspecter = async () => {
    if (!url.trim()) return;
    setInspection(true);
    setMedia(null);
    try {
      setMedia(await api.inspecterSource(url.trim()));
    } catch (e) {
      onErreur(e as ErreurAtelier);
    } finally {
      setInspection(false);
    }
  };

  const surSousTitres =
    media !== null && media.voie_prevue !== "transcription" && !forcerAudio;
  const estimation = media?.estimations?.[modele];

  return (
    <div className="source">
      <div className="source__saisie">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void inspecter(); }}
          placeholder="Adresse de la vidéo — YouTube, Vimeo, et des centaines d'autres"
          disabled={desactive || inspection}
          aria-label="Adresse de la vidéo"
        />
        <button
          type="button"
          onClick={() => void inspecter()}
          disabled={desactive || inspection || !url.trim()}
        >
          {inspection ? "Lecture…" : "Examiner"}
        </button>
      </div>

      {media && (
        <div className="media">
          <div className="media__entete">
            <strong>{media.titre}</strong>
            <span className="media__meta">
              {media.chaine && `${media.chaine} · `}
              {duree(media.duree_secondes)}
            </span>
          </div>

          <p className={`media__voie media__voie--${media.voie_prevue}`}>
            {media.detail}
          </p>

          {media.pistes.length > 0 && (
            <details>
              <summary>
                {media.pistes.length} piste(s) de sous-titres
              </summary>
              <ul className="pistes">
                {media.pistes.map((p) => (
                  <li key={`${p.langue}-${String(p.automatique)}`}>
                    <code>{p.langue}</code>
                    <em>{p.automatique ? "automatique" : "rédigés"}</em>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="source__reglages">
        <label>
          <span>Langue parlée</span>
          <select
            value={langue}
            onChange={(e) => setLangue(e.target.value)}
            disabled={desactive}
          >
            <option value="fr">Français</option>
            <option value="en">Anglais</option>
            <option value="es">Espagnol</option>
            <option value="pt">Portugais</option>
            <option value="">Détecter automatiquement</option>
          </select>
        </label>

        <label>
          <span>Modèle de transcription</span>
          <select
            value={modele}
            onChange={(e) => setModele(e.target.value)}
            disabled={desactive || surSousTitres}
          >
            {MODELES.map((m) => (
              <option key={m.nom} value={m.nom}>{m.libelle}</option>
            ))}
          </select>
        </label>
      </div>

      <label className="case">
        <input
          type="checkbox"
          checked={forcerAudio}
          onChange={(e) => setForcerAudio(e.target.checked)}
          disabled={desactive}
        />
        Transcrire l'audio même si des sous-titres existent
      </label>

      <p className="aide">
        {surSousTitres
          ? "Les sous-titres seront récupérés directement — quelques secondes."
          : estimation
            ? `Transcription estimée à ${duree(estimation)} de calcul `
              + `pour ${duree(media?.duree_secondes ?? 0)} d'audio. `
              + "Ordre de grandeur, très dépendant de ton processeur."
            : "Examine d'abord une adresse pour connaître la durée estimée."}
      </p>

      {travail && <Progression travail={travail} onAnnuler={onAnnuler} />}

      <div className="barre">
        <button
          type="button"
          className="primaire"
          onClick={() => onLancer({
            url: url.trim(), langue, modele, forcer_audio: forcerAudio,
          })}
          disabled={desactive || !url.trim()}
        >
          {surSousTitres ? "Récupérer les sous-titres" : "Transcrire"}
        </button>
      </div>

      <p className="aide">
        Les sous-titres automatiques arrivent sans ponctuation fiable et par
        blocs de quelques secondes. Enchaîne toujours sur le nettoyage puis
        la correction.
      </p>
    </div>
  );
}
