interface TabOption<T extends string> {
  value: T;
  label: string;
}

interface TabsProps<T extends string> {
  options: TabOption<T>[];
  value: T;
  onChange: (value: T) => void;
}

/**
 * Générique sur T (union de strings) — sert au filtre "En attente/Traitées/
 * Toutes" de AlertList ET pourrait servir ailleurs (ex: le sélecteur de
 * scénario "Normal/Erreur/Session expirée" du login). Ne connaît aucune
 * donnée métier, juste value/label.
 */
export function Tabs<T extends string>({ options, value, onChange }: TabsProps<T>) {
  return (
    <div role="tablist" className="flex gap-6 border-b border-gray-200">
      {options.map((opt) => {
        const isActive = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(opt.value)}
            className={`-mb-px border-b-2 px-1 py-2 text-sm font-medium transition-colors ${
              isActive
                ? 'border-blue-600 text-gray-900'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
