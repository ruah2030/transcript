import { useCallback, useMemo, useState } from "react";

export interface Etape {
  /** Identifiant de la passe qui a produit cet état. */
  passe: string;
  /** Ce que la passe a changé, en une ligne. */
  resume: string;
  texte: string;
  a: number;
}

const MAX_ETAPES = 40;

/**
 * Le texte de travail et son historique.
 *
 * Chaque passe transforme le document en place — c'est ce qui rendait
 * l'outil risqué : une correction trop zélée sur 80 000 mots était
 * irrécupérable. Ici toute transformation empile un état, et on peut
 * revenir à n'importe lequel.
 *
 * L'historique est borné à 40 entrées. Sur un document de plusieurs
 * mégaoctets, garder tout saturerait la mémoire de l'onglet.
 */
export function useDocument(initial = "") {
  const [texte, setTexteBrut] = useState(initial);
  const [etapes, setEtapes] = useState<Etape[]>([]);

  /** Saisie libre au clavier : pas d'entrée d'historique, sinon on en
   *  créerait une par frappe. */
  const saisir = useCallback((valeur: string) => setTexteBrut(valeur), []);

  /** Transformation par une passe : empile l'état précédent puis remplace. */
  const appliquer = useCallback(
    (passe: string, resume: string, nouveau: string) => {
      setEtapes((liste) => {
        const suivante: Etape = { passe, resume, texte, a: Date.now() };
        return [suivante, ...liste].slice(0, MAX_ETAPES);
      });
      setTexteBrut(nouveau);
    },
    [texte],
  );

  /** Revient à l'état d'avant la passe la plus récente. */
  const annuler = useCallback(() => {
    setEtapes((liste) => {
      if (!liste.length) return liste;
      setTexteBrut(liste[0].texte);
      return liste.slice(1);
    });
  }, []);

  /** Revient à un point précis, en dépilant tout ce qui a suivi. */
  const revenirA = useCallback((a: number) => {
    setEtapes((liste) => {
      const index = liste.findIndex((e) => e.a === a);
      if (index === -1) return liste;
      setTexteBrut(liste[index].texte);
      return liste.slice(index + 1);
    });
  }, []);

  /** Remplace tout sans historique : import d'un nouveau document. */
  const charger = useCallback((valeur: string) => {
    setTexteBrut(valeur);
    setEtapes([]);
  }, []);

  const mots = useMemo(
    () => (texte.trim() ? texte.trim().split(/\s+/).length : 0),
    [texte],
  );

  return {
    texte, mots, etapes,
    saisir, appliquer, annuler, revenirA, charger,
    peutAnnuler: etapes.length > 0,
    passesFaites: useMemo(
      () => new Set(etapes.map((e) => e.passe)),
      [etapes],
    ),
  };
}
