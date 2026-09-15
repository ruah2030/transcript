import type { Etape } from "@/crochets/useDocument";

interface Props {
  etapes: Etape[];
  onRevenir: (a: number) => void;
  desactive?: boolean;
}

const NOMS: Record<string, string> = {
  nettoyage: "Nettoyage",
  correction: "Correction",
  grammaire: "Grammaire",
  traduction: "Traduction",
  saisie: "Édition manuelle",
};

function heure(a: number): string {
  return new Date(a).toLocaleTimeString("fr-FR", {
    hour: "2-digit", minute: "2-digit",
  });
}

/** Chaque passe empile l'état d'avant. Revenir à une ligne dépile tout ce
 *  qui a suivi — le comportement d'une pile d'annulation, pas d'une
 *  branche : on ne peut pas rejouer sélectivement. */
export function Historique({ etapes, onRevenir, desactive }: Props) {
  if (!etapes.length) {
    return (
      <p className="vide">
        Aucune transformation pour l'instant. Chaque passe s'inscrira ici,
        et tu pourras revenir à n'importe quel état.
      </p>
    );
  }

  return (
    <ol className="historique">
      {etapes.map((etape) => (
        <li key={etape.a}>
          <button
            type="button"
            className="historique__ligne"
            disabled={desactive}
            onClick={() => onRevenir(etape.a)}
            title="Revenir à l'état d'avant cette passe"
          >
            <span className="historique__heure">{heure(etape.a)}</span>
            <span className="historique__corps">
              <strong>{NOMS[etape.passe] ?? etape.passe}</strong>
              <em>{etape.resume}</em>
            </span>
            <span className="historique__action">revenir</span>
          </button>
        </li>
      ))}
    </ol>
  );
}
