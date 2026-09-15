/** Miroir des schémas Pydantic du backend. Toute évolution se fait des deux
 *  côtés à la fois — le schéma OpenAPI sur /docs est la référence. */

export type Capacite = "traduction" | "reparation" | "revision";
export type Registre = "soutenu" | "courant" | "technique" | "commercial";
export type NomMoteur =
  | "opusmt"
  | "argos"
  | "llm"
  | "hybride"
  | "reparation_ciblee";

export type EtatTravail =
  | "en_attente" | "en_cours" | "termine" | "echoue" | "annule";

export interface ErreurApi {
  code: string;
  message: string;
  detail: string | null;
}

export interface EtatMoteur {
  nom: NomMoteur;
  libelle: string;
  capacites: string[];
  debit_mots_seconde: number;
  disponible: boolean;
  detail: string;
  paires: string[];
  /** Commande exacte à lancer quand le moteur est indisponible. */
  remede: string | null;
}

export interface ReponseNettoyage {
  texte: string;
  marqueurs_retires: number;
}

export interface Signalement {
  categorie: string;
  motif: string;
  occurrences: number;
  raison: string;
}

export interface ReponseCorrection {
  texte: string;
  regles_appliquees: Record<string, number>;
  total_applique: number;
  signalements: Signalement[];
  doublons_retires: number;
  references_normalisees: number;
  corrections_grammaire: number;
}

export interface SectionLue {
  indice: number;
  titre: string;
  caracteres: number;
}

export interface Alerte {
  gravite: "info" | "attention";
  message: string;
}

export interface ReponseAnalyse {
  caracteres: number;
  mots: number;
  paragraphes: number;
  sections: SectionLue[];
  segments: number;
  phrases: number;
  alertes: Alerte[];
  estimations: Record<string, number>;
}

export interface ReponseTraduction {
  texte: string;
  moteur: string;
  doutes: string[];
  confiance: number | null;
}

export interface TravailOuvert {
  identifiant: string;
  genre: string;
  etat: EtatTravail;
  flux: string;
}

export interface InstantaneTravail {
  identifiant: string;
  genre: string;
  etat: EtatTravail;
  faits: number;
  total: number;
  progression: number;
  etiquette: string;
  secondes_restantes: number | null;
  erreur: ErreurApi | null;
  cree_le: string;
}

export interface OptionsTraduction {
  moteur: NomMoteur;
  source: string;
  cible: string;
  capacite: Capacite;
  registre: Registre;
  glossaire: string | null;
  /** Surcharge du modèle LLM pour cet appel. null = celui configuré. */
  modele: string | null;
}

export interface ModeleDisponible {
  nom: string;
  taille_octets: number | null;
  parametres: string | null;
}

export interface ReponseModeles {
  disponibles: ModeleDisponible[];
  /** Routage configuré : quelle tâche part sur quel modèle. */
  actifs: Record<string, string>;
  source: string;
  detail: string | null;
}


export interface PisteLue {
  langue: string;
  automatique: boolean;
}

export interface ReponseSource {
  titre: string;
  chaine: string;
  duree_secondes: number;
  url: string;
  pistes: PisteLue[];
  /** Ce que le service fera si on lance la récupération telle quelle. */
  voie_prevue: "sous_titres_humains" | "sous_titres_auto" | "transcription";
  detail: string;
  /** Secondes de calcul estimées, par modèle Whisper. */
  estimations: Record<string, number>;
}

export interface ModeleWhisper {
  nom: string;
  poids: string;
  vitesse_x_temps_reel: number;
  note: string;
}

export interface ReponseTranscription {
  texte: string;
  origine: string;
  langue: string;
  titre: string;
  duree_secondes: number;
  mots: number;
}
