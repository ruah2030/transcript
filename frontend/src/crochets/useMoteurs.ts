import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import type { Capacite, EtatMoteur, NomMoteur } from "@/api/types";

/** Charge l'état des moteurs et fournit de quoi griser les combinaisons
 *  impossibles avant que l'utilisateur ne lance un travail voué à l'échec. */
export function useMoteurs() {
  const [moteurs, setMoteurs] = useState<EtatMoteur[]>([]);
  const [chargement, setChargement] = useState(true);

  const rafraichir = useCallback(async () => {
    setChargement(true);
    try {
      setMoteurs(await api.moteurs());
    } catch {
      setMoteurs([]);
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    void rafraichir();
  }, [rafraichir]);

  const trouver = useCallback(
    (nom: NomMoteur) => moteurs.find((m) => m.nom === nom),
    [moteurs],
  );

  const saitFaire = useCallback(
    (nom: NomMoteur, capacite: Capacite) =>
      trouver(nom)?.capacites.includes(capacite) ?? false,
    [trouver],
  );

  return { moteurs, chargement, rafraichir, trouver, saitFaire };
}
