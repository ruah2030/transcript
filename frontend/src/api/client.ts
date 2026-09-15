import type {
  ErreurApi, EtatMoteur, InstantaneTravail, OptionsTraduction,
  ReponseAnalyse, ReponseCorrection, ReponseModeles, ReponseNettoyage,
  ReponseSource, ReponseTraduction, TravailOuvert,
} from "./types";

const BASE = "/api/v1";

/** Erreur métier du backend. Porte toujours un message ET une piste d'action,
 *  ce qui permet d'afficher « Opus-MT ne sait pas réparer » suivi de la
 *  marche à suivre, plutôt qu'un échec opaque. */
export class ErreurAtelier extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly detail: string | null,
    public readonly statut: number,
  ) {
    super(message);
    this.name = "ErreurAtelier";
  }
}

async function appeler<T>(chemin: string, init?: RequestInit): Promise<T> {
  const reponse = await fetch(`${BASE}${chemin}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  if (!reponse.ok) {
    let charge: Partial<ErreurApi> = {};
    try {
      charge = await reponse.json();
    } catch {
      /* corps non JSON : on garde le statut seul */
    }
    throw new ErreurAtelier(
      charge.code ?? "erreur_reseau",
      charge.message ?? `Échec de la requête (HTTP ${reponse.status})`,
      charge.detail ?? null,
      reponse.status,
    );
  }

  return reponse.json() as Promise<T>;
}

const poster = <T>(chemin: string, corps: unknown) =>
  appeler<T>(chemin, { method: "POST", body: JSON.stringify(corps) });

export const api = {
  moteurs: () => appeler<EtatMoteur[]>("/moteurs"),

  modeles: () => appeler<ReponseModeles>("/modeles"),

  inspecterSource: (url: string) =>
    poster<ReponseSource>("/source/inspecter", { url }),

  modelesTranscription: () =>
    appeler<{ modeles: unknown[]; disponible: boolean; detail: string;
              remede: string | null }>("/transcription/modeles"),

  ouvrirTranscription: (corps: {
    url: string; langue: string; modele: string; forcer_audio: boolean;
  }) => poster<TravailOuvert>("/travaux/transcription", corps),

  nettoyer: (texte: string, fusionner = true) =>
    poster<ReponseNettoyage>("/nettoyage", {
      texte,
      fusionner_paragraphes: fusionner,
    }),

  corriger: (texte: string, options: Partial<{
    dictionnaires: string[];
    typographie: boolean;
    dedoublonner: boolean;
    references: boolean;
    grammaire: boolean;
  }> = {}) => poster<ReponseCorrection>("/correction", { texte, ...options }),

  analyser: (texte: string, options: Partial<OptionsTraduction> = {}) =>
    poster<ReponseAnalyse>("/analyse", { texte, ...options }),

  structure: (texte: string) =>
    poster<{ chapitres: unknown[]; avertissement: string | null }>(
      "/structure", { texte },
    ),

  miseEnPage: (texte: string, format: "html" | "md", options: object = {}) =>
    poster<{ contenu: string; format: string; chapitres: number }>(
      "/mise-en-page", { texte, format, options },
    ),

  /** Traduction directe. Le backend refuse au-delà de 6000 caractères. */
  traduire: (texte: string, options: OptionsTraduction) =>
    poster<ReponseTraduction>("/traduction", { texte, ...options }),

  /** Ouvre un travail long. Rend l'identifiant à suivre en SSE. */
  ouvrirTravail: (texte: string, options: OptionsTraduction) =>
    poster<TravailOuvert>("/travaux/traduction", { texte, ...options }),

  travail: (identifiant: string) =>
    appeler<InstantaneTravail>(`/travaux/${identifiant}`),

  resultatTravail: (identifiant: string) =>
    appeler<ReponseTraduction>(`/travaux/${identifiant}/resultat`),

  annulerTravail: (identifiant: string) =>
    appeler<InstantaneTravail>(`/travaux/${identifiant}`, { method: "DELETE" }),

  importer: (fichier: File) => {
    const corps = new FormData();
    corps.append("fichier", fichier);
    return appeler<{ nom: string; texte: string; mots: number }>(
      "/documents/import",
      { method: "POST", body: corps },
    );
  },
};
