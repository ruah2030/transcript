import { useCallback, useState } from "react";

import { ErreurAtelier, api } from "@/api/client";
import type { ReponseAnalyse, ReponseCorrection } from "@/api/types";

export interface Journal {
  passe: string;
  detail: string;
  a: number;
}

/** Passes 1 à 4 et analyse. Rapides et synchrones : pas de travail long. */
export function usePasses(
  texte: string,
  setTexte: (t: string) => void,
) {
  const [rapport, setRapport] = useState<ReponseCorrection | null>(null);
  const [analyse, setAnalyse] = useState<ReponseAnalyse | null>(null);
  const [journal, setJournal] = useState<Journal[]>([]);
  const [erreur, setErreur] = useState<ErreurAtelier | null>(null);
  const [occupe, setOccupe] = useState(false);

  const noter = (passe: string, detail: string) =>
    setJournal((j) => [{ passe, detail, a: Date.now() }, ...j].slice(0, 30));

  const executer = useCallback(
    async <T,>(passe: string, action: () => Promise<T>, resume: (r: T) => string) => {
      setOccupe(true);
      setErreur(null);
      try {
        const resultat = await action();
        noter(passe, resume(resultat));
        return resultat;
      } catch (e) {
        setErreur(e as ErreurAtelier);
        return null;
      } finally {
        setOccupe(false);
      }
    },
    [],
  );

  const nettoyer = useCallback(async () => {
    const r = await executer(
      "Nettoyage",
      () => api.nettoyer(texte, true),
      (r) => `${r.marqueurs_retires} marqueur(s) temporel(s) retiré(s)`,
    );
    if (r) setTexte(r.texte);
  }, [texte, setTexte, executer]);

  const corriger = useCallback(
    async (grammaire = false) => {
      const r = await executer(
        "Correction",
        () => api.corriger(texte, { grammaire }),
        (r) =>
          `${r.total_applique} règle(s), ${r.doublons_retires} doublon(s), `
          + `${r.references_normalisees} référence(s)`
          + (r.signalements.length ? ` — ${r.signalements.length} à arbitrer` : ""),
      );
      if (r) {
        setTexte(r.texte);
        setRapport(r);
      }
    },
    [texte, setTexte, executer],
  );

  const analyser = useCallback(async () => {
    const r = await executer(
      "Analyse",
      () => api.analyser(texte),
      (r) => `${r.mots} mots, ${r.segments} segment(s), ${r.sections.length} section(s)`,
    );
    if (r) setAnalyse(r);
  }, [texte, executer]);

  const toutEnchainer = useCallback(async () => {
    await nettoyer();
    await corriger(false);
    await analyser();
  }, [nettoyer, corriger, analyser]);

  return {
    rapport, analyse, journal, erreur, occupe,
    nettoyer, corriger, analyser, toutEnchainer,
    effacerErreur: () => setErreur(null),
  };
}
