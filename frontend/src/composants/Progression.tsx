import type { InstantaneTravail } from "@/api/types";

function dureeLisible(secondes: number): string {
  if (secondes < 60) return `${Math.round(secondes)} s`;
  const m = Math.floor(secondes / 60);
  if (m < 60) return `${m} min ${Math.round(secondes % 60)} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

interface Props {
  travail: InstantaneTravail;
  onAnnuler: () => void;
}

export function Progression({ travail, onAnnuler }: Props) {
  const pourcent = Math.round(travail.progression * 100);
  const actif = travail.etat === "en_cours" || travail.etat === "en_attente";
  // Certaines étapes n'ont pas d'avancement mesurable — une requête réseau
  // aboutit ou non. Une barre figée à 0 % y ressemble à un blocage ; une
  // barre indéterminée dit la vérité : « en cours, durée inconnue ».
  const indetermine = actif && travail.total === 0;

  return (
    <div className="progression" role="status" aria-live="polite">
      <div className="progression__entete">
        <span className="progression__etat">
          {travail.etat === "en_attente" && "En attente d'un créneau…"}
          {travail.etat === "en_cours" && (travail.etiquette || "Traitement")}
          {travail.etat === "termine" && "Terminé"}
          {travail.etat === "echoue" && "Échec"}
          {travail.etat === "annule" && "Annulé"}
        </span>
        {actif && (
          <button type="button" className="lien" onClick={onAnnuler}>
            Annuler
          </button>
        )}
      </div>

      <div
        className={`jauge ${indetermine ? "jauge--indeterminee" : ""}`}
        role="progressbar"
        aria-valuenow={indetermine ? undefined : pourcent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="jauge__barre"
          style={indetermine ? undefined : { width: `${pourcent}%` }}
        />
      </div>

      <div className="progression__pied">
        <span>
          {indetermine
            ? "durée inconnue"
            : `${travail.faits} / ${travail.total} · ${pourcent} %`}
        </span>
        {travail.secondes_restantes !== null && actif && !indetermine && (
          <span>reste ~{dureeLisible(travail.secondes_restantes)}</span>
        )}
      </div>
    </div>
  );
}
