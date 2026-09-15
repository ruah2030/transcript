import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import type { ReponseModeles } from "@/api/types";

/** Modèles servis par Ollama, et le routage configuré par tâche.
 *
 *  L'endpoint ne renvoie jamais d'erreur : serveur éteint, il rend quand
 *  même `actifs`. L'interface reste donc utilisable et montre ce qui SERAIT
 *  utilisé, ce qui est l'information la plus utile quand rien ne marche. */
export function useModeles() {
  const [donnees, setDonnees] = useState<ReponseModeles | null>(null);
  const [chargement, setChargement] = useState(true);

  const rafraichir = useCallback(async () => {
    setChargement(true);
    try {
      setDonnees(await api.modeles());
    } catch {
      setDonnees(null);
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    void rafraichir();
  }, [rafraichir]);

  return { ...(donnees ?? { disponibles: [], actifs: {}, source: "", detail: null }),
           chargement, rafraichir };
}
