import { useState } from "react";

import type {
  Capacite, EtatMoteur, ModeleDisponible, NomMoteur, OptionsTraduction, Registre,
} from "@/api/types";

const CAPACITES: { valeur: Capacite; libelle: string; aide: string }[] = [
  {
    valeur: "traduction",
    libelle: "Traduire",
    aide: "D'une langue vers une autre.",
  },
  {
    valeur: "reparation",
    libelle: "Réparer",
    aide: "Réécrire une traduction automatique ratée, dans sa propre langue. "
      + "Monolingue : seul un LLM sait le faire.",
  },
  {
    valeur: "revision",
    libelle: "Réviser",
    aide: "Relire une traduction humaine sans tout réécrire. Monolingue.",
  },
];

const REGISTRES: Registre[] = ["soutenu", "courant", "technique", "commercial"];

const LANGUES = [
  ["en", "anglais"], ["fr", "français"], ["es", "espagnol"],
  ["pt", "portugais"], ["de", "allemand"], ["it", "italien"],
];

/** Moteurs qui appellent réellement un LLM — les seuls pour lesquels
 *  choisir un modèle a un sens. Opus-MT et Argos ont des poids figés. */
const UTILISE_UN_LLM = new Set<NomMoteur>(["llm", "hybride", "reparation_ciblee"]);

function taille(octets: number | null): string {
  if (!octets) return "";
  return `${(octets / 1e9).toFixed(1)} Go`;
}

function dureeLisible(secondes: number): string {
  if (secondes < 90) return `${Math.round(secondes)} s`;
  if (secondes < 5400) return `${Math.round(secondes / 60)} min`;
  const h = Math.floor(secondes / 3600);
  return `${h} h ${Math.round((secondes % 3600) / 60)}`;
}

interface Props {
  moteurs: EtatMoteur[];
  options: OptionsTraduction;
  onChange: (options: OptionsTraduction) => void;
  estimations?: Record<string, number>;
  desactive?: boolean;
  onRafraichir?: () => void;
  modeles?: ModeleDisponible[];
  modelesActifs?: Record<string, string>;
}

