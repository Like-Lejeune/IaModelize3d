import { useEffect, useId, useMemo, useState } from "react";

interface Props {
  files: File[];
  onChange: (files: File[]) => void;
  max?: number;
}

/** The drop zone drawn as the A4 sheet the customer puts the part on: the ruler on its edges is what lets the
 *  workshop measure the part in millimetres. */
export default function PhotoSheet({ files, onChange, max = 6 }: Props) {
  const id = useId();
  const [over, setOver] = useState(false);
  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);

  const add = (list: FileList | null) => {
    if (!list) return;
    const images = Array.from(list).filter((f) => f.type.startsWith("image/"));
    onChange([...files, ...images].slice(0, max));
  };

  return (
    <div>
      <div
        className={`a4 drop${over ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
      >
        <input
          id={id}
          type="file"
          accept="image/*"
          capture="environment"
          multiple
          aria-label="Ajouter des photos de la pièce"
          onChange={(e) => { add(e.target.files); e.target.value = ""; }}
        />
        <div>
          <strong>Photographiez la pièce sur une feuille A4</strong>
          <span>Toute la feuille dans le cadre, prise bien d'en haut. Touchez ici ou déposez vos photos.</span>
        </div>
      </div>
      {files.length > 0 && (
        <div className="thumbs">
          {files.map((f, i) => (
            <div className="thumb" key={urls[i]}>
              <img src={urls[i]} alt={`Photo ${i + 1} : ${f.name}`} />
              <button type="button" aria-label={`Retirer la photo ${i + 1}`} onClick={() => onChange(files.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <p className="help">{files.length} / {max} photos. Une vue de dessus suffit souvent ; ajoutez une vue de côté pour une pièce épaisse.</p>
    </div>
  );
}
