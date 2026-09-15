import type { ErreurAtelier } from "@/api/client";

interface Props {
  erreur: ErreurAtelier;
  onFermer?: () => void;
}

/** Affiche le message ET la piste d'action que le backend joint à chaque
 *  erreur métier. C'est le `detail` qui a de la valeur : il contient la
 *  commande à lancer ou le moteur à choisir. */
export function Alerte({ erreur, onFermer }: Props) {
  return (
    <div className="alerte" role="alert">
      <div className="alerte__corps">
        <strong>{erreur.message}</strong>
        {erreur.detail && <pre className="alerte__detail">{erreur.detail}</pre>}
      </div>
      {onFermer && (
        <button type="button" className="lien" onClick={onFermer}>
          Fermer
        </button>
      )}
    </div>
  );
}