export function PanneauMoteur({
  moteurs, options, onChange, estimations, desactive, onRafraichir,
  modeles = [], modelesActifs = {},
}: Props) {
  const [deplie, setDeplie] = useState<string | null>(null);
  const modifier = <C extends keyof OptionsTraduction>(
    champ: C, valeur: OptionsTraduction[C],
  ) => onChange({ ...options, [champ]: valeur });

  const choisirCapacite = (capacite: Capacite) => {
    const actuel = moteurs.find((m) => m.nom === options.moteur);
    // Si le moteur courant ne sait pas faire, on bascule sur le premier
    // qui sait — plutôt que de laisser une combinaison invalide à l'écran.
    if (actuel && !actuel.capacites.includes(capacite)) {
      const repli = moteurs.find(
        (m) => m.capacites.includes(capacite) && m.disponible,
      ) ?? moteurs.find((m) => m.capacites.includes(capacite));
      onChange({
        ...options, capacite, moteur: (repli?.nom ?? options.moteur) as NomMoteur,
      });
      return;
    }
    modifier("capacite", capacite);
  };

  return (
    <aside className="panneau">
      <section className="panneau__bloc">
        <h3>Tâche</h3>
        <div className="segmente">
          {CAPACITES.map((c) => (
            <button
              key={c.valeur}
              type="button"
              title={c.aide}
              disabled={desactive}
              className={options.capacite === c.valeur ? "actif" : ""}
              onClick={() => choisirCapacite(c.valeur)}
            >
              {c.libelle}
            </button>
          ))}
        </div>
        <p className="aide">
          {CAPACITES.find((c) => c.valeur === options.capacite)?.aide}
        </p>
      </section>

      <section className="panneau__bloc">
        <div className="panneau__titre">
          <h3>Moteur</h3>
          {onRafraichir && (
            <button type="button" className="lien" onClick={onRafraichir}>
              Revérifier
            </button>
          )}
        </div>
        <ul className="moteurs">
          {moteurs.map((moteur) => {
            const compatible = moteur.capacites.includes(options.capacite);
            const choisissable = compatible && moteur.disponible;
            const estimation = estimations?.[moteur.nom];

            return (
              <li key={moteur.nom}>
                <button
                  type="button"
                  disabled={desactive || !choisissable}
                  className={[
                    "moteur",
                    options.moteur === moteur.nom ? "moteur--actif" : "",
                    !compatible ? "moteur--incompatible" : "",
                    compatible && !moteur.disponible ? "moteur--absent" : "",
                  ].join(" ")}
                  onClick={() => modifier("moteur", moteur.nom)}
                >
                  <span className="moteur__entete">
                    <strong>{moteur.libelle}</strong>
                    {estimation !== undefined && choisissable && (
                      <em className="moteur__duree">{dureeLisible(estimation)}</em>
                    )}
                  </span>
                  <span className="moteur__detail">
                    {!compatible
                      ? `Ne sait pas ${options.capacite === "traduction"
                          ? "traduire" : options.capacite}`
                      : moteur.detail}
                  </span>
                  {choisissable && moteur.paires.length > 0 && (
                    <span className="moteur__paires">
                      {moteur.paires.slice(0, 6).join(" · ")}
                      {moteur.paires.length > 6 && " …"}
                    </span>
                  )}
                </button>

                {compatible && !moteur.disponible && moteur.remede && (
                  <div className="remede">
                    <button
                      type="button"
                      className="lien remede__bascule"
                      onClick={() =>
                        setDeplie(deplie === moteur.nom ? null : moteur.nom)}
                    >
                      {deplie === moteur.nom
                        ? "Masquer la marche à suivre"
                        : "Comment l'activer ?"}
                    </button>
                    {deplie === moteur.nom && (
                      <>
                        <pre className="remede__commande">{moteur.remede}</pre>
                        <button
                          type="button"
                          className="lien"
                          onClick={() =>
                            void navigator.clipboard.writeText(moteur.remede!)}
                        >
                          Copier la commande
                        </button>
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        {moteurs.length > 0 && moteurs.every((m) => !m.disponible) && (
          <p className="aide aide--alerte">
            Aucun moteur n'est prêt. Les passes de nettoyage, correction,
            analyse et mise en page fonctionnent sans modèle — tu peux
            préparer ton document en attendant.
          </p>
        )}
      </section>

      {UTILISE_UN_LLM.has(options.moteur) && (
        <section className="panneau__bloc">
          <h3>Modèle</h3>
          {(() => {
            const tache =
              options.capacite === "traduction" ? "traduction" : "reecriture";
            const parDefaut = modelesActifs[tache];
            return (
              <>
                <select
                  value={options.modele ?? ""}
                  disabled={desactive}
                  onChange={(e) =>
                    modifier("modele", e.target.value || null)}
                >
                  <option value="">
                    {parDefaut
                      ? `Configuré — ${parDefaut}`
                      : "Celui de la configuration"}
                  </option>
                  {modeles.map((m) => (
                    <option key={m.nom} value={m.nom}>
                      {m.nom}
                      {m.parametres ? ` · ${m.parametres}` : ""}
                      {m.taille_octets ? ` · ${taille(m.taille_octets)}` : ""}
                    </option>
                  ))}
                </select>
                <p className="aide">
                  {options.modele
                    ? "Surcharge ponctuelle. La configuration n'est pas modifiée."
                    : options.capacite === "traduction"
                      ? "Un modèle spécialisé traduction convient ici."
                      : "Tâche monolingue : prends un généraliste. Un modèle "
                        + "spécialisé traduction suit mal une consigne de "
                        + "réécriture."}
                </p>
                {modeles.length === 0 && (
                  <p className="aide aide--alerte">
                    Aucun modèle listé — serveur de modèles injoignable.
                  </p>
                )}
              </>
            );
          })()}
        </section>
      )}

      {options.capacite === "traduction" && (
        <section className="panneau__bloc">
          <h3>Langues</h3>
          <div className="paire">
            <select
              value={options.source}
              disabled={desactive}
              onChange={(e) => modifier("source", e.target.value)}
            >
              {LANGUES.map(([code, nom]) => (
                <option key={code} value={code}>{nom}</option>
              ))}
            </select>
            <span aria-hidden>→</span>
            <select
              value={options.cible}
              disabled={desactive}
              onChange={(e) => modifier("cible", e.target.value)}
            >
              {LANGUES.map(([code, nom]) => (
                <option key={code} value={code}>{nom}</option>
              ))}
            </select>
          </div>
        </section>
      )}

      <section className="panneau__bloc">
        <h3>Registre</h3>
        <select
          value={options.registre}
          disabled={desactive}
          onChange={(e) => modifier("registre", e.target.value as Registre)}
        >
          {REGISTRES.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <label className="case">
          <input
            type="checkbox"
            checked={options.glossaire !== null}
            disabled={desactive}
            onChange={(e) =>
              modifier("glossaire", e.target.checked ? "glossaire.json" : null)}
          />
          Appliquer le glossaire
        </label>
      </section>
    </aside>
  );
}
