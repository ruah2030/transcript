import { useState } from "react";

import { ErreurAtelier, api } from "@/api/client";

interface Props {
  texte: string;
  desactive?: boolean;
  onErreur: (e: ErreurAtelier) => void;
}

/** Composition finale. Le HTML est rendu dans un iframe isolé : le gabarit
 *  porte ses propres styles d'impression, qui entreraient en conflit avec
 *  ceux de l'atelier s'ils partageaient le même document. */
export function ApercuMiseEnPage({ texte, desactive, onErreur }: Props) {
  const [titre, setTitre] = useState("");
  const [auteur, setAuteur] = useState("");
  const [taille, setTaille] = useState("a5");
  const [rendu, setRendu] = useState<{ contenu: string; format: string } | null>(null);
  const [occupe, setOccupe] = useState(false);

  const composer = async (format: "html" | "md") => {
    setOccupe(true);
    try {
      const r = await api.miseEnPage(texte, format, { titre, auteur, taille });
      setRendu({ contenu: r.contenu, format: r.format });
    } catch (e) {
      onErreur(e as ErreurAtelier);
    } finally {
      setOccupe(false);
    }
  };

  const telecharger = () => {
    if (!rendu) return;
    const extension = rendu.format === "md" ? "md" : "html";
    const lien = document.createElement("a");
    lien.href = URL.createObjectURL(
      new Blob([rendu.contenu], { type: "text/plain;charset=utf-8" }),
    );
    lien.download = `${(titre || "document").replace(/\W+/g, "-").toLowerCase()}.${extension}`;
    lien.click();
    URL.revokeObjectURL(lien.href);
  };

  return (
    <div className="composition">
      <div className="composition__reglages">
        <label>
          <span>Titre</span>
          <input
            value={titre}
            onChange={(e) => setTitre(e.target.value)}
            placeholder="Titre de l'ouvrage"
            disabled={desactive}
          />
        </label>
        <label>
          <span>Auteur</span>
          <input
            value={auteur}
            onChange={(e) => setAuteur(e.target.value)}
            placeholder="Nom de l'auteur"
            disabled={desactive}
          />
        </label>
        <label>
          <span>Format</span>
          <select
            value={taille}
            onChange={(e) => setTaille(e.target.value)}
            disabled={desactive}
          >
            <option value="a5">A5 — livre</option>
            <option value="a4">A4</option>
            <option value="lettre">Lettre US</option>
          </select>
        </label>
      </div>

      <div className="barre">
        <button
          type="button" className="primaire"
          onClick={() => void composer("html")}
          disabled={desactive || occupe || !texte.trim()}
        >
          Composer en HTML
        </button>
        <button
          type="button"
          onClick={() => void composer("md")}
          disabled={desactive || occupe || !texte.trim()}
        >
          Composer en Markdown
        </button>
        {rendu && (
          <button type="button" onClick={telecharger}>
            Télécharger
          </button>
        )}
      </div>

      {rendu?.format === "html" && (
        <>
          <p className="aide">
            Ouvre le fichier téléchargé puis imprime en PDF. Le gabarit gère
            les sauts de page, la lettrine et le sommaire.
          </p>
          <iframe
            className="composition__apercu"
            srcDoc={rendu.contenu}
            title="Aperçu de la composition"
            sandbox=""
          />
        </>
      )}

      {rendu?.format === "md" && (
        <>
          <p className="aide">
            Repasse en .docx avec&nbsp;: <code>pandoc doc.md -o doc.docx</code>
          </p>
          <textarea className="composition__source" value={rendu.contenu} readOnly />
        </>
      )}
    </div>
  );
}
