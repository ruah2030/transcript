import { useCallback, useEffect, useRef, useState } from "react";

import { ErreurAtelier, api } from "@/api/client";
import type { OptionsTraduction, ReponseAnalyse, ReponseCorrection } from "@/api/types";
import { Alerte } from "@/composants/Alerte";
import { ApercuMiseEnPage } from "@/composants/ApercuMiseEnPage";
import { Historique } from "@/composants/Historique";
import { PanneauMoteur } from "@/composants/PanneauMoteur";
import { PanneauSource } from "@/composants/PanneauSource";
import { Progression } from "@/composants/Progression";
import { PASSES, RailPasses, type IdPasse } from "@/composants/RailPasses";
import { RapportCorrection } from "@/composants/RapportCorrection";
import { useDocument } from "@/crochets/useDocument";
import { useModeles } from "@/crochets/useModeles";
import { useMoteurs } from "@/crochets/useMoteurs";
import { useTravail } from "@/crochets/useTravail";

/** Au-delà, le backend refuse le mode direct et impose un travail suivi. */
const SEUIL_TRAVAIL = 6_000;

const OPTIONS_INITIALES: OptionsTraduction = {
  moteur: "hybride", source: "en", cible: "fr",
  capacite: "traduction", registre: "courant",
  glossaire: "glossaire.json", modele: null,
};

