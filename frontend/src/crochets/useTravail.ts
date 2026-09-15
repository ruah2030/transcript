import { useCallback, useEffect, useRef, useState } from "react";

import { ErreurAtelier, api } from "@/api/client";
import type {
  InstantaneTravail, OptionsTraduction, ReponseTraduction,
} from "@/api/types";

interface EtatSuivi {
  travail: InstantaneTravail | null;
  resultat: ReponseTraduction | null;
  erreur: ErreurAtelier | null;
  enCours: boolean;
}

const INITIAL: EtatSuivi = {
  travail: null, resultat: null, erreur: null, enCours: false,
};

/**
 * Lance une traduction longue et en suit l'avancement.
 *
 * Le backend expose la progression en Server-Sent Events plutôt qu'en
 * polling : sur un travail de plusieurs minutes, interroger l'état toutes
 * les secondes est du gaspillage, et le flux permet d'afficher le temps
 * restant sans latence.
 *
 * EventSource se reconnecte tout seul en cas de coupure réseau, et le
 * backend renvoie l'état courant au raccordement — un onglet rouvert
 * retrouve donc sa place sans avoir manqué la fin.
 */
export function useTravail() {
  const [etat, setEtat] = useState<EtatSuivi>(INITIAL);
  const fluxRef = useRef<EventSource | null>(null);

  const fermerFlux = useCallback(() => {
    fluxRef.current?.close();
    fluxRef.current = null;
  }, []);

  useEffect(() => fermerFlux, [fermerFlux]);

  const suivre = useCallback((identifiant: string) => {
    fermerFlux();
    const flux = new EventSource(`/api/v1/travaux/${identifiant}/flux`);
    fluxRef.current = flux;

    const majEtat = (evenement: MessageEvent) => {
      const instantane: InstantaneTravail = JSON.parse(evenement.data);
      setEtat((p) => ({ ...p, travail: instantane }));
    };

    flux.addEventListener("etat", majEtat);
    flux.addEventListener("progression", majEtat);

    flux.addEventListener("fin", async (evenement) => {
      const instantane: InstantaneTravail = JSON.parse(
        (evenement as MessageEvent).data,
      );
      fermerFlux();

      if (instantane.etat === "termine") {
        try {
          const resultat = await api.resultatTravail(identifiant);
          setEtat({
            travail: instantane, resultat, erreur: null, enCours: false,
          });
        } catch (e) {
          setEtat((p) => ({
            ...p, travail: instantane, enCours: false,
            erreur: e as ErreurAtelier,
          }));
        }
        return;
      }

      setEtat((p) => ({
        ...p,
        travail: instantane,
        enCours: false,
        erreur: instantane.erreur
          ? new ErreurAtelier(
              instantane.erreur.code,
              instantane.erreur.message,
              instantane.erreur.detail,
              500,
            )
          : null,
      }));
    });

    flux.onerror = () => {
      // EventSource retente seul ; on ne coupe que si le flux est mort.
      if (flux.readyState === EventSource.CLOSED) {
        fermerFlux();
        setEtat((p) => ({
          ...p,
          enCours: false,
          erreur: new ErreurAtelier(
            "flux_interrompu",
            "Le suivi a été interrompu.",
            "Le travail continue peut-être côté serveur. Recharge la page "
              + "pour le retrouver dans la liste des travaux.",
            0,
          ),
        }));
      }
    };
  }, [fermerFlux]);

  const lancer = useCallback(
    async (texte: string, options: OptionsTraduction) => {
      setEtat({ ...INITIAL, enCours: true });
      try {
        const ouvert = await api.ouvrirTravail(texte, options);
        suivre(ouvert.identifiant);
      } catch (e) {
        setEtat({
          ...INITIAL, enCours: false, erreur: e as ErreurAtelier,
        });
      }
    },
    [suivre],
  );

  /** Même mécanique que `lancer`, pour la passe 0. Le résultat n'a pas la
   *  forme d'une traduction : l'appelant le lit tel quel. */
  const lancerTranscription = useCallback(
    async (corps: {
      url: string; langue: string; modele: string; forcer_audio: boolean;
    }) => {
      setEtat({ ...INITIAL, enCours: true });
      try {
        const ouvert = await api.ouvrirTranscription(corps);
        suivre(ouvert.identifiant);
      } catch (e) {
        setEtat({ ...INITIAL, enCours: false, erreur: e as ErreurAtelier });
      }
    },
    [suivre],
  );

  const annuler = useCallback(async () => {
    if (!etat.travail) return;
    await api.annulerTravail(etat.travail.identifiant).catch(() => undefined);
    fermerFlux();
    setEtat((p) => ({ ...p, enCours: false }));
  }, [etat.travail, fermerFlux]);

  const reinitialiser = useCallback(() => {
    fermerFlux();
    setEtat(INITIAL);
  }, [fermerFlux]);

  return { ...etat, lancer, lancerTranscription, annuler, reinitialiser };
}
