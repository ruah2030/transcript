import type { ReactNode } from "react";

export type IdPasse =
  | "source" | "nettoyage" | "correction" | "grammaire" | "analyse"
  | "traduction" | "miseEnPage" | "verification";

export interface Passe {
  id: IdPasse;
  numero: number;
  nom: string;
  /** Ce que la passe fait, en une phrase, du point de vue de l'utilisateur. */
  role: string;
  /** Passe dont le résultat est nécessaire ici. */
  requiert?: IdPasse;
  /** Pourquoi elle est nécessaire — affiché quand la passe est verrouillée. */
  raison?: string;
}

export const PASSES: Passe[] = [
  {
    id: "source", numero: 0, nom: "Source",
    role: "Récupère le texte d'une vidéo — sous-titres si elle en a, "
      + "transcription audio sinon.",
  },
  {
    id: "nettoyage", numero: 1, nom: "Nettoyer",
    role: "Retire les marqueurs temporels et recolle les paragraphes.",
  },
  {
    id: "correction", numero: 2, nom: "Corriger",
    role: "Applique tes dictionnaires, la typographie et les références.",
  },
  {
    id: "grammaire", numero: 3, nom: "Grammaire",
    role: "Passe LanguageTool sur les fautes sans ambiguïté.",
  },
  {
    id: "analyse", numero: 4, nom: "Analyser",
    role: "Profil du document et durée estimée par moteur.",
  },
  {
    id: "traduction", numero: 5, nom: "Traduire",
    role: "Traduit, répare ou révise selon le moteur choisi.",
  },
  {
    id: "miseEnPage", numero: 6, nom: "Mettre en page",
    role: "Compose un document imprimable ou un Markdown.",
    requiert: "nettoyage",
    raison: "La détection des intertitres suppose un paragraphe par ligne. "
      + "Sans le nettoyage, ils seront pris pour du corps de texte.",
  },
  {
    id: "verification", numero: 7, nom: "Vérifier",
    role: "Compare deux versions et relève ce qui a changé de sens.",
  },
];

interface Props {
  courante: IdPasse;
  faites: Set<string>;
  bilans: Partial<Record<IdPasse, string>>;
  enCours: IdPasse | null;
  onChoisir: (id: IdPasse) => void;
  documentVide: boolean;
}

/**
 * Le rail est la fiche de travail du manuscrit : où il en est, ce que
 * chaque main lui a fait, ce qui reste.
 *
 * Il encode une contrainte réelle et non une décoration : la mise en page
 * dépend du nettoyage, et le dire à l'avance évite un résultat silencieusement
 * faux. Les autres passes restent librement accessibles — l'ordre proposé est
 * un conseil, pas une prison.
 */
export function RailPasses({
  courante, faites, bilans, enCours, onChoisir, documentVide,
}: Props) {
  return (
    <nav className="rail" aria-label="Passes du document">
      <ol className="rail__liste">
        {PASSES.map((passe) => {
          const faite = faites.has(passe.id);
          const active = courante === passe.id;
          const occupee = enCours === passe.id;
          const bloquee =
            passe.requiert !== undefined && !faites.has(passe.requiert);

          return (
            <li key={passe.id} className="rail__case">
              <button
                type="button"
                onClick={() => onChoisir(passe.id)}
                disabled={documentVide}
                aria-current={active ? "step" : undefined}
                className={[
                  "jeton",
                  active ? "jeton--active" : "",
                  faite ? "jeton--faite" : "",
                  occupee ? "jeton--occupee" : "",
                  bloquee ? "jeton--avertie" : "",
                ].join(" ")}
                title={bloquee ? passe.raison : passe.role}
              >
                <span className="jeton__numero">
                  {String(passe.numero).padStart(2, "0")}
                </span>
                <span className="jeton__nom">{passe.nom}</span>
                <span className="jeton__etat">
                  {occupee
                    ? "en cours…"
                    : faite
                      ? bilans[passe.id] ?? "fait"
                      : bloquee
                        ? "à préparer"
                        : "à faire"}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function Consigne({ passe, children }: { passe: Passe; children?: ReactNode }) {
  return (
    <div className="consigne">
      <p className="consigne__role">{passe.role}</p>
      {children}
    </div>
  );
}