export default function App() {
  const doc = useDocument();
  const [sortie, setSortie] = useState("");
  const [options, setOptions] = useState(OPTIONS_INITIALES);
  const [passe, setPasse] = useState<IdPasse>("source");
  const [enCours, setEnCours] = useState<IdPasse | null>(null);
  const [erreur, setErreur] = useState<ErreurAtelier | null>(null);
  const [rapport, setRapport] = useState<ReponseCorrection | null>(null);
  const [analyse, setAnalyse] = useState<ReponseAnalyse | null>(null);
  const [bilans, setBilans] = useState<Partial<Record<IdPasse, string>>>({});
  const [panneauOuvert, setPanneauOuvert] = useState(true);
  const champFichier = useRef<HTMLInputElement>(null);

  const { moteurs, rafraichir } = useMoteurs();
  const catalogue = useModeles();
  const travail = useTravail();
  const capture = useTravail();

  const long = doc.texte.length > SEUIL_TRAVAIL;
  const occupe = enCours !== null || travail.enCours || capture.enCours;
  const passeCourante = PASSES.find((p) => p.id === passe)!;

  /** Exécute une passe : signale l'état, empile l'historique, note le bilan. */
  const executer = useCallback(
    async <T,>(
      id: IdPasse,
      action: () => Promise<T>,
      resume: (r: T) => string,
      texteDe?: (r: T) => string,
    ): Promise<T | null> => {
      setEnCours(id);
      setErreur(null);
      try {
        const r = await action();
        const bilan = resume(r);
        if (texteDe) doc.appliquer(id, bilan, texteDe(r));
        setBilans((b) => ({ ...b, [id]: bilan }));
        return r;
      } catch (e) {
        setErreur(e as ErreurAtelier);
        return null;
      } finally {
        setEnCours(null);
      }
    },
    [doc],
  );

  const nettoyer = useCallback(
    () => executer("nettoyage",
      () => api.nettoyer(doc.texte, true),
      (r) => `${r.marqueurs_retires} marqueur(s) retiré(s)`,
      (r) => r.texte),
    [doc.texte, executer],
  );

  const corriger = useCallback(
    (grammaire: boolean) => executer(
      grammaire ? "grammaire" : "correction",
      () => api.corriger(doc.texte, { grammaire }),
      (r) => grammaire
        ? `${r.corrections_grammaire} correction(s)`
        : `${r.total_applique} règle(s), ${r.signalements.length} à arbitrer`,
      (r) => { setRapport(r); return r.texte; }),
    [doc.texte, executer],
  );

  const analyser = useCallback(async () => {
    const r = await executer("analyse",
      () => api.analyser(doc.texte),
      (r) => `${r.mots.toLocaleString("fr-FR")} mots, ${r.segments} segment(s)`);
    if (r) setAnalyse(r);
  }, [doc.texte, executer]);

  const traduire = useCallback(async () => {
    if (!doc.texte.trim()) return;
    setSortie("");
    setErreur(null);
    if (long) {
      await travail.lancer(doc.texte, options);
      return;
    }
    const r = await executer("traduction",
      () => api.traduire(doc.texte, options),
      (res) => `par ${res.moteur}`);
    if (r) setSortie(r.texte);
  }, [doc.texte, long, options, travail, executer]);

  const importer = useCallback(async (fichier: File) => {
    setErreur(null);
    try {
      const lu = await api.importer(fichier);
      doc.charger(lu.texte);
      setSortie("");
      setBilans({});
      setRapport(null);
      setAnalyse(null);
      setPasse("nettoyage");
    } catch (e) {
      setErreur(e as ErreurAtelier);
    }
  }, [doc]);

  // Le texte transcrit devient le manuscrit, sans écraser l'historique en
  // silence : c'est un chargement, pas une transformation.
  useEffect(() => {
    const recu = capture.resultat as unknown as { texte?: string } | null;
    if (recu?.texte) {
      doc.charger(recu.texte);
      setPasse("nettoyage");
      capture.reinitialiser();
    }
    // doc est stable hors chargement ; on ne dépend que du résultat.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capture.resultat]);

  // Raccourcis : annuler, et lancer la passe affichée.
  useEffect(() => {
    const auClavier = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        if (!occupe) doc.annuler();
      }
      if (meta && e.key === "Enter" && !occupe) {
        e.preventDefault();
        if (passe === "nettoyage") void nettoyer();
        if (passe === "correction") void corriger(false);
        if (passe === "grammaire") void corriger(true);
        if (passe === "analyse") void analyser();
        if (passe === "traduction") void traduire();
      }
    };
    window.addEventListener("keydown", auClavier);
    return () => window.removeEventListener("keydown", auClavier);
  }, [doc, occupe, passe, nettoyer, corriger, analyser, traduire]);

  const resultat = travail.resultat?.texte ?? sortie;
  const erreurAffichee = travail.erreur ?? erreur;

  return (
    <div className="atelier">
      <header className="fiche">
        <div className="fiche__identite">
          <span className="fiche__eyebrow">Atelier</span>
          <h1>Transcription &amp; traduction</h1>
        </div>

        <div className="fiche__mesures">
          <span className="mesure">
            <em>{doc.mots.toLocaleString("fr-FR")}</em> mots
          </span>
          {long && <span className="fanion">travail suivi</span>}
        </div>

        <div className="fiche__actions">
          <input
            ref={champFichier} type="file" accept=".txt,.md,.docx" hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void importer(f);
              e.target.value = "";
            }}
          />
          <button type="button" onClick={() => champFichier.current?.click()}
                  disabled={occupe}>
            Importer
          </button>
          <button type="button" onClick={() => doc.annuler()}
                  disabled={occupe || !doc.peutAnnuler}
                  title="Revenir à l'état précédent (Ctrl+Z)">
            Annuler
          </button>
          <button type="button" className="bascule"
                  aria-expanded={panneauOuvert}
                  onClick={() => setPanneauOuvert((o) => !o)}>
            {panneauOuvert ? "Masquer le volet" : "Afficher le volet"}
          </button>
        </div>
      </header>

      <RailPasses
        courante={passe} faites={doc.passesFaites} bilans={bilans}
        enCours={enCours} onChoisir={setPasse}
        documentVide={!doc.texte.trim()}
      />

      {erreurAffichee && (
        <Alerte erreur={erreurAffichee}
                onFermer={() => { setErreur(null); travail.reinitialiser(); }} />
      )}

      <main className={`etabli ${panneauOuvert ? "" : "etabli--large"}`}>
        <section className="plan">
          <div className="plan__entete">
            <h2>Manuscrit</h2>
            <span className="indication">{passeCourante.role}</span>
          </div>

          <textarea
            className="feuille"
            value={doc.texte}
            onChange={(e) => doc.saisir(e.target.value)}
            placeholder="Colle ta transcription, ou importe un fichier."
            spellCheck={false}
            disabled={occupe}
          />

          {passe === "nettoyage" && (
            <div className="barre">
              <button type="button" className="primaire"
                      onClick={() => void nettoyer()}
                      disabled={occupe || !doc.texte.trim()}>
                Nettoyer le texte
              </button>
            </div>
          )}

          {(passe === "correction" || passe === "grammaire") && (
            <div className="barre">
              <button type="button" className="primaire"
                      onClick={() => void corriger(passe === "grammaire")}
                      disabled={occupe || !doc.texte.trim()}>
                {passe === "grammaire"
                  ? "Passer la grammaire"
                  : "Appliquer les dictionnaires"}
              </button>
            </div>
          )}

          {passe === "analyse" && (
            <div className="barre">
              <button type="button" className="primaire"
                      onClick={() => void analyser()}
                      disabled={occupe || !doc.texte.trim()}>
                Analyser le document
              </button>
            </div>
          )}

          {passe === "source" && (
            <PanneauSource
              desactive={occupe}
              travail={capture.travail}
              onErreur={setErreur}
              onLancer={(corps) => void capture.lancerTranscription(corps)}
              onAnnuler={() => void capture.annuler()}
            />
          )}

          {passe === "miseEnPage" && (
            <ApercuMiseEnPage texte={doc.texte} desactive={occupe}
                              onErreur={setErreur} />
          )}

          {passe === "verification" && (
            <p className="aide">
              Colle la version d'origine dans le manuscrit, la version
              retravaillée dans le résultat, puis lance la comparaison depuis
              le volet. Compare contre le texte source quand tu l'as : aucun
              modèle ne retrouve un sens absent des deux versions.
            </p>
          )}
        </section>

        {passe === "traduction" && (
          <section className="plan">
            <div className="plan__entete">
              <h2>Résultat</h2>
              {travail.resultat?.confiance != null && (
                <span className="indication">
                  {Math.round(travail.resultat.confiance * 100)} % traité sans LLM
                </span>
              )}
            </div>

            {travail.travail && (
              <Progression travail={travail.travail}
                           onAnnuler={() => void travail.annuler()} />
            )}

            <textarea
              className="feuille"
              value={resultat}
              onChange={(e) => setSortie(e.target.value)}
              placeholder="La traduction apparaîtra ici."
              spellCheck={false}
            />

            <div className="barre">
              <button type="button" className="primaire"
                      onClick={() => void traduire()}
                      disabled={occupe || !doc.texte.trim()}>
                {long ? "Lancer le travail" : "Traduire"}
              </button>
              <button type="button"
                      onClick={() => doc.appliquer(
                        "traduction", "résultat repris comme source", resultat)}
                      disabled={occupe || !resultat}>
                Reprendre comme source
              </button>
              <button type="button"
                      onClick={() => void navigator.clipboard.writeText(resultat)}
                      disabled={!resultat}>
                Copier
              </button>
            </div>
          </section>
        )}

        {panneauOuvert && (
          <aside className="volet">
            {(passe === "traduction" || passe === "verification") && (
              <PanneauMoteur
                moteurs={moteurs} options={options} onChange={setOptions}
                estimations={analyse?.estimations} desactive={occupe}
                onRafraichir={() => {
                  void rafraichir();
                  void catalogue.rafraichir();
                }}
                modeles={catalogue.disponibles}
                modelesActifs={catalogue.actifs}
              />
            )}

            <section className="volet__bloc">
              <h3>Historique</h3>
              <Historique etapes={doc.etapes} onRevenir={doc.revenirA}
                          desactive={occupe} />
            </section>
          </aside>
        )}
      </main>

      <section className="releve">
        <h2>Relevé</h2>
        <RapportCorrection rapport={rapport} analyse={analyse}
                           doutes={travail.resultat?.doutes ?? []} />
      </section>
    </div>
  );
}
