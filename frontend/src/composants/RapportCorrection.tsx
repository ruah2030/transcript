import type { ReponseAnalyse, ReponseCorrection } from "@/api/types";

interface Props {
  rapport: ReponseCorrection | null;
  analyse: ReponseAnalyse | null;
  doutes: string[];
}

/** Le rapport est la partie qu'il faut lire avant de lancer un traitement
 *  long : c'est là que se voient les règles qui surcorrigent et les cas
 *  laissés à l'arbitrage humain. */
export function RapportCorrection({ rapport, analyse, doutes }: Props) {
  const rien = !rapport && !analyse && doutes.length === 0;
  if (rien) {
    return (
      <p className="vide">
        Lance une passe pour voir ici le détail de ce qui a été fait
        et ce qui demande ton arbitrage.
      </p>
    );
  }

  return (
    <div className="rapport">
      {analyse && (
        <section>
          <h4>Profil du document</h4>
          <dl className="chiffres">
            <div><dt>Mots</dt><dd>{analyse.mots.toLocaleString("fr-FR")}</dd></div>
            <div><dt>Paragraphes</dt><dd>{analyse.paragraphes}</dd></div>
            <div><dt>Sections</dt><dd>{analyse.sections.length}</dd></div>
            <div><dt>Segments</dt><dd>{analyse.segments}</dd></div>
            <div><dt>Phrases</dt><dd>{analyse.phrases}</dd></div>
          </dl>

          {analyse.alertes.length > 0 && (
            <ul className="alertes">
              {analyse.alertes.map((a, i) => (
                <li key={i} className={`alertes__${a.gravite}`}>{a.message}</li>
              ))}
            </ul>
          )}

          {analyse.sections.length > 1 && (
            <details>
              <summary>{analyse.sections.length} sections détectées</summary>
              <ol className="sections">
                {analyse.sections.map((s) => (
                  <li key={s.indice}>
                    <span>{s.titre}</span>
                    <em>{s.caracteres.toLocaleString("fr-FR")} car.</em>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </section>
      )}

      {rapport && (
        <section>
          <h4>Corrections appliquées — {rapport.total_applique}</h4>
          {rapport.signalements.length > 0 && (
            <>
              <p className="aide">
                Ces cas ne sont jamais corrigés automatiquement : le bon choix
                dépend de la phrase. À vérifier à la relecture.
              </p>
              <ul className="signalements">
                {rapport.signalements.map((s, i) => (
                  <li key={i}>
                    <strong>{s.categorie}</strong> — {s.occurrences} occurrence(s)
                    <span className="aide">{s.raison}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <details>
            <summary>Détail par règle</summary>
            <ul className="regles">
              {Object.entries(rapport.regles_appliquees)
                .sort(([, a], [, b]) => b - a)
                .map(([cle, nb]) => (
                  <li key={cle}><code>{cle}</code><em>×{nb}</em></li>
                ))}
            </ul>
          </details>
        </section>
      )}

      {doutes.length > 0 && (
        <section>
          <h4>Passages à relire — {doutes.length}</h4>
          <p className="aide">
            Le modèle a signalé ces passages comme incertains. Ce sont tes
            points de relecture prioritaires.
          </p>
          <ul className="doutes">
            {doutes.map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
